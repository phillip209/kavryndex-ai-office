from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kavryndex_office.models import RunStatus, TaskStatus


class TaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-100, le=100)
    assignee_slug: str | None = None
    depends_on: list[str] = Field(default_factory=list, description="IDs de tareas previas.")
    max_attempts: int = Field(default=2, ge=1, le=10)
    timeout_s: int = Field(default=300, ge=10, le=3600)


class DependencyChange(BaseModel):
    depends_on: list[str] = Field(min_length=1)


class TaskAssign(BaseModel):
    assignee_slug: str


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    description: str
    input: dict[str, Any]
    status: TaskStatus
    priority: int
    assignee_id: str | None
    parent_id: str | None
    created_by: str
    dependency_ids: list[str]
    attempts: int
    max_attempts: int
    timeout_s: int
    next_attempt_at: datetime | None
    result: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TaskRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    agent_id: str
    attempt: int
    status: RunStatus
    provider: str
    model: str
    steps: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    output: str | None
    error: str | None
    tool_calls: list[dict[str, Any]]
    started_at: datetime
    finished_at: datetime | None
