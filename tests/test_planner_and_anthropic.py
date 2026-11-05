import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from kavryndex_office.api import create_app
from kavryndex_office.config import Settings
from kavryndex_office.errors import BudgetExceededError, ProviderError
from kavryndex_office.providers.anthropic import AnthropicProvider
from kavryndex_office.providers.base import (
    ChatMessage,
    CompletionRequest,
    ToolCall,
    ToolDefinition,
    Usage,
)
from kavryndex_office.providers.mock import MockProvider
from kavryndex_office.providers.registry import ProviderRegistry, build_registry
from tests.conftest import API_KEY, Office, RecordingProvider

# ---------------------------------------------------------------- adaptador Anthropic


def _anthropic(handler: Any) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="sk-test",
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
        transport=httpx.MockTransport(handler),
    )


def test_anthropic_request_format_and_response_parsing() -> None:
    seen: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Delego. "},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "task_delegate",
                        "input": {"title": "X"},
                    },
                ],
                "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000},
            },
        )

    provider = _anthropic(handle)
    response = provider.complete(
        CompletionRequest(
            model="claude-test",
            messages=[
                ChatMessage("system", "Reglas A"),
                ChatMessage("system", "Reglas B"),
                ChatMessage("user", "Tarea"),
                ChatMessage(
                    "assistant",
                    "",
                    [
                        ToolCall("c1", "memory_search", {}),
                        ToolCall("c2", "memory_write", {"key": "k"}),
                    ],
                ),
                ChatMessage("tool", '{"results": []}', tool_call_id="c1"),
                ChatMessage("tool", '{"ok": 1}', tool_call_id="c2"),
            ],
            tools=[ToolDefinition("memory_search", "buscar", {"type": "object"})],
            max_tokens=256,
        )
    )
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    assert body["system"] == "Reglas A\n\nReglas B"
    assert body["max_tokens"] == 256
    assert body["tools"] == [
        {"name": "memory_search", "description": "buscar", "input_schema": {"type": "object"}}
    ]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assistant = body["messages"][1]["content"]
    assert [b["type"] for b in assistant] == ["tool_use", "tool_use"]  # sin bloque de texto vacío
    results = body["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["c1", "c2"]  # resultados agrupados

    assert response.content == "Delego. "
    assert response.tool_calls == [ToolCall("tu_1", "task_delegate", {"title": "X"})]
    assert response.usage == Usage(1_000_000, 100_000)
    assert provider.cost_usd(response.usage) == pytest.approx(4.5)


def test_anthropic_errors_are_retryable_and_redacted() -> None:
    provider = _anthropic(lambda r: httpx.Response(529, text="overloaded secret"))
    with pytest.raises(ProviderError) as exc:
        provider.complete(CompletionRequest(model="m", messages=[ChatMessage("user", "x")]))
    assert "secret" not in str(exc.value)


def test_anthropic_registration_requires_prices_and_paid_approval() -> None:
    base = {"database_url": "sqlite://", "anthropic_api_key": "sk", "_env_file": None}
    with pytest.raises(ValueError, match="PRICE_PER_MTOK"):
        build_registry(Settings(**base))  # type: ignore[arg-type]
    priced = {**base, "anthropic_input_price_per_mtok": 3, "anthropic_output_price_per_mtok": 15}
    blocked = build_registry(Settings(**priced))  # type: ignore[arg-type]
    assert "anthropic" in blocked.names()
    with pytest.raises(BudgetExceededError):
        blocked.get("anthropic")
    allowed = build_registry(Settings(**priced, allow_paid_providers=True))  # type: ignore[arg-type]
    assert allowed.get("anthropic").is_paid is True
    assert (
        "anthropic"
        not in build_registry(Settings(database_url="sqlite://", _env_file=None)).names()
    )  # type: ignore[call-arg]


# ---------------------------------------------------------------- objetivos y planificador

PLAN = [
    {"name": "task_delegate", "arguments": {"title": "Construir", "assignee_slug": "developer"}},
    {
        "name": "task_delegate",
        "arguments": {"title": "Probar", "assignee_slug": "qa", "depends_on_titles": ["Construir"]},
    },
]


def _goal(
    office: Office, project_id: str, plan: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    body = {
        "title": "Lanzar módulo",
        "description": "MVP",
        "input": {"mock_tool_calls": plan or PLAN},
    }
    result: dict[str, Any] = office.ok("POST", f"/projects/{project_id}/goals", 201, json=body)
    return result


def test_goal_plans_delegates_and_reports_last(office: Office, recorder: RecordingProvider) -> None:
    office.bootstrap()
    project = office.project("goal", members=["developer", "qa"])
    goal = _goal(office, project["id"])
    plan, report = goal["plan_task"], goal["report_task"]
    assert report["await_descendants"] is True
    assert report["dependency_ids"] == [plan["id"]]

    office.run(plan["id"])
    office.ok("POST", f"/tasks/{report['id']}/run", 409)  # el equipo aún no termina

    summary = office.ok("POST", f"/projects/{project['id']}/run")
    titles = [e["title"] for e in summary["executed"]]
    assert titles == ["Construir", "Probar", "Informe final: Lanzar módulo"]

    plan_prompt = recorder.requests[0].messages[1].content
    assert "Equipo disponible" in plan_prompt
    assert "- developer:" in plan_prompt and "- qa:" in plan_prompt
    assert "- marketing:" not in plan_prompt  # sin acceso al proyecto
    assert "task_delegate" in plan_prompt

    report_prompt = recorder.requests[-1].messages[1].content
    assert "Resultados del equipo" in report_prompt
    assert "[completed] Construir (developer)" in report_prompt
    assert "[completed] Probar (qa)" in report_prompt
    assert office.get_task(report["id"])["status"] == "completed"
    assert "task_delegate" not in {t.name for t in recorder.requests[-1].tools}

    tree = office.ok("GET", f"/tasks/{plan['id']}/tree")
    assert [c["title"] for c in tree["children"]] == ["Construir", "Probar"]
    assert all(c["status"] == "completed" for c in tree["children"])
    assert (
        office.ok("GET", "/audit?action=goal.created")[0]["details"]["report_task_id"]
        == report["id"]
    )


def test_report_includes_failed_subtasks(office: Office, recorder: RecordingProvider) -> None:
    office.bootstrap()
    project = office.project("partial", members=["developer"])
    plan = [
        {
            "name": "task_delegate",
            "arguments": {
                "title": "Romper",
                "assignee_slug": "developer",
                "input": {"mock_fail_times": 9},
            },
        }
    ]
    goal = _goal(office, project["id"], plan)
    office.ok("POST", f"/projects/{project['id']}/run")
    assert office.get_task(goal["report_task"]["id"])["status"] == "completed"
    assert "[failed] Romper (developer): ProviderError" in recorder.requests[-1].messages[1].content


def test_goal_requires_delegating_planner(office: Office) -> None:
    office.bootstrap()
    project = office.project("noplan", members=["developer"])
    office.ok(
        "POST",
        f"/projects/{project['id']}/goals",
        403,
        json={"title": "X", "planner_slug": "developer"},
    )
    office.ok(
        "POST",
        f"/projects/{project['id']}/goals",
        404,
        json={"title": "X", "planner_slug": "ghost"},
    )


@pytest.mark.parametrize(
    ("limits", "expected_ok"),
    [
        ({"max_delegations_per_task": 1}, [True, False]),
        ({"max_delegation_depth": 0}, [False, False]),
    ],
)
def test_delegation_limits(
    client: TestClient, office: Office, limits: dict[str, int], expected_ok: list[bool]
) -> None:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    engine.settings = engine.settings.model_copy(update=limits)
    office.bootstrap()
    project = office.project("limits", members=["developer", "qa"])
    goal = _goal(office, project["id"])
    run = office.run(goal["plan_task"]["id"])
    assert [c["ok"] for c in run["tool_calls"]] == expected_ok


# ------------------------------------------------ extremo a extremo con Anthropic simulado


class ScriptedClaude:
    """Simula la Messages API: el CEO delega una vez; el resto responde con texto."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        body = json.loads(request.content)
        last = body["messages"][-1]["content"]
        has_results = isinstance(last, list) and any(b.get("type") == "tool_result" for b in last)
        tools = {t["name"] for t in body.get("tools", [])}
        if (
            "task_delegate" in tools
            and not has_results
            and "Planificar" in json.dumps(body["messages"])
        ):
            content = [
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "task_delegate",
                    "input": {"title": "Investigar mercado", "assignee_slug": "research"},
                }
            ]
        else:
            content = [{"type": "text", "text": "Informe: hecho."}]
        return httpx.Response(
            200, json={"content": content, "usage": {"input_tokens": 1000, "output_tokens": 100}}
        )


@pytest.fixture
def claude_office(settings: Settings) -> Iterator[tuple[Office, ScriptedClaude]]:
    script = ScriptedClaude()
    registry = ProviderRegistry(allow_paid=True)
    registry.register(MockProvider())
    registry.register(
        AnthropicProvider(
            api_key="sk",
            input_price_per_mtok=3,
            output_price_per_mtok=15,
            transport=httpx.MockTransport(script),
        )
    )
    with TestClient(
        create_app(settings, providers=registry), headers={"X-API-Key": API_KEY}
    ) as client:
        yield Office(client), script


def test_end_to_end_goal_with_anthropic_adapter(
    claude_office: tuple[Office, ScriptedClaude],
) -> None:
    office, script = claude_office
    agents = office.bootstrap()
    for slug in ("ceo", "research"):
        office.ok(
            "PATCH",
            f"/agents/{agents[slug]['id']}",
            json={"provider": "anthropic", "model": "claude-test"},
        )
    project = office.project("real", members=["research"])
    goal = office.ok("POST", f"/projects/{project['id']}/goals", 201, json={"title": "Estudio"})

    summary = office.ok("POST", f"/projects/{project['id']}/run")
    titles = [e["title"] for e in summary["executed"]]
    assert titles == ["Planificar: Estudio", "Investigar mercado", "Informe final: Estudio"]
    assert script.calls == 4  # plan (tool_use + cierre), investigación, informe

    plan_run = office.ok("GET", f"/tasks/{goal['plan_task']['id']}/runs")[0]
    assert plan_run["provider"] == "anthropic"
    assert plan_run["input_tokens"] == 2000
    assert plan_run["cost_usd"] == pytest.approx(0.009)
    assert office.get_task(goal["report_task"]["id"])["result"] == "Informe: hecho."
