from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kavryndex_office.db import Base
from kavryndex_office.models.common import IdMixin, enum_type, utcnow


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"


class Approval(IdMixin, Base):
    __tablename__ = "approvals"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    tool_name: Mapped[str] = mapped_column(String(80))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus), default=ApprovalStatus.PENDING, index=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
