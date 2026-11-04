"""Autenticación de la API y dependencias compartidas de FastAPI."""

import secrets
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from kavryndex_office.audit.service import HUMAN_ADMIN
from kavryndex_office.config import Settings
from kavryndex_office.execution.engine import ExecutionEngine
from kavryndex_office.execution.orchestrator import Orchestrator

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def require_admin(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Devuelve el actor autenticado. Sin clave configurada, todo acceso se rechaza."""
    expected = settings.admin_api_key
    if expected is None or not expected.get_secret_value():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "OFFICE_ADMIN_API_KEY no configurada"
        )
    if api_key is None or not secrets.compare_digest(
        api_key.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key inválida")
    return HUMAN_ADMIN


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine(request: Request) -> ExecutionEngine:
    engine: ExecutionEngine = request.app.state.engine
    return engine


def get_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator = request.app.state.orchestrator
    return orchestrator
