from __future__ import annotations

import copy
import json

import pytest

from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    HistoryCompactionRangeError,
    build_history_compaction_request,
    build_turn_prefix_compaction_request,
    validate_compaction_response,
)
from app.vnext.agent.instructions import (
    HISTORY_COMPACTION_INSTRUCTION,
    TURN_PREFIX_COMPACTION_INSTRUCTION,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def _request_data(request: ModelRequest) -> dict:
    assert len(request.messages) == 2
    assert isinstance(request.messages[1], UserMessage)
    return json.loads(request.messages[1].content)


def _build(
    *,
    previous_summary: str | None = None,
    history: list | None = None,
    max_output_tokens: int = 256,
) -> ModelRequest:
    return build_history_compaction_request(
        previous_summary=previous_summary,
        history_messages=([UserMessage(content="old history")] if history is None else history),
        max_output_tokens=max_output_tokens,
    )


def _call(call_id: str = "call-1") -> ToolCall:
    return ToolCall(id=call_id, name="lookup", arguments={"query": "TI"})


def _result(call_id: str = "call-1", content: object | None = None) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        content={"value": "observed"} if content is None else content,
    )


def test_first_compaction_request_keeps_null_previous_summary() -> None:
    request = _build()

    assert _request_data(request) == {
        "previous_summary": None,
        "history": [{"content": "old history", "role": "user"}],
    }


def test_follow_up_compaction_request_preserves_previous_summary_verbatim() -> None:
    request = _build(previous_summary="  old summary\n")

    assert _request_data(request)["previous_summary"] == "  old summary\n"


def test_compaction_request_has_only_instruction_and_data_without_tools() -> None:
    request = _build()

    assert request.messages[0] == SystemMessage(content=HISTORY_COMPACTION_INSTRUCTION)
    assert isinstance(request.messages[1], UserMessage)
    assert request.tools == []
    assert request.step is None
    assert request.metadata == {
        "purpose": "context_compaction",
        "compaction_kind": "history",
    }
    assert request.max_output_tokens == 256


def test_compaction_request_preserves_explicit_output_token_limit() -> None:
    request = _build(max_output_tokens=1234)

    assert request.max_output_tokens == 1234


def test_turn_prefix_request_contains_only_its_turn_and_has_distinct_metadata() -> None:
    turn = [UserMessage(content="original request"), AssistantMessage(content="early progress")]
    request = build_turn_prefix_compaction_request(
        turn_prefix_messages=turn,
        max_output_tokens=8192,
    )

    assert request.messages[0] == SystemMessage(content=TURN_PREFIX_COMPACTION_INSTRUCTION)
    assert _request_data(request) == {
        "turn_prefix": [message.model_dump(mode="json") for message in turn],
    }
    assert request.metadata == {
        "purpose": "context_compaction",
        "compaction_kind": "turn_prefix",
    }
    assert request.max_output_tokens == 8192


def test_turn_prefix_request_does_not_mix_old_summary_or_recent_history() -> None:
    request = build_turn_prefix_compaction_request(
        turn_prefix_messages=[UserMessage(content="first question")],
        max_output_tokens=128,
    )
    encoded = request.messages[1].content

    assert "previous_summary" not in encoded
    assert "recent retained" not in encoded


def test_tool_messages_are_serialized_as_history_data_with_relationships() -> None:
    call = _call()
    prefix = [AssistantMessage(tool_calls=[call]), _result(call.id)]

    data = _request_data(_build(history=prefix))

    assert data["history"] == [
        {
            "content": None,
            "role": "assistant",
            "tool_calls": [
                {
                    "arguments": {"query": "TI"},
                    "id": "call-1",
                    "name": "lookup",
                }
            ],
        },
        {
            "content": {"value": "observed"},
            "error": None,
            "role": "tool",
            "status": "ok",
            "tool_call_id": "call-1",
        },
    ]


def test_history_request_does_not_rewrite_repeated_user_text() -> None:
    repeated = [UserMessage(content="same question"), UserMessage(content="same question")]
    data = _request_data(_build(history=repeated))

    assert data["history"] == [
        {"content": "same question", "role": "user"},
        {"content": "same question", "role": "user"},
    ]


@pytest.mark.parametrize(
    "prefix",
    [[]],
)
def test_empty_compaction_history_is_rejected(prefix: list) -> None:
    with pytest.raises(CompactionSummaryError) as error:
        _build(history=prefix)

    assert error.value.code == "empty_compaction_history"


@pytest.mark.parametrize(
    "prefix",
    [
        [AssistantMessage(tool_calls=[_call()])],
        [_result()],
        [SystemMessage(content="runtime instruction")],
        [AssistantMessage(tool_calls=[_call()]), UserMessage(content="interleaved")],
    ],
)
def test_invalid_history_uses_existing_range_structure_error(prefix: list) -> None:
    with pytest.raises(HistoryCompactionRangeError) as error:
        _build(history=prefix)

    assert error.value.code == "invalid_history_structure"


def test_building_request_does_not_mutate_messages_or_nested_tool_content() -> None:
    call = _call()
    result = _result(content={"rows": [{"value": 1}]})
    prefix = [AssistantMessage(tool_calls=[call]), result]
    before = copy.deepcopy(prefix)

    _build(history=prefix)

    assert prefix == before


def test_summary_request_builder_accepts_input_larger_than_legacy_byte_limit() -> None:
    request = _build(history=[UserMessage(content="x" * (256 * 1024 + 1024))])

    assert measure_request_context_bytes(request) > 256 * 1024
    assert request.max_output_tokens == 256


def test_input_budget_counts_utf8_bytes() -> None:
    prefix = [UserMessage(content="中文历史")]
    request = _build(history=prefix)

    assert len(request.messages[1].content.encode("utf-8")) > len(request.messages[1].content)
    assert measure_request_context_bytes(request) == measure_request_context_bytes(
        _build(
            history=prefix,
        )
    )


def test_deferred_and_receipt_observations_are_kept_as_returned_data() -> None:
    calls = AssistantMessage(tool_calls=[_call("deferred"), _call("receipt")])
    prefix = [
        calls,
        _result(
            "deferred",
            content={"_context_materialization": {"state": "deferred"}},
        ),
        _result(
            "receipt",
            content={"_artifact_observation": {"state": "receipt_only"}},
        ),
    ]

    history = _request_data(_build(history=prefix))["history"]

    assert history[1]["content"] == {"_context_materialization": {"state": "deferred"}}
    assert history[2]["content"] == {"_artifact_observation": {"state": "receipt_only"}}


@pytest.mark.parametrize("max_output_tokens", [0, -1, True, False, 1.5, "256"])
def test_invalid_compaction_output_token_limits_are_rejected(
    max_output_tokens: object,
) -> None:
    with pytest.raises(CompactionSummaryError) as error:
        _build(max_output_tokens=max_output_tokens)  # type: ignore[arg-type]

    assert error.value.code == "invalid_summary_budget"


def test_valid_summary_returns_original_text_without_rewriting() -> None:
    summary = "  合法摘要，没有固定标题。\n"

    result = validate_compaction_response(
        ModelResponse.from_final(summary, finish_reason="stop"),
    )

    assert result == summary


@pytest.mark.parametrize(
    "message",
    [
        AssistantMessage(content="summary"),
        AssistantMessage(tool_calls=[_call()]),
    ],
)
def test_assistant_summary_responses_are_rejected(message: AssistantMessage) -> None:
    with pytest.raises(CompactionSummaryError) as error:
        validate_compaction_response(ModelResponse(message=message, finish_reason="stop"))

    assert error.value.code == "invalid_summary_response"


def test_length_finish_reason_is_rejected_as_truncated() -> None:
    with pytest.raises(CompactionSummaryError) as error:
        validate_compaction_response(ModelResponse.from_final("partial", finish_reason="length"))

    assert error.value.code == "summary_output_truncated"


@pytest.mark.parametrize("finish_reason", [None, "content_filter", "unknown"])
def test_unconfirmed_finish_reasons_are_rejected(finish_reason: str | None) -> None:
    with pytest.raises(CompactionSummaryError) as error:
        validate_compaction_response(
            ModelResponse.from_final("summary", finish_reason=finish_reason)
        )

    assert error.value.code == "summary_completion_unconfirmed"


@pytest.mark.parametrize("summary", ["", "   \n\t"])
def test_empty_summary_is_rejected(summary: str) -> None:
    with pytest.raises(CompactionSummaryError) as error:
        validate_compaction_response(ModelResponse.from_final(summary, finish_reason="stop"))

    assert error.value.code == "empty_summary"


def test_summary_larger_than_old_8k_byte_limit_is_accepted() -> None:
    summary = "摘要" + "x" * 8190
    assert len(summary.encode("utf-8")) > 8 * 1024

    assert (
        validate_compaction_response(ModelResponse.from_final(summary, finish_reason="stop"))
        == summary
    )
