"""History construction for complete model tool-call batches rejected by an adapter."""

from __future__ import annotations

from app.vnext.llm.protocol import (
    RejectedAssistantMessage,
    RejectedToolCallBatch,
    ToolResultMessage,
)
from app.vnext.tools.errors import ToolError

NOT_EXECUTED_FEEDBACK = "本批所有调用均未执行，请重新提交完整调用。"


def build_rejected_tool_call_history(
    batch: RejectedToolCallBatch,
) -> tuple[RejectedAssistantMessage, list[ToolResultMessage]]:
    """Preserve raw call text and create one paired, explicitly unexecuted result."""

    failures = {failure.call_index: failure for failure in batch.argument_failures}
    assistant = RejectedAssistantMessage(content=batch.content, tool_calls=batch.calls)
    results: list[ToolResultMessage] = []
    for call in batch.calls:
        failure = failures.get(call.index)
        if batch.reason == "tool_response_truncated":
            code = "model_tool_response_truncated"
            details = {"reason": batch.reason}
        elif failure is not None:
            code = "model_tool_arguments_invalid"
            details = {
                "reason": batch.reason,
                "kind": failure.kind,
                "diagnostic": failure.message,
            }
            for field in ("position", "line", "column"):
                value = getattr(failure, field)
                if value is not None:
                    details[field] = value
        else:
            code = "model_tool_batch_rejected"
            details = {"reason": batch.reason, "cause": "another_call_invalid"}
        results.append(
            ToolResultMessage(
                tool_call_id=call.id,
                content=NOT_EXECUTED_FEEDBACK,
                status="error",
                error=ToolError(
                    code=code,
                    message=NOT_EXECUTED_FEEDBACK,
                    details=details,
                ),
                executed=False,
            )
        )
    return assistant, results


__all__ = ["NOT_EXECUTED_FEEDBACK", "build_rejected_tool_call_history"]
