import inspect
import time
from collections.abc import Callable

from pydantic import ValidationError

from app.agentic.models import QueryContext, ToolCall, ToolResult
from app.agentic.runtime.models import ToolDispatchRecord
from app.agentic.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        call: ToolCall,
        context: QueryContext,
        *,
        before_handler_entered: Callable[[], None] | None = None,
        on_handler_entered: Callable[[], None] | None = None,
    ) -> tuple[ToolResult, ToolDispatchRecord]:
        started = time.perf_counter()
        try:
            definition = self.registry.get(call.tool)
        except KeyError as exc:
            return self._failure(call, started, exc), ToolDispatchRecord(
                tool_call_id=call.id,
                tool=call.tool,
                handler_entered=False,
                stage="pre_dispatch",
                error_code="tool_not_registered",
            )
        try:
            validated_args = definition.input_model.model_validate(call.args)
        except ValidationError as exc:
            return self._failure(call, started, exc), ToolDispatchRecord(
                tool_call_id=call.id,
                tool=call.tool,
                handler_entered=False,
                stage="pre_dispatch",
                error_code="input_validation_error",
            )
        if before_handler_entered is not None:
            before_handler_entered()
        if on_handler_entered is not None:
            on_handler_entered()
        try:
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
            ), ToolDispatchRecord(
                tool_call_id=call.id,
                tool=call.tool,
                handler_entered=True,
                stage="handler",
                error_code=None,
            )
        except Exception as exc:
            return self._failure(call, started, exc), ToolDispatchRecord(
                tool_call_id=call.id,
                tool=call.tool,
                handler_entered=True,
                stage="handler",
                error_code="handler_error",
            )

    def _failure(self, call: ToolCall, started: float, exc: Exception) -> ToolResult:
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
