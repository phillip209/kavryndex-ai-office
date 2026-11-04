"""Entorno de Alembic. La URL sale de ``OFFICE_DATABASE_URL`` (o de la conexión recibida)."""

from alembic import context
from sqlalchemy.engine import Connection

from kavryndex_office import models  # noqa: F401  (registra los modelos)
from kavryndex_office.config import Settings
from kavryndex_office.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    engine = make_engine(_url())
    try:
        with engine.begin() as conn:
            _configure(conn)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
