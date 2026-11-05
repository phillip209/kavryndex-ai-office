"""Motor de base de datos y sesiones (SQLite o PostgreSQL)."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

if TYPE_CHECKING:
    from alembic.config import Config

# Nombres de restricciones deterministas: necesarios para migraciones fiables (Alembic).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            db_path = url.split("///", 1)[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    elif url.startswith("postgresql"):
        # Todas las fechas se leen y escriben en UTC, sea cual sea la zona del servidor.
        kwargs["connect_args"] = {"options": "-c timezone=UTC"}
    engine = create_engine(url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def alembic_config() -> "Config":
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", "kavryndex_office:migrations")
    return config


def init_db(engine: Engine) -> None:
    """Aplica todas las migraciones pendientes (``alembic upgrade head``)."""
    from alembic import command

    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def current_revision(engine: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def check_up_to_date(engine: Engine) -> None:
    current, head = current_revision(engine), head_revision()
    if current != head:
        raise RuntimeError(
            f"Base de datos en revisión {current!r}; se requiere {head!r}. "
            "Ejecuta 'kavryndex-office migrate'."
        )
