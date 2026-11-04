"""Fábrica de la aplicación FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from kavryndex_office import __version__
from kavryndex_office.config import Settings
from kavryndex_office.db import check_up_to_date, init_db, make_engine, make_session_factory
from kavryndex_office.errors import (
    BudgetExceededError,
    ConflictError,
    InvalidStateError,
    NotFoundError,
    OfficeError,
    PermissionDeniedError,
    ValidationFailedError,
)
from kavryndex_office.execution.engine import ExecutionEngine
from kavryndex_office.execution.orchestrator import Orchestrator
from kavryndex_office.providers.registry import ProviderRegistry, build_registry
from kavryndex_office.routers import api, public

_STATUS_BY_ERROR: dict[type[OfficeError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    InvalidStateError: status.HTTP_409_CONFLICT,
    BudgetExceededError: status.HTTP_402_PAYMENT_REQUIRED,
    ValidationFailedError: 422,
}


def create_app(
    settings: Settings | None = None, providers: ProviderRegistry | None = None
) -> FastAPI:
    settings = settings or Settings()
    db_engine = make_engine(settings.database_url)
    try:
        if settings.auto_migrate:
            init_db(db_engine)
        else:
            check_up_to_date(db_engine)
    except Exception:
        db_engine.dispose()
        raise
    registry = providers or build_registry(settings)
    execution = ExecutionEngine(registry, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        db_engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="KAVRYNDEX AI OFFICE",
        version=__version__,
        description="API del núcleo multiagente de KAVRYNDEX AI OFFICE.",
    )
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)
    app.state.engine = execution
    app.state.orchestrator = Orchestrator(execution)

    @app.exception_handler(OfficeError)
    async def _office_error(_request: Request, exc: OfficeError) -> JSONResponse:
        code = next(
            (c for t, c in _STATUS_BY_ERROR.items() if isinstance(exc, t)),
            status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(
            status_code=code, content={"error": type(exc).__name__, "detail": str(exc)}
        )

    app.include_router(public)
    app.include_router(api, prefix="/api/v1")
    return app
