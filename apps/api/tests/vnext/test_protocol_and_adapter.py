from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

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
    ModelTextDelta,
    ModelTool,
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
    final_response = ModelResponse.from_final("done")
    assert final_response.is_final
    assert ModelResponse.model_validate(final_response.model_dump()) == final_response
    assert ModelResponse.model_validate(response.model_dump()) == response
    assert "final" not in ModelResponse.model_fields
    assert "assistant" not in ModelResponse.model_fields


def test_model_tool_is_generic_and_forbids_provider_wrapper_fields() -> None:
    tool = ModelTool(
        name="echo",
        description="echo",
        input_schema={"type": "object"},
    )
    assert tool.model_dump() == {
        "name": "echo",
        "description": "echo",
        "input_schema": {"type": "object"},
    }
    with pytest.raises(ValidationError):
        ModelTool(
            name="echo",
            description="echo",
            input_schema={},
            type="function",
        )


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
    payload = json.loads(seen["payload"])
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
    assert payload["tools"][0]["function"]["parameters"]["properties"]["value"]["type"] == "integer"
    assert request.tools[0].name == "echo"
    assert "type" not in request.tools[0].model_dump()
    assert "function" not in request.tools[0].model_dump()
    assert seen["headers"]["authorization"] == "Bearer test-key"


def _sse_body(*chunks: dict[str, Any]) -> str:
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def _collect_stream(client: OpenAICompatibleModelClient, request: ModelRequest):
    async def collect():
        return [item async for item in client.stream(request)]

    return asyncio.run(collect())


def test_adapter_streams_text_deltas_and_emits_one_final_response() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {
                    "choices": [
                        {"delta": {"role": "assistant", "content": "Hel"}, "finish_reason": None}
                    ]
                },
                {"choices": [{"delta": {"content": "lo"}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ),
            request=request,
        )

    items = _collect_stream(_adapter(handler), _request([UserMessage(content="go")]))
    assert [item.text for item in items if isinstance(item, ModelTextDelta)] == ["Hel", "lo"]
    assert isinstance(items[-1], ModelResponse)
    assert items[-1].message == FinalMessage(content="Hello")  # type: ignore[union-attr]
    assert seen["payload"]["stream"] is True


def test_adapter_assembles_streamed_tool_call_fragments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "echo",
                                            "arguments": '{"value":',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": "3}"},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ),
            request=request,
        )

    items = _collect_stream(_adapter(handler), _request([UserMessage(content="go")]))
    assert len(items) == 1
    assert isinstance(items[0], ModelResponse)
    assert isinstance(items[0].message, AssistantMessage)
    assert items[0].message.tool_calls[0].id == "call-1"
    assert items[0].message.tool_calls[0].name == "echo"
    assert items[0].message.tool_calls[0].arguments == {"value": 3}


def test_adapter_rejects_malformed_sse_and_missing_done_marker() -> None:
    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: not-json\n\n",
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match="valid JSON"):
        _collect_stream(_adapter(malformed), _request([UserMessage(content="go")]))

    def missing_done(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
            ).replace("data: [DONE]\n\n", ""),
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match=r"\[DONE\]"):
        _collect_stream(_adapter(missing_done), _request([UserMessage(content="go")]))

    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="provider secret body", request=request)

    with pytest.raises(ProviderHTTPError):
        _collect_stream(_adapter(http_error), _request([UserMessage(content="go")]))


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
