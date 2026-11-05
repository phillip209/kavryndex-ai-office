"""API Gateway: endpoints REST de todos los módulos.

Todas las rutas (excepto /health) exigen la cabecera ``X-API-Key``.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from kavryndex_office import __version__
from kavryndex_office.agents import service as agent_service
from kavryndex_office.agents.schemas import AgentCreate, AgentRead, AgentUpdate
from kavryndex_office.approvals import service as approval_service
from kavryndex_office.audit import service as audit_service
from kavryndex_office.communication import service as comm_service
from kavryndex_office.config import Settings
from kavryndex_office.execution.engine import ExecutionEngine
from kavryndex_office.execution.orchestrator import Orchestrator
from kavryndex_office.memory import service as memory_service
from kavryndex_office.models import ApprovalStatus, MemoryScope, MessageKind, TaskStatus
from kavryndex_office.projects import service as project_service
from kavryndex_office.projects.schemas import MembershipChange, ProjectCreate, ProjectRead
from kavryndex_office.security import (
    get_engine,
    get_orchestrator,
    get_session,
    get_settings,
    require_admin,
)
from kavryndex_office.tasks import service as task_service
from kavryndex_office.tasks.schemas import (
    DependencyChange,
    GoalCreate,
    GoalRead,
    TaskAssign,
    TaskCreate,
    TaskNode,
    TaskRead,
    TaskRunRead,
)
from kavryndex_office.tools.registry import TOOLS

public = APIRouter()
api = APIRouter(dependencies=[Depends(require_admin)])

SessionDep = Depends(get_session)
ActorDep = Depends(require_admin)
LimitQuery = Query(default=100, ge=1, le=500)
OffsetQuery = Query(default=0, ge=0)


# ---------------------------------------------------------------- esquemas de lectura simples
class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    task_id: str | None
    sender_agent_id: str
    recipient_agent_id: str | None
    kind: MessageKind
    content: str
    created_at: datetime


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    scope: MemoryScope
    project_id: str | None
    agent_id: str | None
    key: str
    content: str
    source_task_id: str | None
    created_by: str
    updated_at: datetime


class MemoryWrite(BaseModel):
    scope: MemoryScope
    key: str
    content: str
    project_id: str | None = None
    agent_id: str | None = None


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    task_id: str
    agent_id: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    status: ApprovalStatus
    decided_by: str | None
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class ApprovalDecision(BaseModel):
    note: str | None = None


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    project_id: str | None
    details: dict[str, Any]


class ToolRead(BaseModel):
    name: str
    description: str
    requires_approval: bool
    destructive: bool


# ---------------------------------------------------------------- sistema
@public.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@api.get("/system/info", tags=["system"])
def system_info(
    settings: Settings = Depends(get_settings), engine: ExecutionEngine = Depends(get_engine)
) -> dict[str, Any]:
    return {
        "version": __version__,
        "env": settings.env,
        "providers": engine.providers.names(),
        "allow_paid_providers": settings.allow_paid_providers,
    }


@api.get("/tools", response_model=list[ToolRead], tags=["system"])
def list_tools() -> list[ToolRead]:
    return [
        ToolRead(
            name=t.name,
            description=t.description,
            requires_approval=t.requires_approval,
            destructive=t.destructive,
        )
        for t in TOOLS.values()
    ]


# ---------------------------------------------------------------- agentes
@api.post("/agents", response_model=AgentRead, status_code=status.HTTP_201_CREATED, tags=["agents"])
def create_agent(
    data: AgentCreate,
    session: Session = SessionDep,
    actor: str = ActorDep,
    engine: ExecutionEngine = Depends(get_engine),
) -> Any:
    return agent_service.create_agent(
        session, data, actor=actor, known_providers=engine.providers.names()
    )


@api.post("/agents/bootstrap", response_model=list[AgentRead], tags=["agents"])
def bootstrap_agents(session: Session = SessionDep, actor: str = ActorDep) -> Any:
    return agent_service.bootstrap_default_agents(session, actor=actor)


@api.get("/agents", response_model=list[AgentRead], tags=["agents"])
def list_agents(session: Session = SessionDep) -> Any:
    return agent_service.list_agents(session)


@api.get("/agents/{agent_id}", response_model=AgentRead, tags=["agents"])
def get_agent(agent_id: str, session: Session = SessionDep) -> Any:
    return agent_service.get_agent(session, agent_id)


@api.patch("/agents/{agent_id}", response_model=AgentRead, tags=["agents"])
def update_agent(
    agent_id: str,
    data: AgentUpdate,
    session: Session = SessionDep,
    actor: str = ActorDep,
    engine: ExecutionEngine = Depends(get_engine),
) -> Any:
    return agent_service.update_agent(
        session, agent_id, data, actor=actor, known_providers=engine.providers.names()
    )


# ---------------------------------------------------------------- proyectos
@api.post(
    "/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, tags=["projects"]
)
def create_project(
    data: ProjectCreate, session: Session = SessionDep, actor: str = ActorDep
) -> Any:
    return project_service.create_project(session, data, actor=actor)


@api.get("/projects", response_model=list[ProjectRead], tags=["projects"])
def list_projects(session: Session = SessionDep) -> Any:
    return project_service.list_projects(session)


@api.get("/projects/{project_id}", response_model=ProjectRead, tags=["projects"])
def get_project(project_id: str, session: Session = SessionDep) -> Any:
    return project_service.get_project(session, project_id)


@api.post("/projects/{project_id}/members", status_code=204, tags=["projects"])
def grant_members(
    project_id: str, data: MembershipChange, session: Session = SessionDep, actor: str = ActorDep
) -> None:
    project_service.grant_access(session, project_id, data.agent_slugs, actor=actor)


@api.delete("/projects/{project_id}/members", status_code=204, tags=["projects"])
def revoke_members(
    project_id: str, data: MembershipChange, session: Session = SessionDep, actor: str = ActorDep
) -> None:
    project_service.revoke_access(session, project_id, data.agent_slugs, actor=actor)


@api.post("/projects/{project_id}/run", tags=["execution"])
def run_project(
    project_id: str,
    max_tasks: int | None = Query(default=None, ge=1, le=200),
    session: Session = SessionDep,
    actor: str = ActorDep,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
) -> Any:
    limit = min(max_tasks or settings.max_tasks_per_project_run, settings.max_tasks_per_project_run)
    return orchestrator.run_project(session, project_id, actor=actor, max_tasks=limit)


@api.post(
    "/projects/{project_id}/goals",
    response_model=GoalRead,
    status_code=status.HTTP_201_CREATED,
    tags=["execution"],
)
def create_goal(
    project_id: str, data: GoalCreate, session: Session = SessionDep, actor: str = ActorDep
) -> Any:
    plan, report = task_service.create_goal(
        session, project_id=project_id, actor=actor, **data.model_dump()
    )
    return {"plan_task": plan, "report_task": report}


# ---------------------------------------------------------------- tareas
@api.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED, tags=["tasks"])
def create_task(data: TaskCreate, session: Session = SessionDep, actor: str = ActorDep) -> Any:
    return task_service.create_task(session, actor=actor, **data.model_dump())


@api.get("/tasks", response_model=list[TaskRead], tags=["tasks"])
def list_tasks(
    project_id: str | None = None,
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    parent_id: str | None = None,
    limit: int = LimitQuery,
    offset: int = OffsetQuery,
    session: Session = SessionDep,
) -> Any:
    return task_service.list_tasks(
        session,
        project_id=project_id,
        status=status_filter,
        parent_id=parent_id,
        limit=limit,
        offset=offset,
    )


@api.get("/tasks/{task_id}", response_model=TaskRead, tags=["tasks"])
def get_task(task_id: str, session: Session = SessionDep) -> Any:
    return task_service.get_task(session, task_id)


@api.get("/tasks/{task_id}/tree", response_model=TaskNode, tags=["tasks"])
def task_tree(task_id: str, session: Session = SessionDep) -> TaskNode:
    def build(task: Any) -> TaskNode:
        return TaskNode(
            id=task.id,
            title=task.title,
            status=task.status,
            assignee_id=task.assignee_id,
            result=task.result,
            error=task.error,
            children=[build(c) for c in task_service.children(session, task.id)],
        )

    return build(task_service.get_task(session, task_id))


@api.post("/tasks/{task_id}/assign", response_model=TaskRead, tags=["tasks"])
def assign_task(
    task_id: str, data: TaskAssign, session: Session = SessionDep, actor: str = ActorDep
) -> Any:
    return task_service.assign_task(session, task_id, data.assignee_slug, actor=actor)


@api.post("/tasks/{task_id}/dependencies", response_model=TaskRead, tags=["tasks"])
def add_dependencies(
    task_id: str, data: DependencyChange, session: Session = SessionDep, actor: str = ActorDep
) -> Any:
    return task_service.add_dependencies(session, task_id, data.depends_on, actor=actor)


@api.delete("/tasks/{task_id}/dependencies", response_model=TaskRead, tags=["tasks"])
def remove_dependencies(
    task_id: str, data: DependencyChange, session: Session = SessionDep, actor: str = ActorDep
) -> Any:
    return task_service.remove_dependencies(session, task_id, data.depends_on, actor=actor)


@api.post("/tasks/{task_id}/retry", response_model=TaskRead, tags=["tasks"])
def retry_task(task_id: str, session: Session = SessionDep, actor: str = ActorDep) -> Any:
    return task_service.retry_task(session, task_id, actor=actor)


@api.post("/system/recover-stale", tags=["system"])
def recover_stale(
    session: Session = SessionDep, engine: ExecutionEngine = Depends(get_engine)
) -> dict[str, int]:
    return {"recovered": engine.recover_stale(session)}


@api.post("/tasks/{task_id}/cancel", response_model=TaskRead, tags=["tasks"])
def cancel_task(task_id: str, session: Session = SessionDep, actor: str = ActorDep) -> Any:
    return task_service.cancel_task(session, task_id, actor=actor)


@api.post("/tasks/{task_id}/run", response_model=TaskRunRead, tags=["execution"])
def run_task(
    task_id: str,
    session: Session = SessionDep,
    actor: str = ActorDep,
    engine: ExecutionEngine = Depends(get_engine),
) -> Any:
    return engine.run_task(session, task_id, actor=actor)


@api.get("/tasks/{task_id}/runs", response_model=list[TaskRunRead], tags=["execution"])
def list_runs(task_id: str, session: Session = SessionDep) -> Any:
    return task_service.list_runs(session, task_id)


# ---------------------------------------------------------------- aprobaciones
@api.get("/approvals", response_model=list[ApprovalRead], tags=["approvals"])
def list_approvals(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    task_id: str | None = None,
    limit: int = LimitQuery,
    offset: int = OffsetQuery,
    session: Session = SessionDep,
) -> Any:
    return approval_service.list_approvals(
        session, status=status_filter, task_id=task_id, limit=limit, offset=offset
    )


@api.post("/approvals/{approval_id}/approve", response_model=ApprovalRead, tags=["approvals"])
def approve(
    approval_id: str,
    data: ApprovalDecision | None = None,
    session: Session = SessionDep,
    actor: str = ActorDep,
) -> Any:
    note = data.note if data else None
    return approval_service.decide(session, approval_id, approve=True, actor=actor, note=note)


@api.post("/approvals/{approval_id}/reject", response_model=ApprovalRead, tags=["approvals"])
def reject(
    approval_id: str,
    data: ApprovalDecision | None = None,
    session: Session = SessionDep,
    actor: str = ActorDep,
) -> Any:
    note = data.note if data else None
    return approval_service.decide(session, approval_id, approve=False, actor=actor, note=note)


# ---------------------------------------------------------------- memoria, mensajes y auditoría
@api.get("/memory", response_model=list[MemoryRead], tags=["memory"])
def list_memory(
    scope: MemoryScope | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    limit: int = LimitQuery,
    offset: int = OffsetQuery,
    session: Session = SessionDep,
) -> Any:
    return memory_service.list_entries(
        session, scope=scope, project_id=project_id, agent_id=agent_id, limit=limit, offset=offset
    )


@api.put("/memory", response_model=MemoryRead, tags=["memory"])
def write_memory(data: MemoryWrite, session: Session = SessionDep, actor: str = ActorDep) -> Any:
    if data.project_id:
        project_service.get_project(session, data.project_id)
    if data.agent_id:
        agent_service.get_agent(session, data.agent_id)
    return memory_service.upsert(session, actor=actor, **data.model_dump())


@api.get("/messages", response_model=list[MessageRead], tags=["communication"])
def list_messages(
    project_id: str | None = None,
    task_id: str | None = None,
    limit: int = LimitQuery,
    offset: int = OffsetQuery,
    session: Session = SessionDep,
) -> Any:
    return comm_service.list_messages(
        session, project_id=project_id, task_id=task_id, limit=limit, offset=offset
    )


@api.get("/audit", response_model=list[AuditRead], tags=["audit"])
def list_audit(
    project_id: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = OffsetQuery,
    session: Session = SessionDep,
) -> Any:
    return audit_service.list_events(
        session,
        project_id=project_id,
        entity_id=entity_id,
        action=action,
        limit=limit,
        offset=offset,
    )
