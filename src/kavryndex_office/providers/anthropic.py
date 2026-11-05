"""Adaptador para la Messages API de Anthropic (Claude), sin SDK.

Es un proveedor de pago: solo se ejecuta con ``OFFICE_ALLOW_PAID_PROVIDERS=true`` y con
precios configurados, para que el coste de cada ejecución quede registrado.
"""

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

API_VERSION = "2023-06-01"


def _to_anthropic(messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
    """Convierte la conversación neutral al formato de Anthropic.

    - Los mensajes ``system`` se unen en el parámetro ``system``.
    - Los resultados de herramientas consecutivos van en un único mensaje ``user``.
    - No se envían bloques de texto vacíos.
    """
    system_parts: list[str] = []
    wire: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system_parts.append(message.content)
            continue
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id or "",
                "content": message.content,
            }
            last = wire[-1] if wire else None
            if last and last["role"] == "user" and last.get("_tool_results"):
                last["content"].append(block)
            else:
                wire.append({"role": "user", "content": [block], "_tool_results": True})
            continue
        blocks: list[dict[str, Any]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        for call in message.tool_calls:
            blocks.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            )
        wire.append({"role": message.role, "content": blocks})
    for item in wire:
        item.pop("_tool_results", None)
    return "\n\n".join(system_parts), wire


class AnthropicProvider:
    name = "anthropic"
    is_paid = True

    def __init__(
        self,
        *,
        api_key: str,
        input_price_per_mtok: float,
        output_price_per_mtok: float,
        base_url: str = "https://api.anthropic.com",
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._input_price = input_price_per_mtok
        self._output_price = output_price_per_mtok
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            timeout=timeout_s,
            transport=transport,
        )

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        system, messages = _to_anthropic(request.messages)
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
        try:
            response = self._client.post("/v1/messages", json=payload)
            response.raise_for_status()
            data = response.json()
            blocks = data["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # No se incluye el cuerpo de la respuesta para no filtrar datos sensibles.
            raise ProviderError(f"Error del proveedor Anthropic: {type(exc).__name__}") from exc

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [
            ToolCall(
                id=b.get("id", ""), name=b.get("name", ""), arguments=dict(b.get("input") or {})
            )
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        return CompletionResponse(
            content=text,
            tool_calls=calls,
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
        )

    def cost_usd(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self._input_price + usage.output_tokens * self._output_price
        ) / 1_000_000
