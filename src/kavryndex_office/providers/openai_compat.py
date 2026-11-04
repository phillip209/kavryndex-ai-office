"""Adaptador para APIs compatibles con OpenAI Chat Completions.

Sirve para Ollama (local), Groq, Gemini (endpoint OpenAI-compatible) y otros, sin SDKs.
Los nombres de herramientas deben cumplir ``^[a-zA-Z0-9_-]+$``.
"""

import json
from typing import Any

import httpx

from kavryndex_office.errors import ProviderError
from kavryndex_office.providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    ToolCall,
    Usage,
)


def _to_wire(message: ChatMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in message.tool_calls
        ]
    if message.tool_call_id:
        wire["tool_call_id"] = message.tool_call_id
    return wire


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        is_paid: bool,
        timeout_s: float = 60.0,
        input_price_per_mtok: float = 0.0,
        output_price_per_mtok: float = 0.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.is_paid = is_paid
        self._input_price = input_price_per_mtok
        self._output_price = output_price_per_mtok
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport
        )

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [_to_wire(m) for m in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            # No se incluye el cuerpo de la respuesta para no filtrar datos sensibles.
            raise ProviderError(
                f"Error del proveedor OpenAI-compatible: {type(exc).__name__}"
            ) from exc

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=raw.get("id", ""), name=fn.get("name", ""), arguments=args))

        usage = data.get("usage") or {}
        return CompletionResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
        )

    def cost_usd(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self._input_price + usage.output_tokens * self._output_price
        ) / 1_000_000
