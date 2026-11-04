from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kavryndex_office.db import Base
from kavryndex_office.models.common import IdMixin, TimestampMixin, enum_type


class MemoryScope(StrEnum):
    AGENT = "agent"
    PROJECT = "project"
    ORGANIZATION = "organization"


class MemoryEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "memory_entries"
    __table_args__ = (UniqueConstraint("scope", "scope_ref", "key", name="uq_memory_scope_key"),)

    scope: Mapped[MemoryScope] = mapped_column(enum_type(MemoryScope), index=True)
    # Referencia normalizada del alcance: id de agente, id de proyecto u "org".
    scope_ref: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    key: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    created_by: Mapped[str] = mapped_column(String(80), default="human")
