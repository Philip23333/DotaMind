from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.vnext.llm.openai_compatible import (
    MalformedToolArgumentsError,
    OpenAICompatibleModelClient,
    ProviderHTTPError,
    ProviderProtocolError,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools import ToolDefinition, ToolRegistry


class EchoInput(BaseModel):
    value: int


class EchoOutput(BaseModel):
    value: int


def _adapter(handler) -> OpenAICompatibleModelClient:
    return OpenAICompatibleModelClient(
        api_key="test-key",
        base_url="https://provider.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )


def _request(messages, tools=None) -> ModelRequest:
    return ModelRequest(messages=messages, tools=tools or [])


def test_protocol_supports_nullable_assistant_and_multiple_calls() -> None:
    message = AssistantMessage(
        content=None,
        tool_calls=[
            ToolCall(id="one", name="echo", arguments={"value": 1}),
            ToolCall(id="two", name="echo", arguments={"value": 2}),
        ],
    )
    response = ModelResponse(message=message)
    assert response.message == message
    assert len(response.message.tool_calls) == 2  # type: ignore[union-attr]
    assert ModelResponse(final=FinalMessage(content="done")).is_final


def test_adapter_serializes_messages_tools_and_tool_result_ids() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["payload"] = request.read()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=lambda args: EchoOutput(value=args.value),
        )
    )
    client = _adapter(handler)
    request = _request(
        [
            SystemMessage(content="system"),
            UserMessage(content="hello"),
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="c1", name="echo", arguments={"value": 3})],
            ),
            ToolResultMessage(tool_call_id="c1", content={"value": 3}),
        ],
        registry.schemas(),
    )

    result = asyncio.run(client.complete(request))
    payload = __import__("json").loads(seen["payload"])
    assert result.message == FinalMessage(content="ok")
    assert payload["model"] == "test-model"
    assert payload["messages"][2]["tool_calls"][0]["id"] == "c1"
    assert payload["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"value":3}'
    assert payload["messages"][3] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": '{"value":3}',
    }
    assert payload["tools"][0]["function"]["name"] == "echo"
    assert seen["headers"]["authorization"] == "Bearer test-key"


def test_adapter_parses_final_and_multiple_tool_calls_with_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-a",
                                    "type": "function",
                                    "function": {"name": "echo", "arguments": '{"value":1}'},
                                },
                                {
                                    "id": "call-b",
                                    "type": "function",
                                    "function": {"name": "echo", "arguments": '{"value":2}'},
                                },
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            request=request,
        )

    result = asyncio.run(_adapter(handler).complete(_request([UserMessage(content="go")])))
    assert isinstance(result.message, AssistantMessage)
    assert [call.id for call in result.message.tool_calls] == ["call-a", "call-b"]
    assert [call.arguments for call in result.message.tool_calls] == [{"value": 1}, {"value": 2}]


def test_adapter_rejects_malformed_arguments_http_errors_and_protocol_shapes() -> None:
    def malformed_arguments(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "bad",
                                    "function": {"name": "echo", "arguments": "not-json"},
                                }
                            ],
                        }
                    }
                ]
            },
            request=request,
        )

    with pytest.raises(MalformedToolArgumentsError):
        asyncio.run(_adapter(malformed_arguments).complete(_request([])))

    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="upstream unavailable", request=request)

    with pytest.raises(ProviderHTTPError) as http_exc:
        asyncio.run(_adapter(http_error).complete(_request([])))
    assert http_exc.value.status_code == 502

    def malformed_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []}, request=request)

    with pytest.raises(ProviderProtocolError):
        asyncio.run(_adapter(malformed_response).complete(_request([])))
