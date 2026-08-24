"""Pydantic-validated, explicit-error tool registration and dispatch."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.vnext.agent.errors import ToolError, ToolErrorCode
from app.vnext.llm.protocol import ToolCall, ToolResultMessage
from app.vnext.tools.definition import ToolDefinition


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    async def execute(
        self,
        call: ToolCall,
        *,
        timeout: float | None = None,
    ) -> ToolResultMessage:
        """Execute one call and turn tool-local failures into explicit results."""

        try:
            definition = self.get(call.name)
        except KeyError:
            return self._error_result(
                call,
                "unknown_tool",
                f"unknown tool: {call.name}",
                {"tool_name": call.name},
            )

        try:
            arguments = definition.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            return self._error_result(
                call,
                "invalid_arguments",
                f"invalid arguments for tool {call.name}",
                {"validation_errors": exc.errors(include_url=False)},
            )

        effective_timeout = definition.timeout if timeout is None else timeout
        try:
            raw_output = self._invoke(definition, arguments)
            if effective_timeout is None:
                raw_output = await raw_output
            else:
                raw_output = await asyncio.wait_for(raw_output, effective_timeout)
        except asyncio.TimeoutError:
            return self._error_result(
                call,
                "tool_timeout",
                f"tool timed out: {call.name}",
                {"timeout_seconds": effective_timeout},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._error_result(
                call,
                "tool_execution_error",
                f"tool execution failed: {call.name}",
                {"exception_type": type(exc).__name__, "exception_message": str(exc)},
            )

        try:
            validated_output = definition.output_model.model_validate(raw_output)
            output = validated_output.model_dump(mode="json")
        except (ValidationError, TypeError, ValueError) as exc:
            details: dict[str, Any] = {"exception_type": type(exc).__name__}
            if isinstance(exc, ValidationError):
                details["validation_errors"] = exc.errors(include_url=False)
            return self._error_result(
                call,
                "invalid_tool_output",
                f"invalid output from tool: {call.name}",
                details,
            )
        return ToolResultMessage(
            tool_call_id=call.id,
            content=output,
            status="ok",
        )

    async def execute_many(
        self,
        calls: list[ToolCall],
        *,
        timeout: float | None = None,
    ) -> list[ToolResultMessage]:
        """Dispatch calls in order, grouping only adjacent parallel-safe calls."""

        results: list[ToolResultMessage] = []
        index = 0
        while index < len(calls):
            call = calls[index]
            if self._is_parallel_safe(call):
                end = index + 1
                while end < len(calls) and self._is_parallel_safe(calls[end]):
                    end += 1
                group = calls[index:end]
                results.extend(
                    await asyncio.gather(
                        *(self.execute(item, timeout=timeout) for item in group)
                    )
                )
                index = end
            else:
                results.append(await self.execute(call, timeout=timeout))
                index += 1
        return results

    @staticmethod
    def _invoke(definition: ToolDefinition, arguments: BaseModel) -> Awaitable[Any]:
        if inspect.iscoroutinefunction(definition.handler):
            return definition.handler(arguments)  # type: ignore[return-value]

        async def invoke_sync() -> Any:
            result = await asyncio.to_thread(definition.handler, arguments)
            if inspect.isawaitable(result):
                return await result
            return result

        return invoke_sync()

    def _is_parallel_safe(self, call: ToolCall) -> bool:
        try:
            return self.get(call.name).parallel_safe
        except KeyError:
            return False

    @staticmethod
    def _error_result(
        call: ToolCall,
        code: ToolErrorCode,
        message: str,
        details: dict[str, Any],
    ) -> ToolResultMessage:
        return ToolResultMessage(
            tool_call_id=call.id,
            status="error",
            error=ToolError(code=code, message=message, details=details),
        )


__all__ = ["ToolRegistry"]
