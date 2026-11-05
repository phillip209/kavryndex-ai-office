from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.models import AuditEvent

HUMAN_ADMIN = "human:admin"


def agent_actor(agent_slug: str) -> str:
    return f"agent:{agent_slug}"


def record(
    session: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    project_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Registra un evento de auditoría. Nunca incluir secretos en ``details``."""
    event = AuditEvent(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=project_id,
        details=details or {},
    )
    session.add(event)
    return event


def list_events(
    session: Session,
    *,
    project_id: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .offset(offset)
        .limit(limit)
    )
    if project_id:
        stmt = stmt.where(AuditEvent.project_id == project_id)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    return list(session.scalars(stmt))
