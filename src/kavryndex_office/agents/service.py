from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.agents.defaults import DEFAULT_AGENTS
from kavryndex_office.agents.schemas import AgentCreate, AgentUpdate
from kavryndex_office.audit.service import record
from kavryndex_office.errors import ConflictError, NotFoundError, ValidationFailedError
from kavryndex_office.models import ALL_PROJECTS, Agent, AgentRole, AgentStatus

DELEGATION_TOOL = "task_delegate"
# Campos cuyo cambio altera lo que el agente puede hacer: se auditan con valor previo y nuevo.
_SENSITIVE_FIELDS = (
    "provider",
    "model",
    "allowed_tools",
    "project_access",
    "can_delegate",
    "max_steps",
    "max_tokens_per_task",
    "status",
)


def _validate(
    *,
    role: AgentRole,
    allowed_tools: list[str],
    can_delegate: bool,
    provider: str,
    project_access: list[str],
    known_providers: list[str] | None,
) -> None:
    """Reglas de coherencia del registro de agentes."""
    from kavryndex_office.tools.registry import TOOLS  # import diferido: evita ciclo

    unknown = sorted(set(allowed_tools) - set(TOOLS))
    if unknown:
        raise ValidationFailedError(f"Herramientas desconocidas: {', '.join(unknown)}")
    if len(set(allowed_tools)) != len(allowed_tools):
        raise ValidationFailedError("allowed_tools contiene duplicados")
    if (DELEGATION_TOOL in allowed_tools) != can_delegate:
        raise ValidationFailedError(
            "can_delegate y la herramienta task_delegate deben activarse juntos"
        )
    if ALL_PROJECTS in project_access and role is not AgentRole.EXECUTIVE:
        raise ValidationFailedError(
            "Solo el rol executive puede tener acceso a todos los proyectos"
        )
    if known_providers is not None and provider not in known_providers:
        raise ValidationFailedError(
            f"Proveedor '{provider}' no configurado. Disponibles: {', '.join(known_providers)}"
        )


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


def create_agent(
    session: Session,
    data: AgentCreate,
    *,
    actor: str,
    known_providers: list[str] | None = None,
) -> Agent:
    if session.scalar(select(Agent).where(Agent.slug == data.slug)):
        raise ConflictError(f"Ya existe un agente con slug '{data.slug}'")
    _validate(
        role=data.role,
        allowed_tools=data.allowed_tools,
        can_delegate=data.can_delegate,
        provider=data.provider,
        project_access=data.project_access,
        known_providers=known_providers,
    )
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


def update_agent(
    session: Session,
    agent_id: str,
    data: AgentUpdate,
    *,
    actor: str,
    known_providers: list[str] | None = None,
) -> Agent:
    agent = get_agent(session, agent_id)
    changes = {
        k: v for k, v in data.model_dump(exclude_unset=True).items() if getattr(agent, k) != v
    }
    if not changes:
        return agent
    _validate(
        role=agent.role,
        allowed_tools=changes.get("allowed_tools", agent.allowed_tools),
        can_delegate=changes.get("can_delegate", agent.can_delegate),
        provider=changes.get("provider", agent.provider),
        project_access=changes.get("project_access", agent.project_access),
        known_providers=known_providers if "provider" in changes else None,
    )
    diff = {
        field: {"from": _plain(getattr(agent, field)), "to": _plain(value)}
        for field, value in changes.items()
        if field in _SENSITIVE_FIELDS
    }
    for field, value in changes.items():
        setattr(agent, field, value)
    agent.version += 1
    record(
        session,
        actor=actor,
        action="agent.updated",
        entity_type="agent",
        entity_id=agent.id,
        details={"fields": sorted(changes), "version": agent.version, "changes": diff},
    )
    return agent


def _plain(value: object) -> object:
    return value.value if isinstance(value, AgentRole | AgentStatus) else value


def bootstrap_default_agents(session: Session, *, actor: str) -> list[Agent]:
    """Crea los agentes por defecto que falten. Idempotente."""
    created: list[Agent] = []
    for spec in DEFAULT_AGENTS:
        if session.scalar(select(Agent).where(Agent.slug == spec.slug)) is None:
            created.append(create_agent(session, spec, actor=actor))
    return created
