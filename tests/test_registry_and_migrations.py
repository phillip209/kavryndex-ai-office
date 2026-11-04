from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from kavryndex_office import cli
from kavryndex_office.api import create_app
from kavryndex_office.config import Settings
from kavryndex_office.db import (
    Base,
    alembic_config,
    current_revision,
    head_revision,
    init_db,
    make_engine,
)
from tests.conftest import TEST_DATABASE_URL, Office, _reset_database

EXPECTED_TABLES = {
    "agents",
    "approvals",
    "audit_events",
    "memory_entries",
    "messages",
    "projects",
    "task_dependencies",
    "task_runs",
    "tasks",
    "alembic_version",
}


def test_migrations_match_models_and_downgrade(tmp_path: Path) -> None:
    # Usa PostgreSQL si OFFICE_TEST_DATABASE_URL lo indica (CI); si no, SQLite temporal.
    url = TEST_DATABASE_URL
    if url.startswith("sqlite"):
        url = f"sqlite:///{tmp_path / 'm.db'}"
    _reset_database(url)
    engine = make_engine(url)
    init_db(engine)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    assert current_revision(engine) == head_revision()
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Modelos y migraciones divergen: {diff}"

    config = alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    init_db(engine)  # vuelve a subir sin errores
    assert current_revision(engine) == head_revision()
    engine.dispose()


def test_app_refuses_outdated_db_when_auto_migrate_disabled(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    settings = Settings(database_url=url, admin_api_key="k", auto_migrate=False, _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="kavryndex-office migrate"):
        create_app(settings)


def test_cli_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("OFFICE_DATABASE_URL", url)
    assert cli.main(["db-status"]) == 1
    assert cli.main(["migrate"]) == 0
    assert cli.main(["db-status"]) == 0
    assert cli.main(["bootstrap-agents"]) == 0
    assert cli.main(["bootstrap-agents"]) == 0
    assert cli.main(["generate-key"]) == 0
    out = capsys.readouterr().out
    assert "ceo" in out and "ninguno" in out
    assert len(out.strip().splitlines()[-1]) >= 40

    settings = Settings(database_url=url, admin_api_key="k", auto_migrate=False, _env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:
        agents = c.get("/api/v1/agents", headers={"X-API-Key": "k"}).json()
    assert len(agents) == 6


AGENT = {
    "slug": "analyst",
    "name": "Analyst",
    "role": "research",
    "department": "Research",
    "system_prompt": "Analiza.",
    "allowed_tools": ["memory_search"],
}


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"allowed_tools": ["memory_search", "memory_search"]}, "duplicados"),
        ({"allowed_tools": ["task_delegate"]}, "can_delegate"),
        ({"can_delegate": True}, "can_delegate"),
        ({"project_access": ["*"]}, "executive"),
        ({"provider": "openai_compat"}, "no configurado"),
    ],
)
def test_agent_registry_rules(office: Office, override: dict[str, object], fragment: str) -> None:
    error = office.ok("POST", "/agents", 422, json={**AGENT, **override})
    assert fragment in error["detail"]


def test_agent_updates_are_versioned_and_audited(office: Office) -> None:
    agent = office.ok("POST", "/agents", 201, json=AGENT)
    assert agent["version"] == 1
    same = office.ok("PATCH", f"/agents/{agent['id']}", json={"name": "Analyst"})
    assert same["version"] == 1  # sin cambios reales no hay nueva versión

    updated = office.ok(
        "PATCH",
        f"/agents/{agent['id']}",
        json={"allowed_tools": ["memory_search", "memory_write"], "status": "disabled"},
    )
    assert updated["version"] == 2
    office.ok("PATCH", f"/agents/{agent['id']}", 422, json={"can_delegate": True})

    event = office.ok("GET", f"/audit?entity_id={agent['id']}&action=agent.updated")[0]
    assert event["details"]["version"] == 2
    assert event["details"]["changes"]["status"] == {"from": "active", "to": "disabled"}
    assert event["details"]["changes"]["allowed_tools"]["to"] == ["memory_search", "memory_write"]
