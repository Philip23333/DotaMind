"""Per-answer local verification permissions and cumulative admission bounds."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.vnext.llm.protocol import ModelTool, ToolCall, ToolResultMessage
from app.vnext.tools.definition import ToolAccess
from app.vnext.tools.errors import ToolError
from app.vnext.tools.registry import ToolRegistry

_ACCESS = {ToolAccess.LOCAL_ARTIFACT_READ, ToolAccess.PURE_COMPUTE}
_ERROR_RESERVE = 512
_PROMPT_PREFIX = "Answer verification budget:"


@dataclass
class AnswerToolSession:
    """One budget shared by primary, overflow retries and degraded answers."""

    registry: ToolRegistry
    max_calls: int = 12
    max_bytes: int = 240 * 1024
    calls: int = 0
    returned_bytes: int = 0
    closed: bool = False
    seen: set[str] = field(default_factory=set)

    @property
    def enabled(self) -> bool:
        return any(tool.read_only and tool.access in _ACCESS for tool in self.registry.list())

    def schemas(self) -> list[ModelTool]:
        if self.closed or self.calls >= self.max_calls:
            return []
        return [
            tool.schema()
            for tool in self.registry.list()
            if tool.read_only and tool.access in _ACCESS
        ]

    def prompt(self) -> str:
        return (
            f"{_PROMPT_PREFIX}\n"
            f"Remaining calls: {max(0, self.max_calls - self.calls)}\n"
            f"Remaining UTF-8 result bytes: {max(0, self.max_bytes - self.returned_bytes)}\n"
            f"Verification tools available: {'yes' if self.schemas() else 'no'}\n"
            "Only the declared local read-only and pure-computation tools are permitted. "
            "No new external data, task planning, or checkpoint writes. "
            "Identical calls are rejected and consume the call budget. "
            "When tools are unavailable, answer from verified evidence and state remaining gaps."
        )

    @staticmethod
    def is_prompt(content: str) -> bool:
        return content.startswith(_PROMPT_PREFIX)

    @staticmethod
    def error(call: ToolCall, reason: str) -> ToolResultMessage:
        return ToolResultMessage(
            tool_call_id=call.id,
            status="error",
            error=ToolError(code="invalid_arguments", message=reason),
        )

    @staticmethod
    def size(result: ToolResultMessage) -> int:
        # Meter the actual business/error JSON admitted to the model, not call IDs.
        value = result.content if result.status == "ok" else result.error.model_dump(mode="json")
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    async def execute(self, call: ToolCall, *, timeout: float | None) -> ToolResultMessage:
        self.calls += 1
        try:
            definition = self.registry.get(call.name)
        except KeyError:
            definition = None
        key = json.dumps([call.name, call.arguments], sort_keys=True, ensure_ascii=False)
        if self.closed or self.calls > self.max_calls:
            result = self.error(
                call, "answer verification call budget exhausted; produce the answer"
            )
        elif definition is None or not definition.read_only or definition.access not in _ACCESS:
            result = self.error(call, "tool is not permitted during answer verification")
        elif key in self.seen:
            result = self.error(
                call, "identical answer-stage call already attempted; use its previous result"
            )
        else:
            self.seen.add(key)
            result = await self.registry.execute(call, timeout=timeout)

        # Leave enough room to report a small rejection for each remaining call.
        reserve = _ERROR_RESERVE * max(0, self.max_calls - self.calls)
        size = self.size(result)
        if size > min(35 * 1024, self.max_bytes - self.returned_bytes - reserve):
            result = self.error(call, "answer result byte limit exceeded; read a narrower path")
            size = self.size(result)
        self.returned_bytes += size
        if self.returned_bytes + reserve + _ERROR_RESERVE >= self.max_bytes:
            self.closed = True
        return result
