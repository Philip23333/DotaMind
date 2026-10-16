"""Request-local answer permissions, duplicate tracking and result bounds."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.vnext.llm.protocol import ModelTool, ToolCall, ToolResultMessage
from app.vnext.tools.definition import ToolAccess
from app.vnext.tools.errors import ToolError
from app.vnext.tools.registry import ToolRegistry

_ACCESS = {ToolAccess.LOCAL_ARTIFACT_READ, ToolAccess.PURE_COMPUTE}
_PROMPT_PREFIX = "Answer verification controls:"


@dataclass
class AnswerToolSession:
    """One verification session retained through retries and degraded answers."""

    registry: ToolRegistry
    calls: int = 0
    returned_bytes: int = 0
    seen: set[str] = field(default_factory=set)

    @property
    def enabled(self) -> bool:
        return any(tool.read_only and tool.access in _ACCESS for tool in self.registry.list())

    def schemas(self) -> list[ModelTool]:
        return [
            tool.schema()
            for tool in self.registry.list()
            if tool.read_only and tool.access in _ACCESS
        ]

    def prompt(self) -> str:
        return (
            f"{_PROMPT_PREFIX}\n"
            f"Calls attempted: {self.calls}\n"
            f"Admitted UTF-8 result bytes: {self.returned_bytes}\n"
            f"Verification tools available: {'yes' if self.schemas() else 'no'}\n"
            "Only the declared local read-only and pure-computation tools are permitted. "
            "No new external data, task planning, or checkpoint writes. "
            "There is no total call or cumulative result-byte quota. "
            "Stage deadlines, context capacity and the 35 KiB per-result bound still apply. "
            "Identical calls are rejected; reuse prior results or choose a different narrow read. "
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
        if definition is None or not definition.read_only or definition.access not in _ACCESS:
            result = self.error(call, "tool is not permitted during answer verification")
        elif key in self.seen:
            result = self.error(
                call, "identical answer-stage call already attempted; use its previous result"
            )
        else:
            self.seen.add(key)
            result = await self.registry.execute(call, timeout=timeout)

        size = self.size(result)
        if size > 35 * 1024:
            result = self.error(call, "answer result byte limit exceeded; read a narrower path")
            size = self.size(result)
        self.returned_bytes += size
        return result
