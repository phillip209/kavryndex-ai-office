"""Contrato de los adaptadores de IA. El núcleo solo depende de este módulo."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ChatMessage:
    role: Role
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class CompletionRequest:
    model: str
    messages: list[ChatMessage]
    tools: list[ToolDefinition] = field(default_factory=list)
    max_tokens: int = 1024
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class CompletionResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class LLMProvider(Protocol):
    name: str
    is_paid: bool

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    def cost_usd(self, usage: Usage) -> float: ...
