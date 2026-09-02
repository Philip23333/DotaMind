"""Pydantic-validated, explicit-error tool registration and dispatch."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.vnext.artifacts import ToolResponseArtifactError
from app.vnext.artifacts.retrieval import (
    ArtifactPathNotFoundError,
    ArtifactReadValidationError,
)
from app.vnext.artifacts.store import ArtifactNotFoundError, InvalidArtifactRefError
from app.vnext.capabilities.game_detail.errors import GameDetailProviderError
from app.vnext.domain.source import SourceLocatorError
from app.vnext.llm.protocol import ModelTool, ToolCall, ToolResultMessage
from app.vnext.providers.pandascore.adapter import (
    PandaScoreConfigurationError,
    PandaScoreHTTPError,
    PandaScoreProviderError,
    PandaScoreSchemaError,
    PandaScoreTimeoutError,
)
from app.vnext.providers.pandascore.capabilities import PandaScoreQueryValidationError
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.errors import ToolError, ToolErrorCode


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

    def schemas(self) -> list[ModelTool]:
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
            details = {
                "validation_errors": [
                    {
                        "loc": error.get("loc", ()),
                        "type": error.get("type", "value_error"),
                    }
                    for error in exc.errors(include_url=False)
                ]
            }
            return self._error_result(
                call,
                "invalid_arguments",
                f"invalid arguments for tool {call.name}",
                details,
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
        except (ArtifactNotFoundError, InvalidArtifactRefError):
            return self._error_result(
                call,
                "artifact_not_found",
                f"artifact not found: {call.name}",
                {},
            )
        except ArtifactPathNotFoundError:
            return self._error_result(
                call,
                "artifact_path_not_found",
                f"artifact path not found: {call.name}",
                {},
            )
        except SourceLocatorError as exc:
            return self._error_result(
                call,
                "invalid_source_locator",
                str(exc),
                exc.details,
            )
        except GameDetailProviderError as exc:
            return self._error_result(
                call,
                "provider_error",
                str(exc),
                exc.details,
            )
        except ToolResponseArtifactError as exc:
            return self._error_result(
                call,
                "artifact_error",
                str(exc),
                {},
            )
        except ArtifactReadValidationError as exc:
            return self._error_result(
                call,
                "invalid_arguments",
                str(exc),
                {},
            )
        except PandaScoreQueryValidationError as exc:
            return self._error_result(
                call,
                exc.code,
                f"invalid esports search query: {exc.code}",
                exc.details,
            )
        except PandaScoreConfigurationError:
            return self._error_result(
                call,
                "configuration_error",
                "PandaScore is not configured for esports search",
                {},
            )
        except PandaScoreTimeoutError:
            return self._error_result(
                call,
                "provider_timeout",
                "PandaScore request timed out",
                {},
            )
        except PandaScoreHTTPError as exc:
            return self._error_result(
                call,
                "provider_http_error",
                "PandaScore returned an unsuccessful response",
                {"status_code": exc.status_code},
            )
        except PandaScoreSchemaError:
            return self._error_result(
                call,
                "provider_schema_error",
                "PandaScore returned an invalid response",
                {},
            )
        except PandaScoreProviderError:
            return self._error_result(
                call,
                "provider_error",
                "PandaScore request failed",
                {},
            )
        except Exception:
            return self._error_result(
                call,
                "tool_execution_error",
                f"tool execution failed: {call.name}",
                {},
            )

        try:
            validated_output = definition.output_model.model_validate(raw_output)
            output = validated_output.model_dump(mode="json")
        except ValidationError as exc:
            details = {
                "validation_errors": [
                    {
                        "loc": error.get("loc", ()),
                        "type": error.get("type", "value_error"),
                    }
                    for error in exc.errors(include_url=False)
                ]
            }
            return self._error_result(
                call,
                "invalid_tool_output",
                f"invalid output from tool: {call.name}",
                details,
            )
        except (TypeError, ValueError):
            return self._error_result(
                call,
                "invalid_tool_output",
                f"invalid output from tool: {call.name}",
                {},
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
                    await asyncio.gather(*(self.execute(item, timeout=timeout) for item in group))
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
