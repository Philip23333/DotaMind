"""The in-memory, session-neutral vNext agent runtime.

The package uses lazy exports so importing the provider-neutral message module
never creates a package-level cycle through runtime event types.
"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AgentCancelled": ("app.vnext.agent.events", "AgentCancelled"),
    "AgentCancelledError": ("app.vnext.agent.errors", "AgentCancelledError"),
    "AgentCompleted": ("app.vnext.agent.events", "AgentCompleted"),
    "AgentDeadlineExceeded": ("app.vnext.agent.errors", "AgentDeadlineExceeded"),
    "AgentEvent": ("app.vnext.agent.events", "AgentEvent"),
    "AgentFailed": ("app.vnext.agent.events", "AgentFailed"),
    "AgentLimits": ("app.vnext.agent.limits", "AgentLimits"),
    "AgentRuntime": ("app.vnext.agent.runtime", "AgentRuntime"),
    "AgentRuntimeError": ("app.vnext.agent.errors", "AgentRuntimeError"),
    "AgentStarted": ("app.vnext.agent.events", "AgentStarted"),
    "CancellationToken": ("app.vnext.agent.runtime", "CancellationToken"),
    "MaxStepsExceeded": ("app.vnext.agent.errors", "MaxStepsExceeded"),
    "MaxToolCallsExceeded": ("app.vnext.agent.errors", "MaxToolCallsExceeded"),
    "ModelProviderError": ("app.vnext.agent.errors", "ModelProviderError"),
    "ModelProtocolError": ("app.vnext.agent.errors", "ModelProtocolError"),
    "ModelRequested": ("app.vnext.agent.events", "ModelRequested"),
    "ModelResponded": ("app.vnext.agent.events", "ModelResponded"),
    "TextDelta": ("app.vnext.agent.events", "TextDelta"),
    "ToolCompleted": ("app.vnext.agent.events", "ToolCompleted"),
    "ToolFailed": ("app.vnext.agent.events", "ToolFailed"),
    "ToolStarted": ("app.vnext.agent.events", "ToolStarted"),
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
