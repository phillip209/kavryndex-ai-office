import json
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy.orm import Session

from kavryndex_office.config import Settings
from kavryndex_office.db import init_db, make_engine, make_session_factory
from kavryndex_office.errors import BudgetExceededError, ProviderError
from kavryndex_office.memory import service as memory_service
from kavryndex_office.models import Agent, AgentRole, MemoryScope, Project
from kavryndex_office.providers.base import (
    ChatMessage,
    CompletionRequest,
    ToolCall,
    ToolDefinition,
    Usage,
)
from kavryndex_office.providers.openai_compat import OpenAICompatProvider
from kavryndex_office.providers.registry import build_registry


def _provider(handler: httpx.MockTransport) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="https://llm.example/v1/",
        api_key="secret",
        is_paid=False,
        input_price_per_mtok=1.0,
        output_price_per_mtok=2.0,
        transport=handler,
    )


def test_openai_compat_parses_tool_calls_and_usage() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "memory_search",
                                        "arguments": '{"query": "x"}',
                                    },
                                },
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {"name": "memory_write", "arguments": "not-json"},
                                },
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    provider = _provider(httpx.MockTransport(handle))
    response = provider.complete(
        CompletionRequest(
            model="llama",
            messages=[
                ChatMessage("user", "hola"),
                ChatMessage(
                    "assistant", "", tool_calls=[ToolCall("c0", "memory_search", {"q": 1})]
                ),
                ChatMessage("tool", "{}", tool_call_id="c0"),
            ],
            tools=[ToolDefinition("memory_search", "buscar", {"type": "object"})],
        )
    )
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["tools"][0]["function"]["name"] == "memory_search"
    assert body["messages"][1]["tool_calls"][0]["function"]["arguments"] == '{"q": 1}'
    assert body["messages"][2]["tool_call_id"] == "c0"

    assert response.content == ""
    assert response.tool_calls[0] == ToolCall("c1", "memory_search", {"query": "x"})
    assert response.tool_calls[1].arguments == {}
    assert response.usage == Usage(1000, 500)
    assert provider.cost_usd(response.usage) == pytest.approx(0.002)


def test_openai_compat_errors_are_retryable_and_redacted() -> None:
    provider = _provider(httpx.MockTransport(lambda r: httpx.Response(429, text="secret body")))
    with pytest.raises(ProviderError) as exc:
        provider.complete(CompletionRequest(model="m", messages=[ChatMessage("user", "x")]))
    assert "secret body" not in str(exc.value)


def test_registry_policy_blocks_paid_compat_provider() -> None:
    settings = Settings(
        database_url="sqlite://",
        openai_compat_base_url="https://api.example/v1",
        openai_compat_api_key="k",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )
    registry = build_registry(settings)
    assert registry.names() == ["mock", "openai_compat"]
    with pytest.raises(BudgetExceededError):
        registry.get("openai_compat")

    free = build_registry(settings.model_copy(update={"openai_compat_is_paid": False}))
    assert free.get("openai_compat").is_paid is False


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def _agent(slug: str, role: AgentRole, access: list[str]) -> Agent:
    return Agent(
        slug=slug,
        name=slug,
        role=role,
        department="d",
        system_prompt="p",
        allowed_tools=[],
        project_access=access,
    )


def test_memory_scopes_are_isolated(session: Session) -> None:
    p1, p2 = Project(slug="p1", name="P1"), Project(slug="p2", name="P2")
    session.add_all([p1, p2])
    session.flush()
    alice = _agent("alice", AgentRole.DEVELOPER, [p1.id])
    bob = _agent("bob", AgentRole.QA, [p2.id])
    session.add_all([alice, bob])
    session.flush()

    memory_service.upsert(
        session,
        scope=MemoryScope.AGENT,
        key="nota",
        content="privada",
        actor="t",
        agent_id=alice.id,
    )
    memory_service.upsert(
        session,
        scope=MemoryScope.PROJECT,
        key="req",
        content="p1 data",
        actor="t",
        project_id=p1.id,
    )
    memory_service.upsert(
        session,
        scope=MemoryScope.PROJECT,
        key="req",
        content="p2 data",
        actor="t",
        project_id=p2.id,
    )
    memory_service.upsert(
        session, scope=MemoryScope.ORGANIZATION, key="regla", content="global", actor="t"
    )
    memory_service.upsert(
        session, scope=MemoryScope.ORGANIZATION, key="regla", content="global v2", actor="t"
    )

    alice_sees = {
        e.content for e in memory_service.readable_for_agent(session, alice, project_id=p1.id)
    }
    assert alice_sees == {"privada", "p1 data", "global v2"}
    bob_in_p1 = {
        e.content for e in memory_service.readable_for_agent(session, bob, project_id=p1.id)
    }
    assert bob_in_p1 == {"global v2"}
    found = memory_service.readable_for_agent(session, alice, project_id=p1.id, query="P1")
    assert [e.key for e in found] == ["req"]


def test_memory_write_permissions(session: Session) -> None:
    from kavryndex_office.errors import PermissionDeniedError

    dev = _agent("dev", AgentRole.DEVELOPER, ["proj"])
    ceo = _agent("ceo", AgentRole.EXECUTIVE, ["*"])
    with pytest.raises(PermissionDeniedError):
        memory_service.check_write_permission(dev, MemoryScope.ORGANIZATION, "proj")
    with pytest.raises(PermissionDeniedError):
        memory_service.check_write_permission(dev, MemoryScope.PROJECT, "other")
    memory_service.check_write_permission(dev, MemoryScope.PROJECT, "proj")
    memory_service.check_write_permission(ceo, MemoryScope.ORGANIZATION, None)
    with pytest.raises(PermissionDeniedError):
        memory_service.upsert(session, scope=MemoryScope.AGENT, key="k", content="c", actor="t")
