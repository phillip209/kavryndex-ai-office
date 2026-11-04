from tests.conftest import Office, RecordingProvider


def test_task_creation_assignment_and_cancel(office: Office) -> None:
    office.bootstrap()
    project = office.project("p1", members=["developer"])
    pid = project["id"]

    office.ok("POST", "/tasks", 403, json={"project_id": pid, "title": "x", "assignee_slug": "qa"})
    task = office.task(pid, "Diseñar API")
    assert task["status"] == "pending"
    assert task["assignee_id"] is None

    office.ok("POST", f"/tasks/{task['id']}/run", 409)  # sin agente
    office.ok("POST", f"/tasks/{task['id']}/assign", 403, json={"assignee_slug": "marketing"})
    assigned = office.ok("POST", f"/tasks/{task['id']}/assign", json={"assignee_slug": "developer"})
    assert assigned["assignee_id"] is not None

    cancelled = office.ok("POST", f"/tasks/{task['id']}/cancel")
    assert cancelled["status"] == "cancelled"
    office.ok("POST", f"/tasks/{task['id']}/cancel", 409)
    office.ok("POST", f"/tasks/{task['id']}/assign", 409, json={"assignee_slug": "developer"})
    office.ok("GET", "/tasks/missing", 404)
    assert len(office.ok("GET", f"/tasks?project_id={pid}&status=cancelled")) == 1


def test_dependencies_must_share_project(office: Office) -> None:
    office.bootstrap()
    a = office.project("pa")
    b = office.project("pb")
    other = office.task(b["id"], "Otra")
    office.ok(
        "POST",
        "/tasks",
        409,
        json={"project_id": a["id"], "title": "x", "depends_on": [other["id"]]},
    )


def test_run_task_completes_and_stores_results(office: Office, recorder: RecordingProvider) -> None:
    office.bootstrap()
    project = office.project("p2", members=["research"])
    task = office.task(
        project["id"],
        "Analizar mercado",
        description="Resumen",
        assignee_slug="research",
        input={"region": "LATAM"},
    )
    run = office.run(task["id"])
    assert run["status"] == "completed"
    assert run["provider"] == "mock"
    assert run["input_tokens"] > 0
    assert run["cost_usd"] == 0.0

    done = office.get_task(task["id"])
    assert done["status"] == "completed"
    assert "Analizar mercado" in done["result"]
    assert done["attempts"] == 1

    prompt = recorder.requests[0].messages[1].content
    assert "LATAM" in prompt
    tool_names = {t.name for t in recorder.requests[0].tools}
    assert tool_names == {"memory_search", "memory_write", "message_send"}

    messages = office.ok("GET", f"/messages?task_id={task['id']}")
    assert messages[0]["kind"] == "report"
    assert len(office.ok("GET", f"/tasks/{task['id']}/runs")) == 1
    office.ok("POST", f"/tasks/{task['id']}/run", 409)  # ya completada


def test_dependencies_block_and_handoff_results(
    office: Office, recorder: RecordingProvider
) -> None:
    office.bootstrap()
    project = office.project("p3", members=["developer", "qa"])
    build = office.task(project["id"], "Construir módulo", assignee_slug="developer")
    test = office.task(
        project["id"], "Probar módulo", assignee_slug="qa", depends_on=[build["id"]], priority=10
    )
    office.ok("POST", f"/tasks/{test['id']}/run", 409)

    summary = office.ok("POST", f"/projects/{project['id']}/run")
    assert [e["title"] for e in summary["executed"]] == ["Construir módulo", "Probar módulo"]
    assert summary["remaining_pending"] == 0

    qa_prompt = recorder.requests[-1].messages[1].content
    assert "Resultados entregados por tareas previas" in qa_prompt
    assert "Construir módulo" in qa_prompt


def test_ceo_delegates_structured_workflow(office: Office) -> None:
    agents = office.bootstrap()
    project = office.project("launch", members=["developer", "qa", "marketing"])
    goal = office.task(
        project["id"],
        "Lanzar landing page",
        assignee_slug="ceo",
        input={
            "mock_tool_calls": [
                {
                    "name": "task_delegate",
                    "arguments": {
                        "title": "Construir landing",
                        "assignee_slug": "developer",
                        "priority": 5,
                    },
                },
                {
                    "name": "task_delegate",
                    "arguments": {
                        "title": "Validar landing",
                        "assignee_slug": "qa",
                        "depends_on_titles": ["Construir landing"],
                    },
                },
                {
                    "name": "task_delegate",
                    "arguments": {"title": "Plan de campaña", "assignee_slug": "marketing"},
                },
                {
                    "name": "memory_write",
                    "arguments": {
                        "scope": "project",
                        "key": "objetivo",
                        "content": "Landing en 2 semanas",
                    },
                },
            ]
        },
    )
    summary = office.ok("POST", f"/projects/{project['id']}/run")
    titles = [e["title"] for e in summary["executed"]]
    assert titles[0] == "Lanzar landing page"
    assert titles.index("Construir landing") < titles.index("Validar landing")
    assert len(titles) == 4

    subtasks = office.ok("GET", f"/tasks?parent_id={goal['id']}")
    assert {t["status"] for t in subtasks} == {"completed"}
    validate = next(t for t in subtasks if t["title"] == "Validar landing")
    assert len(validate["dependency_ids"]) == 1

    handoffs = [
        m
        for m in office.ok("GET", f"/messages?project_id={project['id']}")
        if m["kind"] == "handoff"
    ]
    assert len(handoffs) == 3
    assert all(m["recipient_agent_id"] == agents["ceo"]["id"] for m in handoffs)

    memory = office.ok("GET", f"/memory?project_id={project['id']}")
    assert memory[0]["key"] == "objetivo"
    assert memory[0]["source_task_id"] == goal["id"]


def test_delegation_to_agent_without_access_is_reported_to_model(office: Office) -> None:
    office.bootstrap()
    project = office.project("closed")
    goal = office.task(
        project["id"],
        "Objetivo",
        assignee_slug="ceo",
        input={
            "mock_tool_calls": [
                {"name": "task_delegate", "arguments": {"title": "X", "assignee_slug": "developer"}}
            ]
        },
    )
    run = office.run(goal["id"])
    assert run["status"] == "completed"
    assert run["tool_calls"][0]["ok"] is False
    assert office.ok("GET", f"/tasks?parent_id={goal['id']}") == []
    assert office.ok("GET", "/audit?action=tool.error")


def test_messages_search_and_delete_errors(office: Office) -> None:
    office.bootstrap()
    project = office.project("comms", members=["research", "qa", "operations"])
    office.ok(
        "PUT",
        "/memory",
        json={"scope": "project", "project_id": project["id"], "key": "glosario", "content": "KPI"},
    )
    task = office.task(
        project["id"],
        "Coordinar",
        assignee_slug="research",
        input={
            "mock_tool_calls": [
                {"name": "memory_search", "arguments": {"query": "KPI"}},
                {
                    "name": "message_send",
                    "arguments": {
                        "recipient_slug": "qa",
                        "kind": "request",
                        "content": "Revisa KPI",
                    },
                },
                {
                    "name": "message_send",
                    "arguments": {"recipient_slug": "marketing", "content": "sin acceso"},
                },
                {"name": "message_send", "arguments": {"content": ""}},
            ]
        },
    )
    run = office.run(task["id"])
    assert [c["ok"] for c in run["tool_calls"]] == [True, True, False, False]
    requests = [
        m for m in office.ok("GET", f"/messages?task_id={task['id']}") if m["kind"] == "request"
    ]
    assert requests[0]["content"] == "Revisa KPI"

    ops = office.task(
        project["id"],
        "Borrar inexistente",
        assignee_slug="operations",
        input={"mock_tool_calls": [{"name": "memory_delete", "arguments": {"entry_id": "nope"}}]},
    )
    office.run(ops["id"])
    approval = office.ok("GET", f"/approvals?task_id={ops['id']}")[0]
    office.ok("POST", f"/approvals/{approval['id']}/approve")
    run = office.run(ops["id"])
    assert run["status"] == "completed"
    assert run["tool_calls"][-1]["ok"] is False
