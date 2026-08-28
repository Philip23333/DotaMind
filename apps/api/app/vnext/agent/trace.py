"""Canonical application-visible trace capture for one agent execution."""

from __future__ import annotations

from collections.abc import Sequence
from time import monotonic
from typing import Any

from app.vnext.llm.protocol import Message, ModelRequest, ModelResponse, ToolResultMessage


class AgentTraceCollector:
    """Collect one run's model and tool evidence without provider transport data."""

    def __init__(self) -> None:
        self._started = monotonic()
        self._trace: dict[str, Any] = {"initial_messages": [], "tool_schemas": [], "steps": []}

    def begin(self, messages: Sequence[Message], tool_schemas: list[dict[str, Any]]) -> None:
        self._trace["initial_messages"] = [message.model_dump(mode="json") for message in messages]
        self._trace["tool_schemas"] = tool_schemas

    def model_request(self, request: ModelRequest) -> None:
        self._step(request.step)["model_request"] = request.model_dump(mode="json")

    def text_delta(self, step: int, text: str) -> None:
        self._step(step).setdefault("streamed_text", []).append(text)

    def model_response(self, step: int, response: ModelResponse, duration: float) -> None:
        item = self._step(step)
        item["model_response"] = response.model_dump(mode="json")
        item["model_duration_seconds"] = duration

    def tool_result(self, step: int, result: ToolResultMessage, duration: float) -> None:
        item = self._step(step)
        item.setdefault("tool_results", []).append(
            {"result": result.model_dump(mode="json"), "duration_seconds": duration}
        )

    def terminal(self, *, status: str, error_code: str | None, error_message: str | None) -> None:
        self._trace["terminal"] = {
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
            "duration_seconds": max(0.0, monotonic() - self._started),
        }

    def snapshot(self) -> dict[str, Any]:
        return self._trace.copy()

    def _step(self, step: int | None) -> dict[str, Any]:
        normalized_step = step or 0
        for item in self._trace["steps"]:
            if item["step"] == normalized_step:
                return item
        item = {"step": normalized_step}
        self._trace["steps"].append(item)
        return item


__all__ = ["AgentTraceCollector"]
