"""Execution Engine: ejecuta una tarea con su agente de forma controlada."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kavryndex_office.agents import service as agent_service
from kavryndex_office.agents.defaults import with_office_rules
from kavryndex_office.approvals import service as approval_service
from kavryndex_office.audit.service import agent_actor, record
from kavryndex_office.communication import service as comm_service
from kavryndex_office.config import Settings
from kavryndex_office.errors import (
    BudgetExceededError,
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    TaskTimeoutError,
)
from kavryndex_office.memory import service as memory_service
from kavryndex_office.models import (
    Agent,
    AgentStatus,
    Approval,
    MessageKind,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from kavryndex_office.models.common import as_utc, utcnow
from kavryndex_office.providers.base import ChatMessage, CompletionRequest, LLMProvider, ToolCall
from kavryndex_office.providers.registry import ProviderRegistry
from kavryndex_office.tasks import service as task_service
from kavryndex_office.tools.base import ToolContext
from kavryndex_office.tools.registry import TOOLS, tools_for

MAX_COMPLETION_TOKENS = 1024
_PERMANENT_ERRORS = (PermissionDeniedError, BudgetExceededError, InvalidStateError, NotFoundError)
_RETRYABLE_ERRORS = (ProviderError, TaskTimeoutError)
_RECOVERABLE_TOOL_ERRORS = (InvalidStateError, NotFoundError, PermissionDeniedError, ValueError)


class ApprovalRequiredError(Exception):
    def __init__(self, approval: Approval) -> None:
        super().__init__(f"Aprobación requerida: {approval.id}")
        self.approval = approval


class ExecutionEngine:
    def __init__(
        self,
        providers: ProviderRegistry,
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.providers = providers
        self.settings = settings
        self.clock = clock

    def retry_delay(self, attempt: int) -> timedelta:
        base = self.settings.retry_base_delay_s * (2 ** max(attempt - 1, 0))
        return timedelta(seconds=min(base, self.settings.retry_max_delay_s))

    # ------------------------------------------------------------------ API pública
    def run_task(self, session: Session, task_id: str, *, actor: str) -> TaskRun:
        task = task_service.get_task(session, task_id)
        agent, provider = self._check_preconditions(session, task)

        task.status = TaskStatus.RUNNING
        task.attempts += 1
        task.started_at = task.started_at or self.clock()
        task.error = None
        task.next_attempt_at = None
        run = TaskRun(
            task_id=task.id,
            agent_id=agent.id,
            attempt=task.attempts,
            provider=provider.name,
            model=agent.model,
            tool_calls=[],
            started_at=self.clock(),
        )
        session.add(run)
        session.flush()
        record(
            session,
            actor=actor,
            action="task.started",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={"agent": agent.slug, "attempt": task.attempts, "run_id": run.id},
        )

        try:
            output = self._loop(session, task, agent, provider, run)
        except ApprovalRequiredError as exc:
            self._pause_for_approval(session, task, run, exc.approval)
        except _PERMANENT_ERRORS as exc:
            self._fail(session, task, run, exc, retry=False)
        except _RETRYABLE_ERRORS as exc:
            self._fail(session, task, run, exc, retry=task.attempts < task.max_attempts)
        else:
            self._complete(session, task, agent, run, output)
        session.flush()
        return run

    # ------------------------------------------------------------------ precondiciones
    def _check_preconditions(self, session: Session, task: Task) -> tuple[Agent, LLMProvider]:
        if task.status is not TaskStatus.PENDING:
            raise InvalidStateError(f"La tarea está en estado {task.status.value}, no pending")
        if task.assignee_id is None:
            raise InvalidStateError("La tarea no tiene agente asignado")
        if not task_service.dependencies_satisfied(session, task):
            raise InvalidStateError("La tarea tiene dependencias sin completar")
        if task.next_attempt_at and as_utc(task.next_attempt_at) > self.clock():
            raise InvalidStateError(
                f"Reintento programado para {as_utc(task.next_attempt_at).isoformat()}"
            )
        agent = agent_service.get_agent(session, task.assignee_id)
        if agent.status is not AgentStatus.ACTIVE:
            raise InvalidStateError(f"El agente '{agent.slug}' está deshabilitado")
        if not agent.has_project_access(task.project_id):
            raise PermissionDeniedError(f"El agente '{agent.slug}' no tiene acceso al proyecto")
        provider = self.providers.get(agent.provider)
        return agent, provider

    # ------------------------------------------------------------------ bucle
    def _loop(
        self, session: Session, task: Task, agent: Agent, provider: LLMProvider, run: TaskRun
    ) -> str:
        tools = tools_for(agent.allowed_tools)
        if task.await_descendants:
            # Un informe de consolidación no crea trabajo nuevo que nadie esperaría.
            tools = [t for t in tools if t.name != "task_delegate"]
        messages = [
            ChatMessage("system", with_office_rules(agent.system_prompt)),
            ChatMessage("user", self._build_prompt(session, task, agent)),
        ]
        metadata: dict[str, Any] = {
            **task.input,
            "task_title": task.title,
            "agent_slug": agent.slug,
            "attempt": task.attempts,
        }
        ctx = ToolContext(
            session=session,
            agent=agent,
            task=task,
            actor=agent_actor(agent.slug),
            settings=self.settings,
        )
        deadline = self.clock() + timedelta(seconds=task.timeout_s)

        for step in range(1, agent.max_steps + 1):
            if self.clock() > deadline:
                raise TaskTimeoutError(f"Tiempo máximo excedido ({task.timeout_s} s)")
            run.steps = step
            response = provider.complete(
                CompletionRequest(
                    model=agent.model,
                    messages=messages,
                    tools=[t.definition() for t in tools],
                    max_tokens=MAX_COMPLETION_TOKENS,
                    metadata=metadata,
                )
            )
            run.input_tokens += response.usage.input_tokens
            run.output_tokens += response.usage.output_tokens
            run.cost_usd += provider.cost_usd(response.usage)
            if run.input_tokens + run.output_tokens > agent.max_tokens_per_task:
                raise BudgetExceededError(
                    f"Límite de tokens excedido ({agent.max_tokens_per_task})"
                )
            if not response.tool_calls:
                return response.content

            messages.append(ChatMessage("assistant", response.content, response.tool_calls))
            for call in response.tool_calls:
                result = self._invoke_tool(ctx, call, run)
                messages.append(
                    ChatMessage("tool", json.dumps(result, default=str), tool_call_id=call.id)
                )

        raise BudgetExceededError(f"Límite de pasos excedido ({agent.max_steps})")

    def _invoke_tool(self, ctx: ToolContext, call: ToolCall, run: TaskRun) -> dict[str, Any]:
        session, agent, task = ctx.session, ctx.agent, ctx.task
        spec = TOOLS.get(call.name)
        if spec is None or not agent.can_use_tool(call.name):
            record(
                session,
                actor=ctx.actor,
                action="tool.denied",
                entity_type="task",
                entity_id=task.id,
                project_id=task.project_id,
                details={"tool": call.name},
            )
            raise PermissionDeniedError(f"El agente '{agent.slug}' no puede usar '{call.name}'")

        if spec.requires_approval:
            approval = approval_service.find_approved(session, task.id, call.name, call.arguments)
            if approval is None:
                pending = approval_service.request(
                    session,
                    task=task,
                    agent_id=agent.id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    actor=ctx.actor,
                )
                raise ApprovalRequiredError(pending)
            approval_service.consume(session, approval)

        ok = True
        try:
            with session.begin_nested():
                result = spec.handler(ctx, call.arguments)
        except _RECOVERABLE_TOOL_ERRORS as exc:
            ok = False
            result = {"error": str(exc)}

        record(
            session,
            actor=ctx.actor,
            action="tool.executed" if ok else "tool.error",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={"tool": call.name, "ok": ok},
        )
        run.tool_calls = [
            *run.tool_calls,
            {"name": call.name, "arguments": call.arguments, "ok": ok},
        ]
        return result

    # ------------------------------------------------------------------ contexto
    def _build_prompt(self, session: Session, task: Task, agent: Agent) -> str:
        parts = [f"# Tarea: {task.title}"]
        if task.description:
            parts.append(task.description)
        visible_input = {k: v for k, v in task.input.items() if not k.startswith("mock_")}
        if visible_input:
            parts.append("## Entrada\n" + json.dumps(visible_input, ensure_ascii=False, indent=2))
        if task.dependencies:
            lines = [f"- {d.title}: {d.result or '(sin resultado)'}" for d in task.dependencies]
            parts.append("## Resultados entregados por tareas previas\n" + "\n".join(lines))
        if task.await_descendants:
            team = [d for dep in task.dependencies for d in task_service.descendants(session, dep)]
            if team:
                names = {a.id: a.slug for a in agent_service.list_agents(session)}
                lines = [
                    f"- [{d.status.value}] {d.title} ({names.get(d.assignee_id or '', '?')}): "
                    f"{d.result or d.error or '(sin resultado)'}"
                    for d in team
                ]
                parts.append("## Resultados del equipo\n" + "\n".join(lines))
        if agent.can_delegate:
            roster = [
                a
                for a in agent_service.list_agents(session)
                if a.id != agent.id
                and a.status is AgentStatus.ACTIVE
                and a.has_project_access(task.project_id)
            ]
            lines = [f"- {a.slug}: {a.name} — {a.department}. {a.description}" for a in roster]
            parts.append(
                "## Equipo disponible para delegar (assignee_slug)\n"
                + ("\n".join(lines) or "(ningún especialista tiene acceso a este proyecto)")
            )
        entries = memory_service.readable_for_agent(
            session, agent, project_id=task.project_id, limit=self.settings.memory_context_limit
        )
        if entries:
            lines = [f"- [{e.scope.value}] {e.key}: {e.content}" for e in entries]
            parts.append("## Memoria disponible\n" + "\n".join(lines))
        parts.append(
            "## Entrega\nResponde con un informe final: resultado, evidencias, riesgos y "
            "próximos pasos."
        )
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ cierres
    def _complete(
        self, session: Session, task: Task, agent: Agent, run: TaskRun, output: str
    ) -> None:
        now = self.clock()
        task.status = TaskStatus.COMPLETED
        task.result = output
        task.completed_at = now
        run.status = RunStatus.COMPLETED
        run.output = output
        run.finished_at = now

        recipient_id = None
        if task.parent_id:
            parent = session.get(Task, task.parent_id)
            recipient_id = parent.assignee_id if parent else None
        comm_service.send(
            session,
            project_id=task.project_id,
            task_id=task.id,
            sender_agent_id=agent.id,
            recipient_agent_id=recipient_id,
            kind=MessageKind.HANDOFF if recipient_id else MessageKind.REPORT,
            content=output,
            actor=agent_actor(agent.slug),
        )
        record(
            session,
            actor=agent_actor(agent.slug),
            action="task.completed",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={
                "run_id": run.id,
                "steps": run.steps,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cost_usd": run.cost_usd,
            },
        )

    def _pause_for_approval(
        self, session: Session, task: Task, run: TaskRun, approval: Approval
    ) -> None:
        task.status = TaskStatus.WAITING_APPROVAL
        task.attempts -= 1  # una pausa no consume intentos
        run.status = RunStatus.WAITING_APPROVAL
        run.finished_at = self.clock()
        record(
            session,
            actor="system",
            action="task.waiting_approval",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={"approval_id": approval.id, "tool": approval.tool_name},
        )

    def _fail(
        self, session: Session, task: Task, run: TaskRun, exc: Exception, *, retry: bool
    ) -> None:
        now = self.clock()
        message = f"{type(exc).__name__}: {exc}"
        run.status = RunStatus.FAILED
        run.error = message
        run.finished_at = now
        task.error = message
        if retry:
            task.status = TaskStatus.PENDING
            task.next_attempt_at = now + self.retry_delay(task.attempts)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = now
        record(
            session,
            actor="system",
            action="task.retry_scheduled" if retry else "task.failed",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
            details={
                "error": message,
                "attempt": task.attempts,
                "next_attempt_at": task.next_attempt_at.isoformat()
                if retry and task.next_attempt_at
                else None,
            },
        )

    # ------------------------------------------------------------------ recuperación
    def recover_stale(self, session: Session, *, project_id: str | None = None) -> int:
        """Cierra ejecuciones que quedaron en 'running' (p. ej. el proceso se reinició).

        La tarea vuelve a 'pending' si le quedan intentos; si no, queda 'failed'.
        """
        cutoff = self.clock() - timedelta(seconds=self.settings.stale_run_after_s)
        stmt = select(TaskRun).where(TaskRun.status == RunStatus.RUNNING)
        if project_id:
            stmt = stmt.join(Task, Task.id == TaskRun.task_id).where(Task.project_id == project_id)
        recovered = 0
        for run in session.scalars(stmt):
            if as_utc(run.started_at) > cutoff:
                continue
            task = session.get(Task, run.task_id)
            if task is None or task.status is not TaskStatus.RUNNING:
                run.status = RunStatus.FAILED
                run.finished_at = self.clock()
                continue
            self._fail(
                session,
                task,
                run,
                TaskTimeoutError("Ejecución interrumpida (sin finalizar)"),
                retry=task.attempts < task.max_attempts,
            )
            recovered += 1
        return recovered
