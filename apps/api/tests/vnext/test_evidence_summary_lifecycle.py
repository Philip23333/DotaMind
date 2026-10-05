from __future__ import annotations

import json

import pytest

from app.vnext.agent.evidence_summary_lifecycle import (
    HistoryCompactionRangeError,
    prepare_compaction,
    validate_compaction_cut,
)
from app.vnext.agent.evidence_summary_lifecycle import (
    select_compaction_range as _select_compaction_range,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    RawToolCall,
    RejectedAssistantMessage,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.errors import ToolError


def _message_bytes(message) -> int:
    return len(
        json.dumps(
            message.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _size(messages) -> int:
    return sum(_message_bytes(message) for message in messages)


def _tokens(messages, bytes_per_token: int = 2) -> int:
    return (_size(messages) + bytes_per_token - 1) // bytes_per_token


def select_compaction_range(messages, *, recent_history_tokens, bytes_per_token=2):
    return _select_compaction_range(
        messages,
        recent_history_tokens=recent_history_tokens,
        bytes_per_token=bytes_per_token,
    )


def _call(call_id: str, name: str = "lookup") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"id": call_id})


def _result(call_id: str, *, content=None, error: bool = False) -> ToolResultMessage:
    if error:
        return ToolResultMessage(
            tool_call_id=call_id,
            status="error",
            error=ToolError(code="tool_execution_error", message="failed"),
        )
    return ToolResultMessage(
        tool_call_id=call_id,
        content=content if content is not None else {"value": call_id},
    )


def _tool_group(*call_ids: str, results=None) -> list:
    calls = AssistantMessage(tool_calls=[_call(call_id) for call_id in call_ids])
    returned = list(results) if results is not None else [_result(call_id) for call_id in call_ids]
    return [calls, *returned]


def test_empty_history_returns_none() -> None:
    assert select_compaction_range([], recent_history_tokens=100) is None


@pytest.mark.parametrize("budget", [0, -1, True, False])
def test_non_positive_or_non_integer_budget_is_rejected(budget: int) -> None:
    with pytest.raises(HistoryCompactionRangeError) as error:
        select_compaction_range([UserMessage(content="history")], recent_history_tokens=budget)

    assert error.value.code == "invalid_recent_history_budget"


def test_all_history_within_budget_returns_none() -> None:
    messages = [UserMessage(content="one"), FinalMessage(content="two")]

    assert select_compaction_range(messages, recent_history_tokens=_tokens(messages)) is None


def test_single_unsplittable_group_returns_none_even_when_over_budget() -> None:
    messages = _tool_group("a", "b")

    assert select_compaction_range(messages, recent_history_tokens=1) is None


def test_exact_budget_keeps_latest_group_and_compresses_older_prefix() -> None:
    first = [UserMessage(content="first")]
    second = [FinalMessage(content="second")]
    third = [UserMessage(content="third")]
    messages = [*first, *second, *third]

    selected = select_compaction_range(messages, recent_history_tokens=_tokens(third))

    assert selected is not None
    assert selected.cut_index == 2
    assert selected.prefix_messages == tuple(messages[:2])
    assert selected.retained_messages == tuple(third)
    assert selected.retained_bytes == _size(third)
    assert selected.retained_estimated_tokens == _tokens(third)


def test_budget_crossing_keeps_the_group_that_crossed_the_target() -> None:
    first = [UserMessage(content="first")]
    second = [FinalMessage(content="second")]
    third = [UserMessage(content="third")]
    messages = [*first, *second, *third]
    budget = _tokens([*second, *third]) - 1

    selected = select_compaction_range(messages, recent_history_tokens=budget)

    assert selected is not None
    assert selected.cut_index == 1
    assert selected.retained_messages == tuple(messages[1:])
    assert selected.retained_bytes == _size(second) + _size(third)


def test_latest_group_over_budget_is_kept_intact() -> None:
    latest = _tool_group("a", "b")
    messages = [UserMessage(content="old"), *latest]

    selected = select_compaction_range(messages, recent_history_tokens=1)

    assert selected is not None
    assert selected.cut_index == 1
    assert selected.retained_messages == tuple(latest)
    assert selected.retained_bytes == _size(latest)


def test_multiple_tool_calls_and_out_of_order_results_stay_one_group() -> None:
    group = _tool_group(
        "a",
        "b",
        results=[_result("b"), _result("a")],
    )
    messages = [*group, FinalMessage(content="answer")]

    selected = select_compaction_range(
        messages,
        recent_history_tokens=_tokens([messages[-1]]),
    )

    assert selected is not None
    assert selected.cut_index == len(group)
    assert selected.prefix_messages == tuple(group)


def test_error_deferred_and_receipt_results_are_complete_returns() -> None:
    group = _tool_group(
        "error",
        "deferred",
        "receipt",
        results=[
            _result("deferred", content={"_context_materialization": {"state": "deferred"}}),
            _result("receipt", content={"_artifact_observation": {"state": "receipt_only"}}),
            _result("error", error=True),
        ],
    )
    messages = [UserMessage(content="old"), *group]

    selected = select_compaction_range(messages, recent_history_tokens=1)

    assert selected is not None
    assert selected.prefix_messages == (messages[0],)
    assert selected.retained_messages == tuple(group)


@pytest.mark.parametrize(
    "messages",
    [
        [AssistantMessage(tool_calls=[_call("a")])],
        _tool_group("a", results=[_result("b")]),
        [_result("a")],
        _tool_group("a") + [_result("a")],
        [AssistantMessage(tool_calls=[_call("a"), _call("a")]), _result("a")],
        [
            AssistantMessage(tool_calls=[_call("a")]),
            UserMessage(content="interleaved"),
            _result("a"),
        ],
        [SystemMessage(content="runtime instruction"), UserMessage(content="query")],
    ],
)
def test_invalid_history_structure_is_rejected(messages: list) -> None:
    with pytest.raises(HistoryCompactionRangeError) as error:
        select_compaction_range(messages, recent_history_tokens=100)

    assert error.value.code == "invalid_history_structure"


def test_repeated_tool_call_id_is_allowed_in_different_batches() -> None:
    messages = [
        *_tool_group("same"),
        FinalMessage(content="between batches"),
        *_tool_group("same"),
    ]

    selected = select_compaction_range(messages, recent_history_tokens=1)

    assert selected is not None
    assert selected.cut_index == 3
    assert selected.prefix_messages == tuple(messages[:3])


def test_single_user_task_can_split_early_tool_work_without_a_new_user_message() -> None:
    early_group = _tool_group("early")
    latest = [FinalMessage(content="completed answer")]
    messages = [UserMessage(content="one long task"), *early_group, *latest]

    selected = select_compaction_range(messages, recent_history_tokens=_tokens(latest))

    assert selected is not None
    assert selected.cut_index == 1 + len(early_group)
    assert selected.prefix_messages == tuple(messages[: selected.cut_index])
    assert selected.retained_messages == tuple(latest)


def test_input_and_result_are_deeply_isolated() -> None:
    messages = [
        *_tool_group(
            "read",
            results=[_result("read", content={"facts": [{"value": "old"}]})],
        ),
        FinalMessage(content="recent"),
    ]
    selected = select_compaction_range(messages, recent_history_tokens=_tokens([messages[-1]]))
    assert selected is not None

    selected.prefix_messages[1].content["facts"][0]["value"] = "result changed"  # type: ignore[index]
    assert messages[1].content == {"facts": [{"value": "old"}]}
    messages[1].content = "input changed"

    assert selected.prefix_messages[1].content == {"facts": [{"value": "result changed"}]}
    assert selected.retained_messages[0].content == "recent"


def test_retained_bytes_use_utf8_serialized_message_size() -> None:
    latest = UserMessage(content="中文内容")
    messages = [UserMessage(content="old"), latest]

    selected = select_compaction_range(messages, recent_history_tokens=_tokens([latest]))

    assert selected is not None
    assert selected.retained_bytes == _message_bytes(latest)
    assert selected.retained_bytes > len(latest.content)
    assert selected.retained_estimated_tokens == _tokens([latest])


def test_cut_at_next_user_message_uses_history_only() -> None:
    messages = [
        UserMessage(content="completed question"),
        FinalMessage(content="completed answer"),
        UserMessage(content="next question"),
    ]

    prepared = prepare_compaction(
        messages,
        recent_history_tokens=_tokens([messages[-1]]),
        bytes_per_token=2,
    )

    assert prepared is not None
    assert prepared.cut_index == 2
    assert prepared.history_messages == tuple(messages[:2])
    assert prepared.turn_prefix_messages == ()
    assert prepared.split_turn_start_index is None


def test_cut_inside_long_turn_splits_original_request_from_older_history() -> None:
    calls = _tool_group("read")
    messages = [
        UserMessage(content="older request"),
        FinalMessage(content="older answer"),
        UserMessage(content="current long request"),
        AssistantMessage(content="early progress"),
        *calls,
        AssistantMessage(content="recent progress"),
        FinalMessage(content="latest retained final"),
    ]
    suffix = messages[4:]

    prepared = prepare_compaction(
        messages,
        recent_history_tokens=_tokens(suffix),
        bytes_per_token=2,
    )

    assert prepared is not None
    assert prepared.cut_index == 4
    assert prepared.history_messages == tuple(messages[:2])
    assert prepared.turn_prefix_messages == tuple(messages[2:4])
    assert prepared.retained_messages == tuple(suffix)
    assert prepared.split_turn_start_index == 2


def test_second_question_retained_does_not_replace_split_first_question() -> None:
    messages = [
        UserMessage(content="first question"),
        AssistantMessage(content="first task early progress"),
        AssistantMessage(content="first task later progress"),
        UserMessage(content="second question"),
        AssistantMessage(content="second task progress"),
        FinalMessage(content="second answer"),
    ]

    prepared = prepare_compaction(
        messages,
        recent_history_tokens=_tokens(messages[2:]),
        bytes_per_token=2,
    )

    assert prepared is not None
    assert prepared.cut_index == 2
    assert prepared.history_messages == ()
    assert prepared.turn_prefix_messages == tuple(messages[:2])
    assert prepared.turn_prefix_messages[0].content == "first question"
    assert prepared.retained_messages[0].content == "first task later progress"


def test_missing_owning_user_message_falls_back_to_history_summary() -> None:
    messages = [
        AssistantMessage(content="orphaned but structurally valid progress"),
        FinalMessage(content="recent final"),
    ]

    prepared = prepare_compaction(
        messages,
        recent_history_tokens=_tokens([messages[-1]]),
        bytes_per_token=2,
    )

    assert prepared is not None
    assert prepared.history_messages == (messages[0],)
    assert prepared.turn_prefix_messages == ()
    assert prepared.split_turn_start_index is None


def test_repeated_question_text_is_split_by_position_and_retained_final_is_not_history() -> None:
    messages = [
        UserMessage(content="same question"),
        AssistantMessage(content="first turn progress"),
        UserMessage(content="same question"),
        AssistantMessage(content="second turn progress"),
        FinalMessage(content="still retained"),
    ]

    prepared = prepare_compaction(
        messages,
        recent_history_tokens=_tokens([messages[-1]]),
        bytes_per_token=2,
    )

    assert prepared is not None
    assert prepared.cut_index == 4
    assert prepared.split_turn_start_index == 2
    assert prepared.history_messages == tuple(messages[:2])
    assert prepared.turn_prefix_messages == tuple(messages[2:4])
    assert isinstance(prepared.retained_messages[0], FinalMessage)


def test_complete_group_estimate_uses_ceil_for_multibyte_json() -> None:
    group = _tool_group("中文", results=[_result("中文", content={"detail": "赛事"})])
    messages = [UserMessage(content="older"), *group]

    selected = _select_compaction_range(
        messages,
        recent_history_tokens=1,
        bytes_per_token=3,
    )

    assert selected is not None
    assert selected.retained_messages == tuple(group)
    assert selected.retained_estimated_tokens == (selected.retained_bytes + 2) // 3


def test_validate_compaction_cut_accepts_plain_and_tool_group_boundaries() -> None:
    messages = [
        UserMessage(content="old"),
        *_tool_group("one"),
        UserMessage(content="new"),
    ]

    validate_compaction_cut(messages, cut_index=1)
    validate_compaction_cut(messages, cut_index=3)


def test_validate_compaction_cut_rejects_tool_call_and_return_boundaries() -> None:
    messages = [UserMessage(content="old"), *_tool_group("one", "two"), UserMessage(content="new")]

    for cut_index in (2, 3):
        with pytest.raises(HistoryCompactionRangeError) as error:
            validate_compaction_cut(messages, cut_index=cut_index)
        assert error.value.code == "invalid_compaction_boundary"


def test_rejected_assistant_and_all_non_execution_results_are_one_group() -> None:
    rejected = RejectedAssistantMessage(
        tool_calls=[
            RawToolCall(
                index=index,
                id=call_id,
                name="lookup",
                provider_name="lookup",
                raw_arguments="{}",
            )
            for index, call_id in enumerate(("same", "other"))
        ]
    )
    results = [
        ToolResultMessage(
            tool_call_id=call_id,
            content="本批所有调用均未执行，请重新提交完整调用。",
            status="error",
            error=ToolError(
                code="model_tool_batch_rejected",
                message="本批所有调用均未执行，请重新提交完整调用。",
            ),
            executed=False,
        )
        for call_id in ("same", "other")
    ]
    messages = [UserMessage(content="old"), rejected, *results, UserMessage(content="new")]

    validate_compaction_cut(messages, cut_index=4)
    for cut_index in (2, 3):
        with pytest.raises(HistoryCompactionRangeError) as error:
            validate_compaction_cut(messages, cut_index=cut_index)
        assert error.value.code == "invalid_compaction_boundary"


def test_rejected_tool_call_ids_may_be_reused_in_later_turn_groups() -> None:
    def rejected_group():
        assistant = RejectedAssistantMessage(
            tool_calls=[
                RawToolCall(
                    index=0,
                    id="reused",
                    name="lookup",
                    provider_name="lookup",
                    raw_arguments="{bad",
                )
            ]
        )
        result = ToolResultMessage(
            tool_call_id="reused",
            content="not executed",
            status="error",
            error=ToolError(
                code="model_tool_arguments_invalid",
                message="not executed",
            ),
            executed=False,
        )
        return [assistant, result]

    messages = [
        UserMessage(content="old"),
        *rejected_group(),
        *rejected_group(),
        UserMessage(content="new"),
    ]

    validate_compaction_cut(messages, cut_index=3)
    validate_compaction_cut(messages, cut_index=5)


@pytest.mark.parametrize("cut_index", [0, 5, 6, -1, True, False])
def test_validate_compaction_cut_rejects_invalid_indices(cut_index: object) -> None:
    messages = [UserMessage(content="old"), *_tool_group("one"), UserMessage(content="new")]

    with pytest.raises(HistoryCompactionRangeError) as error:
        validate_compaction_cut(messages, cut_index=cut_index)  # type: ignore[arg-type]

    assert error.value.code == "invalid_compaction_boundary"


def test_validate_compaction_cut_preserves_existing_invalid_history_error() -> None:
    messages = [AssistantMessage(tool_calls=[_call("orphan")]), UserMessage(content="new")]

    with pytest.raises(HistoryCompactionRangeError) as error:
        validate_compaction_cut(messages, cut_index=1)

    assert error.value.code == "invalid_history_structure"
