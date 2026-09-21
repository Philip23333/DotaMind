from __future__ import annotations

from uuid import UUID, uuid4

import pytest

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


def test_raw_records_are_defensive_and_effective_history_is_replaceable() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    tool_call = ToolCall(id="same", name="lookup", arguments={"key": "a"})
    assistant = AssistantMessage(tool_calls=[tool_call])
    result = ToolResultMessage(tool_call_id="same", content={"value": [1]})
    history.begin_request(request_id, "first", initial_messages=[])
    history.record(request_id, assistant, kind="assistant_tool_call")
    history.record_tool_results(request_id, [result])

    result.content["value"].append(2)  # type: ignore[index]
    history.set_effective([FinalMessage(content="receipt")])

    assert history.records[1].message == assistant
    assert history.records[2].message == ToolResultMessage(
        tool_call_id="same", content={"value": [1]}
    )
    assert history.effective_messages() == [FinalMessage(content="receipt")]


def test_each_request_gets_one_user_record_without_rebuilding_projection() -> None:
    history = SessionExecutionHistory()
    first_id = uuid4()
    second_id = uuid4()
    history.begin_request(first_id, "first", initial_messages=[])
    history.set_effective([UserMessage(content="first"), FinalMessage(content="answer")])
    second_messages = history.begin_request(second_id, "second")

    assert second_messages == [
        UserMessage(content="first"),
        FinalMessage(content="answer"),
        UserMessage(content="second"),
    ]
    assert [record.kind for record in history.records] == ["user", "user"]


def test_request_id_query_conflict_does_not_change_history() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "first", initial_messages=[])
    records_before = history.records
    effective_before = history.effective_messages()

    with pytest.raises(RequestIdempotencyConflict) as error:
        history.begin_request(request_id, "changed")

    assert error.value.code == "idempotency_conflict"
    assert history.records == records_before
    assert history.effective_messages() == effective_before


def test_same_request_id_and_query_does_not_append_another_user_message() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "same", initial_messages=[])

    history.begin_request(request_id, "same")

    assert history.effective_messages() == [UserMessage(content="same")]
    assert [record.kind for record in history.records] == ["user"]


def test_new_request_id_with_same_query_appends_after_an_unfinished_request() -> None:
    history = SessionExecutionHistory()
    first_id = uuid4()
    second_id = uuid4()
    history.begin_request(first_id, "same", initial_messages=[])

    history.begin_request(second_id, "same")

    assert history.effective_messages() == [
        UserMessage(content="same"),
        UserMessage(content="same"),
    ]
    assert [record.request_id for record in history.records] == [first_id, second_id]


def test_bootstrap_query_is_attached_once_but_later_requests_are_appended() -> None:
    history = SessionExecutionHistory()
    first_id = uuid4()
    second_id = uuid4()
    initial_messages = [
        UserMessage(content="context"),
        UserMessage(content="same"),
    ]

    history.begin_request(first_id, "same", initial_messages=initial_messages)
    assert history.effective_messages() == initial_messages

    history.begin_request(second_id, "later")

    assert history.effective_messages() == [
        *initial_messages,
        UserMessage(content="later"),
    ]
    assert [record.request_id for record in history.records] == [first_id, second_id]


def _initialized_history() -> tuple[SessionExecutionHistory, UUID]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(request_id, "collect", initial_messages=[])
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
        history.records,
        history.compaction_records,
    )


def test_compaction_state_starts_empty() -> None:
    history = SessionExecutionHistory()

    snapshot = history.context_snapshot()

    assert history.summary is None
    assert history.revision == 0
    assert history.compaction_records == ()
    assert snapshot.revision == 0
    assert snapshot.summary is None
    assert snapshot.messages == []


def test_context_snapshot_isolated_from_history_and_later_projection_changes() -> None:
    history, _ = _initialized_history()
    snapshot = history.context_snapshot()

    snapshot.messages[0] = UserMessage(content="changed outside history")
    assert history.effective_messages()[0] == UserMessage(content="collect")
    history.set_effective([FinalMessage(content="new effective answer")])

    assert history.effective_messages() == [FinalMessage(content="new effective answer")]
    assert snapshot.messages[0] == UserMessage(content="changed outside history")


def test_compaction_commit_replaces_effective_state_without_touching_raw_records() -> None:
    history, request_id = _initialized_history()
    records_before = history.records
    base_revision = history.revision
    retained = [UserMessage(content="recent")]

    record = history.commit_compaction(
        request_id=request_id,
        base_revision=base_revision,
        summary="The user is collecting match rows.",
        retained_messages=retained,
    )

    assert record.request_id == request_id
    assert record.base_revision == base_revision
    assert record.previous_compaction_id is None
    assert record.created_at.tzinfo is not None
    assert history.summary == "The user is collecting match rows."
    assert history.effective_messages() == retained
    assert history.revision == base_revision + 1
    assert history.records == records_before
    assert history.compaction_records == (record,)


def test_stale_compaction_snapshot_is_rejected_atomically() -> None:
    history, request_id = _initialized_history()
    snapshot = history.context_snapshot()
    history.set_effective([UserMessage(content="newer")])
    state_before_attempt = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.commit_compaction(
            request_id=request_id,
            base_revision=snapshot.revision,
            summary="stale summary",
            retained_messages=[],
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
            retained_messages=[],
        )

    assert error.value.code == code
    assert _state(history) == state_before_attempt


def test_second_commit_from_same_revision_is_rejected_without_new_record() -> None:
    history, request_id = _initialized_history()
    base_revision = history.revision
    first = history.commit_compaction(
        request_id=request_id,
        base_revision=base_revision,
        summary="first summary",
        retained_messages=[UserMessage(content="kept")],
    )
    state_before_attempt = _state(history)

    with pytest.raises(SessionCompactionError) as error:
        history.commit_compaction(
            request_id=request_id,
            base_revision=base_revision,
            summary="second summary",
            retained_messages=[],
        )

    assert error.value.code == "stale_context_revision"
    assert history.compaction_records == (first,)
    assert _state(history) == state_before_attempt


def test_successive_commits_chain_records_and_never_inject_summary_message() -> None:
    history, first_request_id = _initialized_history()
    first = history.commit_compaction(
        request_id=first_request_id,
        base_revision=history.revision,
        summary="first summary",
        retained_messages=[UserMessage(content="recent one")],
    )
    second_request_id = uuid4()
    history.begin_request(second_request_id, "follow up")
    second = history.commit_compaction(
        request_id=second_request_id,
        base_revision=history.revision,
        summary="second summary",
        retained_messages=[UserMessage(content="recent two")],
    )

    assert history.summary == "second summary"
    assert history.compaction_records == (first, second)
    assert second.previous_compaction_id == first.compaction_id
    assert history.effective_messages() == [UserMessage(content="recent two")]
    assert all(message.role != "system" for message in history.effective_messages())


def test_follow_up_keeps_summary_while_adding_new_user_message() -> None:
    history, request_id = _initialized_history()
    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="facts retained for follow up",
        retained_messages=[UserMessage(content="recent")],
    )

    history.begin_request(uuid4(), "new question")

    assert history.summary == "facts retained for follow up"
    assert history.effective_messages() == [
        UserMessage(content="recent"),
        UserMessage(content="new question"),
    ]


def test_versions_change_only_for_effective_state_operations() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    assert history.revision == 0

    history.begin_request(request_id, "same", initial_messages=[])
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
        retained_messages=[],
    )
    assert history.revision == 3


def test_compaction_copies_retained_messages_and_does_not_modify_request_queries() -> None:
    history, request_id = _initialized_history()
    retained = [UserMessage(content="kept")]
    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="summary",
        retained_messages=retained,
    )
    retained[0].content = "changed by caller"

    assert history.effective_messages() == [UserMessage(content="kept")]
    history.begin_request(request_id, "collect")
    with pytest.raises(RequestIdempotencyConflict):
        history.begin_request(request_id, "different")
