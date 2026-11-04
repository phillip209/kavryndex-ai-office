"""Herramientas internas. Ninguna ejecuta comandos del sistema ni accede a archivos."""

from typing import Any

from sqlalchemy import select

from kavryndex_office.agents import service as agent_service
from kavryndex_office.communication import service as comm_service
from kavryndex_office.errors import InvalidStateError, NotFoundError, PermissionDeniedError
from kavryndex_office.memory import service as memory_service
from kavryndex_office.models import MemoryEntry, MemoryScope, MessageKind, Task
from kavryndex_office.tasks import service as task_service
from kavryndex_office.tools.base import ToolContext, ToolSpec


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidStateError(f"Argumento '{key}' obligatorio")
    return value.strip()


def memory_write(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    scope = MemoryScope(args.get("scope", MemoryScope.PROJECT.value))
    memory_service.check_write_permission(ctx.agent, scope, ctx.task.project_id)
    entry = memory_service.upsert(
        ctx.session,
        scope=scope,
        key=_require_str(args, "key"),
        content=_require_str(args, "content"),
        actor=ctx.actor,
        agent_id=ctx.agent.id,
        project_id=ctx.task.project_id,
        source_task_id=ctx.task.id,
    )
    return {"memory_id": entry.id, "scope": scope.value, "key": entry.key}


def memory_search(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entries = memory_service.readable_for_agent(
        ctx.session,
        ctx.agent,
        project_id=ctx.task.project_id,
        query=args.get("query") or None,
        limit=int(args.get("limit", 10)),
    )
    return {
        "results": [
            {"id": e.id, "scope": e.scope.value, "key": e.key, "content": e.content}
            for e in entries
        ]
    }


def memory_delete(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entry_id = _require_str(args, "entry_id")
    entry = ctx.session.get(MemoryEntry, entry_id)
    if entry is None:
        raise NotFoundError(f"Entrada de memoria {entry_id} no existe")
    if not memory_service.can_read(ctx.agent, entry):
        raise PermissionDeniedError("Sin acceso a esa entrada de memoria")
    memory_service.delete(ctx.session, entry_id, actor=ctx.actor)
    return {"deleted": entry_id}


def message_send(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    recipient_id = None
    if args.get("recipient_slug"):
        recipient = agent_service.get_agent_by_slug(ctx.session, str(args["recipient_slug"]))
        if not recipient.has_project_access(ctx.task.project_id):
            raise PermissionDeniedError("El destinatario no tiene acceso a este proyecto")
        recipient_id = recipient.id
    message = comm_service.send(
        ctx.session,
        project_id=ctx.task.project_id,
        task_id=ctx.task.id,
        sender_agent_id=ctx.agent.id,
        recipient_agent_id=recipient_id,
        kind=MessageKind(args.get("kind", MessageKind.REPORT.value)),
        content=_require_str(args, "content"),
        actor=ctx.actor,
    )
    return {"message_id": message.id}


def task_delegate(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not ctx.agent.can_delegate:
        raise PermissionDeniedError(f"{ctx.agent.slug} no puede delegar")
    title = _require_str(args, "title")

    # Idempotencia: misma subtarea (padre + título) no se duplica al reanudar.
    existing = ctx.session.scalar(
        select(Task).where(Task.parent_id == ctx.task.id, Task.title == title)
    )
    if existing is not None:
        return {"task_id": existing.id, "created": False}

    siblings = {
        t.title: t.id
        for t in ctx.session.scalars(select(Task).where(Task.parent_id == ctx.task.id))
    }
    depends_on: list[str] = []
    for dep_title in args.get("depends_on_titles") or []:
        if dep_title not in siblings:
            raise InvalidStateError(f"Dependencia '{dep_title}' no es una subtarea existente")
        depends_on.append(siblings[dep_title])

    task = task_service.create_task(
        ctx.session,
        project_id=ctx.task.project_id,
        title=title,
        description=str(args.get("description", "")),
        input=dict(args.get("input") or {}),
        priority=int(args.get("priority", 0)),
        assignee_slug=_require_str(args, "assignee_slug"),
        depends_on=depends_on,
        parent_id=ctx.task.id,
        actor=ctx.actor,
    )
    return {"task_id": task.id, "created": True}


_SCOPE = {"type": "string", "enum": [s.value for s in MemoryScope]}

BUILTIN_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="memory_write",
        description="Guarda o actualiza conocimiento por clave (agent/project/organization).",
        parameters={
            "type": "object",
            "properties": {
                "scope": _SCOPE,
                "key": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["key", "content"],
        },
        handler=memory_write,
    ),
    ToolSpec(
        name="memory_search",
        description="Busca en la memoria legible por el agente.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        },
        handler=memory_search,
    ),
    ToolSpec(
        name="memory_delete",
        description="Elimina una entrada de memoria. Requiere aprobación humana.",
        parameters={
            "type": "object",
            "properties": {"entry_id": {"type": "string"}},
            "required": ["entry_id"],
        },
        handler=memory_delete,
        requires_approval=True,
        destructive=True,
    ),
    ToolSpec(
        name="message_send",
        description="Envía un informe, solicitud o entrega ligada a la tarea actual.",
        parameters={
            "type": "object",
            "properties": {
                "recipient_slug": {"type": "string"},
                "kind": {"type": "string", "enum": [k.value for k in MessageKind]},
                "content": {"type": "string"},
            },
            "required": ["content"],
        },
        handler=message_send,
    ),
    ToolSpec(
        name="task_delegate",
        description=(
            "Crea una subtarea asignada a otro agente. Usa depends_on_titles para indicar "
            "subtareas previas de esta misma tarea."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "assignee_slug": {"type": "string"},
                "priority": {"type": "integer"},
                "depends_on_titles": {"type": "array", "items": {"type": "string"}},
                "input": {"type": "object"},
            },
            "required": ["title", "assignee_slug"],
        },
        handler=task_delegate,
    ),
]
