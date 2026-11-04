from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.agents.defaults import DEFAULT_AGENTS
from kavryndex_office.agents.schemas import AgentCreate, AgentUpdate
from kavryndex_office.audit.service import record
from kavryndex_office.errors import ConflictError, NotFoundError, PermissionDeniedError
from kavryndex_office.models import Agent


def _validate_tools(tool_names: list[str]) -> None:
    from kavryndex_office.tools.registry import TOOLS  # import diferido: evita ciclo

    unknown = sorted(set(tool_names) - set(TOOLS))
    if unknown:
        raise PermissionDeniedError(f"Herramientas desconocidas: {', '.join(unknown)}")


def get_agent(session: Session, agent_id: str) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise NotFoundError(f"Agente {agent_id} no existe")
    return agent


def get_agent_by_slug(session: Session, slug: str) -> Agent:
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    if agent is None:
        raise NotFoundError(f"Agente '{slug}' no existe")
    return agent


def list_agents(session: Session) -> list[Agent]:
    return list(session.scalars(select(Agent).order_by(Agent.created_at)))


def create_agent(session: Session, data: AgentCreate, *, actor: str) -> Agent:
    if session.scalar(select(Agent).where(Agent.slug == data.slug)):
        raise ConflictError(f"Ya existe un agente con slug '{data.slug}'")
    _validate_tools(data.allowed_tools)
    agent = Agent(**data.model_dump())
    session.add(agent)
    session.flush()
    record(
        session,
        actor=actor,
        action="agent.created",
        entity_type="agent",
        entity_id=agent.id,
        details={"slug": agent.slug, "role": agent.role.value},
    )
    return agent


def update_agent(session: Session, agent_id: str, data: AgentUpdate, *, actor: str) -> Agent:
    agent = get_agent(session, agent_id)
    changes = data.model_dump(exclude_unset=True)
    if "allowed_tools" in changes:
        _validate_tools(changes["allowed_tools"])
    for field, value in changes.items():
        setattr(agent, field, value)
    record(
        session,
        actor=actor,
        action="agent.updated",
        entity_type="agent",
        entity_id=agent.id,
        details={"fields": sorted(changes)},
    )
    return agent


def bootstrap_default_agents(session: Session, *, actor: str) -> list[Agent]:
    """Crea los agentes por defecto que falten. Idempotente."""
    created: list[Agent] = []
    for spec in DEFAULT_AGENTS:
        if session.scalar(select(Agent).where(Agent.slug == spec.slug)) is None:
            created.append(create_agent(session, spec, actor=actor))
    return created
