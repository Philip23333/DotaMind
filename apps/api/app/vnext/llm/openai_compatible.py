"""httpx adapter for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any

import httpx

from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ModelTool,
    ToolCall,
)


class OpenAICompatibleError(RuntimeError):
    """Base error for an OpenAI-compatible transport/protocol failure."""


class ProviderHTTPError(OpenAICompatibleError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"model provider returned HTTP {status_code}")
        self.status_code = status_code
        self.body = body


class ProviderProtocolError(OpenAICompatibleError):
    """The provider returned data that is not a supported chat-completions response."""


class MalformedToolArgumentsError(ProviderProtocolError):
    """A provider tool call contained invalid JSON or a non-object argument value."""


@dataclass
class _ToolCallAccumulator:
    call_id: str | None = None
    name: str | None = None
    argument_fragments: list[str] = field(default_factory=list)


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
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self._client = client

    async def complete(self, request: ModelRequest) -> ModelResponse:
        response = await self._post(self._payload(request))
        return self._parse_response(response)

    async def stream(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ModelTextDelta | ModelResponse]:
        """Stream provider text deltas and one assembled terminal response."""

        payload = self._payload(request)
        payload["stream"] = True

        content_parts: list[str] = []
        tool_calls: dict[int, _ToolCallAccumulator] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] = {}
        saw_done = False

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

        yield self._assemble_stream_response(
            content_parts,
            tool_calls,
            finish_reason,
            usage,
        )

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._serialize_message(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in request.tools]
            payload["tool_choice"] = "auto"
        return payload

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = self._headers()
        url = self._url()
        if self._client is not None:
            response = await self._client.post(url, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        self._raise_for_status(response)
        return response

    @asynccontextmanager
    async def _open_stream(self, payload: dict[str, Any]) -> AsyncIterator[httpx.Response]:
        headers = self._headers()
        url = self._url()
        if self._client is not None:
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_error:
            raise ProviderHTTPError(response.status_code, response.text)

    @staticmethod
    async def _raise_for_status_async(response: httpx.Response) -> None:
        if response.is_error:
            await response.aread()
            raise ProviderHTTPError(response.status_code, response.text)

    @classmethod
    def _parse_response(cls, response: httpx.Response) -> ModelResponse:
        try:
            data = response.json()
        except (JSONDecodeError, ValueError) as exc:
            raise ProviderProtocolError("model provider returned invalid JSON") from exc
        if not isinstance(data, Mapping):
            raise ProviderProtocolError("model provider response must be a JSON object")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderProtocolError("model provider response has no choices")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ProviderProtocolError("model provider choice must be an object")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ProviderProtocolError("model provider choice has no message object")

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ProviderProtocolError("assistant message content must be a string or null")
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls is not None and not isinstance(raw_tool_calls, list):
            raise ProviderProtocolError("assistant tool_calls must be a list")

        tool_calls = [cls._parse_tool_call(raw_call) for raw_call in (raw_tool_calls or [])]
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise ProviderProtocolError("finish_reason must be a string or null")
        if tool_calls:
            return ModelResponse(
                message=AssistantMessage(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
                usage=cls._usage(data),
            )
        if content is None:
            raise ProviderProtocolError("final assistant message has no content")
        return ModelResponse(
            message=FinalMessage(content=content),
            finish_reason=finish_reason,
            usage=cls._usage(data),
        )

    @classmethod
    def _consume_stream_chunk(
        cls,
        chunk: Any,
        content_parts: list[str],
        tool_calls: dict[int, _ToolCallAccumulator],
    ) -> tuple[list[ModelTextDelta], str | None, dict[str, Any]]:
        if not isinstance(chunk, Mapping):
            raise ProviderProtocolError("stream data must be a JSON object")

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
        if not isinstance(index, int) or index < 0:
            raise ProviderProtocolError("stream tool call index must be a non-negative integer")
        accumulator = tool_calls.setdefault(index, _ToolCallAccumulator())

        call_id = raw_call.get("id")
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id:
                raise ProviderProtocolError("stream tool call id must be a non-empty string")
            if accumulator.call_id is not None and accumulator.call_id != call_id:
                raise ProviderProtocolError("stream tool call id changed during assembly")
            accumulator.call_id = call_id

        raw_function = raw_call.get("function")
        if raw_function is not None and not isinstance(raw_function, Mapping):
            raise ProviderProtocolError("stream tool call function must be an object")
        if raw_function is None:
            return

        name = raw_function.get("name")
        if name is not None:
            if not isinstance(name, str) or not name:
                raise ProviderProtocolError("stream tool call name must be a non-empty string")
            if accumulator.name is not None and accumulator.name != name:
                raise ProviderProtocolError("stream tool call name changed during assembly")
            accumulator.name = name

        arguments = raw_function.get("arguments")
        if arguments is not None:
            if not isinstance(arguments, str):
                raise ProviderProtocolError("stream tool call arguments must be a string")
            accumulator.argument_fragments.append(arguments)

    @classmethod
    def _assemble_stream_response(
        cls,
        content_parts: list[str],
        tool_calls: dict[int, _ToolCallAccumulator],
        finish_reason: str | None,
        usage: dict[str, Any],
    ) -> ModelResponse:
        content = "".join(content_parts) if content_parts else None
        if tool_calls:
            assembled_calls: list[ToolCall] = []
            for index, accumulator in sorted(tool_calls.items()):
                if not accumulator.call_id:
                    raise ProviderProtocolError(f"stream tool call {index} has no id")
                if not accumulator.name:
                    raise ProviderProtocolError(f"stream tool call {index} has no name")
                encoded_arguments = "".join(accumulator.argument_fragments) or "{}"
                try:
                    arguments = json.loads(encoded_arguments)
                except JSONDecodeError as exc:
                    raise MalformedToolArgumentsError(
                        "stream tool call arguments are not valid JSON"
                    ) from exc
                if not isinstance(arguments, dict):
                    raise MalformedToolArgumentsError(
                        "stream tool call arguments must decode to an object"
                    )
                assembled_calls.append(
                    ToolCall(
                        id=accumulator.call_id,
                        name=accumulator.name,
                        arguments=arguments,
                    )
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
    def _parse_tool_call(cls, raw_call: Any) -> ToolCall:
        if not isinstance(raw_call, Mapping):
            raise ProviderProtocolError("tool call must be an object")
        call_id = raw_call.get("id")
        if not isinstance(call_id, str) or not call_id:
            raise ProviderProtocolError("tool call id must be a non-empty string")
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            raise ProviderProtocolError("tool call function must be an object")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ProviderProtocolError("tool call function name must be a non-empty string")
        raw_arguments = function.get("arguments")
        if not isinstance(raw_arguments, str):
            raise MalformedToolArgumentsError(
                "tool call arguments must be a JSON-encoded string"
            )
        try:
            arguments = json.loads(raw_arguments)
        except JSONDecodeError as exc:
            raise MalformedToolArgumentsError("tool call arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise MalformedToolArgumentsError("tool call arguments must decode to an object")
        try:
            return ToolCall(id=call_id, name=name, arguments=arguments)
        except ValueError as exc:
            raise ProviderProtocolError("tool call arguments are not a valid object") from exc

    @staticmethod
    def _serialize_tool(tool: ModelTool) -> dict[str, Any]:
        """Convert the generic tool only at the OpenAI-compatible adapter edge."""

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _serialize_message(message: Message) -> dict[str, Any]:
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
                            "name": call.name,
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
    "MalformedToolArgumentsError",
    "OpenAICompatibleAdapter",
    "OpenAICompatibleError",
    "OpenAICompatibleModelClient",
    "ProviderHTTPError",
    "ProviderProtocolError",
]
