from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from kavryndex_office.models import AgentRole, AgentStatus
from kavryndex_office.projects.schemas import SLUG_PATTERN


class AgentCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    role: AgentRole
    department: str = Field(min_length=1, max_length=120)
    description: str = ""
    system_prompt: str = Field(min_length=1)
    provider: str = "mock"
    model: str = "mock-1"
    allowed_tools: list[str] = Field(default_factory=list)
    project_access: list[str] = Field(default_factory=list)
    can_delegate: bool = False
    max_steps: int = Field(default=6, ge=1, le=50)
    max_tokens_per_task: int = Field(default=20_000, ge=100, le=2_000_000)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    system_prompt: str | None = Field(default=None, min_length=1)
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] | None = None
    project_access: list[str] | None = None
    can_delegate: bool | None = None
    max_steps: int | None = Field(default=None, ge=1, le=50)
    max_tokens_per_task: int | None = Field(default=None, ge=100, le=2_000_000)
    status: AgentStatus | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    role: AgentRole
    department: str
    description: str
    system_prompt: str
    provider: str
    model: str
    allowed_tools: list[str]
    project_access: list[str]
    can_delegate: bool
    max_steps: int
    max_tokens_per_task: int
    status: AgentStatus
    created_at: datetime
    updated_at: datetime
