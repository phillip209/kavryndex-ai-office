from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from kavryndex_office.db import Base
from kavryndex_office.models.common import IdMixin, enum_type, utcnow


class MessageKind(StrEnum):
    HANDOFF = "handoff"
    REPORT = "report"
    REQUEST = "request"


class Message(IdMixin, Base):
    __tablename__ = "messages"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    sender_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    recipient_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[MessageKind] = mapped_column(enum_type(MessageKind))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
