from kavryndex_office.tools.base import ToolSpec
from kavryndex_office.tools.builtin import BUILTIN_TOOLS

TOOLS: dict[str, ToolSpec] = {tool.name: tool for tool in BUILTIN_TOOLS}


def tools_for(allowed: list[str]) -> list[ToolSpec]:
    """Herramientas visibles para un agente: solo las autorizadas y registradas."""
    return [TOOLS[name] for name in allowed if name in TOOLS]
