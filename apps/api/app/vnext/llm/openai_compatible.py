"""httpx adapter for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any

import httpx

from app.vnext.llm.diagnostic_limits import (
    DEFAULT_MODEL_DIAGNOSTIC_LIMITS,
    ModelDiagnosticLimits,
)
from app.vnext.llm.diagnostics import (
    DiagnosticResponseMode,
    DiagnosticStage,
    ModelFailureDiagnostics,
    ModelJSONErrorDiagnostic,
    ToolCallDiagnosticInput,
    build_model_failure_diagnostics,
)
from app.vnext.llm.errors import (
    ModelContextWindowError,
    ModelResponseDiagnosticError,
    ModelToolCallBatchRejected,
    ModelTransientError,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ModelTool,
    RawToolCall,
    RejectedAssistantMessage,
    RejectedToolCallBatch,
    ToolArgumentFailure,
    ToolCall,
)


class OpenAICompatibleError(ModelResponseDiagnosticError):
    """Base error for an OpenAI-compatible transport/protocol failure."""


class ProviderHTTPError(OpenAICompatibleError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"model provider returned HTTP {status_code}")
        self.status_code = status_code
        self.body = body


class TransientProviderHTTPError(ProviderHTTPError, ModelTransientError):
    """An HTTP provider failure classified as transient by status and code."""


class ProviderProtocolError(OpenAICompatibleError):
    """The provider returned data that is not a supported chat-completions response."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: ModelFailureDiagnostics | None = None,
        failed_tool_call_index: int | None = None,
    ) -> None:
        super().__init__(message, diagnostics=diagnostics)
        self.failed_tool_call_index = failed_tool_call_index


_CONTEXT_WINDOW_HTTP_STATUSES = frozenset({400, 413, 422})
_CONTEXT_WINDOW_PROVIDER_CODE = "context_length_exceeded"
_TRANSIENT_HTTP_STATUSES = frozenset({408, 500, 502, 503, 504})
_QUOTA_ERROR_CODES = frozenset(
    {"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"}
)
_TRANSIENT_HTTPX_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


@dataclass
class _ToolCallAccumulator:
    call_id: str | None = None
    name: str | None = None
    argument_fragments: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ToolCallCandidate:
    raw: RawToolCall
    argument_fragment_count: int | None
    agent_name: str | None


def _attach_diagnostics_best_effort(
    error: ModelResponseDiagnosticError,
    build: Callable[[], ModelFailureDiagnostics],
) -> None:
    """Attach bounded evidence without replacing the provider parsing error."""

    try:
        error.diagnostics = build()
    except Exception:
        pass


class OpenAICompatibleModelClient:
    """Translate the vNext protocol at the provider boundary only."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str,
        model: str,
        timeout: float | httpx.Timeout = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        diagnostic_limits: ModelDiagnosticLimits = DEFAULT_MODEL_DIAGNOSTIC_LIMITS,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self._client = client
        self.diagnostic_limits = diagnostic_limits

    async def complete(self, request: ModelRequest) -> ModelResponse:
        agent_to_provider, provider_to_agent = self._tool_name_maps(request.tools)
        response = await self._post(self._payload(request, agent_to_provider))
        return self._parse_response(
            response,
            provider_to_agent,
            diagnostic_limits=self.diagnostic_limits,
        )

    async def stream(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ModelTextDelta | ModelResponse]:
        """Stream provider text deltas and one assembled terminal response."""

        agent_to_provider, provider_to_agent = self._tool_name_maps(request.tools)
        payload = self._payload(request, agent_to_provider)
        payload["stream"] = True

        content_parts: list[str] = []
        tool_calls: dict[int, _ToolCallAccumulator] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] = {}
        saw_done = False
        diagnostic_stage: DiagnosticStage = "stream_protocol"

        try:
            async with self._open_stream(payload) as response:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        raise ProviderProtocolError("malformed SSE line")

                    encoded = line[len("data:") :].lstrip()
                    if encoded == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk = json.loads(encoded)
                    except JSONDecodeError as exc:
                        raise ProviderProtocolError("stream data is not valid JSON") from exc

                    if isinstance(chunk, Mapping):
                        observed_usage = chunk.get("usage")
                        if isinstance(observed_usage, Mapping):
                            usage.update(observed_usage)
                        observed_choices = chunk.get("choices")
                        if (
                            isinstance(observed_choices, list)
                            and observed_choices
                            and isinstance(observed_choices[0], Mapping)
                        ):
                            observed_finish_reason = observed_choices[0].get("finish_reason")
                            if isinstance(observed_finish_reason, str):
                                finish_reason = observed_finish_reason

                    deltas, chunk_finish_reason, chunk_usage = self._consume_stream_chunk(
                        chunk,
                        content_parts,
                        tool_calls,
                    )
                    for delta in deltas:
                        yield delta
                    if chunk_finish_reason is not None:
                        finish_reason = chunk_finish_reason
                    usage.update(chunk_usage)

            if not saw_done:
                raise ProviderProtocolError("stream ended before [DONE]")

            diagnostic_stage = "response_assembly"
            yield self._assemble_stream_response(
                content_parts,
                tool_calls,
                finish_reason,
                usage,
                provider_to_agent,
                diagnostic_limits=self.diagnostic_limits,
            )
        except ProviderProtocolError as exc:
            if exc.diagnostics is None:
                _attach_diagnostics_best_effort(
                    exc,
                    lambda exc=exc: self._stream_failure_diagnostics(
                        stage=diagnostic_stage,
                        original_error_type=type(exc).__name__,
                        tool_calls=tool_calls,
                        provider_to_agent=provider_to_agent,
                        finish_reason=finish_reason,
                        usage=usage,
                        stream_done_received=saw_done,
                        failed_tool_call_index=exc.failed_tool_call_index,
                        diagnostic_limits=self.diagnostic_limits,
                    ),
                )
            raise

    def _payload(
        self,
        request: ModelRequest,
        agent_to_provider: Mapping[str, str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                self._serialize_message(message, agent_to_provider) for message in request.messages
            ],
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.tools:
            payload["tools"] = [
                self._serialize_tool(tool, agent_to_provider[tool.name]) for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
        return payload

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = self._headers()
        url = self._url()
        try:
            if self._client is not None:
                response = await self._client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    transport=self.transport,
                ) as client:
                    response = await client.post(url, headers=headers, json=payload)
        except _TRANSIENT_HTTPX_ERRORS as exc:
            raise ModelTransientError("model provider transport failed") from exc
        self._raise_for_status(response)
        return response

    @asynccontextmanager
    async def _open_stream(self, payload: dict[str, Any]) -> AsyncIterator[httpx.Response]:
        headers = self._headers()
        url = self._url()
        try:
            if self._client is not None:
                async with self._client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    await self._raise_for_status_async(response)
                    yield response
                return

            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    await self._raise_for_status_async(response)
                    yield response
        except _TRANSIENT_HTTPX_ERRORS as exc:
            raise ModelTransientError("model provider transport failed") from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @classmethod
    def _raise_for_status(cls, response: httpx.Response) -> None:
        if response.is_error:
            context_error = cls._context_window_error_from_response(response)
            if context_error is not None:
                raise context_error
            error_type = (
                TransientProviderHTTPError
                if cls._is_transient_status(response.status_code, response)
                else ProviderHTTPError
            )
            raise error_type(response.status_code, response.text)

    @classmethod
    async def _raise_for_status_async(cls, response: httpx.Response) -> None:
        if response.is_error:
            await response.aread()
            context_error = cls._context_window_error_from_response(response)
            if context_error is not None:
                raise context_error
            error_type = (
                TransientProviderHTTPError
                if cls._is_transient_status(response.status_code, response)
                else ProviderHTTPError
            )
            raise error_type(response.status_code, response.text)

    @classmethod
    def _is_transient_status(cls, status_code: int, response: httpx.Response) -> bool:
        if status_code in _TRANSIENT_HTTP_STATUSES:
            return True
        if status_code != 429:
            return False
        try:
            data = response.json()
        except (JSONDecodeError, ValueError):
            return True
        if not isinstance(data, Mapping):
            return True
        error = data.get("error")
        if not isinstance(error, Mapping):
            return True
        return not any(
            isinstance(error.get(field), str) and error[field] in _QUOTA_ERROR_CODES
            for field in ("code", "type")
        )

    @classmethod
    def _context_window_error_from_response(
        cls,
        response: httpx.Response,
    ) -> ModelContextWindowError | None:
        if response.status_code not in _CONTEXT_WINDOW_HTTP_STATUSES:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        return cls._context_window_error(data, status_code=response.status_code)

    @staticmethod
    def _context_window_error(
        data: Any,
        *,
        status_code: int | None,
    ) -> ModelContextWindowError | None:
        if not isinstance(data, Mapping):
            return None
        error = data.get("error")
        if not isinstance(error, Mapping):
            return None
        provider_code = error.get("code")
        if provider_code != _CONTEXT_WINDOW_PROVIDER_CODE:
            return None
        return ModelContextWindowError(
            provider_code=provider_code,
            status_code=status_code,
        )

    @classmethod
    def _parse_response(
        cls,
        response: httpx.Response,
        provider_to_agent: Mapping[str, str],
        *,
        diagnostic_limits: ModelDiagnosticLimits,
    ) -> ModelResponse:
        try:
            data = response.json()
        except (JSONDecodeError, ValueError) as exc:
            error = ProviderProtocolError("model provider returned invalid JSON")
            _attach_diagnostics_best_effort(
                error,
                lambda: build_model_failure_diagnostics(
                    stage="response_assembly",
                    response_mode="complete",
                    original_error_type=type(error).__name__,
                    finish_reason=None,
                    usage=None,
                    stream_done_received=None,
                    tool_calls=(),
                    limits=diagnostic_limits,
                ),
            )
            raise error from exc
        if not isinstance(data, Mapping):
            error = ProviderProtocolError("model provider response must be a JSON object")
            _attach_diagnostics_best_effort(
                error,
                lambda: cls._complete_failure_diagnostics(
                    error,
                    provider_to_agent=provider_to_agent,
                    raw_tool_calls=(),
                    finish_reason=None,
                    usage=None,
                    failed_tool_call_index=None,
                    diagnostic_limits=diagnostic_limits,
                ),
            )
            raise error
        context_error = cls._context_window_error(data, status_code=None)
        if context_error is not None:
            raise context_error

        usage = cls._usage(data)
        finish_reason: str | None = None
        raw_tool_calls: Sequence[Any] = ()
        try:
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ProviderProtocolError("model provider response has no choices")
            choice = choices[0]
            if not isinstance(choice, Mapping):
                raise ProviderProtocolError("model provider choice must be an object")

            candidate_finish_reason = choice.get("finish_reason")
            if candidate_finish_reason is not None and not isinstance(candidate_finish_reason, str):
                raise ProviderProtocolError("finish_reason must be a string or null")
            finish_reason = candidate_finish_reason

            message = choice.get("message")
            if not isinstance(message, Mapping):
                raise ProviderProtocolError("model provider choice has no message object")

            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ProviderProtocolError("assistant message content must be a string or null")
            candidate_tool_calls = message.get("tool_calls")
            if candidate_tool_calls is not None and not isinstance(candidate_tool_calls, list):
                raise ProviderProtocolError("assistant tool_calls must be a list")
            raw_tool_calls = candidate_tool_calls or []

            candidates: list[_ToolCallCandidate] = []
            for index, raw_call in enumerate(raw_tool_calls):
                candidates.append(
                    cls._extract_tool_call_candidate(
                        raw_call,
                        provider_to_agent,
                        index=index,
                    )
                )
            if candidates:
                tool_calls = cls._validate_tool_call_batch(
                    candidates,
                    content=content,
                    finish_reason=finish_reason,
                    usage=usage,
                    response_mode="complete",
                    stream_done_received=None,
                    diagnostic_limits=diagnostic_limits,
                )
                return ModelResponse(
                    message=AssistantMessage(content=content, tool_calls=tool_calls),
                    finish_reason=finish_reason,
                    usage=usage,
                )
            if content is None:
                raise ProviderProtocolError("final assistant message has no content")
            return ModelResponse(
                message=FinalMessage(content=content),
                finish_reason=finish_reason,
                usage=usage,
            )
        except ProviderProtocolError as exc:
            if exc.diagnostics is None:
                _attach_diagnostics_best_effort(
                    exc,
                    lambda exc=exc: cls._complete_failure_diagnostics(
                        exc,
                        provider_to_agent=provider_to_agent,
                        raw_tool_calls=raw_tool_calls,
                        finish_reason=finish_reason,
                        usage=usage,
                        failed_tool_call_index=exc.failed_tool_call_index,
                        diagnostic_limits=diagnostic_limits,
                    ),
                )
            raise

    @classmethod
    def _consume_stream_chunk(
        cls,
        chunk: Any,
        content_parts: list[str],
        tool_calls: dict[int, _ToolCallAccumulator],
    ) -> tuple[list[ModelTextDelta], str | None, dict[str, Any]]:
        if not isinstance(chunk, Mapping):
            raise ProviderProtocolError("stream data must be a JSON object")
        context_error = cls._context_window_error(chunk, status_code=None)
        if context_error is not None:
            raise context_error

        choices = chunk.get("choices")
        if not isinstance(choices, list):
            raise ProviderProtocolError("stream choices must be a list")
        raw_usage = chunk.get("usage")
        if raw_usage is not None and not isinstance(raw_usage, Mapping):
            raise ProviderProtocolError("stream usage must be an object or null")
        if not choices:
            return [], None, dict(raw_usage or {})

        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ProviderProtocolError("stream choice must be an object")
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            raise ProviderProtocolError("stream choice has no delta object")

        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise ProviderProtocolError("stream text delta must be a string or null")
        deltas: list[ModelTextDelta] = []
        if content:
            content_parts.append(content)
            deltas.append(ModelTextDelta(text=content))

        raw_tool_calls = delta.get("tool_calls")
        if raw_tool_calls is not None and not isinstance(raw_tool_calls, list):
            raise ProviderProtocolError("stream tool_calls must be a list")
        for raw_call in raw_tool_calls or []:
            cls._accumulate_tool_call(raw_call, tool_calls)

        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise ProviderProtocolError("stream finish_reason must be a string or null")
        return deltas, finish_reason, dict(raw_usage or {})

    @classmethod
    def _accumulate_tool_call(
        cls,
        raw_call: Any,
        tool_calls: dict[int, _ToolCallAccumulator],
    ) -> None:
        if not isinstance(raw_call, Mapping):
            raise ProviderProtocolError("stream tool call must be an object")
        index = raw_call.get("index")
        if type(index) is not int or index < 0:
            raise ProviderProtocolError("stream tool call index must be a non-negative integer")
        accumulator = tool_calls.setdefault(index, _ToolCallAccumulator())

        call_id = raw_call.get("id")
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id:
                raise ProviderProtocolError(
                    "stream tool call id must be a non-empty string",
                    failed_tool_call_index=index,
                )
            if accumulator.call_id is not None and accumulator.call_id != call_id:
                raise ProviderProtocolError(
                    "stream tool call id changed during assembly",
                    failed_tool_call_index=index,
                )
            accumulator.call_id = call_id

        raw_function = raw_call.get("function")
        if raw_function is not None and not isinstance(raw_function, Mapping):
            raise ProviderProtocolError(
                "stream tool call function must be an object",
                failed_tool_call_index=index,
            )
        if raw_function is None:
            return

        name = raw_function.get("name")
        if name is not None:
            if not isinstance(name, str) or not name:
                raise ProviderProtocolError(
                    "stream tool call name must be a non-empty string",
                    failed_tool_call_index=index,
                )
            if accumulator.name is not None and accumulator.name != name:
                raise ProviderProtocolError(
                    "stream tool call name changed during assembly",
                    failed_tool_call_index=index,
                )
            accumulator.name = name

        if "arguments" in raw_function:
            arguments = raw_function["arguments"]
            if not isinstance(arguments, str):
                raise ProviderProtocolError(
                    "stream tool call arguments must be a string",
                    failed_tool_call_index=index,
                )
            accumulator.argument_fragments.append(arguments)

    @classmethod
    def _assemble_stream_response(
        cls,
        content_parts: list[str],
        tool_calls: dict[int, _ToolCallAccumulator],
        finish_reason: str | None,
        usage: dict[str, Any],
        provider_to_agent: Mapping[str, str],
        *,
        diagnostic_limits: ModelDiagnosticLimits,
    ) -> ModelResponse:
        content = "".join(content_parts) if content_parts else None
        if tool_calls:
            candidates: list[_ToolCallCandidate] = []
            for index, accumulator in sorted(tool_calls.items()):
                if not accumulator.call_id:
                    raise ProviderProtocolError(
                        f"stream tool call {index} has no id",
                        failed_tool_call_index=index,
                    )
                if not accumulator.name:
                    raise ProviderProtocolError(
                        f"stream tool call {index} has no name",
                        failed_tool_call_index=index,
                    )
                candidates.append(
                    _ToolCallCandidate(
                        raw=RawToolCall(
                            index=index,
                            id=accumulator.call_id,
                            name=provider_to_agent.get(accumulator.name, accumulator.name),
                            provider_name=accumulator.name,
                            raw_arguments="".join(accumulator.argument_fragments),
                        ),
                        argument_fragment_count=len(accumulator.argument_fragments),
                        agent_name=provider_to_agent.get(accumulator.name),
                    )
                )
            assembled_calls = cls._validate_tool_call_batch(
                candidates,
                content=content,
                finish_reason=finish_reason,
                usage=usage,
                response_mode="stream",
                stream_done_received=True,
                diagnostic_limits=diagnostic_limits,
            )
            return ModelResponse(
                message=AssistantMessage(content=content, tool_calls=assembled_calls),
                finish_reason=finish_reason,
                usage=usage,
            )
        if content is None:
            raise ProviderProtocolError("stream final assistant message has no content")
        return ModelResponse(
            message=FinalMessage(content=content),
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _usage(data: Mapping[str, Any]) -> dict[str, Any]:
        usage = data.get("usage")
        return dict(usage) if isinstance(usage, Mapping) else {}

    @classmethod
    def _stream_failure_diagnostics(
        cls,
        *,
        stage: DiagnosticStage,
        original_error_type: str,
        tool_calls: Mapping[int, _ToolCallAccumulator],
        provider_to_agent: Mapping[str, str],
        finish_reason: str | None,
        usage: Mapping[str, Any] | None,
        stream_done_received: bool | None,
        failed_tool_call_index: int | None,
        diagnostic_limits: ModelDiagnosticLimits,
        json_error: ModelJSONErrorDiagnostic | None = None,
    ) -> ModelFailureDiagnostics:
        inputs = [
            ToolCallDiagnosticInput(
                index=index,
                call_id=accumulator.call_id,
                provider_name=accumulator.name,
                agent_name=(
                    provider_to_agent.get(accumulator.name)
                    if accumulator.name is not None
                    else None
                ),
                argument_fragments=tuple(accumulator.argument_fragments),
                argument_fragment_count=len(accumulator.argument_fragments),
            )
            for index, accumulator in tool_calls.items()
        ]
        return build_model_failure_diagnostics(
            stage=stage,
            response_mode="stream",
            original_error_type=original_error_type,
            finish_reason=finish_reason,
            usage=usage,
            stream_done_received=stream_done_received,
            tool_calls=inputs,
            failed_tool_call_index=failed_tool_call_index,
            json_error=json_error,
            limits=diagnostic_limits,
        )

    @classmethod
    def _complete_failure_diagnostics(
        cls,
        error: ProviderProtocolError,
        *,
        provider_to_agent: Mapping[str, str],
        raw_tool_calls: Sequence[Any],
        finish_reason: str | None,
        usage: Mapping[str, Any] | None,
        failed_tool_call_index: int | None,
        diagnostic_limits: ModelDiagnosticLimits,
        stage: DiagnosticStage = "response_assembly",
        json_error: ModelJSONErrorDiagnostic | None = None,
    ) -> ModelFailureDiagnostics:
        inputs: list[ToolCallDiagnosticInput] = []
        for index, raw_call in enumerate(raw_tool_calls):
            call_id: str | None = None
            provider_name: str | None = None
            arguments: str | None = None
            if isinstance(raw_call, Mapping):
                raw_id = raw_call.get("id")
                call_id = raw_id if isinstance(raw_id, str) else None
                function = raw_call.get("function")
                if isinstance(function, Mapping):
                    raw_name = function.get("name")
                    provider_name = raw_name if isinstance(raw_name, str) else None
                    raw_arguments = function.get("arguments")
                    arguments = raw_arguments if isinstance(raw_arguments, str) else None
            inputs.append(
                ToolCallDiagnosticInput(
                    index=index,
                    call_id=call_id,
                    provider_name=provider_name,
                    agent_name=(
                        provider_to_agent.get(provider_name)
                        if provider_name is not None
                        else None
                    ),
                    argument_fragments=(arguments,) if arguments is not None else None,
                    argument_fragment_count=None,
                )
            )
        return build_model_failure_diagnostics(
            stage=stage,
            response_mode="complete",
            original_error_type=type(error).__name__,
            finish_reason=finish_reason,
            usage=usage,
            stream_done_received=None,
            tool_calls=inputs,
            failed_tool_call_index=failed_tool_call_index,
            json_error=json_error,
            limits=diagnostic_limits,
        )

    @classmethod
    def _extract_tool_call_candidate(
        cls,
        raw_call: Any,
        provider_to_agent: Mapping[str, str],
        *,
        index: int,
    ) -> _ToolCallCandidate:
        if not isinstance(raw_call, Mapping):
            raise ProviderProtocolError("tool call must be an object", failed_tool_call_index=index)
        call_id = raw_call.get("id")
        if not isinstance(call_id, str) or not call_id:
            raise ProviderProtocolError(
                "tool call id must be a non-empty string",
                failed_tool_call_index=index,
            )
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            raise ProviderProtocolError(
                "tool call function must be an object",
                failed_tool_call_index=index,
            )
        provider_name = function.get("name")
        if not isinstance(provider_name, str) or not provider_name:
            raise ProviderProtocolError(
                "tool call function name must be a non-empty string",
                failed_tool_call_index=index,
            )
        raw_arguments = function.get("arguments")
        if not isinstance(raw_arguments, str):
            raise ProviderProtocolError(
                "tool call arguments must be a JSON-encoded string",
                failed_tool_call_index=index,
            )
        return _ToolCallCandidate(
            raw=RawToolCall(
                index=index,
                id=call_id,
                name=provider_to_agent.get(provider_name, provider_name),
                provider_name=provider_name,
                raw_arguments=raw_arguments,
            ),
            argument_fragment_count=None,
            agent_name=provider_to_agent.get(provider_name),
        )

    @classmethod
    def _validate_tool_call_batch(
        cls,
        candidates: Sequence[_ToolCallCandidate],
        *,
        content: str | None,
        finish_reason: str | None,
        usage: Mapping[str, Any],
        response_mode: DiagnosticResponseMode,
        stream_done_received: bool | None,
        diagnostic_limits: ModelDiagnosticLimits,
    ) -> list[ToolCall]:
        ids: set[str] = set()
        for candidate in candidates:
            call = candidate.raw
            if call.id in ids:
                raise ProviderProtocolError(
                    "tool call IDs must be unique",
                    failed_tool_call_index=call.index,
                )
            ids.add(call.id)

        parsed_arguments: list[dict[str, Any] | None] = []
        failures: list[ToolArgumentFailure] = []
        for candidate in candidates:
            try:
                arguments = json.loads(
                    candidate.raw.raw_arguments,
                    parse_constant=cls._reject_non_json_constant,
                )
            except JSONDecodeError as exc:
                parsed_arguments.append(None)
                failures.append(
                    ToolArgumentFailure(
                        call_index=candidate.raw.index,
                        kind="invalid_json",
                        message=exc.msg,
                        position=exc.pos,
                        line=exc.lineno,
                        column=exc.colno,
                    )
                )
            except ValueError:
                parsed_arguments.append(None)
                failures.append(
                    ToolArgumentFailure(
                        call_index=candidate.raw.index,
                        kind="invalid_json",
                        message="non-finite numeric values are not valid JSON",
                    )
                )
            else:
                if not isinstance(arguments, dict):
                    parsed_arguments.append(None)
                    failures.append(
                        ToolArgumentFailure(
                            call_index=candidate.raw.index,
                            kind="non_object_json",
                            message="tool call arguments must decode to a JSON object",
                        )
                    )
                else:
                    parsed_arguments.append(arguments)

        if finish_reason == "length" or failures:
            reason = (
                "tool_response_truncated"
                if finish_reason == "length"
                else "invalid_tool_arguments"
            )
            batch = RejectedToolCallBatch(
                reason=reason,
                content=content,
                calls=[candidate.raw for candidate in candidates],
                argument_failures=failures,
                finish_reason=finish_reason,
                usage=dict(usage),
            )
            error = ModelToolCallBatchRejected(batch=batch)
            _attach_diagnostics_best_effort(
                error,
                lambda: cls._batch_failure_diagnostics(
                    candidates,
                    failures=failures,
                    finish_reason=finish_reason,
                    usage=usage,
                    response_mode=response_mode,
                    stream_done_received=stream_done_received,
                    diagnostic_limits=diagnostic_limits,
                ),
            )
            raise error

        calls: list[ToolCall] = []
        for candidate, arguments in zip(candidates, parsed_arguments, strict=True):
            if arguments is None:
                raise ProviderProtocolError("validated tool arguments are unavailable")
            calls.append(
                ToolCall(
                    id=candidate.raw.id,
                    name=candidate.raw.name,
                    arguments=arguments,
                )
            )
        return calls

    @staticmethod
    def _reject_non_json_constant(_value: str) -> None:
        raise ValueError("non-finite numeric values are not valid JSON")

    @classmethod
    def _batch_failure_diagnostics(
        cls,
        candidates: Sequence[_ToolCallCandidate],
        *,
        failures: Sequence[ToolArgumentFailure],
        finish_reason: str | None,
        usage: Mapping[str, Any],
        response_mode: DiagnosticResponseMode,
        stream_done_received: bool | None,
        diagnostic_limits: ModelDiagnosticLimits,
    ) -> ModelFailureDiagnostics:
        first_failure = failures[0] if failures else None
        json_error = (
            ModelJSONErrorDiagnostic(
                message=first_failure.message,
                position=first_failure.position,
                line=first_failure.line,
                column=first_failure.column,
            )
            if first_failure is not None and first_failure.kind == "invalid_json"
            else None
        )
        inputs = [
            ToolCallDiagnosticInput(
                index=candidate.raw.index,
                call_id=candidate.raw.id,
                provider_name=candidate.raw.provider_name,
                agent_name=candidate.agent_name,
                argument_fragments=(candidate.raw.raw_arguments,),
                argument_fragment_count=candidate.argument_fragment_count,
            )
            for candidate in candidates
        ]
        return build_model_failure_diagnostics(
            stage="tool_arguments_decode" if failures else "response_assembly",
            response_mode=response_mode,
            original_error_type="ModelToolCallBatchRejected",
            finish_reason=finish_reason,
            usage=usage,
            stream_done_received=stream_done_received,
            tool_calls=inputs,
            failed_tool_call_index=(
                first_failure.call_index if first_failure is not None else None
            ),
            json_error=json_error,
            limits=diagnostic_limits,
        )

    @staticmethod
    def _tool_name_maps(
        tools: list[ModelTool],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map agent names to provider-safe, unique function identifiers."""

        agent_to_provider: dict[str, str] = {}
        provider_to_agent: dict[str, str] = {}
        for tool in tools:
            base_name = re.sub(r"[^a-zA-Z0-9_-]", "_", tool.name)
            provider_name = base_name
            suffix = 2
            while provider_name in provider_to_agent:
                provider_name = f"{base_name}_{suffix}"
                suffix += 1
            agent_to_provider[tool.name] = provider_name
            provider_to_agent[provider_name] = tool.name
        return agent_to_provider, provider_to_agent

    @staticmethod
    def _serialize_tool(tool: ModelTool, provider_name: str) -> dict[str, Any]:
        """Convert the generic tool only at the OpenAI-compatible adapter edge."""

        return {
            "type": "function",
            "function": {
                "name": provider_name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _serialize_message(
        message: Message,
        agent_to_provider: Mapping[str, str],
    ) -> dict[str, Any]:
        if isinstance(message, RejectedAssistantMessage):
            return {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.provider_name,
                            "arguments": call.raw_arguments,
                        },
                    }
                    for call in message.tool_calls
                ],
            }
        if message.role == "system":
            return {"role": "system", "content": message.content}
        if message.role == "user":
            return {"role": "user", "content": message.content}
        if message.role == "assistant":
            payload: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": agent_to_provider.get(call.name, call.name),
                            "arguments": json.dumps(
                                call.arguments,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                    for call in message.tool_calls
                ]
            return payload
        if message.role == "tool":
            content = message.content
            if message.status == "error":
                content = {
                    "status": "error",
                    "error": message.error.model_dump(mode="json") if message.error else None,
                    "content": content,
                }
                if message.executed is not None:
                    content["executed"] = message.executed
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": OpenAICompatibleModelClient._content_to_string(content),
            }
        if message.role == "final":
            return {"role": "assistant", "content": message.content}
        raise ProviderProtocolError(f"unsupported message role: {message.role}")

    @staticmethod
    def _content_to_string(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


OpenAICompatibleAdapter = OpenAICompatibleModelClient

__all__ = [
    "ModelContextWindowError",
    "OpenAICompatibleAdapter",
    "OpenAICompatibleError",
    "OpenAICompatibleModelClient",
    "ProviderHTTPError",
    "ProviderProtocolError",
]
