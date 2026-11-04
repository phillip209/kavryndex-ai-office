from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from kavryndex_office.models import Agent, Task
from kavryndex_office.providers.base import ToolDefinition


@dataclass
class ToolContext:
    session: Session
    agent: Agent
    task: Task
    actor: str


ToolHandler = Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    requires_approval: bool = False
    destructive: bool = False

    def definition(self) -> ToolDefinition:
        return ToolDefinition(self.name, self.description, self.parameters)
