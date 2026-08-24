"""httpx adapter for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any

import httpx

from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelRequest,
    ModelResponse,
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
    """The provider returned JSON that is not a supported chat-completions response."""


class MalformedToolArgumentsError(ProviderProtocolError):
    """A provider tool call contained invalid JSON or a non-object argument value."""


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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._serialize_message(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        response = await self._post(payload)
        return self._parse_response(response)

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        if self._client is not None:
            response = await self._client.post(url, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        if response.is_error:
            raise ProviderHTTPError(response.status_code, response.text)
        return response

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
