"""Proveedor determinista y gratuito para desarrollo y pruebas.

Comportamiento:
- Si la tarea define ``input["mock_tool_calls"]`` (lista de ``{"name", "arguments"}``) y aún no
  hay resultados de herramientas en la conversación, solicita esas herramientas (solo las que
  el agente tiene disponibles).
- Si ``input["mock_fail_times"] = n``, falla con ``ProviderError`` en los primeros ``n`` intentos.
- En otro caso, devuelve un informe final determinista.
"""

from kavryndex_office.errors import ProviderError
from kavryndex_office.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ToolCall,
    Usage,
)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockProvider:
    name = "mock"
    is_paid = False

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        meta = request.metadata
        if int(meta.get("attempt", 1)) <= int(meta.get("mock_fail_times", 0)):
            raise ProviderError("Fallo simulado del proveedor mock")

        prompt_text = "\n".join(m.content for m in request.messages)
        usage_in = _estimate_tokens(prompt_text)
        has_tool_results = any(m.role == "tool" for m in request.messages)
        available = {t.name for t in request.tools}

        scripted = meta.get("mock_tool_calls") or []
        if scripted and not has_tool_results:
            calls = [
                ToolCall(id=f"call_{i}", name=c["name"], arguments=dict(c.get("arguments", {})))
                for i, c in enumerate(scripted)
                if c.get("name") in available or meta.get("mock_force_tools")
            ]
            if calls:
                return CompletionResponse(
                    content="", tool_calls=calls, usage=Usage(usage_in, 10 * len(calls))
                )

        tool_results = [m.content for m in request.messages if m.role == "tool"]
        title = meta.get("task_title", "tarea")
        summary = f"Resultado de '{title}': completado por {meta.get('agent_slug', 'agente')}."
        if tool_results:
            summary += f" Herramientas usadas: {len(tool_results)}."
        return CompletionResponse(content=summary, usage=Usage(usage_in, _estimate_tokens(summary)))

    def cost_usd(self, usage: Usage) -> float:
        return 0.0
