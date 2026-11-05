"""Core Orchestrator: ejecuta bajo demanda las tareas listas de un proyecto."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from kavryndex_office.audit.service import record
from kavryndex_office.execution.engine import ExecutionEngine
from kavryndex_office.models import TaskStatus
from kavryndex_office.projects import service as project_service
from kavryndex_office.tasks import service as task_service


@dataclass
class ProjectRunSummary:
    project_id: str
    executed: list[dict[str, str]] = field(default_factory=list)
    stopped_reason: str = "no_ready_tasks"
    remaining_pending: int = 0
    deferred_retries: int = 0
    waiting_approval: int = 0
    recovered_stale_runs: int = 0


class Orchestrator:
    def __init__(self, engine: ExecutionEngine) -> None:
        self.engine = engine

    def run_project(
        self, session: Session, project_id: str, *, actor: str, max_tasks: int
    ) -> ProjectRunSummary:
        """Ejecuta tareas listas por prioridad hasta que no queden o se alcance el límite.

        Hace commit tras cada tarea para que un fallo posterior no pierda trabajo terminado.
        """
        project_service.get_project(session, project_id)
        summary = ProjectRunSummary(project_id=project_id)
        summary.recovered_stale_runs = self.engine.recover_stale(session, project_id=project_id)
        record(
            session,
            actor=actor,
            action="project.run_started",
            entity_type="project",
            entity_id=project_id,
            project_id=project_id,
            details={"max_tasks": max_tasks},
        )
        session.commit()

        while True:
            if len(summary.executed) >= max_tasks:
                summary.stopped_reason = "max_tasks_reached"
                break
            ready = task_service.ready_tasks(session, project_id, self.engine.clock())
            if not ready:
                break
            task = ready[0]
            run = self.engine.run_task(session, task.id, actor=actor)
            session.commit()
            summary.executed.append(
                {"task_id": task.id, "title": task.title, "run_id": run.id, "status": task.status}
            )

        tasks = task_service.list_tasks(session, project_id=project_id)
        now = self.engine.clock()
        pending = [t for t in tasks if t.status is TaskStatus.PENDING]
        summary.remaining_pending = len(pending)
        summary.deferred_retries = sum(not task_service.is_due(t, now) for t in pending)
        summary.waiting_approval = sum(t.status is TaskStatus.WAITING_APPROVAL for t in tasks)
        return summary
