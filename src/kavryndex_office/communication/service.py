"""Inter-Agent Communication: entregas, informes y solicitudes ligadas a tareas."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.audit.service import record
from kavryndex_office.models import Message, MessageKind


def send(
    session: Session,
    *,
    project_id: str,
    sender_agent_id: str,
    kind: MessageKind,
    content: str,
    actor: str,
    task_id: str | None = None,
    recipient_agent_id: str | None = None,
) -> Message:
    message = Message(
        project_id=project_id,
        task_id=task_id,
        sender_agent_id=sender_agent_id,
        recipient_agent_id=recipient_agent_id,
        kind=kind,
        content=content,
    )
    session.add(message)
    session.flush()
    record(
        session,
        actor=actor,
        action="message.sent",
        entity_type="message",
        entity_id=message.id,
        project_id=project_id,
        details={"kind": kind.value, "task_id": task_id, "recipient": recipient_agent_id},
    )
    return message


def list_messages(
    session: Session,
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    recipient_agent_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Message]:
    stmt = select(Message).order_by(Message.created_at, Message.id).offset(offset).limit(limit)
    if project_id:
        stmt = stmt.where(Message.project_id == project_id)
    if task_id:
        stmt = stmt.where(Message.task_id == task_id)
    if recipient_agent_id:
        stmt = stmt.where(Message.recipient_agent_id == recipient_agent_id)
    return list(session.scalars(stmt))
