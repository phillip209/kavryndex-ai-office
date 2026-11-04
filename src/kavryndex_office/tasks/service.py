"""Task Management Engine: creación, asignación, dependencias y estados."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.agents import service as agent_service
from kavryndex_office.audit.service import record
from kavryndex_office.errors import InvalidStateError, NotFoundError, PermissionDeniedError
from kavryndex_office.models import (
    TERMINAL_STATUSES,
    Agent,
    AgentStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from kavryndex_office.projects import service as project_service


def get_task(session: Session, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"Tarea {task_id} no existe")
    return task


def list_tasks(
    session: Session,
    *,
    project_id: str | None = None,
    status: TaskStatus | None = None,
    assignee_id: str | None = None,
    parent_id: str | None = None,
) -> list[Task]:
    stmt = select(Task).order_by(Task.created_at)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if parent_id:
        stmt = stmt.where(Task.parent_id == parent_id)
    return list(session.scalars(stmt))


def list_runs(session: Session, task_id: str) -> list[TaskRun]:
    get_task(session, task_id)
    stmt = select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.attempt)
    return list(session.scalars(stmt))


def _check_assignable(agent: Agent, project_id: str) -> None:
    if agent.status is not AgentStatus.ACTIVE:
        raise InvalidStateError(f"El agente '{agent.slug}' está deshabilitado")
    if not agent.has_project_access(project_id):
        raise PermissionDeniedError(f"El agente '{agent.slug}' no tiene acceso a este proyecto")


def create_task(
    session: Session,
    *,
    project_id: str,
    title: str,
    actor: str,
    description: str = "",
    input: dict[str, Any] | None = None,
    priority: int = 0,
    assignee_slug: str | None = None,
    depends_on: list[str] | None = None,
    max_attempts: int = 2,
    parent_id: str | None = None,
) -> Task:
    project_service.get_project(session, project_id)
    dependencies: list[Task] = []
    for dep_id in depends_on or []:
        dep = get_task(session, dep_id)
        if dep.project_id != project_id:
            raise InvalidStateError("Las dependencias deben pertenecer al mismo proyecto")
        dependencies.append(dep)

    assignee: Agent | None = None
    if assignee_slug:
        assignee = agent_service.get_agent_by_slug(session, assignee_slug)
        _check_assignable(assignee, project_id)

    task = Task(
        project_id=project_id,
        title=title,
        description=description,
        input=input or {},
        priority=priority,
        assignee_id=assignee.id if assignee else None,
        parent_id=parent_id,
        created_by=actor,
        max_attempts=max_attempts,
        dependencies=dependencies,
    )
    session.add(task)
    session.flush()
    record(
        session,
        actor=actor,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        project_id=project_id,
        details={
            "title": title,
            "assignee": assignee_slug,
            "depends_on": [d.id for d in dependencies],
            "parent_id": parent_id,
        },
    )
    return task


def assign_task(session: Session, task_id: str, assignee_slug: str, *, actor: str) -> Task:
    task = get_task(session, task_id)
    if task.status is not TaskStatus.PENDING:
        raise InvalidStateError("Solo se pueden reasignar tareas pendientes")
    agent = agent_service.get_agent_by_slug(session, assignee_slug)
    _check_assignable(agent, task.project_id)
    task.assignee_id = agent.id
    record(
        session,
        actor=actor,
        action="task.assigned",
        entity_type="task",
        entity_id=task.id,
        project_id=task.project_id,
        details={"assignee": assignee_slug},
    )
    return task


def cancel_task(session: Session, task_id: str, *, actor: str) -> Task:
    task = get_task(session, task_id)
    if task.status in TERMINAL_STATUSES or task.status is TaskStatus.RUNNING:
        raise InvalidStateError(f"No se puede cancelar una tarea en estado {task.status.value}")
    task.status = TaskStatus.CANCELLED
    record(
        session,
        actor=actor,
        action="task.cancelled",
        entity_type="task",
        entity_id=task.id,
        project_id=task.project_id,
    )
    return task


def is_ready(task: Task) -> bool:
    return (
        task.status is TaskStatus.PENDING
        and task.assignee_id is not None
        and task.dependencies_completed()
    )


def ready_tasks(session: Session, project_id: str) -> list[Task]:
    pending = session.scalars(
        select(Task)
        .where(Task.project_id == project_id, Task.status == TaskStatus.PENDING)
        .order_by(Task.priority.desc(), Task.created_at)
    )
    return [t for t in pending if is_ready(t)]
