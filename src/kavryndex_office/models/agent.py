from enum import StrEnum

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kavryndex_office.db import Base
from kavryndex_office.models.common import IdMixin, TimestampMixin, enum_type

ALL_PROJECTS = "*"


class AgentRole(StrEnum):
    EXECUTIVE = "executive"
    DEVELOPER = "developer"
    MARKETING = "marketing"
    RESEARCH = "research"
    QA = "qa"
    OPERATIONS = "operations"


class AgentStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Agent(IdMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[AgentRole] = mapped_column(enum_type(AgentRole))
    department: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    model: Mapped[str] = mapped_column(String(120), default="mock-1")
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    project_access: Mapped[list[str]] = mapped_column(JSON, default=list)
    can_delegate: Mapped[bool] = mapped_column(default=False)
    max_steps: Mapped[int] = mapped_column(default=6)
    max_tokens_per_task: Mapped[int] = mapped_column(default=20_000)
    status: Mapped[AgentStatus] = mapped_column(enum_type(AgentStatus), default=AgentStatus.ACTIVE)

    def has_project_access(self, project_id: str) -> bool:
        return ALL_PROJECTS in self.project_access or project_id in self.project_access

    def can_use_tool(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools
