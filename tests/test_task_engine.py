from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kavryndex_office.config import Settings
from kavryndex_office.execution.engine import ExecutionEngine
from kavryndex_office.models import RunStatus, Task, TaskRun, TaskStatus
from kavryndex_office.providers.registry import ProviderRegistry
from tests.conftest import Office


class FakeClock:
    """Reloj controlable; ``tick`` avanza el tiempo en cada lectura."""

    def __init__(self, tick_s: float = 0.0) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        self.tick = timedelta(seconds=tick_s)

    def __call__(self) -> datetime:
        self.now += self.tick
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _use_clock(client: TestClient, clock: FakeClock, **settings: Any) -> ExecutionEngine:
    engine: ExecutionEngine = client.app.state.engine  # type: ignore[attr-defined]
    engine.clock = clock
    engine.settings = engine.settings.model_copy(update=settings)
    return engine


def test_retry_delay_grows_exponentially_with_cap() -> None:
    settings = Settings(retry_base_delay_s=5, retry_max_delay_s=30, _env_file=None)  # type: ignore[call-arg]
    engine = ExecutionEngine(ProviderRegistry(allow_paid=False), settings)
    assert [engine.retry_delay(n).total_seconds() for n in range(1, 6)] == [5, 10, 20, 30, 30]


def test_failed_attempt_is_deferred_until_backoff_expires(
    client: TestClient, office: Office
) -> None:
    clock = FakeClock()
    _use_clock(client, clock, retry_base_delay_s=10)
    office.bootstrap()
    project = office.project("backoff", members=["developer"])
    task = office.task(
        project["id"],
        "Inestable",
        assignee_slug="developer",
        input={"mock_fail_times": 2},
        max_attempts=3,
    )

    assert office.run(task["id"])["status"] == "failed"
    pending = office.get_task(task["id"])
    assert pending["status"] == "pending"
    assert pending["next_attempt_at"].startswith("2026-01-01T12:00:10")
    office.ok("POST", f"/tasks/{task['id']}/run", 409)

    summary = office.ok("POST", f"/projects/{project['id']}/run")
    assert summary["executed"] == []
    assert summary["deferred_retries"] == 1

    clock.advance(11)
    assert office.run(task["id"])["status"] == "failed"
    second = office.get_task(task["id"])
    assert second["next_attempt_at"].startswith("2026-01-01T12:00:31")  # espera doble: 20 s

    clock.advance(21)
    summary = office.ok("POST", f"/projects/{project['id']}/run")
    assert [e["status"] for e in summary["executed"]] == ["completed"]
    done = office.get_task(task["id"])
    assert done["next_attempt_at"] is None
    assert done["attempts"] == 3


def test_task_timeout_between_steps(client: TestClient, office: Office) -> None:
    _use_clock(client, FakeClock(tick_s=6))
    office.bootstrap()
    project = office.project("slow", members=["research"])
    task = office.task(
        project["id"],
        "Lenta",
        assignee_slug="research",
        timeout_s=10,
        max_attempts=1,
        input={"mock_tool_calls": [{"name": "memory_search", "arguments": {}}]},
    )
    run = office.run(task["id"])
    assert run["status"] == "failed"
    assert "TaskTimeoutError" in run["error"]
    assert office.get_task(task["id"])["status"] == "failed"
    office.ok(
        "POST", "/tasks", 422, json={"project_id": project["id"], "title": "x", "timeout_s": 1}
    )


def _stuck_run(client: TestClient, task_id: str, agent_id: str, started: datetime) -> None:
    factory = client.app.state.session_factory  # type: ignore[attr-defined]
    with factory() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = TaskStatus.RUNNING
        task.attempts = 1
        session.add(
            TaskRun(
                task_id=task_id,
                agent_id=agent_id,
                attempt=1,
                provider="mock",
                model="mock-1",
                tool_calls=[],
                started_at=started,
            )
        )
        session.commit()


def test_stale_running_tasks_are_recovered(client: TestClient, office: Office) -> None:
    clock = FakeClock()
    _use_clock(client, clock, stale_run_after_s=900)
    agents = office.bootstrap()
    project = office.project("crash", members=["developer"])
    fresh = office.task(project["id"], "Reciente", assignee_slug="developer")
    stuck = office.task(project["id"], "Atascada", assignee_slug="developer")
    _stuck_run(client, fresh["id"], agents["developer"]["id"], clock.now - timedelta(seconds=60))
    _stuck_run(client, stuck["id"], agents["developer"]["id"], clock.now - timedelta(hours=1))

    assert office.ok("POST", "/system/recover-stale") == {"recovered": 1}
    recovered = office.get_task(stuck["id"])
    assert recovered["status"] == "pending"
    assert "interrumpida" in recovered["error"]
    runs = office.ok("GET", f"/tasks/{stuck['id']}/runs")
    assert runs[0]["status"] == RunStatus.FAILED.value
    assert office.get_task(fresh["id"])["status"] == "running"  # aún dentro del margen

    clock.advance(3600)
    summary = office.ok("POST", f"/projects/{project['id']}/run")
    assert summary["recovered_stale_runs"] == 1
    assert {office.get_task(t)["status"] for t in (fresh["id"], stuck["id"])} == {"completed"}


def test_dependency_editing_and_cycle_detection(office: Office) -> None:
    office.bootstrap()
    project = office.project("graph", members=["developer"])
    other = office.project("other")
    a = office.task(project["id"], "A", assignee_slug="developer")
    b = office.task(project["id"], "B", assignee_slug="developer", depends_on=[a["id"]])
    c = office.task(project["id"], "C", assignee_slug="developer")
    foreign = office.task(other["id"], "F")

    deps = {"depends_on": [b["id"], b["id"]]}
    updated = office.ok("POST", f"/tasks/{c['id']}/dependencies", json=deps)
    assert updated["dependency_ids"] == [b["id"]]
    office.ok("POST", f"/tasks/{c['id']}/dependencies", json=deps)  # idempotente

    error = office.ok("POST", f"/tasks/{a['id']}/dependencies", 409, json={"depends_on": [c["id"]]})
    assert "ciclo" in error["detail"]
    office.ok("POST", f"/tasks/{a['id']}/dependencies", 409, json={"depends_on": [a["id"]]})
    office.ok("POST", f"/tasks/{a['id']}/dependencies", 409, json={"depends_on": [foreign["id"]]})
    office.ok("POST", f"/tasks/{a['id']}/dependencies", 404, json={"depends_on": ["missing"]})

    removed = office.ok("DELETE", f"/tasks/{c['id']}/dependencies", json={"depends_on": [b["id"]]})
    assert removed["dependency_ids"] == []
    office.ok("POST", f"/tasks/{a['id']}/dependencies", json={"depends_on": [c["id"]]})

    office.ok("POST", f"/projects/{project['id']}/run")
    office.ok("POST", f"/tasks/{c['id']}/dependencies", 409, json={"depends_on": [b["id"]]})
    office.ok("DELETE", f"/tasks/{c['id']}/dependencies", 409, json={"depends_on": [b["id"]]})
    audit = {e["action"] for e in office.ok("GET", f"/audit?project_id={project['id']}")}
    assert {"task.dependencies_added", "task.dependencies_removed"} <= audit


def test_human_requeue_of_failed_task(office: Office) -> None:
    office.bootstrap()
    project = office.project("requeue", members=["developer"])
    task = office.task(
        project["id"],
        "Falla",
        assignee_slug="developer",
        input={"mock_fail_times": 1},
        max_attempts=1,
    )
    office.ok("POST", f"/tasks/{task['id']}/retry", 409)  # aún pendiente
    office.run(task["id"])
    assert office.get_task(task["id"])["status"] == "failed"

    requeued = office.ok("POST", f"/tasks/{task['id']}/retry")
    assert requeued["status"] == "pending"
    assert requeued["attempts"] == 0
    assert requeued["error"] is None
    # El fallo simulado ocurre en el intento 1; al reiniciar el contador vuelve a fallar.
    assert office.run(task["id"])["status"] == "failed"
    event = office.ok("GET", f"/audit?entity_id={task['id']}&action=task.requeued")[0]
    assert "Fallo simulado" in event["details"]["previous_error"]


@pytest.mark.parametrize("resource", ["tasks", "messages", "approvals", "memory", "audit"])
def test_list_endpoints_paginate(office: Office, resource: str) -> None:
    office.bootstrap()
    project = office.project("paged", members=["developer"])
    ids = [office.task(project["id"], f"T{i}", assignee_slug="developer")["id"] for i in range(5)]
    for i in range(3):
        office.ok(
            "PUT",
            "/memory",
            json={"scope": "project", "project_id": project["id"], "key": f"k{i}", "content": "v"},
        )
    office.ok("POST", f"/projects/{project['id']}/run")

    page = office.ok("GET", f"/{resource}?limit=2&offset=0")
    assert len(page) <= 2
    office.ok("GET", f"/{resource}?limit=0", 422)
    office.ok("GET", f"/{resource}?offset=-1", 422)
    if resource == "tasks":
        second = office.ok("GET", f"/tasks?project_id={project['id']}&limit=2&offset=2")
        assert [t["id"] for t in second] == ids[2:4]
