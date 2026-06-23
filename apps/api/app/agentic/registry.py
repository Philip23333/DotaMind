import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.agentic.models import ExecutionPlan, ToolCall, ToolResult, ToolSource

ToolHandler = Callable[[BaseModel], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    source: ToolSource | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute_plan(self, plan: ExecutionPlan) -> list[ToolResult]:
        if len(plan.tool_calls) > plan.constraints.max_tool_calls:
            return [
                ToolResult(
                    tool_call_id="plan",
                    tool="plan",
                    status="error",
                    latency_ms=0,
                    error=(
                        "ValueError: plan exceeds max_tool_calls "
                        f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
                    ),
                )
            ]
        return [await self.execute(call) for call in plan.tool_calls]

    async def execute(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        try:
            definition = self.registry.get(call.tool)
            validated_args = definition.input_model.model_validate(call.args)
            data = definition.handler(validated_args)
            if inspect.isawaitable(data):
                data = await data
            return ToolResult(
                tool_call_id=call.id,
                tool=call.tool,
                status="ok",
                data=data,
                source=definition.source,
                latency_ms=self._elapsed_ms(started),
                metadata=definition.metadata,
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool=call.tool,
                status="error",
                latency_ms=self._elapsed_ms(started),
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
