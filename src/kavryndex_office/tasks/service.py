"""Task Management Engine: creación, asignación, dependencias y estados."""

from datetime import datetime
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
from kavryndex_office.models.common import as_utc, utcnow
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
    limit: int | None = None,
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task).order_by(Task.created_at, Task.id).offset(offset).limit(limit)
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
    timeout_s: int = 300,
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
        timeout_s=timeout_s,
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


def is_due(task: Task, now: datetime) -> bool:
    return task.next_attempt_at is None or as_utc(task.next_attempt_at) <= now


def children(session: Session, task_id: str) -> list[Task]:
    stmt = select(Task).where(Task.parent_id == task_id).order_by(Task.created_at, Task.id)
    return list(session.scalars(stmt))


def descendants(session: Session, task: Task) -> list[Task]:
    """Subtareas delegadas a cualquier profundidad (orden de creación por nivel)."""
    result: list[Task] = []
    frontier = [task]
    while frontier:
        level = [c for t in frontier for c in children(session, t.id)]
        result.extend(level)
        frontier = level
    return result


def depth(session: Session, task: Task) -> int:
    """Nivel de delegación: 0 para tareas creadas por humanos."""
    level, current = 0, task
    while current.parent_id:
        parent = session.get(Task, current.parent_id)
        if parent is None:
            break
        level, current = level + 1, parent
    return level


def dependencies_satisfied(session: Session, task: Task) -> bool:
    if not task.dependencies_completed():
        return False
    if task.await_descendants:
        for dep in task.dependencies:
            if any(d.status not in TERMINAL_STATUSES for d in descendants(session, dep)):
                return False
    return True


def is_ready(session: Session, task: Task, now: datetime | None = None) -> bool:
    return (
        task.status is TaskStatus.PENDING
        and task.assignee_id is not None
        and is_due(task, now or utcnow())
        and dependencies_satisfied(session, task)
    )


def ready_tasks(session: Session, project_id: str, now: datetime | None = None) -> list[Task]:
    now = now or utcnow()
    pending = session.scalars(
        select(Task)
        .where(Task.project_id == project_id, Task.status == TaskStatus.PENDING)
        .order_by(Task.priority.desc(), Task.created_at, Task.id)
    )
    return [t for t in pending if is_ready(session, t, now)]


PLANNING_INSTRUCTIONS = (
    "Eres responsable de este objetivo. 1) Descompónlo en subtareas concretas y verificables. "
    "2) Asigna cada una con task_delegate al especialista adecuado del equipo disponible, con "
    "criterios de aceptación en la descripción y depends_on_titles cuando una necesite el "
    "resultado de otra. 3) Registra el objetivo y las decisiones clave con memory_write "
    "(scope project). 4) Responde con el plan: subtareas, responsables, orden y riesgos."
)
REPORT_INSTRUCTIONS = (
    "Consolida el trabajo del equipo para el director humano: qué se logró, qué falló y por "
    "qué, evidencias, riesgos y próximos pasos recomendados. No inventes resultados que no "
    "aparezcan en los resultados del equipo."
)


def create_goal(
    session: Session,
    *,
    project_id: str,
    title: str,
    actor: str,
    description: str = "",
    input: dict[str, Any] | None = None,
    priority: int = 0,
    planner_slug: str = "ceo",
) -> tuple[Task, Task]:
    """Crea un objetivo: tarea de planificación + informe final que espera a todo el equipo."""
    planner = agent_service.get_agent_by_slug(session, planner_slug)
    if not planner.can_delegate:
        raise PermissionDeniedError(f"El agente '{planner_slug}' no puede planificar (delegar)")
    goal_text = f"Objetivo: {title}" + (f"\n\n{description}" if description else "")
    plan = create_task(
        session,
        project_id=project_id,
        title=f"Planificar: {title}",
        description=f"{goal_text}\n\n{PLANNING_INSTRUCTIONS}",
        input=input,
        priority=priority,
        assignee_slug=planner_slug,
        actor=actor,
    )
    report = create_task(
        session,
        project_id=project_id,
        title=f"Informe final: {title}",
        description=f"{goal_text}\n\n{REPORT_INSTRUCTIONS}",
        priority=priority,
        assignee_slug=planner_slug,
        depends_on=[plan.id],
        actor=actor,
    )
    report.await_descendants = True
    record(
        session,
        actor=actor,
        action="goal.created",
        entity_type="task",
        entity_id=plan.id,
        project_id=project_id,
        details={"title": title, "report_task_id": report.id, "planner": planner_slug},
    )
    return plan, report


def _reaches(start: Task, target_id: str) -> bool:
    """True si ``target_id`` es alcanzable desde ``start`` siguiendo dependencias."""
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node.id == target_id:
            return True
        if node.id in seen:
            continue
        seen.add(node.id)
        stack.extend(node.dependencies)
    return False


def add_dependencies(session: Session, task_id: str, dep_ids: list[str], *, actor: str) -> Task:
    task = get_task(session, task_id)
    if task.status is not TaskStatus.PENDING:
        raise InvalidStateError("Solo se pueden cambiar dependencias de tareas pendientes")
    added: list[str] = []
    for dep_id in dict.fromkeys(dep_ids):
        if dep_id in task.dependency_ids:
            continue
        dep = get_task(session, dep_id)
        if dep.project_id != task.project_id:
            raise InvalidStateError("Las dependencias deben pertenecer al mismo proyecto")
        if dep.id == task.id or _reaches(dep, task.id):
            raise InvalidStateError(f"La dependencia '{dep.title}' crearía un ciclo")
        task.dependencies.append(dep)
        added.append(dep.id)
    if added:
        record(
            session,
            actor=actor,
            action="task.dependencies_added",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={"added": added},
        )
    return task


def remove_dependencies(session: Session, task_id: str, dep_ids: list[str], *, actor: str) -> Task:
    task = get_task(session, task_id)
    if task.status is not TaskStatus.PENDING:
        raise InvalidStateError("Solo se pueden cambiar dependencias de tareas pendientes")
    removed = [d.id for d in task.dependencies if d.id in dep_ids]
    task.dependencies = [d for d in task.dependencies if d.id not in dep_ids]
    if removed:
        record(
            session,
            actor=actor,
            action="task.dependencies_removed",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={"removed": removed},
        )
    return task


def retry_task(session: Session, task_id: str, *, actor: str) -> Task:
    """Reabre una tarea fallida con un presupuesto de intentos nuevo (decisión humana)."""
    task = get_task(session, task_id)
    if task.status is not TaskStatus.FAILED:
        raise InvalidStateError("Solo se pueden reintentar tareas fallidas")
    previous_error = task.error
    task.status = TaskStatus.PENDING
    task.attempts = 0
    task.error = None
    task.next_attempt_at = None
    task.completed_at = None
    record(
        session,
        actor=actor,
        action="task.requeued",
        entity_type="task",
        entity_id=task.id,
        project_id=task.project_id,
        details={"previous_error": previous_error},
    )
    return task
