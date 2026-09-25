from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.application.chat_repository import (
    ChatDialogueTurnResult,
    ChatIdempotencyConflictError,
)
from app.vnext.agent.events import (
    AgentCompleted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
    TextDelta,
)
from app.vnext.llm.protocol import FinalMessage
from app.vnext.product.chat import (
    PreparedVNextChatTurn,
    ProductChatCompleted,
    ProductChatError,
    ProductChatState,
    VNextChatService,
)
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.product.presentation import DotaVisualEntityEnricher


class _Repository:
    def __init__(self) -> None:
        self.turns: dict[UUID, tuple[str, ChatDialogueTurnResult]] = {}
        self.appended: list[dict[str, object]] = []
        self.failures = 0
        self.append_started = asyncio.Event()
        self.release_append: asyncio.Event | None = None
        self.block_after_commit = False
        self.release_after_commit = asyncio.Event()
        self.append_finalized = asyncio.Event()
        self.active_appends = 0

    async def lookup_dialogue_request(
        self,
        _browser_id: str,
        _session_id: UUID,
        request_id: UUID,
        query: str,
    ) -> ChatDialogueTurnResult | None:
        stored = self.turns.get(request_id)
        if stored is None:
            return None
        stored_query, result = stored
        if stored_query != query:
            raise ChatIdempotencyConflictError()
        return result

    async def get_all_dialogue_turns(self, *_args):
        return [], 1

    async def append_dialogue_turn(self, **kwargs) -> ChatDialogueTurnResult:
        self.appended.append(kwargs)
        self.append_started.set()
        self.active_appends += 1
        try:
            if self.release_append is not None:
                await self.release_append.wait()
            if self.failures:
                self.failures -= 1
                raise RuntimeError("SECRET repository failure")
            request_id = kwargs["request_id"]
            query = str(kwargs["user_query"])
            existing = self.turns.get(request_id)
            if existing is not None:
                if existing[0] != query:
                    raise ChatIdempotencyConflictError()
                return existing[1]
            result = ChatDialogueTurnResult(
                status="executed",
                turn_index=len(self.turns) + 1,
                assistant_message=str(kwargs["assistant_message"]),
                catalog_visual_entities=list(kwargs["catalog_visual_entities"]),
            )
            self.turns[request_id] = (query, result)
            if self.block_after_commit:
                await self.release_after_commit.wait()
            return result
        finally:
            self.active_appends -= 1
            self.append_finalized.set()


class _Runtime:
    def __init__(self, events) -> None:
        self.events = events
        self.run_count = 0
        self.closed = asyncio.Event()

    async def run_stream(self, _messages, *, trace_collector=None):
        self.run_count += 1
        try:
            for event in self.events:
                if isinstance(event, BaseException):
                    raise event
                yield event
        finally:
            self.closed.set()


class _TraceStore:
    def __init__(self) -> None:
        self.saved = []

    async def put(self, trace) -> None:
        self.saved.append(trace)


def _events(
    final: str,
    *,
    attempt_id: str = "attempt-1",
    kind: str = "primary",
    deltas: tuple[str, ...] = (),
):
    return [
        AnswerStageStarted(),
        AnswerAttemptStarted(attempt_id=attempt_id, answer_kind=kind),
        *(TextDelta(text=delta, attempt_id=attempt_id) for delta in deltas),
        AgentCompleted(
            duration=0.1,
            final=FinalMessage(content=final),
            attempt_id=attempt_id,
        ),
    ]


def _service(
    repository,
    runtime,
    *,
    trace_store=None,
    test_recording_enabled=False,
    persistence_timeout_seconds=15.0,
    visual_entity_enricher=None,
):
    return VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
        ConversationContextBuilder(),
        visual_entity_enricher or DotaVisualEntityEnricher(),
        trace_store=trace_store,
        test_recording_enabled=test_recording_enabled,
        persistence_timeout_seconds=persistence_timeout_seconds,
    )


async def _prepared(
    service: VNextChatService,
    *,
    request_id: UUID | None = None,
    session_id: UUID | None = None,
    query: str = "question",
) -> PreparedVNextChatTurn:
    return await service.prepare_turn(
        browser_id="browser",
        session_id=session_id or uuid4(),
        request_id=request_id or uuid4(),
        query=query,
    )


def test_service_emits_ready_saving_and_saved_in_order() -> None:
    async def run():
        repository = _Repository()
        runtime = _Runtime(_events("canonical", deltas=("live",)))
        service = _service(repository, runtime)
        prepared = await _prepared(service)
        return [update async for update in service.stream_turn_states(prepared)]

    updates = asyncio.run(run())
    states = [update.state for update in updates]

    assert [(state.status, state.answer.status, state.persistence) for state in states] == [
        ("running", "pending", "pending"),
        ("running", "pending", "pending"),
        ("running", "pending", "pending"),
        ("running", "streaming", "pending"),
        ("completed", "ready", "pending"),
        ("completed", "ready", "saving"),
        ("completed", "ready", "saved"),
    ]
    assert states[-1].answer.text == "canonical"
    assert states[-1].assistant_message_id == f"assistant:{states[-1].request_id}"
    assert updates[-1].turn_index == 1


def test_service_publishes_text_before_the_runtime_produces_a_final() -> None:
    async def run():
        release_final = asyncio.Event()
        final_produced = asyncio.Event()

        class GatedRuntime:
            async def run_stream(self, _messages, *, trace_collector=None):
                yield AnswerStageStarted()
                yield AnswerAttemptStarted(attempt_id="attempt-live", answer_kind="primary")
                yield TextDelta(text="live fragment", attempt_id="attempt-live")
                await release_final.wait()
                final_produced.set()
                yield AgentCompleted(
                    duration=0.1,
                    final=FinalMessage(content="live fragment complete"),
                    attempt_id="attempt-live",
                )

        service = _service(_Repository(), GatedRuntime())
        prepared = await _prepared(service)
        stream = service.stream_turn_states(prepared)
        seen = []
        while True:
            update = await anext(stream)
            seen.append(update)
            if update.state.answer.status == "streaming":
                assert update.state.answer.text == "live fragment"
                assert not final_produced.is_set()
                break
        release_final.set()
        seen.extend([update async for update in stream])
        return seen

    updates = asyncio.run(run())
    assert updates[-1].state.persistence == "saved"


def test_fallback_attempts_replace_text_without_changing_message_identity() -> None:
    async def run():
        events = [
            AnswerStageStarted(),
            AnswerAttemptStarted(attempt_id="primary", answer_kind="primary"),
            TextDelta(text="partial primary", attempt_id="primary"),
            AnswerAttemptFailed(attempt_id="primary", error_code="answer_failed"),
            AnswerAttemptStarted(attempt_id="degraded", answer_kind="degraded"),
            TextDelta(text="degraded answer", attempt_id="degraded"),
            AnswerAttemptStarted(attempt_id="deterministic", answer_kind="deterministic"),
            AgentCompleted(
                duration=0.1,
                final=FinalMessage(content="deterministic answer"),
                attempt_id="deterministic",
            ),
        ]
        service = _service(_Repository(), _Runtime(events))
        prepared = await _prepared(service)
        return [update async for update in service.stream_turn_states(prepared)]

    updates = asyncio.run(run())
    answers = [update.state.answer for update in updates]
    assert [(answer.kind, answer.text) for answer in answers if answer.attempt_id] == [
        ("primary", ""),
        ("primary", "partial primary"),
        ("degraded", ""),
        ("degraded", "degraded answer"),
        ("deterministic", ""),
        ("deterministic", "deterministic answer"),
        ("deterministic", "deterministic answer"),
        ("deterministic", "deterministic answer"),
    ]
    assert {update.state.assistant_message_id for update in updates} == {
        f"assistant:{updates[0].state.request_id}"
    }
    assert updates[-1].state.answer.text == "deterministic answer"


def test_save_failure_preserves_ready_answer_and_same_request_retries_without_runtime() -> None:
    async def run():
        repository = _Repository()
        repository.failures = 1
        runtime = _Runtime(_events("ready answer", deltas=("ready",)))
        service = _service(repository, runtime)
        prepared = await _prepared(service)
        first = [update async for update in service.stream_turn_states(prepared)]
        records_before_retry = service._sessions[prepared.session_id].history.records
        retry = await service.prepare_turn(
            browser_id=prepared.browser_id,
            session_id=prepared.session_id,
            request_id=prepared.request_id,
            query=prepared.query,
        )
        second = [update async for update in service.stream_turn_states(retry)]
        return first, second, runtime, repository, records_before_retry, service, prepared

    first, second, runtime, repository, records, service, prepared = asyncio.run(run())
    failed = first[-1].state
    saved = second[-1].state
    assert (failed.status, failed.answer.status, failed.persistence) == (
        "completed",
        "ready",
        "failed",
    )
    assert failed.answer.text == "ready answer"
    assert failed.error is not None
    assert failed.error.scope == "persistence"
    assert failed.error.code == "chat_store_error"
    assert failed.error.message == "回答已生成，但未能确认保存结果，请重试保存。"
    assert (saved.status, saved.answer.status, saved.persistence) == (
        "completed",
        "ready",
        "saved",
    )
    assert runtime.run_count == 1
    assert len(repository.appended) == 2
    assert len(records) == len(service._sessions[prepared.session_id].history.records)
    assert sum(
        record.kind == "delivery_answer"
        for record in service._sessions[prepared.session_id].history.records
    ) == 1
    assert first[0].state.assistant_message_id == second[0].state.assistant_message_id
    assert first[-1].state.answer.attempt_id == second[-1].state.answer.attempt_id == "attempt-1"


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan"), True])
def test_persistence_timeout_must_be_finite_and_positive(timeout_seconds) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        _service(_Repository(), _Runtime([]), persistence_timeout_seconds=timeout_seconds)


def test_blocked_repository_times_out_and_preserves_completed_answer_without_leaking_task() -> None:
    async def run():
        repository = _Repository()
        repository.release_append = asyncio.Event()
        request_id = uuid4()
        runtime = _Runtime(_events("body survives timeout"))
        service = _service(
            repository,
            runtime,
            persistence_timeout_seconds=0.03,
        )
        prepared = await _prepared(service, request_id=request_id)
        updates = [update async for update in service.stream_turn_states(prepared)]
        save_tasks = [
            task
            for task in asyncio.all_tasks()
            if task.get_name() == f"vnext-chat-save-{request_id}"
        ]
        return updates, repository, save_tasks

    updates, repository, save_tasks = asyncio.run(run())
    state = updates[-1].state
    assert (state.status, state.answer.status, state.persistence) == (
        "completed",
        "ready",
        "failed",
    )
    assert state.answer.text == "body survives timeout"
    assert state.error is not None
    assert state.error.scope == "persistence"
    assert state.error.code == "chat_store_error"
    assert "未能确认保存结果" in state.error.message
    assert repository.append_finalized.is_set()
    assert repository.active_appends == 0
    assert save_tasks == []


def test_cancel_during_save_uses_remaining_budget_and_releases_session_for_next_request() -> None:
    async def run():
        repository = _Repository()
        repository.release_append = asyncio.Event()
        runtime = _Runtime(_events("answer"))
        service = _service(
            repository,
            runtime,
            persistence_timeout_seconds=0.15,
        )
        prepared = await _prepared(service, session_id=uuid4())

        async def consume():
            async for _update in service.stream_turn_states(prepared):
                pass

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(repository.append_started.wait(), timeout=1)
        await asyncio.sleep(0.09)
        cancel_at = asyncio.get_running_loop().time()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(consumer, timeout=0.12)
        cancel_wait = asyncio.get_running_loop().time() - cancel_at
        assert repository.append_finalized.is_set()
        assert repository.active_appends == 0

        repository.release_append.set()
        next_prepared = await _prepared(
            service,
            session_id=prepared.session_id,
            query="next question",
        )
        next_updates = await asyncio.wait_for(
            _collect_states(service, next_prepared),
            timeout=0.2,
        )
        return cancel_wait, next_updates, repository

    cancel_wait, next_updates, repository = asyncio.run(run())
    assert cancel_wait < 0.12
    assert next_updates[-1].state.persistence == "saved"
    assert len(repository.appended) == 2
    assert repository.active_appends == 0


def test_timed_out_save_retries_cached_answer_without_reinvoking_runtime() -> None:
    async def run():
        repository = _Repository()
        repository.release_append = asyncio.Event()
        runtime = _Runtime(_events("cached answer"))
        service = _service(repository, runtime, persistence_timeout_seconds=0.03)
        prepared = await _prepared(service)
        first = await _collect_states(service, prepared)
        repository.release_append.set()
        retry = await service.prepare_turn(
            browser_id=prepared.browser_id,
            session_id=prepared.session_id,
            request_id=prepared.request_id,
            query=prepared.query,
        )
        second = await _collect_states(service, retry)
        return first, second, runtime, repository

    first, second, runtime, repository = asyncio.run(run())
    assert first[-1].state.persistence == "failed"
    assert second[-1].state.persistence == "saved"
    assert second[-1].state.answer.text == "cached answer"
    assert runtime.run_count == 1
    assert len(repository.appended) == 2


def test_retry_replays_repository_commit_that_timed_out_while_returning() -> None:
    async def run():
        repository = _Repository()
        repository.block_after_commit = True
        runtime = _Runtime(_events("committed answer"))
        service = _service(repository, runtime, persistence_timeout_seconds=0.03)
        prepared = await _prepared(service)
        first = await _collect_states(service, prepared)
        retry = await service.prepare_turn(
            browser_id=prepared.browser_id,
            session_id=prepared.session_id,
            request_id=prepared.request_id,
            query=prepared.query,
        )
        second = await _collect_states(service, retry)
        return first, second, runtime, repository

    first, second, runtime, repository = asyncio.run(run())
    assert first[-1].state.persistence == "failed"
    assert second[-1].state.persistence == "saved"
    assert second[-1].state.answer.text == "committed answer"
    assert runtime.run_count == 1
    assert len(repository.appended) == 1
    assert len(repository.turns) == 1


def test_visual_enrichment_failure_does_not_block_canonical_answer_persistence() -> None:
    class FailingVisualEntityEnricher:
        def match(self, _content):
            raise RuntimeError("visual enrichment failed")

    async def run():
        repository = _Repository()
        runtime = _Runtime(_events("canonical text unchanged"))
        service = _service(
            repository,
            runtime,
            visual_entity_enricher=FailingVisualEntityEnricher(),
        )
        prepared = await _prepared(service)
        updates = await _collect_states(service, prepared)
        return updates, runtime, repository

    updates, runtime, repository = asyncio.run(run())
    assert (updates[-1].state.status, updates[-1].state.answer.status) == (
        "completed",
        "ready",
    )
    assert updates[-1].state.persistence == "saved"
    assert updates[-1].state.answer.text == "canonical text unchanged"
    assert len(repository.appended) == 1
    assert repository.appended[0]["assistant_message"] == "canonical text unchanged"
    assert repository.appended[0]["catalog_visual_entities"] == []
    assert runtime.run_count == 1


def test_repository_failure_remains_visible_when_visual_enrichment_also_fails() -> None:
    class FailingVisualEntityEnricher:
        def match(self, _content):
            raise RuntimeError("visual enrichment failed")

    async def run():
        repository = _Repository()
        repository.failures = 1
        runtime = _Runtime(_events("answer survives repository failure"))
        service = _service(
            repository,
            runtime,
            visual_entity_enricher=FailingVisualEntityEnricher(),
        )
        prepared = await _prepared(service)
        updates = await _collect_states(service, prepared)
        return updates, repository

    updates, repository = asyncio.run(run())
    state = updates[-1].state
    assert state.status == "completed"
    assert state.answer.status == "ready"
    assert state.persistence == "failed"
    assert state.answer.text == "answer survives repository failure"
    assert state.error is not None
    assert state.error.scope == "persistence"
    assert state.error.code == "chat_store_error"
    assert len(repository.appended) == 1
    assert repository.appended[0]["assistant_message"] == "answer survives repository failure"
    assert repository.appended[0]["catalog_visual_entities"] == []


async def _collect_states(service, prepared):
    return [update async for update in service.stream_turn_states(prepared)]


def test_repository_replay_has_no_runtime_activity_attempt_or_second_append() -> None:
    async def run():
        repository = _Repository()
        request_id = uuid4()
        repository.turns[request_id] = (
            "question",
            ChatDialogueTurnResult(
                status="replay",
                turn_index=7,
                assistant_message="stored answer",
            ),
        )
        runtime = _Runtime([])
        service = _service(repository, runtime)
        prepared = await _prepared(service, request_id=request_id)
        updates = [update async for update in service.stream_turn_states(prepared)]
        return updates, repository, runtime

    updates, repository, runtime = asyncio.run(run())
    assert len(updates) == 1
    replay = updates[0]
    assert replay.state.status == "completed"
    assert replay.state.answer.status == "ready"
    assert replay.state.persistence == "saved"
    assert replay.state.answer.text == "stored answer"
    assert replay.state.answer.attempt_id is None
    assert replay.state.answer.kind is None
    assert replay.state.activity == []
    assert replay.turn_index == 7
    assert replay.state.assistant_message_id == f"assistant:{replay.state.request_id}"
    assert runtime.run_count == 0
    assert repository.appended == []


def test_changed_query_for_cached_request_returns_conflict_without_leaking_answer() -> None:
    async def run():
        repository = _Repository()
        repository.failures = 1
        runtime = _Runtime(_events("secret prior answer"))
        service = _service(repository, runtime)
        first = await _prepared(service)
        first_stream = service.stream_turn_states(first)
        first_states = [update async for update in first_stream]
        assert first_states[-1].state.persistence == "failed"
        changed = await service.prepare_turn(
            browser_id=first.browser_id,
            session_id=first.session_id,
            request_id=first.request_id,
            query="different query",
        )
        second = [update async for update in service.stream_turn_states(changed)]
        return second, runtime, repository

    updates, runtime, repository = asyncio.run(run())
    state = updates[-1].state
    assert state.status == "failed"
    assert state.error is not None and state.error.code == "idempotency_conflict"
    assert state.answer.text == ""
    assert "secret prior answer" not in state.model_dump_json()
    assert runtime.run_count == 1
    assert len(repository.appended) == 1


def test_same_request_competitors_share_one_runtime_and_one_durable_turn() -> None:
    async def run():
        repository = _Repository()
        repository.release_append = asyncio.Event()
        runtime = _Runtime(_events("one result"))
        service = _service(repository, runtime)
        first = await _prepared(service)
        second = await service.prepare_turn(
            browser_id=first.browser_id,
            session_id=first.session_id,
            request_id=first.request_id,
            query=first.query,
        )

        async def collect(prepared):
            return [update async for update in service.stream_turn_states(prepared)]

        first_task = asyncio.create_task(collect(first))
        await asyncio.wait_for(repository.append_started.wait(), timeout=1)
        second_task = asyncio.create_task(collect(second))
        await asyncio.sleep(0)
        assert not second_task.done()
        repository.release_append.set()
        return await first_task, await second_task, runtime, repository

    first, second, runtime, repository = asyncio.run(run())
    assert first[-1].state.persistence == "saved"
    assert second[-1].state.persistence == "saved"
    assert runtime.run_count == 1
    assert len(repository.appended) == 1


def test_cancellation_before_final_closes_runtime_and_does_not_save_partial_text() -> None:
    async def run():
        started = asyncio.Event()

        class WaitingRuntime:
            def __init__(self):
                self.closed = asyncio.Event()

            async def run_stream(self, _messages, *, trace_collector=None):
                try:
                    yield AnswerStageStarted()
                    yield AnswerAttemptStarted(attempt_id="attempt-1", answer_kind="primary")
                    yield TextDelta(text="partial", attempt_id="attempt-1")
                    started.set()
                    await asyncio.Event().wait()
                finally:
                    self.closed.set()

        repository = _Repository()
        runtime = WaitingRuntime()
        service = _service(repository, runtime)
        prepared = await _prepared(service)

        async def consume():
            async for _update in service.stream_turn_states(prepared):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        return repository, runtime

    repository, runtime = asyncio.run(run())
    assert runtime.closed.is_set()
    assert repository.appended == []


def test_closing_after_ready_waits_for_the_owned_save_and_leaves_no_task() -> None:
    async def run():
        repository = _Repository()
        repository.release_append = asyncio.Event()
        service = _service(repository, _Runtime(_events("saved after close")))
        prepared = await _prepared(service)
        stream = service.stream_turn_states(prepared)
        while True:
            update = await anext(stream)
            if update.state.status == "completed" and update.state.persistence == "pending":
                break
        await asyncio.wait_for(repository.append_started.wait(), timeout=1)
        close_task = asyncio.create_task(stream.aclose())
        await asyncio.sleep(0)
        assert not close_task.done()
        repository.release_append.set()
        await asyncio.wait_for(close_task, timeout=1)
        outstanding = [
            task
            for task in asyncio.all_tasks()
            if task.get_name() == f"vnext-chat-save-{prepared.request_id}" and not task.done()
        ]
        return prepared, repository, outstanding

    prepared, repository, outstanding = asyncio.run(run())
    assert len(repository.turns) == 1
    assert repository.turns[prepared.request_id][1].assistant_message == "saved after close"
    assert outstanding == []


def test_cancellation_during_save_does_not_cancel_write_and_replay_confirms_it() -> None:
    async def run():
        repository = _Repository()
        repository.release_append = asyncio.Event()
        runtime = _Runtime(_events("durable answer"))
        service = _service(repository, runtime)
        prepared = await _prepared(service)

        async def consume():
            async for _update in service.stream_turn_states(prepared):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(repository.append_started.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        repository.release_append.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

        replay_prepared = await service.prepare_turn(
            browser_id=prepared.browser_id,
            session_id=prepared.session_id,
            request_id=prepared.request_id,
            query=prepared.query,
        )
        replay = [
            update async for update in service.stream_turn_states(replay_prepared)
        ]
        return replay, runtime, repository

    replay, runtime, repository = asyncio.run(run())
    assert replay[-1].state.persistence == "saved"
    assert replay[-1].state.answer.text == "durable answer"
    assert runtime.run_count == 1
    assert len(repository.appended) == 1


def test_runtime_errors_are_safe_and_incomplete_or_invalid_streams_settle() -> None:
    async def exercise(events):
        runtime = _Runtime(events)
        service = _service(_Repository(), runtime)
        prepared = await _prepared(service)
        return [update async for update in service.stream_turn_states(prepared)]

    incomplete = asyncio.run(
        exercise(
            [
                AnswerStageStarted(),
                AnswerAttemptStarted(attempt_id="attempt-1", answer_kind="primary"),
                TextDelta(text="partial", attempt_id="attempt-1"),
            ]
        )
    )[-1].state
    invalid = asyncio.run(
        exercise(
            [
                AnswerStageStarted(),
                AnswerAttemptStarted(attempt_id="attempt-1", answer_kind="primary"),
                TextDelta(text="missing identity"),
            ]
        )
    )[-1].state
    missing_final_identity = asyncio.run(
        exercise(
            [
                AnswerStageStarted(),
                AnswerAttemptStarted(attempt_id="attempt-1", answer_kind="primary"),
                AgentCompleted(duration=0.1, final=FinalMessage(content="unidentified")),
            ]
        )
    )[-1].state
    unknown = asyncio.run(
        exercise([AnswerStageStarted(), RuntimeError("SECRET provider text")])
    )[-1]

    async def fail_before_stream_creation():
        class UnstartableRuntime:
            def run_stream(self, _messages, **_kwargs):
                raise RuntimeError("SECRET startup failure")

        service = _service(_Repository(), UnstartableRuntime())
        prepared = await _prepared(service)
        return [update async for update in service.stream_turn_states(prepared)]

    startup_error = asyncio.run(fail_before_stream_creation())[-1]

    assert incomplete.error is not None
    assert incomplete.error.code == "agent_stream_incomplete"
    assert invalid.error is not None
    assert invalid.error.code == "agent_runtime_error"
    assert missing_final_identity.error is not None
    assert missing_final_identity.error.code == "agent_runtime_error"
    assert unknown.state.error is not None
    assert unknown.state.error.code == "agent_runtime_error"
    assert "SECRET" not in unknown.model_dump_json()
    assert startup_error.state.error is not None
    assert startup_error.state.error.code == "agent_runtime_error"
    assert "SECRET" not in startup_error.model_dump_json()


def test_legacy_stream_adapter_emits_terminal_only_and_uses_the_new_service_path() -> None:
    async def run():
        runtime = _Runtime(
            _events("replacement answer", deltas=("old partial",))
        )
        service = _service(_Repository(), runtime)
        prepared = await _prepared(service)
        events = [event async for event in service.stream_turn(prepared)]
        return events, runtime

    events, runtime = asyncio.run(run())
    assert len(events) == 1
    assert isinstance(events[0], ProductChatCompleted)
    assert events[0].content == "replacement answer"
    assert not any(isinstance(event, ProductChatState) for event in events)
    assert not any(isinstance(event, ProductChatError) for event in events)
    assert runtime.run_count == 1


def test_repository_exception_text_is_not_exposed_in_persistence_state() -> None:
    async def run():
        repository = _Repository()
        repository.failures = 1
        service = _service(repository, _Runtime(_events("canonical answer")))
        prepared = await _prepared(service)
        return [update async for update in service.stream_turn_states(prepared)]

    updates = asyncio.run(run())
    state = updates[-1].state
    assert state.error is not None
    assert state.error.code == "chat_store_error"
    assert "SECRET" not in state.model_dump_json()


def test_two_sessions_do_not_block_each_other_or_share_answer_state() -> None:
    async def run():
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        class BlockedRuntime:
            async def run_stream(self, _messages, *, trace_collector=None):
                yield AnswerStageStarted()
                yield AnswerAttemptStarted(attempt_id="first-attempt", answer_kind="primary")
                yield TextDelta(text="first live", attempt_id="first-attempt")
                first_started.set()
                await release_first.wait()
                yield AgentCompleted(
                    duration=0.1,
                    final=FinalMessage(content="first answer"),
                    attempt_id="first-attempt",
                )

        runtimes = [BlockedRuntime(), _Runtime(_events("second answer"))]

        def runtime_factory():
            return runtimes.pop(0)

        repository = _Repository()
        service = VNextChatService(
            repository,  # type: ignore[arg-type]
            _Runtime([]),  # type: ignore[arg-type]
            ConversationContextBuilder(),
            DotaVisualEntityEnricher(),
            runtime_factory=runtime_factory,  # type: ignore[arg-type]
        )
        first = await _prepared(service, session_id=uuid4(), query="first")
        second = await _prepared(service, session_id=uuid4(), query="second")

        async def collect(prepared):
            return [update async for update in service.stream_turn_states(prepared)]

        first_task = asyncio.create_task(collect(first))
        await asyncio.wait_for(first_started.wait(), timeout=1)
        second_updates = await asyncio.wait_for(collect(second), timeout=1)
        release_first.set()
        first_updates = await asyncio.wait_for(first_task, timeout=1)
        return first_updates, second_updates

    first, second = asyncio.run(run())
    assert first[-1].state.answer.text == "first answer"
    assert second[-1].state.answer.text == "second answer"
    assert first[-1].state.request_id != second[-1].state.request_id
    assert first[-1].state.assistant_message_id != second[-1].state.assistant_message_id
