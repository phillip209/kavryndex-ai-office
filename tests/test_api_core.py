from fastapi.testclient import TestClient

from kavryndex_office.api import create_app
from kavryndex_office.config import Settings
from tests.conftest import Office


def test_health_is_public(client: TestClient) -> None:
    r = client.get("/health", headers={})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_requires_valid_key(client: TestClient) -> None:
    assert client.get("/api/v1/agents", headers={"X-API-Key": ""}).status_code == 401
    assert client.get("/api/v1/agents", headers={"X-API-Key": "wrong"}).status_code == 401


def test_api_rejects_everything_without_configured_key() -> None:
    app = create_app(Settings(database_url="sqlite://", _env_file=None))  # type: ignore[call-arg]
    with TestClient(app) as c:
        assert c.get("/api/v1/agents", headers={"X-API-Key": "anything"}).status_code == 503
        assert c.get("/health").status_code == 200


def test_system_info_and_tools(office: Office) -> None:
    info = office.ok("GET", "/system/info")
    assert info["allow_paid_providers"] is False
    assert "mock" in info["providers"]
    tools = {t["name"]: t for t in office.ok("GET", "/tools")}
    assert tools["memory_delete"]["requires_approval"] is True
    assert tools["memory_write"]["requires_approval"] is False


def test_bootstrap_creates_six_agents_idempotently(office: Office) -> None:
    created = office.ok("POST", "/agents/bootstrap")
    assert {a["slug"] for a in created} == {
        "ceo",
        "developer",
        "marketing",
        "research",
        "qa",
        "operations",
    }
    assert office.ok("POST", "/agents/bootstrap") == []
    agents = {a["slug"]: a for a in office.ok("GET", "/agents")}
    assert agents["ceo"]["can_delegate"] is True
    assert agents["developer"]["can_delegate"] is False
    assert "memory_delete" in agents["operations"]["allowed_tools"]
    assert "task_delegate" not in agents["marketing"]["allowed_tools"]


def test_agent_validation_and_update(office: Office) -> None:
    body = {
        "slug": "writer",
        "name": "Writer",
        "role": "marketing",
        "department": "Marketing",
        "system_prompt": "Escribe.",
        "allowed_tools": ["shell_exec"],
    }
    office.ok("POST", "/agents", 403, json=body)
    body["allowed_tools"] = ["memory_write"]
    agent = office.ok("POST", "/agents", 201, json=body)
    office.ok("POST", "/agents", 409, json=body)
    office.ok("PATCH", f"/agents/{agent['id']}", 403, json={"allowed_tools": ["nope"]})
    updated = office.ok("PATCH", f"/agents/{agent['id']}", json={"status": "disabled"})
    assert updated["status"] == "disabled"
    assert office.ok("GET", f"/agents/{agent['id']}")["slug"] == "writer"
    office.ok("GET", "/agents/missing", 404)


def test_projects_and_membership(office: Office) -> None:
    agents = office.bootstrap()
    project = office.project("alpha", members=["developer"])
    office.ok("POST", "/projects", 409, json={"slug": "alpha", "name": "Alpha"})
    assert [p["slug"] for p in office.ok("GET", "/projects")] == ["alpha"]
    assert office.ok("GET", f"/projects/{project['id']}")["name"] == "Alpha"

    dev = office.ok("GET", f"/agents/{agents['developer']['id']}")
    assert project["id"] in dev["project_access"]

    office.ok("POST", f"/projects/{project['id']}/members", 204, json={"agent_slugs": ["qa"]})
    office.ok(
        "DELETE", f"/projects/{project['id']}/members", 204, json={"agent_slugs": ["developer"]}
    )
    dev = office.ok("GET", f"/agents/{agents['developer']['id']}")
    assert project["id"] not in dev["project_access"]
    qa = office.ok("GET", f"/agents/{agents['qa']['id']}")
    assert project["id"] in qa["project_access"]
    office.ok("GET", "/projects/missing", 404)


def test_audit_records_operations(office: Office) -> None:
    office.bootstrap()
    project = office.project("audited")
    events = office.ok("GET", f"/audit?project_id={project['id']}")
    assert "project.created" in {e["action"] for e in events}
    created = office.ok("GET", "/audit?action=agent.created")
    assert len(created) == 6
    assert all(e["actor"] == "human:admin" for e in created)
