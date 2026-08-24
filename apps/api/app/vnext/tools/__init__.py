"""Independent, Pydantic-validated agent-visible tool capabilities."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ToolDefinition": ("app.vnext.tools.definition", "ToolDefinition"),
    "ToolError": ("app.vnext.tools.errors", "ToolError"),
    "ToolErrorCode": ("app.vnext.tools.errors", "ToolErrorCode"),
    "ToolHandler": ("app.vnext.tools.definition", "ToolHandler"),
    "ToolRegistry": ("app.vnext.tools.registry", "ToolRegistry"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
