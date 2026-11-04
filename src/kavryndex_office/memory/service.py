"""Persistent Memory Engine: memoria con alcance agente / proyecto / organización."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kavryndex_office.audit.service import record
from kavryndex_office.errors import NotFoundError, PermissionDeniedError
from kavryndex_office.models import Agent, AgentRole, MemoryEntry, MemoryScope

ORG_REF = "org"


def _scope_ref(scope: MemoryScope, *, agent_id: str | None, project_id: str | None) -> str:
    if scope is MemoryScope.AGENT:
        if not agent_id:
            raise PermissionDeniedError("La memoria de agente requiere agent_id")
        return agent_id
    if scope is MemoryScope.PROJECT:
        if not project_id:
            raise PermissionDeniedError("La memoria de proyecto requiere project_id")
        return project_id
    return ORG_REF


def check_write_permission(agent: Agent, scope: MemoryScope, project_id: str | None) -> None:
    if scope is MemoryScope.PROJECT and (
        not project_id or not agent.has_project_access(project_id)
    ):
        raise PermissionDeniedError(f"{agent.slug} no tiene acceso a la memoria de ese proyecto")
    if scope is MemoryScope.ORGANIZATION and agent.role is not AgentRole.EXECUTIVE:
        raise PermissionDeniedError("Solo el rol executive escribe memoria de organización")


def can_read(agent: Agent, entry: MemoryEntry) -> bool:
    if entry.scope is MemoryScope.ORGANIZATION:
        return True
    if entry.scope is MemoryScope.AGENT:
        return entry.scope_ref == agent.id
    return agent.has_project_access(entry.scope_ref)


def upsert(
    session: Session,
    *,
    scope: MemoryScope,
    key: str,
    content: str,
    actor: str,
    agent_id: str | None = None,
    project_id: str | None = None,
    source_task_id: str | None = None,
) -> MemoryEntry:
    """Crea o actualiza una entrada por (alcance, referencia, clave). Idempotente."""
    ref = _scope_ref(scope, agent_id=agent_id, project_id=project_id)
    entry = session.scalar(
        select(MemoryEntry).where(
            MemoryEntry.scope == scope, MemoryEntry.scope_ref == ref, MemoryEntry.key == key
        )
    )
    action = "memory.updated"
    if entry is None:
        action = "memory.created"
        entry = MemoryEntry(
            scope=scope,
            scope_ref=ref,
            key=key,
            agent_id=agent_id if scope is MemoryScope.AGENT else None,
            project_id=project_id if scope is MemoryScope.PROJECT else None,
            created_by=actor,
        )
        session.add(entry)
    entry.content = content
    entry.source_task_id = source_task_id
    session.flush()
    record(
        session,
        actor=actor,
        action=action,
        entity_type="memory",
        entity_id=entry.id,
        project_id=entry.project_id,
        details={"scope": scope.value, "key": key},
    )
    return entry


def readable_for_agent(
    session: Session,
    agent: Agent,
    *,
    project_id: str | None = None,
    query: str | None = None,
    limit: int = 20,
) -> list[MemoryEntry]:
    conditions = [
        MemoryEntry.scope == MemoryScope.ORGANIZATION,
        (MemoryEntry.scope == MemoryScope.AGENT) & (MemoryEntry.scope_ref == agent.id),
    ]
    # La memoria de proyecto solo se lee en el contexto de un proyecto con acceso.
    if project_id and agent.has_project_access(project_id):
        conditions.append(
            (MemoryEntry.scope == MemoryScope.PROJECT) & (MemoryEntry.scope_ref == project_id)
        )

    stmt = select(MemoryEntry).where(or_(*conditions))
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(MemoryEntry.key.ilike(like), MemoryEntry.content.ilike(like)))
    stmt = stmt.order_by(MemoryEntry.updated_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def list_entries(
    session: Session,
    *,
    scope: MemoryScope | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 100,
) -> list[MemoryEntry]:
    stmt = select(MemoryEntry).order_by(MemoryEntry.updated_at.desc()).limit(limit)
    if scope:
        stmt = stmt.where(MemoryEntry.scope == scope)
    if project_id:
        stmt = stmt.where(MemoryEntry.project_id == project_id)
    if agent_id:
        stmt = stmt.where(MemoryEntry.agent_id == agent_id)
    return list(session.scalars(stmt))


def delete(session: Session, entry_id: str, *, actor: str) -> None:
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        raise NotFoundError(f"Entrada de memoria {entry_id} no existe")
    record(
        session,
        actor=actor,
        action="memory.deleted",
        entity_type="memory",
        entity_id=entry.id,
        project_id=entry.project_id,
        details={"scope": entry.scope.value, "key": entry.key},
    )
    session.delete(entry)
