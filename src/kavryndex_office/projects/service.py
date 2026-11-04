from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.agents import service as agent_service
from kavryndex_office.audit.service import record
from kavryndex_office.errors import ConflictError, NotFoundError
from kavryndex_office.models import Project
from kavryndex_office.projects.schemas import ProjectCreate


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Proyecto {project_id} no existe")
    return project


def list_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at)))


def create_project(session: Session, data: ProjectCreate, *, actor: str) -> Project:
    if session.scalar(select(Project).where(Project.slug == data.slug)):
        raise ConflictError(f"Ya existe un proyecto con slug '{data.slug}'")
    project = Project(slug=data.slug, name=data.name, description=data.description)
    session.add(project)
    session.flush()
    record(
        session,
        actor=actor,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        project_id=project.id,
        details={"slug": project.slug},
    )
    if data.members:
        grant_access(session, project.id, data.members, actor=actor)
    return project


def grant_access(session: Session, project_id: str, agent_slugs: list[str], *, actor: str) -> None:
    get_project(session, project_id)
    for slug in agent_slugs:
        agent = agent_service.get_agent_by_slug(session, slug)
        if project_id not in agent.project_access:
            agent.project_access = [*agent.project_access, project_id]
            record(
                session,
                actor=actor,
                action="project.access_granted",
                entity_type="agent",
                entity_id=agent.id,
                project_id=project_id,
                details={"agent": slug},
            )


def revoke_access(session: Session, project_id: str, agent_slugs: list[str], *, actor: str) -> None:
    get_project(session, project_id)
    for slug in agent_slugs:
        agent = agent_service.get_agent_by_slug(session, slug)
        if project_id in agent.project_access:
            agent.project_access = [p for p in agent.project_access if p != project_id]
            record(
                session,
                actor=actor,
                action="project.access_revoked",
                entity_type="agent",
                entity_id=agent.id,
                project_id=project_id,
                details={"agent": slug},
            )
