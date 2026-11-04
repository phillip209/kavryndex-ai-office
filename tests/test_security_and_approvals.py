from typing import Any

from tests.conftest import Office


def _ops_delete_setup(office: Office) -> tuple[dict[str, Any], dict[str, Any], str]:
    office.bootstrap()
    project = office.project("infra", members=["operations"])
    entry = office.ok(
        "PUT",
        "/memory",
        json={"scope": "project", "project_id": project["id"], "key": "tmp", "content": "borrar"},
    )
    task = office.task(
        project["id"],
        "Limpiar memoria",
        assignee_slug="operations",
        input={
            "mock_tool_calls": [{"name": "memory_delete", "arguments": {"entry_id": entry["id"]}}]
        },
    )
    return project, task, entry["id"]


def test_destructive_tool_waits_for_human_approval(office: Office) -> None:
    project, task, _ = _ops_delete_setup(office)

    run = office.run(task["id"])
    assert run["status"] == "waiting_approval"
    assert office.get_task(task["id"])["status"] == "waiting_approval"
    assert office.get_task(task["id"])["attempts"] == 0
    assert len(office.ok("GET", f"/memory?project_id={project['id']}")) == 1  # aún no borrado

    pending = office.ok("GET", "/approvals?status=pending")
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "memory_delete"

    office.ok("POST", f"/approvals/{pending[0]['id']}/approve", json={"note": "ok"})
    assert office.get_task(task["id"])["status"] == "pending"
    office.ok("POST", f"/approvals/{pending[0]['id']}/approve", 409)

    run = office.run(task["id"])
    assert run["status"] == "completed"
    assert office.ok("GET", f"/memory?project_id={project['id']}") == []
    assert office.ok("GET", f"/approvals?task_id={task['id']}")[0]["status"] == "consumed"
    actions = {e["action"] for e in office.ok("GET", f"/audit?project_id={project['id']}")}
    assert {
        "approval.requested",
        "approval.approved",
        "memory.deleted",
        "task.waiting_approval",
    } <= actions


def test_rejected_approval_fails_task(office: Office) -> None:
    project, task, _ = _ops_delete_setup(office)
    office.run(task["id"])
    approval = office.ok("GET", "/approvals?status=pending")[0]
    office.ok("POST", f"/approvals/{approval['id']}/reject", json={"note": "No autorizado"})
    failed = office.get_task(task["id"])
    assert failed["status"] == "failed"
    assert "No autorizado" in failed["error"]
    assert len(office.ok("GET", f"/memory?project_id={project['id']}")) == 1


def test_unauthorized_tool_fails_task(office: Office) -> None:
    office.bootstrap()
    project = office.project("sec", members=["marketing"])
    task = office.task(
        project["id"],
        "Intento",
        assignee_slug="marketing",
        input={
            "mock_force_tools": True,
            "mock_tool_calls": [{"name": "task_delegate", "arguments": {}}],
        },
    )
    run = office.run(task["id"])
    assert run["status"] == "failed"
    assert "PermissionDeniedError" in run["error"]
    assert office.get_task(task["id"])["status"] == "failed"
    assert office.ok("GET", "/audit?action=tool.denied")


def test_non_executive_cannot_write_organization_memory(office: Office) -> None:
    office.bootstrap()
    project = office.project("mem", members=["research"])
    task = office.task(
        project["id"],
        "Guardar",
        assignee_slug="research",
        input={
            "mock_tool_calls": [
                {
                    "name": "memory_write",
                    "arguments": {"scope": "organization", "key": "k", "content": "v"},
                }
            ]
        },
    )
    run = office.run(task["id"])
    assert run["status"] == "completed"
    assert run["tool_calls"][0]["ok"] is False
    assert office.ok("GET", "/memory?scope=organization") == []


def test_agent_losing_access_cannot_run(office: Office) -> None:
    agents = office.bootstrap()
    project = office.project("revoked", members=["developer"])
    task = office.task(project["id"], "T", assignee_slug="developer")
    office.ok(
        "DELETE", f"/projects/{project['id']}/members", 204, json={"agent_slugs": ["developer"]}
    )
    office.ok("POST", f"/tasks/{task['id']}/run", 403)
    office.ok(
        "PATCH",
        f"/agents/{agents['developer']['id']}",
        json={"status": "disabled", "project_access": ["*"]},
    )
    office.ok("POST", f"/tasks/{task['id']}/run", 409)


def test_paid_provider_blocked_by_default(office: Office) -> None:
    agents = office.bootstrap()
    office.ok("PATCH", f"/agents/{agents['research']['id']}", json={"provider": "paid"})
    project = office.project("cost", members=["research"])
    task = office.task(project["id"], "Caro", assignee_slug="research")
    office.ok("POST", f"/tasks/{task['id']}/run", 402)
    assert office.get_task(task["id"])["status"] == "pending"

    office.ok("PATCH", f"/agents/{agents['research']['id']}", json={"provider": "unknown"})
    office.ok("POST", f"/tasks/{task['id']}/run", 404)


def test_retry_then_success(office: Office) -> None:
    office.bootstrap()
    project = office.project("retry", members=["developer"])
    task = office.task(
        project["id"], "Flaky", assignee_slug="developer", input={"mock_fail_times": 1}
    )
    first = office.run(task["id"])
    assert first["status"] == "failed"
    assert office.get_task(task["id"])["status"] == "pending"
    second = office.run(task["id"])
    assert second["status"] == "completed"
    assert len(office.ok("GET", f"/tasks/{task['id']}/runs")) == 2


def test_retries_exhausted(office: Office) -> None:
    office.bootstrap()
    project = office.project("dead", members=["developer"])
    task = office.task(
        project["id"],
        "Roto",
        assignee_slug="developer",
        input={"mock_fail_times": 9},
        max_attempts=2,
    )
    summary = office.ok("POST", f"/projects/{project['id']}/run")
    assert len(summary["executed"]) == 2
    failed = office.get_task(task["id"])
    assert failed["status"] == "failed"
    assert failed["attempts"] == 2


def test_token_and_step_budgets(office: Office) -> None:
    agents = office.bootstrap()
    project = office.project("budget", members=["developer", "qa"])
    office.ok("PATCH", f"/agents/{agents['developer']['id']}", json={"max_tokens_per_task": 100})
    big = office.task(project["id"], "Grande", description="x" * 2000, assignee_slug="developer")
    run = office.run(big["id"])
    assert run["status"] == "failed"
    assert "tokens" in run["error"]

    office.ok("PATCH", f"/agents/{agents['qa']['id']}", json={"max_steps": 1})
    loop = office.task(
        project["id"],
        "Pasos",
        assignee_slug="qa",
        input={"mock_tool_calls": [{"name": "memory_search", "arguments": {}}]},
    )
    run = office.run(loop["id"])
    assert run["status"] == "failed"
    assert "pasos" in run["error"]


def test_project_run_respects_max_tasks(office: Office) -> None:
    office.bootstrap()
    project = office.project("many", members=["developer"])
    for i in range(3):
        office.task(project["id"], f"T{i}", assignee_slug="developer")
    summary = office.ok("POST", f"/projects/{project['id']}/run?max_tasks=2")
    assert summary["stopped_reason"] == "max_tasks_reached"
    assert summary["remaining_pending"] == 1
