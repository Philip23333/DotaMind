"""Stable failures for the vNext runtime."""

from __future__ import annotations

from typing import Any


class AgentRuntimeError(RuntimeError):
    """Base class for failures that terminate an agent run."""

    code = "agent_runtime_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AgentCancelledError(AgentRuntimeError):
    code = "agent_cancelled"

    def __init__(self, message: str = "agent run was cancelled") -> None:
        super().__init__(message)


class AgentDeadlineExceeded(AgentRuntimeError):
    code = "deadline_exceeded"

    def __init__(self, message: str = "agent run deadline exceeded") -> None:
        super().__init__(message)


class ModelProviderError(AgentRuntimeError):
    code = "model_provider_error"

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        details = {"exception_type": type(cause).__name__} if cause else {}
        super().__init__(message, details=details)
        self.cause = cause


class ModelContextWindowExceeded(ModelProviderError):
    code = "model_context_window_exceeded"

    def __init__(
        self,
        *,
        cause: Exception,
        provider_code: str,
        status_code: int | None,
    ) -> None:
        super().__init__(
            "model provider reported a context window limit",
            cause=cause,
        )
        self.details.update(
            {
                "provider_code": provider_code,
                "status_code": status_code,
            }
        )


class CompactionFailedError(AgentRuntimeError):
    code = "context_compaction_failed"

    def __init__(
        self,
        *,
        step: int,
        trigger: str,
        stage: str,
        summary_kind: str | None,
        reason_code: str,
        attempt_count: int,
        cause: Exception,
    ) -> None:
        details = {
            "trigger": trigger,
            "stage": stage,
            "summary_kind": summary_kind,
            "reason_code": reason_code,
            "attempt_count": attempt_count,
        }
        super().__init__("context compaction failed", details=details)
        self.step = step
        self.trigger = trigger
        self.stage = stage
        self.summary_kind = summary_kind
        self.reason_code = reason_code
        self.attempt_count = attempt_count
        self.cause = cause


class ModelProtocolError(AgentRuntimeError):
    code = "model_protocol_error"


class ContextCapacityExceeded(AgentRuntimeError):
    """The local request estimate cannot fit within the configured budget."""

    code = "context_capacity_exceeded"


# The shorter aliases are useful to callers that want to name failures without
# the implementation-oriented ``Error`` suffix.  The event named
# ``AgentCancelled`` intentionally lives in events.py and is not aliased here.
AgentCancelled = AgentCancelledError
AgentDeadlineExceededError = AgentDeadlineExceeded

__all__ = [
    "AgentCancelled",
    "AgentCancelledError",
    "AgentDeadlineExceeded",
    "AgentDeadlineExceededError",
    "AgentRuntimeError",
    "CompactionFailedError",
    "ContextCapacityExceeded",
    "ModelContextWindowExceeded",
    "ModelProviderError",
    "ModelProtocolError",
]
