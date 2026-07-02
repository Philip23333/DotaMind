import inspect
import time

from app.agentic.models import QueryContext, ToolCall, ToolResult
from app.agentic.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, call: ToolCall, context: QueryContext) -> ToolResult:
        started = time.perf_counter()
        try:
            definition = self.registry.get(call.tool)
            validated_args = definition.input_model.model_validate(call.args)
            data = definition.handler(validated_args, context)
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
