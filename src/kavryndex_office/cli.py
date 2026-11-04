"""CLI de administración: ``kavryndex-office <comando>``.

Comandos:
  migrate           Aplica las migraciones pendientes.
  db-status         Muestra la revisión actual y la última disponible.
  bootstrap-agents  Crea los agentes por defecto que falten.
  generate-key      Genera una API key aleatoria (no la guarda en ningún sitio).
"""

import argparse
import secrets
import sys
from collections.abc import Sequence

from kavryndex_office.agents import service as agent_service
from kavryndex_office.audit.service import HUMAN_ADMIN
from kavryndex_office.config import Settings
from kavryndex_office.db import (
    current_revision,
    head_revision,
    init_db,
    make_engine,
    make_session_factory,
)

CLI_ACTOR = f"{HUMAN_ADMIN}:cli"


def _migrate(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        init_db(engine)
        print(f"Base de datos en la revisión {current_revision(engine)}")
    finally:
        engine.dispose()
    return 0


def _db_status(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        current, head = current_revision(engine), head_revision()
    finally:
        engine.dispose()
    print(f"actual: {current or '(vacía)'}  ·  última: {head}")
    return 0 if current == head else 1


def _bootstrap(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        init_db(engine)
        with make_session_factory(engine)() as session:
            created = agent_service.bootstrap_default_agents(session, actor=CLI_ACTOR)
            session.commit()
            names = ", ".join(a.slug for a in created) or "ninguno (ya existían)"
    finally:
        engine.dispose()
    print(f"Agentes creados: {names}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kavryndex-office", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("migrate", "db-status", "bootstrap-agents", "generate-key"):
        sub.add_parser(name)
    args = parser.parse_args(argv)

    if args.command == "generate-key":
        print(secrets.token_urlsafe(32))
        return 0
    settings = Settings()
    handlers = {"migrate": _migrate, "db-status": _db_status, "bootstrap-agents": _bootstrap}
    return handlers[args.command](settings)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
