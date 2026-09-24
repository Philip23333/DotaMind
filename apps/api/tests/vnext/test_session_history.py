from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from app.vnext.agent.evidence_summary_lifecycle import (
    HistoryCompactionRangeError,
    build_history_compaction_request,
    build_turn_prefix_compaction_request,
    prepare_compaction,
    validate_compaction_cut,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import (
    RequestIdempotencyConflict,
    SessionCompactionError,
    SessionExecutionHistory,
)


def _tool_group(call_id: str, value: str | None = None) -> list:
    call = ToolCall(id=call_id, name="lookup", arguments={"id": call_id})
    result = ToolResultMessage(
        tool_call_id=call_id,
        content={"value": value or call_id},
    )
    return [AssistantMessage(tool_calls=[call]), result]


def _initialized_history(
    *,
    request_id: UUID | None = None,
    query: str = "collect",
) -> tuple[SessionExecutionHistory, UUID]:
    history = SessionExecutionHistory()
    request_id = request_id or uuid4()
    history.begin_request(request_id, query, initial_messages=[UserMessage(content="old")])
    history.record(
        request_id,
        ToolResultMessage(tool_call_id="read", content={"rows": [1, 2]}),
        kind="tool_result",
    )
    return history, request_id


def _state(history: SessionExecutionHistory) -> tuple[object, ...]:
    snapshot = history.context_snapshot()
    return (
        history.summary,
        history.revision,
        snapshot.messages,
        snapshot.current_request_id,
        snapshot.current_user_message,
        snapshot.current_user_index,
        history.records,
        history.compaction_records,
    )


def test_raw_records_are_defensive_and_effective_history_updates_are_bounded() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    tool_call = ToolCall(id="same", name="lookup", arguments={"key": "a"})
    assistant = AssistantMessage(tool_calls=[tool_call])
    result = ToolResultMessage(tool_call_id="same", content={"value": [1]})
    history.begin_request(request_id, "first", initial_messages=[])
    history.record(request_id, assistant, kind="assistant_tool_call")
    history.record_tool_results(request_id, [result])

    result.content["value"].append(2)  # type: ignore[index]
    history.set_effective([UserMessage(content="first"), FinalMessage(content="receipt")])

    assert history.records[1].message == assistant
    assert history.records[2].message == ToolResultMessage(
        tool_call_id="same", content={"value": [1]}
    )
    assert history.effective_messages() == [
        UserMessage(content="first"),
        FinalMessage(content="receipt"),
    ]


def test_bootstrap_records_current_request_and_user_position() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "same",
        initial_messages=[UserMessage(content="context"), UserMessage(content="same")],
    )

    snapshot = history.context_snapshot()

    assert snapshot.current_request_id == request_id
    assert snapshot.current_user_message == UserMessage(content="same")
    assert snapshot.current_user_index == 1


def test_new_request_updates_current_user_position_even_when_text_repeats() -> None:
    history = SessionExecutionHistory()
    first_id = uuid4()
    second_id = uuid4()
    history.begin_request(first_id, "same", initial_messages=[])
    history.begin_request(second_id, "same")

    snapshot = history.context_snapshot()
    assert history.effective_messages() == [
        UserMessage(content="same"),
        UserMessage(content="same"),
    ]
    assert snapshot.current_request_id == second_id
    assert snapshot.current_user_index == 1
    assert snapshot.current_user_message == UserMessage(content="same")


def test_same_current_request_retry_does_not_append_or_bump_version() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "same", initial_messages=[])
    before = _state(history)

    history.begin_request(request_id, "same")

    assert _state(history) == before


def test_old_request_cannot_be_reactivated_after_new_request_is_current() -> None:
    history = SessionExecutionHistory()
    old_id = uuid4()
    new_id = uuid4()
    history.begin_request(old_id, "old", initial_messages=[])
    history.begin_request(new_id, "new")
    before = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.begin_request(old_id, "old")

    assert error.value.code == "inactive_request"
    assert _state(history) == before


def test_request_id_query_conflict_does_not_change_history() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "first", initial_messages=[])
    before = _state(history)

    with pytest.raises(RequestIdempotencyConflict) as error:
        history.begin_request(request_id, "changed")

    assert error.value.code == "idempotency_conflict"
    assert _state(history) == before


def test_context_snapshot_is_defensive_including_current_user_message() -> None:
    history, _ = _initialized_history()
    snapshot = history.context_snapshot()

    snapshot.messages[0] = UserMessage(content="changed outside history")
    assert snapshot.current_user_message is not None
    snapshot.current_user_message.content = "changed current outside history"

    fresh = history.context_snapshot()
    assert fresh.messages[0] == UserMessage(content="old")
    assert fresh.current_user_message == UserMessage(content="collect")
    assert fresh.current_user_index == 1


def test_uninitialized_set_effective_keeps_storage_layer_behavior() -> None:
    history = SessionExecutionHistory()

    history.set_effective([FinalMessage(content="receipt")])

    assert history.effective_messages() == [FinalMessage(content="receipt")]
    assert history.revision == 1


def test_set_effective_allows_append_and_receipt_rewrite_at_current_position() -> None:
    history, _ = _initialized_history()
    history.set_effective(
        [
            UserMessage(content="old"),
            UserMessage(content="collect"),
            *_tool_group("read"),
        ]
    )
    history.set_effective(
        [
            UserMessage(content="old"),
            UserMessage(content="collect"),
            AssistantMessage(
                tool_calls=[ToolCall(id="read", name="lookup", arguments={"id": "read"})]
            ),
            ToolResultMessage(tool_call_id="read", content={"receipt": True}),
        ]
    )

    snapshot = history.context_snapshot()
    assert snapshot.current_user_index == 1
    assert snapshot.current_user_message == UserMessage(content="collect")


@pytest.mark.parametrize(
    "messages",
    [
        [UserMessage(content="old")],
        [UserMessage(content="collect"), UserMessage(content="old")],
        [UserMessage(content="old"), UserMessage(content="changed")],
    ],
)
def test_set_effective_rejects_delete_move_or_overwrite_of_current_user(
    messages: list,
) -> None:
    history, _ = _initialized_history()
    before = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.set_effective(messages)

    assert error.value.code == "invalid_effective_history"
    assert _state(history) == before


def test_compaction_state_starts_empty() -> None:
    history = SessionExecutionHistory()

    snapshot = history.context_snapshot()

    assert history.summary is None
    assert history.revision == 0
    assert history.compaction_records == ()
    assert snapshot.revision == 0
    assert snapshot.summary is None
    assert snapshot.messages == []
    assert snapshot.current_request_id is None
    assert snapshot.current_user_message is None
    assert snapshot.current_user_index is None


def test_compaction_commit_keeps_current_user_and_records_source_boundary() -> None:
    history, request_id = _initialized_history()
    history.set_effective(
        [
            UserMessage(content="old"),
            UserMessage(content="collect"),
            *_tool_group("first"),
            *_tool_group("second"),
        ]
    )
    records_before = history.records
    base_revision = history.revision

    record = history.commit_compaction(
        request_id=request_id,
        base_revision=base_revision,
        summary="The user is collecting match rows.",
        cut_index=4,
    )

    assert record.request_id == request_id
    assert record.base_revision == base_revision
    assert record.cut_index == 4
    assert record.source_message_count == 6
    assert record.current_user_index_before == 1
    assert record.previous_compaction_id is None
    assert record.created_at.tzinfo is not None
    assert history.summary == "The user is collecting match rows."
    assert history.effective_messages() == [
        UserMessage(content="collect"),
        *_tool_group("second"),
    ]
    assert history.context_snapshot().current_user_index == 0
    assert history.records == records_before
    assert history.compaction_records == (record,)


def test_compaction_keeps_current_user_when_it_is_already_in_retained_suffix() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "collect",
        initial_messages=[
            UserMessage(content="old"),
            *_tool_group("first"),
            UserMessage(content="collect"),
        ],
    )

    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="summary",
        cut_index=3,
    )

    assert history.effective_messages() == [UserMessage(content="collect")]
    assert history.context_snapshot().current_user_index == 0


def test_successive_compactions_keep_one_current_user_and_chain_records() -> None:
    history, request_id = _initialized_history()
    history.set_effective(
        [
            UserMessage(content="old"),
            UserMessage(content="collect"),
            *_tool_group("first"),
            *_tool_group("second"),
        ]
    )
    first = history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="first summary",
        cut_index=4,
    )
    history.set_effective([*history.effective_messages(), *_tool_group("third")])

    second = history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="second summary",
        cut_index=3,
    )

    assert history.effective_messages() == [UserMessage(content="collect"), *_tool_group("third")]
    assert history.context_snapshot().current_user_index == 0
    assert second.previous_compaction_id == first.compaction_id
    assert history.compaction_records == (first, second)
    assert sum(isinstance(message, UserMessage) for message in history.effective_messages()) == 1


def test_follow_up_makes_previous_question_ordinary_compressible_history() -> None:
    history, request_id = _initialized_history()
    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="facts retained for follow up",
        cut_index=1,
    )
    next_id = uuid4()
    history.begin_request(next_id, "new question")

    assert history.effective_messages() == [
        UserMessage(content="collect"),
        UserMessage(content="new question"),
    ]
    history.commit_compaction(
        request_id=next_id,
        base_revision=history.revision,
        summary="new summary",
        cut_index=1,
    )
    assert history.effective_messages() == [UserMessage(content="new question")]


def test_stale_compaction_snapshot_is_rejected_atomically() -> None:
    history, request_id = _initialized_history()
    snapshot = history.context_snapshot()
    history.set_effective([*history.effective_messages(), FinalMessage(content="newer")])
    state_before_attempt = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.commit_compaction(
            request_id=request_id,
            base_revision=snapshot.revision,
            summary="stale summary",
            cut_index=1,
        )

    assert error.value.code == "stale_context_revision"
    assert _state(history) == state_before_attempt


@pytest.mark.parametrize(
    ("setup", "summary", "code"),
    [
        ("uninitialized", "valid", "session_not_initialized"),
        ("unknown_request", "valid", "unknown_request"),
        ("initialized", "", "empty_summary"),
        ("initialized", "  \n\t", "empty_summary"),
    ],
)
def test_invalid_compaction_inputs_leave_state_unchanged(
    setup: str,
    summary: str,
    code: str,
) -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    if setup == "initialized":
        history, request_id = _initialized_history()
    elif setup == "unknown_request":
        history, _ = _initialized_history()
    state_before_attempt = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.commit_compaction(
            request_id=request_id,
            base_revision=history.revision,
            summary=summary,
            cut_index=1,
        )

    assert error.value.code == code
    assert _state(history) == state_before_attempt


def test_compacting_only_current_user_is_rejected_without_state_change() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "only", initial_messages=[])
    history.set_effective([UserMessage(content="only"), FinalMessage(content="recent")])
    before = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.commit_compaction(
            request_id=request_id,
            base_revision=history.revision,
            summary="summary",
            cut_index=1,
        )

    assert error.value.code == "empty_compaction_history"
    assert _state(history) == before


def test_second_commit_from_same_revision_is_rejected_without_new_record() -> None:
    history, request_id = _initialized_history()
    first = history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="first summary",
        cut_index=1,
    )
    state_before_attempt = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.commit_compaction(
            request_id=request_id,
            base_revision=first.base_revision,
            summary="second summary",
            cut_index=1,
        )

    assert error.value.code == "stale_context_revision"
    assert history.compaction_records == (first,)
    assert _state(history) == state_before_attempt


def test_versions_change_only_for_effective_state_operations() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "same", initial_messages=[UserMessage(content="old")])
    assert history.revision == 1
    history.begin_request(request_id, "same")
    assert history.revision == 1
    history.record(
        request_id,
        ToolResultMessage(tool_call_id="read", content={"value": 1}),
        kind="tool_result",
    )
    assert history.revision == 1
    history.set_effective(history.effective_messages())
    assert history.revision == 2
    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="summary",
        cut_index=1,
    )
    assert history.revision == 3


def test_compaction_does_not_copy_prefix_into_record_or_modify_request_queries() -> None:
    history, request_id = _initialized_history()
    history.set_effective([*history.effective_messages(), *_tool_group("read")])
    records_before = history.records

    record = history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="summary",
        cut_index=1,
    )

    assert history.records == records_before
    assert record.source_message_count == 4
    history.begin_request(request_id, "collect")
    with pytest.raises(RequestIdempotencyConflict):
        history.begin_request(request_id, "different")


def test_snapshot_compaction_preparation_splits_old_history_and_current_turn() -> None:
    history, request_id = _initialized_history()
    history.set_effective(
        [
            UserMessage(content="old"),
            UserMessage(content="collect"),
            *_tool_group("read"),
        ]
    )
    snapshot = history.context_snapshot()
    preparation = prepare_compaction(
        snapshot.messages,
        recent_history_tokens=1,
        bytes_per_token=2,
    )
    assert preparation is not None
    assert snapshot.current_user_message is not None
    assert snapshot.current_user_index == 1
    assert preparation.history_messages == (UserMessage(content="old"),)
    assert preparation.turn_prefix_messages == (UserMessage(content="collect"),)

    history_request = build_history_compaction_request(
        previous_summary=snapshot.summary,
        history_messages=preparation.history_messages,
        max_input_bytes=100_000,
        max_output_tokens=256,
    )
    prefix_request = build_turn_prefix_compaction_request(
        turn_prefix_messages=preparation.turn_prefix_messages,
        max_input_bytes=100_000,
        max_output_tokens=128,
    )
    history_payload = json.loads(history_request.messages[1].content)  # type: ignore[union-attr]
    prefix_payload = json.loads(prefix_request.messages[1].content)  # type: ignore[union-attr]
    history.commit_compaction(
        request_id=request_id,
        base_revision=snapshot.revision,
        summary="fixed summary",
        cut_index=preparation.cut_index,
    )

    assert [message["content"] for message in history_payload["history"]] == ["old"]
    assert [message["content"] for message in prefix_payload["turn_prefix"]] == ["collect"]
    assert history.effective_messages() == [UserMessage(content="collect"), *_tool_group("read")]


def test_validate_compaction_cut_accepts_message_group_boundaries() -> None:
    messages = [UserMessage(content="old"), *_tool_group("one"), UserMessage(content="new")]

    validate_compaction_cut(messages, cut_index=1)
    validate_compaction_cut(messages, cut_index=3)


@pytest.mark.parametrize("cut_index", [0, 4, 5, True, False, -1])
def test_validate_compaction_cut_rejects_invalid_indices(cut_index: object) -> None:
    messages = [UserMessage(content="old"), *_tool_group("one"), UserMessage(content="new")]

    with pytest.raises(HistoryCompactionRangeError) as error:
        validate_compaction_cut(messages, cut_index=cut_index)  # type: ignore[arg-type]

    assert error.value.code == "invalid_compaction_boundary"


def test_validate_compaction_cut_rejects_inside_tool_group_and_invalid_history() -> None:
    messages = [UserMessage(content="old"), *_tool_group("one"), UserMessage(content="new")]

    with pytest.raises(HistoryCompactionRangeError) as boundary_error:
        validate_compaction_cut(messages, cut_index=2)
    assert boundary_error.value.code == "invalid_compaction_boundary"

    with pytest.raises(HistoryCompactionRangeError) as structure_error:
        validate_compaction_cut(
            [AssistantMessage(tool_calls=[ToolCall(id="orphan", name="lookup")])],
            cut_index=1,
        )
    assert structure_error.value.code == "invalid_history_structure"
