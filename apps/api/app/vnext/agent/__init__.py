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
    "CompactionFailed": ("app.vnext.agent.events", "CompactionFailed"),
    "AgentLimits": ("app.vnext.agent.limits", "AgentLimits"),
    "AgentRuntime": ("app.vnext.agent.runtime", "AgentRuntime"),
    "AgentRuntimeError": ("app.vnext.agent.errors", "AgentRuntimeError"),
    "CompactionFailedError": ("app.vnext.agent.errors", "CompactionFailedError"),
    "AgentStarted": ("app.vnext.agent.events", "AgentStarted"),
    "AnswerAttemptFailed": ("app.vnext.agent.events", "AnswerAttemptFailed"),
    "AnswerAttemptStarted": ("app.vnext.agent.events", "AnswerAttemptStarted"),
    "AnswerStageStarted": ("app.vnext.agent.events", "AnswerStageStarted"),
    "CancellationToken": ("app.vnext.agent.runtime", "CancellationToken"),
    "ModelProviderError": ("app.vnext.agent.errors", "ModelProviderError"),
    "ModelProtocolError": ("app.vnext.agent.errors", "ModelProtocolError"),
    "ModelRequested": ("app.vnext.agent.events", "ModelRequested"),
    "ModelResponded": ("app.vnext.agent.events", "ModelResponded"),
    "TextDelta": ("app.vnext.agent.events", "TextDelta"),
    "ToolCompleted": ("app.vnext.agent.events", "ToolCompleted"),
    "ToolFailed": ("app.vnext.agent.events", "ToolFailed"),
    "ToolStarted": ("app.vnext.agent.events", "ToolStarted"),
    "TranscriptRewriteEvent": (
        "app.vnext.agent.transcript_rewrite",
        "TranscriptRewriteEvent",
    ),
    "TranscriptRewriteResult": (
        "app.vnext.agent.transcript_rewrite",
        "TranscriptRewriteResult",
    ),
    "TranscriptRewriter": ("app.vnext.agent.transcript_rewrite", "TranscriptRewriter"),
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
