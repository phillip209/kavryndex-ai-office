import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kavryndex_office.api import create_app
from kavryndex_office.config import Settings
from kavryndex_office.providers.base import CompletionRequest, CompletionResponse, Usage
from kavryndex_office.providers.mock import MockProvider
from kavryndex_office.providers.registry import ProviderRegistry

API_KEY = "test-admin-key"


class RecordingProvider(MockProvider):
    """Mock que guarda las peticiones para inspeccionar el contexto enviado."""

    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        return super().complete(request)


class PaidProvider(MockProvider):
    name = "paid"
    is_paid = True

    def cost_usd(self, usage: Usage) -> float:
        return 1.0


@pytest.fixture
def recorder() -> RecordingProvider:
    return RecordingProvider()


# Con OFFICE_TEST_DATABASE_URL (p. ej. PostgreSQL en CI) las pruebas de API usan esa base.
TEST_DATABASE_URL = os.environ.get("OFFICE_TEST_DATABASE_URL", "sqlite://")


def _reset_database(url: str) -> None:
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        engine.dispose()


@pytest.fixture
def settings() -> Settings:
    _reset_database(TEST_DATABASE_URL)
    return Settings(database_url=TEST_DATABASE_URL, admin_api_key=API_KEY, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def client(settings: Settings, recorder: RecordingProvider) -> Iterator[TestClient]:
    registry = ProviderRegistry(allow_paid=False)
    registry.register(recorder)
    registry.register(PaidProvider())
    app = create_app(settings, providers=registry)
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c


class Office:
    """Atajos de API para las pruebas."""

    def __init__(self, client: TestClient) -> None:
        self.c = client

    def ok(self, method: str, url: str, expected: int = 200, **kw: Any) -> Any:
        r = self.c.request(method, f"/api/v1{url}", **kw)
        assert r.status_code == expected, r.text
        return r.json() if r.content else None

    def bootstrap(self) -> dict[str, dict[str, Any]]:
        self.ok("POST", "/agents/bootstrap")
        return {a["slug"]: a for a in self.ok("GET", "/agents")}

    def project(self, slug: str = "demo", members: list[str] | None = None) -> dict[str, Any]:
        body = {"slug": slug, "name": slug.title(), "members": members or []}
        result: dict[str, Any] = self.ok("POST", "/projects", 201, json=body)
        return result

    def task(self, project_id: str, title: str, **kw: Any) -> dict[str, Any]:
        body = {"project_id": project_id, "title": title, **kw}
        result: dict[str, Any] = self.ok("POST", "/tasks", 201, json=body)
        return result

    def run(self, task_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self.ok("POST", f"/tasks/{task_id}/run")
        return result

    def get_task(self, task_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self.ok("GET", f"/tasks/{task_id}")
        return result


@pytest.fixture
def office(client: TestClient) -> Office:
    return Office(client)
