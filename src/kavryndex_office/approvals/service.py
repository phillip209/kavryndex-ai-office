"""Aprobaciones humanas para herramientas sensibles."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.audit.service import record
from kavryndex_office.errors import InvalidStateError, NotFoundError
from kavryndex_office.models import Approval, ApprovalStatus, Task, TaskStatus
from kavryndex_office.models.common import utcnow


def fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps({"tool": tool_name, "args": arguments}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_approval(session: Session, approval_id: str) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise NotFoundError(f"Aprobación {approval_id} no existe")
    return approval


def list_approvals(
    session: Session, *, status: ApprovalStatus | None = None, task_id: str | None = None
) -> list[Approval]:
    stmt = select(Approval).order_by(Approval.created_at)
    if status:
        stmt = stmt.where(Approval.status == status)
    if task_id:
        stmt = stmt.where(Approval.task_id == task_id)
    return list(session.scalars(stmt))


def find_approved(
    session: Session, task_id: str, tool_name: str, arguments: dict[str, Any]
) -> Approval | None:
    return session.scalar(
        select(Approval).where(
            Approval.task_id == task_id,
            Approval.fingerprint == fingerprint(tool_name, arguments),
            Approval.status == ApprovalStatus.APPROVED,
        )
    )


def request(
    session: Session,
    *,
    task: Task,
    agent_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    actor: str,
) -> Approval:
    fp = fingerprint(tool_name, arguments)
    existing = session.scalar(
        select(Approval).where(
            Approval.task_id == task.id,
            Approval.fingerprint == fp,
            Approval.status == ApprovalStatus.PENDING,
        )
    )
    if existing is not None:
        return existing
    approval = Approval(
        task_id=task.id,
        agent_id=agent_id,
        tool_name=tool_name,
        arguments=arguments,
        fingerprint=fp,
        reason=f"La herramienta '{tool_name}' requiere aprobación humana",
    )
    session.add(approval)
    session.flush()
    record(
        session,
        actor=actor,
        action="approval.requested",
        entity_type="approval",
        entity_id=approval.id,
        project_id=task.project_id,
        details={"task_id": task.id, "tool": tool_name},
    )
    return approval


def consume(session: Session, approval: Approval) -> None:
    approval.status = ApprovalStatus.CONSUMED


def decide(
    session: Session, approval_id: str, *, approve: bool, actor: str, note: str | None = None
) -> Approval:
    approval = get_approval(session, approval_id)
    if approval.status is not ApprovalStatus.PENDING:
        raise InvalidStateError(f"La aprobación ya está en estado {approval.status.value}")
    task = session.get(Task, approval.task_id)
    assert task is not None  # FK garantizada  # noqa: S101

    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_by = actor
    approval.decision_note = note
    approval.decided_at = utcnow()

    if task.status is TaskStatus.WAITING_APPROVAL:
        if approve:
            task.status = TaskStatus.PENDING
        else:
            task.status = TaskStatus.FAILED
            task.error = f"Aprobación rechazada para '{approval.tool_name}'" + (
                f": {note}" if note else ""
            )
            task.completed_at = utcnow()

    record(
        session,
        actor=actor,
        action="approval.approved" if approve else "approval.rejected",
        entity_type="approval",
        entity_id=approval.id,
        project_id=task.project_id,
        details={"task_id": task.id, "tool": approval.tool_name, "note": note},
    )
    return approval
