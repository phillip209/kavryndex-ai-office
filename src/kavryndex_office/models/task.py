from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kavryndex_office.db import Base
from kavryndex_office.models.common import IdMixin, TimestampMixin, enum_type, utcnow


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


task_dependencies = Table(
    "task_dependencies",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("depends_on_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
)


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[TaskStatus] = mapped_column(
        enum_type(TaskStatus), default=TaskStatus.PENDING, index=True
    )
    priority: Mapped[int] = mapped_column(default=0)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    created_by: Mapped[str] = mapped_column(String(80), default="human")
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=2)
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Reintentos con espera progresiva: la tarea no está lista antes de esta fecha.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Tiempo máximo de una ejecución (segundos), comprobado entre pasos del agente.
    timeout_s: Mapped[int] = mapped_column(default=300, server_default="300")

    dependencies: Mapped[list["Task"]] = relationship(
        secondary=task_dependencies,
        primaryjoin=lambda: Task.id == task_dependencies.c.task_id,
        secondaryjoin=lambda: Task.id == task_dependencies.c.depends_on_id,
        lazy="selectin",
    )

    @property
    def dependency_ids(self) -> list[str]:
        return [d.id for d in self.dependencies]

    def dependencies_completed(self) -> bool:
        return all(d.status == TaskStatus.COMPLETED for d in self.dependencies)


class TaskRun(IdMixin, Base):
    __tablename__ = "task_runs"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    attempt: Mapped[int] = mapped_column()
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus), default=RunStatus.RUNNING)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    steps: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
