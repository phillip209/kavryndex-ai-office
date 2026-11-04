"""Modelos ORM. Importar este paquete registra todas las tablas."""

from kavryndex_office.models.agent import ALL_PROJECTS, Agent, AgentRole, AgentStatus
from kavryndex_office.models.approval import Approval, ApprovalStatus
from kavryndex_office.models.audit import AuditEvent
from kavryndex_office.models.communication import Message, MessageKind
from kavryndex_office.models.memory import MemoryEntry, MemoryScope
from kavryndex_office.models.project import Project, ProjectStatus
from kavryndex_office.models.task import (
    TERMINAL_STATUSES,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
    task_dependencies,
)

__all__ = [
    "ALL_PROJECTS",
    "TERMINAL_STATUSES",
    "Agent",
    "AgentRole",
    "AgentStatus",
    "Approval",
    "ApprovalStatus",
    "AuditEvent",
    "MemoryEntry",
    "MemoryScope",
    "Message",
    "MessageKind",
    "Project",
    "ProjectStatus",
    "RunStatus",
    "Task",
    "TaskRun",
    "TaskStatus",
    "task_dependencies",
]
