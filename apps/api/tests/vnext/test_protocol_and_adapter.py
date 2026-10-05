from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    build_history_compaction_request,
    validate_compaction_response,
)
from app.vnext.llm.diagnostics import (
    MAX_DIAGNOSTIC_ARGUMENT_BYTES,
    MAX_DIAGNOSTIC_ARGUMENT_EDGE_BYTES,
    MAX_DIAGNOSTIC_TOTAL_ARGUMENT_BYTES,
)
from app.vnext.llm.errors import ModelToolCallBatchRejected
from app.vnext.llm.openai_compatible import (
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


def _request(
    messages,
    tools=None,
    *,
    max_output_tokens: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ModelRequest:
    return ModelRequest(
        messages=messages,
        tools=tools or [],
        max_output_tokens=max_output_tokens,
        metadata={} if metadata is None else metadata,
    )


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


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "256"])
def test_model_request_rejects_invalid_output_token_limits(value: object) -> None:
    with pytest.raises(ValidationError):
        ModelRequest(
            messages=[UserMessage(content="hello")],
            max_output_tokens=value,  # type: ignore[arg-type]
        )


def test_model_request_output_token_limit_is_nullable_strict_and_round_trips() -> None:
    omitted = ModelRequest(messages=[UserMessage(content="hello")])
    explicit_none = ModelRequest(
        messages=[UserMessage(content="hello")],
        max_output_tokens=None,
    )
    request = ModelRequest(
        messages=[UserMessage(content="hello")],
        max_output_tokens=256,
    )

    assert omitted.max_output_tokens is None
    assert explicit_none.max_output_tokens is None
    assert request.max_output_tokens == 256
    assert ModelRequest.model_validate(request.model_dump(mode="json")) == request


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
    assert "max_tokens" not in payload
    assert "max_output_tokens" not in payload
    assert "max_completion_tokens" not in payload
    assert seen["headers"]["authorization"] == "Bearer test-key"


def test_adapter_complete_maps_explicit_output_limit_to_provider_payload() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    result = asyncio.run(
        _adapter(handler).complete(_request([UserMessage(content="go")], max_output_tokens=256))
    )

    assert result.message == FinalMessage(content="ok")
    assert seen["payload"]["max_tokens"] == 256
    assert "max_output_tokens" not in seen["payload"]
    assert "max_completion_tokens" not in seen["payload"]


def test_adapter_does_not_read_metadata_for_output_limit() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    asyncio.run(
        _adapter(handler).complete(
            _request(
                [UserMessage(content="go")],
                metadata={"max_output_tokens": 999},
            )
        )
    )

    assert "max_tokens" not in seen["payload"]


def test_adapter_output_limit_is_request_scoped() -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    client = _adapter(handler)
    asyncio.run(client.complete(_request([UserMessage(content="first")], max_output_tokens=256)))
    asyncio.run(client.complete(_request([UserMessage(content="second")])))

    assert payloads[0]["max_tokens"] == 256
    assert "max_tokens" not in payloads[1]


def test_adapter_maps_provider_unsafe_tool_names_at_its_boundary() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-2",
                                    "type": "function",
                                    "function": {
                                        "name": "sample_lookup",
                                        "arguments": '{"query":"Grand Final"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            request=request,
        )

    tool = ModelTool(
        name="sample.lookup",
        description="search matches",
        input_schema={"type": "object"},
    )
    request = _request(
        [
            UserMessage(content="find a match"),
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="call-1", name="sample.lookup", arguments={})],
            ),
            ToolResultMessage(tool_call_id="call-1", content={"matches": []}),
        ],
        [tool],
    )

    result = asyncio.run(_adapter(handler).complete(request))

    assert seen["payload"]["tools"][0]["function"]["name"] == "sample_lookup"
    assert seen["payload"]["messages"][1]["tool_calls"][0]["function"]["name"] == "sample_lookup"
    assert isinstance(result.message, AssistantMessage)
    assert result.message.tool_calls[0].name == "sample.lookup"


def _sse_body(*chunks: dict[str, Any]) -> str:
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def _collect_stream(client: OpenAICompatibleModelClient, request: ModelRequest):
    async def collect():
        return [item async for item in client.stream(request)]

    return asyncio.run(collect())


def _tool_batch_response(
    response_mode: str,
    calls: list[dict[str, Any]],
    *,
    finish_reason: str | None = "tool_calls",
    content: str | None = None,
) -> httpx.Response:
    request = httpx.Request("POST", "https://provider.test/v1/chat/completions")
    if response_mode == "complete":
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": content, "tool_calls": calls},
                        "finish_reason": finish_reason,
                    }
                ]
            },
            request=request,
        )
    stream_calls = [
        {"index": index, **call}
        for index, call in enumerate(calls)
    ]
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=_sse_body(
            {
                "choices": [
                    {
                        "delta": {"content": content, "tool_calls": stream_calls},
                        "finish_reason": finish_reason,
                    }
                ]
            }
        ),
        request=request,
    )


def _tool_call(call_id: str, arguments: Any, *, name: str = "echo") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _read_tool_batch(client: OpenAICompatibleModelClient, response_mode: str) -> ModelResponse:
    request = _request([UserMessage(content="run")])
    if response_mode == "complete":
        return asyncio.run(client.complete(request))
    items = _collect_stream(client, request)
    assert len(items) == 1
    assert isinstance(items[0], ModelResponse)
    return items[0]


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
def test_tool_call_batch_rejection_retains_every_call_and_failure(response_mode: str) -> None:
    raw_valid = '{"value":1, "label":"斯温\\n\\\"captain\\\""}'
    raw_invalid = "{not-json"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [_tool_call("call-valid", raw_valid), _tool_call("call-invalid", raw_invalid)],
            content="provider note",
        )

    client = _adapter(handler)
    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _read_tool_batch(client, response_mode)

    batch = raised.value.batch
    assert batch.reason == "invalid_tool_arguments"
    assert batch.content == "provider note"
    assert [call.id for call in batch.calls] == ["call-valid", "call-invalid"]
    assert [call.raw_arguments for call in batch.calls] == [raw_valid, raw_invalid]
    assert [failure.call_index for failure in batch.argument_failures] == [1]
    assert batch.argument_failures[0].kind == "invalid_json"
    assert batch.argument_failures[0].position is not None
    assert str(raised.value) == "model tool-call batch rejected: invalid_tool_arguments"
    assert raised.value.diagnostics is not None
    assert raised.value.diagnostics.tool_calls[1].id == "call-invalid"


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
def test_batch_classifies_all_invalid_arguments_without_reordering_calls(
    response_mode: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [
                _tool_call("call-first-invalid", "{"),
                _tool_call("call-valid", '{"value":2}'),
                _tool_call("call-last-invalid", "[]"),
            ],
        )

    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _read_tool_batch(_adapter(handler), response_mode)

    assert [call.id for call in raised.value.batch.calls] == [
        "call-first-invalid",
        "call-valid",
        "call-last-invalid",
    ]
    assert [failure.call_index for failure in raised.value.batch.argument_failures] == [0, 2]
    assert [failure.kind for failure in raised.value.batch.argument_failures] == [
        "invalid_json",
        "non_object_json",
    ]


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
@pytest.mark.parametrize(
    ("raw_arguments", "failure_kind"),
    [
        ("", "invalid_json"),
        (" \n\t", "invalid_json"),
        ("[]", "non_object_json"),
        ("null", "non_object_json"),
        ("12", "non_object_json"),
        ('"text"', "non_object_json"),
        ("false", "non_object_json"),
        ("NaN", "invalid_json"),
    ],
)
def test_tool_call_arguments_must_be_strict_json_objects(
    response_mode: str,
    raw_arguments: str,
    failure_kind: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [_tool_call("call-one", raw_arguments)],
        )

    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _read_tool_batch(_adapter(handler), response_mode)

    failure = raised.value.batch.argument_failures[0]
    assert failure.kind == failure_kind
    assert raised.value.batch.calls[0].raw_arguments == raw_arguments
    assert raised.value.batch.reason == "invalid_tool_arguments"


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
def test_tool_call_batch_with_length_is_rejected_even_when_arguments_are_valid(
    response_mode: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [_tool_call("call-one", '{"value":1}')],
            finish_reason="length",
        )

    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _read_tool_batch(_adapter(handler), response_mode)

    assert raised.value.batch.reason == "tool_response_truncated"
    assert raised.value.batch.argument_failures == []
    assert raised.value.batch.calls[0].raw_arguments == '{"value":1}'


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
def test_protocol_identity_errors_take_precedence_over_argument_json_errors(
    response_mode: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [
                _tool_call("call-invalid", "{"),
                {"type": "function", "function": {"name": "echo", "arguments": "{}"}},
            ],
        )

    with pytest.raises(ProviderProtocolError, match="id"):
        _read_tool_batch(_adapter(handler), response_mode)


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
def test_duplicate_tool_call_ids_are_protocol_errors(response_mode: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [_tool_call("call-same", "{"), _tool_call("call-same", "{}")],
        )

    with pytest.raises(ProviderProtocolError, match="IDs must be unique"):
        _read_tool_batch(_adapter(handler), response_mode)


@pytest.mark.parametrize("response_mode", ["complete", "stream"])
@pytest.mark.parametrize("raw_arguments", [None, 42, [], {}])
def test_non_string_argument_carriers_are_protocol_errors(
    response_mode: str,
    raw_arguments: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            response_mode,
            [_tool_call("call-one", raw_arguments)],
        )

    with pytest.raises(ProviderProtocolError, match="arguments must be"):
        _read_tool_batch(_adapter(handler), response_mode)


def test_raw_batch_keeps_full_arguments_while_trace_diagnostic_stays_bounded() -> None:
    large_raw = '{"text":"' + "λ" * (MAX_DIAGNOSTIC_ARGUMENT_BYTES + 200) + '"}'

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _tool_batch_response(
            "complete",
            [_tool_call("call-large", large_raw), _tool_call("call-invalid", "{")],
        )

    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _read_tool_batch(_adapter(handler), "complete")

    assert raised.value.batch.calls[0].raw_arguments == large_raw
    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    first_diagnostic_call = diagnostic.tool_calls[0]
    assert first_diagnostic_call.arguments_truncated is True
    assert first_diagnostic_call.raw_arguments is None


def test_raw_tool_call_contract_is_strict_and_forbids_unknown_fields() -> None:
    from app.vnext.llm.protocol import RawToolCall, RejectedToolCallBatch, ToolArgumentFailure

    raw_call = RawToolCall(
        index=0,
        id="call-1",
        name="echo",
        provider_name="echo",
        raw_arguments="{}",
    )
    batch = RejectedToolCallBatch(reason="invalid_tool_arguments", calls=[raw_call])
    failure = ToolArgumentFailure(call_index=0, kind="invalid_json", message="bad json")
    assert RejectedToolCallBatch.model_validate(batch.model_dump()) == batch
    assert ToolArgumentFailure.model_validate(failure.model_dump()) == failure
    with pytest.raises(ValidationError):
        RawToolCall(index=True, id="call-1", name="echo", provider_name="echo", raw_arguments="{}")
    with pytest.raises(ValidationError):
        RawToolCall(
            index=0,
            id="call-1",
            name="echo",
            provider_name="echo",
            raw_arguments="{}",
            unexpected=True,
        )


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

    items = _collect_stream(
        _adapter(handler),
        _request([UserMessage(content="go")], max_output_tokens=256),
    )
    assert [item.text for item in items if isinstance(item, ModelTextDelta)] == ["Hel", "lo"]
    assert isinstance(items[-1], ModelResponse)
    assert items[-1].message == FinalMessage(content="Hello")  # type: ignore[union-attr]
    assert seen["payload"]["stream"] is True
    assert seen["payload"]["max_tokens"] == 256
    assert "max_output_tokens" not in seen["payload"]
    assert "max_completion_tokens" not in seen["payload"]


def test_adapter_stream_omits_output_limit_when_request_does_not_set_one() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ),
            request=request,
        )

    items = _collect_stream(_adapter(handler), _request([UserMessage(content="go")]))

    assert items[-1].message == FinalMessage(content="ok")  # type: ignore[union-attr]
    assert seen["payload"]["stream"] is True
    assert "max_tokens" not in seen["payload"]


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


def test_adapter_maps_streamed_provider_tool_names_back_to_agent_names() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "sample_lookup",
                                            "arguments": "{}",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
            request=request,
        )

    items = _collect_stream(
        _adapter(handler),
        _request(
            [UserMessage(content="go")],
            [
                ModelTool(
                    name="sample.lookup",
                    description="search matches",
                    input_schema={"type": "object"},
                )
            ],
        ),
    )

    assert seen["payload"]["tools"][0]["function"]["name"] == "sample_lookup"
    assert isinstance(items[0], ModelResponse)
    assert isinstance(items[0].message, AssistantMessage)
    assert items[0].message.tool_calls[0].name == "sample.lookup"


def test_adapter_rejects_malformed_sse_and_missing_done_marker() -> None:
    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: not-json\n\n",
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match="valid JSON") as malformed_error:
        _collect_stream(_adapter(malformed), _request([UserMessage(content="go")]))
    malformed_diagnostics = malformed_error.value.diagnostics
    assert malformed_diagnostics is not None
    assert malformed_diagnostics.stage == "stream_protocol"
    assert malformed_diagnostics.stream_done_received is False
    assert malformed_diagnostics.tool_calls == ()
    assert "not-json" not in str(malformed_diagnostics.model_dump(mode="json"))

    def missing_done(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
            ).replace("data: [DONE]\n\n", ""),
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match=r"\[DONE\]") as missing_done_error:
        _collect_stream(_adapter(missing_done), _request([UserMessage(content="go")]))
    assert missing_done_error.value.diagnostics is not None
    assert missing_done_error.value.diagnostics.stream_done_received is False

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

    with pytest.raises(ModelToolCallBatchRejected) as malformed_error:
        asyncio.run(_adapter(malformed_arguments).complete(_request([])))
    assert malformed_error.value.batch.reason == "invalid_tool_arguments"
    assert str(malformed_error.value) == "model tool-call batch rejected: invalid_tool_arguments"
    diagnostic = malformed_error.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.response_mode == "complete"
    assert diagnostic.stage == "tool_arguments_decode"
    assert diagnostic.finish_reason is None
    assert diagnostic.usage == {}
    assert diagnostic.stream_done_received is None
    assert diagnostic.failed_tool_call_index == 0
    assert diagnostic.tool_calls[0].raw_arguments == "not-json"
    assert diagnostic.json_error is not None
    assert diagnostic.json_error.position == 0

    def malformed_arguments_with_metadata(request: httpx.Request) -> httpx.Response:
        response = malformed_arguments(request)
        payload = response.json()
        payload["usage"] = {"completion_tokens": 3}
        payload["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(ModelToolCallBatchRejected) as metadata_error:
        asyncio.run(_adapter(malformed_arguments_with_metadata).complete(_request([])))
    assert metadata_error.value.batch.reason == "tool_response_truncated"
    assert metadata_error.value.batch.argument_failures[0].kind == "invalid_json"
    metadata_diagnostic = metadata_error.value.diagnostics
    assert metadata_diagnostic is not None
    assert metadata_diagnostic.finish_reason == "length"
    assert metadata_diagnostic.usage == {"completion_tokens": 3}

    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="upstream unavailable", request=request)

    with pytest.raises(ProviderHTTPError) as http_exc:
        asyncio.run(_adapter(http_error).complete(_request([])))
    assert http_exc.value.status_code == 502

    def malformed_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []}, request=request)

    with pytest.raises(ProviderProtocolError):
        asyncio.run(_adapter(malformed_response).complete(_request([])))


def test_stream_tool_argument_failure_records_complete_multifragment_diagnostic() -> None:
    raw_arguments = '{"key":"斯温\n"bad"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-good",
                                        "function": {
                                            "name": "task_checkpoint",
                                            "arguments": '{"key":"position-4"}',
                                        },
                                    },
                                    {
                                        "index": 1,
                                        "id": "call-bad",
                                        "function": {
                                            "name": "task_checkpoint",
                                            "arguments": raw_arguments[:12],
                                        },
                                    },
                                ]
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
                                        "index": 1,
                                        "function": {"arguments": raw_arguments[12:]},
                                    }
                                ]
                            },
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"completion_tokens": 4096},
                },
            ),
            request=request,
        )

    request = _request(
        [UserMessage(content="run")],
        [ModelTool(name="task.checkpoint", description="checkpoint", input_schema={})],
    )
    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _collect_stream(_adapter(handler), request)

    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.stage == "tool_arguments_decode"
    assert diagnostic.response_mode == "stream"
    assert diagnostic.original_error_type == "ModelToolCallBatchRejected"
    assert raised.value.batch.reason == "tool_response_truncated"
    assert raised.value.batch.argument_failures[0].kind == "invalid_json"
    assert diagnostic.finish_reason == "length"
    assert diagnostic.usage == {"completion_tokens": 4096}
    assert diagnostic.stream_done_received is True
    assert diagnostic.failed_tool_call_index == 1
    assert diagnostic.tool_calls_total == 2
    assert [call.index for call in diagnostic.tool_calls] == [0, 1]
    assert diagnostic.tool_calls[0].raw_arguments == '{"key":"position-4"}'
    assert diagnostic.tool_calls[0].argument_fragment_count == 1
    assert diagnostic.tool_calls[0].provider_name == "task_checkpoint"
    assert diagnostic.tool_calls[0].agent_name == "task.checkpoint"
    assert diagnostic.tool_calls[1].raw_arguments == raw_arguments
    assert diagnostic.tool_calls[1].argument_fragment_count == 2
    assert diagnostic.json_error is not None
    expected_error = None
    try:
        json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        expected_error = exc
    assert expected_error is not None
    assert diagnostic.json_error.message == expected_error.msg
    assert diagnostic.json_error.position == expected_error.pos
    assert diagnostic.json_error.line == expected_error.lineno
    assert diagnostic.json_error.column == expected_error.colno
    failure = raised.value.batch.argument_failures[0]
    assert failure.message == expected_error.msg
    assert failure.position == expected_error.pos
    assert failure.line == expected_error.lineno
    assert failure.column == expected_error.colno


@pytest.mark.parametrize("finish_reason", ["tool_calls", None])
def test_stream_argument_diagnostic_does_not_infer_finish_reason_or_usage(
    finish_reason: str | None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-invalid",
                                        "function": {"name": "echo", "arguments": "not-json"},
                                    }
                                ]
                            },
                            "finish_reason": finish_reason,
                        }
                    ]
                }
            ),
            request=request,
        )

    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _collect_stream(_adapter(handler), _request([UserMessage(content="run")]))
    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.finish_reason == finish_reason
    assert diagnostic.usage == {}
    assert diagnostic.stream_done_received is True
    assert diagnostic.tool_calls[0].raw_arguments == "not-json"
    assert diagnostic.json_error is not None


def test_stream_protocol_diagnostic_retains_partial_calls_when_done_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse_body(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 3,
                                    "id": "call-partial",
                                    "function": {
                                        "name": "unknown_provider_tool",
                                        "arguments": '{"partial":',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"completion_tokens": 9},
            }
        ).replace("data: [DONE]\n\n", "")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match=r"\[DONE\]") as raised:
        _collect_stream(_adapter(handler), _request([UserMessage(content="run")]))
    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.stage == "stream_protocol"
    assert diagnostic.stream_done_received is False
    assert diagnostic.failed_tool_call_index is None
    assert diagnostic.finish_reason == "tool_calls"
    assert diagnostic.usage == {"completion_tokens": 9}
    assert diagnostic.tool_calls[0].agent_name is None
    assert diagnostic.tool_calls[0].raw_arguments == '{"partial":'
    assert diagnostic.tool_calls[0].argument_fragment_count == 1


def test_stream_protocol_failure_keeps_metadata_from_the_invalid_chunk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        chunk = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 4,
                                "id": "call-invalid",
                                "function": {"name": "echo", "arguments": ["not", "text"]},
                            }
                        ]
                    },
                    "finish_reason": "length",
                }
            ],
            "usage": {"completion_tokens": 13},
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(chunk),
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match="arguments must be a string") as raised:
        _collect_stream(_adapter(handler), _request([UserMessage(content="go")]))

    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.stage == "stream_protocol"
    assert diagnostic.finish_reason == "length"
    assert diagnostic.usage == {"completion_tokens": 13}
    assert diagnostic.stream_done_received is False
    assert diagnostic.failed_tool_call_index == 4
    assert diagnostic.tool_calls[0].id == "call-invalid"
    assert diagnostic.tool_calls[0].argument_fragment_count == 0


@pytest.mark.parametrize("response_mode", ["stream", "complete"])
def test_diagnostic_build_failure_does_not_replace_parse_error(
    monkeypatch: pytest.MonkeyPatch,
    response_mode: str,
) -> None:
    import app.vnext.llm.openai_compatible as adapter_module

    def fail_diagnostics(**_kwargs):
        raise RuntimeError("diagnostic builder failure")

    monkeypatch.setattr(adapter_module, "build_model_failure_diagnostics", fail_diagnostics)

    def handler(request: httpx.Request) -> httpx.Response:
        if response_mode == "stream":
            event = {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-bad",
                                    "function": {"name": "echo", "arguments": "not-json"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse_body(event),
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call-bad",
                                    "function": {"name": "echo", "arguments": "not-json"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            request=request,
        )

    client = _adapter(handler)
    request = _request([UserMessage(content="go")])
    expected_message = "model tool-call batch rejected: invalid_tool_arguments"
    with pytest.raises(ModelToolCallBatchRejected, match=expected_message) as raised:
        if response_mode == "stream":
            _collect_stream(client, request)
        else:
            asyncio.run(client.complete(request))

    assert str(raised.value) == expected_message
    assert raised.value.batch.reason == "invalid_tool_arguments"
    assert raised.value.diagnostics is None


def test_stream_response_assembly_failure_records_known_partial_tool_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 2,
                                        "function": {
                                            "name": "echo",
                                            "arguments": '{"value":1}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match="has no id") as raised:
        _collect_stream(_adapter(handler), _request([UserMessage(content="run")]))
    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.stage == "response_assembly"
    assert diagnostic.response_mode == "stream"
    assert diagnostic.stream_done_received is True
    assert diagnostic.failed_tool_call_index == 2
    assert diagnostic.tool_calls[0].id is None
    assert diagnostic.tool_calls[0].provider_name == "echo"
    assert diagnostic.tool_calls[0].raw_arguments == '{"value":1}'


def test_complete_response_diagnostic_includes_prior_tool_calls_and_exact_metadata() -> None:
    bad_arguments = "[1, 2]"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-first",
                                    "function": {"name": "echo", "arguments": '{"value":1}'},
                                },
                                {
                                    "id": "call-second",
                                    "function": {"name": "echo", "arguments": bad_arguments},
                                },
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
            request=request,
        )

    request = _request(
        [UserMessage(content="run")],
        [ModelTool(name="echo", description="echo", input_schema={})],
    )
    with pytest.raises(ModelToolCallBatchRejected) as raised:
        asyncio.run(_adapter(handler).complete(request))
    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.response_mode == "complete"
    assert diagnostic.stage == "tool_arguments_decode"
    assert diagnostic.failed_tool_call_index == 1
    assert diagnostic.finish_reason == "tool_calls"
    assert diagnostic.usage == {"prompt_tokens": 12, "completion_tokens": 4}
    assert diagnostic.stream_done_received is None
    assert [call.id for call in diagnostic.tool_calls] == ["call-first", "call-second"]
    assert [call.argument_fragment_count for call in diagnostic.tool_calls] == [None, None]
    assert diagnostic.tool_calls[1].raw_arguments == bad_arguments
    assert diagnostic.json_error is None
    assert raised.value.batch.argument_failures[0].kind == "non_object_json"


def test_complete_response_assembly_failure_keeps_observed_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length"}], "usage": {"prompt_tokens": 6}},
            request=request,
        )

    with pytest.raises(ProviderProtocolError, match="no message object") as raised:
        asyncio.run(_adapter(handler).complete(_request([UserMessage(content="go")])))

    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.stage == "response_assembly"
    assert diagnostic.response_mode == "complete"
    assert diagnostic.original_error_type == "ProviderProtocolError"
    assert diagnostic.finish_reason == "length"
    assert diagnostic.usage == {"prompt_tokens": 6}
    assert diagnostic.stream_done_received is None
    assert diagnostic.tool_calls == ()
    assert diagnostic.json_error is None


def test_diagnostic_argument_capture_respects_per_call_total_and_utf8_caps() -> None:
    raw_values = [f'{{"text":"{"λ" * 40000}"}}'] + [
        f'{{"text":"{"x" * 50000}"}}' for _ in range(6)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        chunk = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": index,
                                "id": f"call-{index}",
                                "function": {"name": "echo", "arguments": value},
                            }
                            for index, value in enumerate(raw_values)
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        body = _sse_body(chunk).replace("data: [DONE]\n\n", "")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    with pytest.raises(ProviderProtocolError) as raised:
        _collect_stream(_adapter(handler), _request([UserMessage(content="run")]))
    diagnostic = raised.value.diagnostics
    assert diagnostic is not None
    assert diagnostic.stream_done_received is False
    assert diagnostic.tool_calls_total == 7
    assert any(call.arguments_truncated for call in diagnostic.tool_calls)
    retained_bytes = 0
    for call in diagnostic.tool_calls:
        if call.raw_arguments is not None:
            retained_bytes += len(call.raw_arguments.encode("utf-8"))
            assert call.arguments_utf8_bytes <= MAX_DIAGNOSTIC_ARGUMENT_BYTES
        else:
            assert call.arguments_truncated
            for fragment in (call.arguments_prefix, call.arguments_suffix):
                if fragment is not None:
                    fragment_bytes = fragment.encode("utf-8")
                    assert fragment_bytes.decode("utf-8") == fragment
                    assert len(fragment_bytes) <= MAX_DIAGNOSTIC_ARGUMENT_EDGE_BYTES
                    retained_bytes += len(fragment_bytes)
        assert call.arguments_utf8_bytes == len(raw_values[call.index].encode("utf-8"))
    assert retained_bytes <= MAX_DIAGNOSTIC_TOTAL_ARGUMENT_BYTES
    assert diagnostic.tool_calls[0].arguments_utf8_bytes > MAX_DIAGNOSTIC_ARGUMENT_BYTES
    assert diagnostic.tool_calls[0].raw_arguments is None


def test_diagnostic_tool_call_count_is_capped_and_sorted_by_provider_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "id": f"call-{index}",
                                    "function": {"name": "unknown", "arguments": "{"},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
            for index in range(65, -1, -1)
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse_body(*chunks),
            request=request,
        )

    with pytest.raises(ModelToolCallBatchRejected) as raised:
        _collect_stream(_adapter(handler), _request([UserMessage(content="go")]))

    diagnostic = raised.value.diagnostics
    assert raised.value.batch.reason == "invalid_tool_arguments"
    assert diagnostic is not None
    assert diagnostic.tool_calls_total == 66
    assert diagnostic.tool_calls_truncated is True
    assert len(diagnostic.tool_calls) == 64
    assert [call.index for call in diagnostic.tool_calls] == list(range(64))


def test_compaction_request_limit_reaches_http_and_length_is_rejected() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]},
            request=request,
        )

    request = build_history_compaction_request(
        previous_summary=None,
        history_messages=[UserMessage(content="history")],
        max_input_bytes=100_000,
        max_output_tokens=256,
    )
    assert request.tools == []

    response = asyncio.run(_adapter(handler).complete(request))

    assert seen["payload"]["max_tokens"] == 256
    with pytest.raises(CompactionSummaryError) as error:
        validate_compaction_response(response)
    assert error.value.code == "summary_output_truncated"


def test_compaction_request_normal_stop_returns_valid_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "complete summary"}, "finish_reason": "stop"}]
            },
            request=request,
        )

    request = build_history_compaction_request(
        previous_summary="old",
        history_messages=[UserMessage(content="history")],
        max_input_bytes=100_000,
        max_output_tokens=256,
    )
    response = asyncio.run(_adapter(handler).complete(request))

    assert validate_compaction_response(response) == "complete summary"
