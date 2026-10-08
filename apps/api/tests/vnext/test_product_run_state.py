from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.vnext.product.run_state import (
    CommentaryActivity,
    ProductRunStateProjector,
    StageActivity,
    ToolActivity,
)


def _projector() -> ProductRunStateProjector:
    return ProductRunStateProjector(
        request_id=uuid4(),
        assistant_message_id="assistant-message-1",
    )


def _begin_answer(
    projector: ProductRunStateProjector,
    *,
    attempt_id: str = "attempt-1",
    kind: str = "primary",
) -> None:
    projector.enter_stage("answer")
    projector.start_answer_attempt(attempt_id, kind)  # type: ignore[arg-type]


def test_initial_state_has_stable_identity_and_execution_activity() -> None:
    request_id = uuid4()
    projector = ProductRunStateProjector(request_id, "assistant-1")

    state = projector.snapshot()

    assert state.request_id == request_id
    assert state.assistant_message_id == "assistant-1"
    assert state.status == "running"
    assert state.stage == "execution"
    assert state.activity == [StageActivity(id="stage:execution", stage="execution")]
    assert state.omitted_activity_count == 0
    assert state.execution_timing is None
    assert state.answer.model_dump() == {
        "attempt_id": None,
        "kind": None,
        "text": "",
        "status": "pending",
    }
    assert state.persistence == "pending"
    assert state.error is None


@pytest.mark.parametrize(
    ("attempt_id", "kind"),
    [(None, None), ("answer-attempt", "degraded")],
)
def test_restore_completed_server_answer_without_synthetic_activity(
    attempt_id: str | None,
    kind: str | None,
) -> None:
    request_id = uuid4()

    projector = ProductRunStateProjector.from_completed_answer(
        request_id,
        f"assistant:{request_id}",
        "stored answer",
        attempt_id=attempt_id,
        kind=kind,  # type: ignore[arg-type]
    )

    state = projector.snapshot()
    assert state.request_id == request_id
    assert state.assistant_message_id == f"assistant:{request_id}"
    assert state.status == "completed"
    assert state.stage == "answer"
    assert state.activity == []
    assert state.omitted_activity_count == 0
    assert state.answer.attempt_id == attempt_id
    assert state.answer.kind == kind
    assert state.answer.text == "stored answer"
    assert state.answer.status == "ready"
    assert state.persistence == "pending"
    assert state.execution_timing is None


def test_restore_completed_answer_rejects_partial_attempt_identity() -> None:
    with pytest.raises(ValueError, match="both be present"):
        ProductRunStateProjector.from_completed_answer(
            uuid4(),
            "assistant:request",
            "stored answer",
            attempt_id="attempt-1",
        )


def test_commentary_is_ordered_bounded_and_included_in_activity_eviction() -> None:
    projector = _projector()
    source = "a" * 1_999 + "🐉" + "tail"
    projector.add_commentary(1, source)
    projector.tool_started("call-1", "game.detail")

    activity = projector.snapshot().activity
    commentary = activity[1]
    assert isinstance(commentary, CommentaryActivity)
    assert commentary.id == "commentary:1"
    assert commentary.text == source[:2_000]
    assert len(commentary.text) == 2_000
    assert commentary.text.endswith("🐉")
    assert commentary.truncated is True
    assert activity[2].id == "call-1"  # type: ignore[union-attr]

    for index in range(99):
        projector.tool_started(f"extra-{index}", "tool")
    state = projector.snapshot()
    assert len(state.activity) == ProductRunStateProjector.MAX_ACTIVITY_ITEMS
    assert state.omitted_activity_count == 2
    assert all(not isinstance(item, CommentaryActivity) for item in state.activity)


def test_blank_and_duplicate_commentary_are_ignored() -> None:
    projector = _projector()
    projector.add_commentary(1, " \n ")
    projector.add_commentary(1, "first")
    projector.add_commentary(1, "duplicate")

    assert [
        item.text for item in projector.snapshot().activity
        if isinstance(item, CommentaryActivity)
    ] == ["first"]


def test_execution_timing_uses_runtime_boundaries_and_freezes_after_answer_start() -> None:
    projector = _projector()
    started_at = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)
    answer_started_at = started_at + timedelta(seconds=7, milliseconds=250)
    projector.start_execution(started_at)
    started_timing = projector.snapshot().execution_timing
    assert started_timing is not None
    assert started_timing.finished_at is None
    assert started_timing.duration_seconds is None

    projector.enter_stage("answer", timestamp=answer_started_at)
    frozen_timing = projector.snapshot().execution_timing
    assert frozen_timing is not None
    assert frozen_timing.started_at == started_at
    assert frozen_timing.finished_at == answer_started_at
    assert frozen_timing.duration_seconds == 7.25

    projector.start_answer_attempt("primary", "primary")
    projector.start_answer_attempt("degraded", "degraded")
    projector.complete_answer("degraded", "answer")
    assert projector.snapshot().execution_timing == frozen_timing


@pytest.mark.parametrize("terminal", ["cancel", "fail"])
def test_execution_timing_ends_at_early_cancel_or_failure(terminal: str) -> None:
    projector = _projector()
    started_at = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)
    stopped_at = started_at + timedelta(seconds=2)
    projector.start_execution(started_at)
    if terminal == "cancel":
        projector.cancel(timestamp=stopped_at)
    else:
        projector.fail_execution("runtime_error", "safe", timestamp=stopped_at)

    timing = projector.snapshot().execution_timing
    assert timing is not None
    assert timing.finished_at == stopped_at
    assert timing.duration_seconds == 2


def test_execution_timing_is_not_invented_without_agent_started() -> None:
    projector = _projector()
    projector.enter_stage("answer")
    projector.start_answer_attempt("attempt-1", "primary")
    projector.complete_answer("attempt-1", "answer")

    assert projector.snapshot().execution_timing is None


def test_normal_lifecycle_reconciles_final_text_and_saves_separately() -> None:
    projector = _projector()
    _begin_answer(projector)

    projector.append_answer_text("attempt-1", "abc")
    projector.complete_answer("attempt-1", "abcd")
    projector.start_persistence()
    state_while_saving = projector.snapshot()
    projector.persistence_succeeded()

    assert state_while_saving.status == "completed"
    assert state_while_saving.answer.text == "abcd"
    assert state_while_saving.answer.status == "ready"
    assert state_while_saving.persistence == "saving"
    state = projector.snapshot()
    assert state.status == "completed"
    assert state.answer.text == "abcd"
    assert state.answer.status == "ready"
    assert state.persistence == "saved"


def test_degraded_attempt_replaces_primary_and_ignores_stale_primary_events() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.append_answer_text("primary-1", "partial primary")

    projector.start_answer_attempt("degraded-1", "degraded")
    state_after_replacement = projector.snapshot()
    projector.append_answer_text("primary-1", " stale")
    projector.complete_answer("primary-1", "stale final")
    projector.append_answer_text("degraded-1", "replacement")

    assert state_after_replacement.answer.text == ""
    assert state_after_replacement.answer.kind == "degraded"
    assert projector.snapshot().answer.text == "replacement"
    assert projector.snapshot().status == "running"


def test_deterministic_fallback_completes_without_concatenating_old_text() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.append_answer_text("primary-1", "discarded")
    projector.start_answer_attempt("degraded-1", "degraded")
    projector.append_answer_text("degraded-1", "also discarded")

    projector.start_answer_attempt("deterministic-1", "deterministic")
    projector.complete_answer("deterministic-1", "stable fallback")

    state = projector.snapshot()
    assert state.answer.text == "stable fallback"
    assert state.answer.kind == "deterministic"
    assert state.answer.status == "ready"
    assert state.status == "completed"


def test_duplicate_attempt_start_does_not_reset_text_but_kind_change_is_rejected() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.append_answer_text("attempt-1", "already visible")

    projector.start_answer_attempt("attempt-1", "primary")

    assert projector.snapshot().answer.text == "already visible"
    with pytest.raises(ValueError, match="cannot change answer kind"):
        projector.start_answer_attempt("attempt-1", "degraded")


def test_completion_replaces_streamed_text_instead_of_appending() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.append_answer_text("attempt-1", "abc")

    projector.complete_answer("attempt-1", "abcd")

    assert projector.snapshot().answer.text == "abcd"


def test_cancel_interrupts_partial_answer_and_ignores_late_updates() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.append_answer_text("attempt-1", "partial")

    projector.cancel()
    cancelled = projector.snapshot()
    projector.append_answer_text("attempt-1", " late")
    projector.complete_answer("attempt-1", "late complete")

    state = projector.snapshot()
    assert state.status == "cancelled"
    assert state.answer.status == "interrupted"
    assert state.answer.text == "partial"
    assert state.persistence == "pending"
    assert state == cancelled
    with pytest.raises(ValueError, match="completed, ready answer"):
        projector.start_persistence()


def test_cancel_without_text_keeps_answer_pending() -> None:
    projector = _projector()

    projector.cancel()

    state = projector.snapshot()
    assert state.status == "cancelled"
    assert state.answer.status == "pending"
    assert state.answer.text == ""


def test_cancel_after_completion_does_not_change_completed_state() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.complete_answer("attempt-1", "ready answer")
    completed = projector.snapshot()

    projector.cancel()

    assert projector.snapshot() == completed


def test_execution_failure_keeps_partial_text_interrupted_and_is_structured() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.append_answer_text("attempt-1", "partial")

    projector.fail_execution("runtime_error", "A safe user-facing message")

    state = projector.snapshot()
    assert state.status == "failed"
    assert state.answer.text == "partial"
    assert state.answer.status == "interrupted"
    assert state.persistence == "pending"
    assert state.error is not None
    assert state.error.model_dump() == {
        "scope": "execution",
        "code": "runtime_error",
        "message": "A safe user-facing message",
    }


def test_persistence_failure_preserves_answer_and_can_retry_without_regenerating() -> None:
    projector = _projector()
    _begin_answer(projector)
    projector.complete_answer("attempt-1", "canonical answer")
    projector.start_persistence()
    projector.persistence_failed("store_unavailable", "Could not save the answer")

    failed = projector.snapshot()
    assert failed.status == "completed"
    assert failed.answer.status == "ready"
    assert failed.answer.text == "canonical answer"
    assert failed.persistence == "failed"
    assert failed.error is not None
    assert failed.error.scope == "persistence"

    projector.start_persistence()
    retrying = projector.snapshot()
    assert retrying.persistence == "saving"
    assert retrying.error is None
    assert retrying.answer.text == "canonical answer"
    projector.persistence_succeeded()
    assert projector.snapshot().persistence == "saved"


def test_persistence_transitions_are_idempotent_only_where_specified() -> None:
    projector = _projector()
    with pytest.raises(ValueError, match="completed, ready answer"):
        projector.start_persistence()
    _begin_answer(projector)
    projector.complete_answer("attempt-1", "answer")

    projector.start_persistence()
    projector.start_persistence()
    projector.persistence_succeeded()
    projector.persistence_succeeded()
    with pytest.raises(ValueError, match="saving state"):
        projector.persistence_failed("store_error", "save failed")

    assert projector.snapshot().persistence == "saved"


def test_tool_failure_does_not_fail_run() -> None:
    projector = _projector()
    projector.tool_started("call-1", "esports.match.search")

    projector.tool_finished(
        "call-1",
        duration_seconds=0.25,
        error_code="provider_unavailable",
    )

    state = projector.snapshot()
    tool = state.activity[-1]
    assert isinstance(tool, ToolActivity)
    assert tool.status == "failed"
    assert tool.duration_seconds == 0.25
    assert tool.error_code == "provider_unavailable"
    assert state.status == "running"
    assert state.error is None


def test_tool_completion_updates_in_place_and_preserves_start_order() -> None:
    projector = _projector()
    projector.tool_started("call-a", "first.tool")
    projector.tool_started("call-b", "second.tool")

    projector.tool_finished("call-b", duration_seconds=0.2)
    projector.tool_finished("call-a", duration_seconds=0.1)

    tools = [item for item in projector.snapshot().activity if isinstance(item, ToolActivity)]
    assert [item.id for item in tools] == ["call-a", "call-b"]
    assert [item.status for item in tools] == ["completed", "completed"]


def test_duplicate_tool_start_is_ignored_and_tool_events_are_execution_only() -> None:
    projector = _projector()
    projector.tool_started("call-1", "first.tool")
    projector.tool_started("call-1", "different.tool")
    assert len(projector.snapshot().activity) == 2
    assert projector.snapshot().activity[-1].tool_name == "first.tool"  # type: ignore[union-attr]

    projector.enter_stage("answer")
    projector.tool_started("call-2", "late.tool")
    assert all(
        not isinstance(item, ToolActivity) or item.id != "call-2"
        for item in projector.snapshot().activity
    )


def test_tool_completion_for_unknown_or_evicted_call_is_ignored() -> None:
    projector = _projector()
    projector.tool_started("call-0", "tool")
    for index in range(1, 101):
        projector.tool_started(f"call-{index}", "tool")

    before = projector.snapshot()
    assert len(before.activity) == 100
    assert before.omitted_activity_count == 2
    assert all(
        not isinstance(item, ToolActivity) or item.id != "call-0"
        for item in before.activity
    )

    projector.tool_finished("call-0", duration_seconds=0.5)
    projector.tool_finished("missing", duration_seconds=0.5)

    after = projector.snapshot()
    assert len(after.activity) == 100
    assert after.omitted_activity_count == 2
    assert [item.id for item in after.activity if isinstance(item, ToolActivity)] == [
        f"call-{index}" for index in range(1, 101)
    ]


def test_negative_tool_duration_is_rejected() -> None:
    projector = _projector()
    projector.tool_started("call-1", "tool")

    with pytest.raises(ValueError, match="non-negative"):
        projector.tool_finished("call-1", duration_seconds=-0.1)


def test_snapshot_is_deeply_isolated() -> None:
    projector = _projector()
    projector.tool_started("call-1", "tool")
    snapshot = projector.snapshot()
    snapshot.answer.text = "outside mutation"
    snapshot.activity[0].id = "mutated stage"  # type: ignore[union-attr]
    snapshot.activity[1].tool_name = "mutated tool"  # type: ignore[union-attr]

    state = projector.snapshot()
    assert state.answer.text == ""
    assert state.activity[0].id == "stage:execution"  # type: ignore[union-attr]
    assert isinstance(state.activity[1], ToolActivity)
    assert state.activity[1].tool_name == "tool"


def test_two_projectors_do_not_share_state() -> None:
    first = _projector()
    second = _projector()
    first.enter_stage("answer")
    second.tool_started("only-second", "tool")
    first.start_answer_attempt("first-answer", "primary")
    first.append_answer_text("first-answer", "first")

    assert first.snapshot().stage == "answer"
    assert first.snapshot().answer.text == "first"
    assert second.snapshot().stage == "execution"
    assert second.snapshot().answer.text == ""
    assert [item.id for item in second.snapshot().activity] == [
        "stage:execution",
        "only-second",
    ]


def test_invalid_stage_and_attempt_transitions_are_rejected() -> None:
    projector = _projector()
    with pytest.raises(ValueError, match="answer stage"):
        projector.start_answer_attempt("attempt-1", "primary")

    projector.enter_stage("answer")
    with pytest.raises(ValueError, match="return to the execution"):
        projector.enter_stage("execution")
