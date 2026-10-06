from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.vnext_chat_routes import router as chat_router
from app.application.chat_repository import ChatDialogueTurnResult, ChatNotFoundError
from app.vnext.agent.events import (
    AgentCompleted,
    AgentFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import FinalMessage, ModelRequest, ModelResponse, UserMessage
from app.vnext.product.chat import VNextChatService
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.product.presentation import DotaVisualEntityEnricher
from app.vnext.product.trace_store import RunTrace, TraceNotFoundError
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class _Repository:
    def __init__(self) -> None:
        self.results: dict[UUID, ChatDialogueTurnResult] = {}
        self.owner_calls: list[tuple[str, UUID]] = []

    async def lookup_dialogue_request(self, _browser_id, _session_id, request_id, _query):
        return self.results.get(request_id)

    async def get_all_dialogue_turns(self, _browser_id, _session_id):
        return [], 1

    async def append_dialogue_turn(self, **kwargs):
        result = ChatDialogueTurnResult(
            status="executed",
            turn_index=len(self.results) + 1,
            assistant_message=kwargs["assistant_message"],
            catalog_visual_entities=kwargs.get("catalog_visual_entities", []),
        )
        self.results[kwargs["request_id"]] = result
        return result

    async def get_session(self, browser_id: str, session_id: UUID):
        self.owner_calls.append((browser_id, session_id))
        if browser_id == "wrong-browser":
            raise ChatNotFoundError()
        return object()


class _TraceStore:
    def __init__(self, *, put_delay: float = 0.0, block_put: bool = False) -> None:
        self.saved: dict[str, RunTrace] = {}
        self.put_delay = put_delay
        self.block_put = block_put
        self.put_started = asyncio.Event()
        self.active_puts = 0
        self.put_calls = 0

    async def put(self, trace: RunTrace) -> None:
        self.put_started.set()
        self.active_puts += 1
        self.put_calls += 1
        try:
            if self.put_delay:
                await asyncio.sleep(self.put_delay)
            if self.block_put:
                await asyncio.Event().wait()
            self.saved[trace.trace_id] = trace
        finally:
            self.active_puts -= 1

    async def get(self, trace_id: str) -> RunTrace:
        trace = self.saved[trace_id]
        if trace.expires_at <= datetime.now(UTC):
            raise TraceNotFoundError(trace_id)
        return trace

    async def list_session(self, session_id: str, *, limit: int = 100) -> list[RunTrace]:
        traces = [trace for trace in self.saved.values() if trace.session_id == session_id]
        traces.sort(key=lambda trace: trace.created_at, reverse=True)
        return traces[:limit]


def _service(
    repository,
    runtime,
    trace_store,
    *,
    visual_entity_enricher=None,
    test_recording_enabled: bool = True,
) -> VNextChatService:
    return VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
        ConversationContextBuilder(),
        visual_entity_enricher or DotaVisualEntityEnricher(),
        trace_store=trace_store,
        test_recording_enabled=test_recording_enabled,
    )


def _runtime(model, tools=None) -> AgentRuntime:
    return AgentRuntime(
        model,
        tools or ToolRegistry(),
        limits=AgentLimits(application_max_output_tokens=4096),
    )


def _transport_request(request_id: UUID, session_id: UUID, query: str) -> dict[str, object]:
    return {
        "request_id": str(request_id),
        "threadId": str(session_id),
        "commands": [
            {
                "type": "add-message",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": query}],
                },
                "parentId": None,
                "sourceId": None,
            }
        ],
        "state": None,
    }


async def _disconnect_asgi_chat(service, *, started, browser_id, session_id, request_id):
    app = FastAPI()
    app.include_router(chat_router)
    app.state.vnext_chat_service = service
    path = f"/chat/sessions/{session_id}/transport"
    requests: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    await requests.put(
        {
            "type": "http.request",
            "body": json.dumps(_transport_request(request_id, session_id, "question")).encode(),
            "more_body": False,
        }
    )
    sent: list[dict[str, object]] = []

    async def receive():
        return await requests.get()

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"x-dotamind-browser-id", browser_id.encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(started.wait(), timeout=1)
    await requests.put({"type": "http.disconnect"})
    try:
        await asyncio.wait_for(task, timeout=4)
    except asyncio.CancelledError:
        pass
    assert task.done()
    return sent


def test_completed_recording_is_exported_and_replay_reuses_its_reference() -> None:
    async def exercise():
        repository = _Repository()
        trace_store = _TraceStore()
        model = ScriptedModelClient(
            [
                ModelResponse.from_final("execution", usage={"prompt_tokens": 4}),
                ModelResponse.from_final("delivered answer", usage={"prompt_tokens": 9}),
            ]
        )
        runtime = _runtime(model, ToolRegistry())
        service = _service(repository, runtime, trace_store)
        browser_id = str(uuid4())
        session_id = uuid4()
        request_id = uuid4()
        kwargs = {
            "browser_id": browser_id,
            "session_id": session_id,
            "request_id": request_id,
            "query": "question",
        }
        prepared = await service.prepare_turn(**kwargs)
        first_events = [event async for event in service.stream_turn_states(prepared)]
        replay_prepared = await service.prepare_turn(**kwargs)
        replay_events = [event async for event in service.stream_turn_states(replay_prepared)]
        return service, trace_store, model, first_events, replay_events, browser_id

    service, trace_store, model, first_events, replay_events, browser_id = asyncio.run(exercise())

    completed = first_events[-1]
    assert completed.state.status == "completed"
    assert completed.state.answer.status == "ready"
    assert completed.trace is not None
    assert len(trace_store.saved) == 1
    run_trace = trace_store.saved[completed.trace.trace_id]
    assert run_trace.status == "completed"
    assert run_trace.recording_mode == "test"
    assert len(run_trace.trace["model_calls"]) == 2
    assert [call["purpose"] for call in run_trace.trace["model_calls"]] == [
        "execution",
        "primary_answer",
    ]
    run_trace.trace["compaction_capacity_checks"] = [
        {
            "step": 4,
            "summary_kind": "history",
            "measurement": "canonical_json_utf8_bytes_ratio_estimate",
            "context_bytes": 600_000,
            "estimated_input_tokens": 300_000,
            "context_window_tokens": 1_048_576,
            "max_output_tokens": 13_107,
            "safety_margin_tokens": 1_024,
            "required_tokens": 314_131,
            "fits": True,
        }
    ]
    replay_completed = replay_events[-1]
    assert replay_completed.state.status == "completed"
    assert replay_completed.state.answer.text == completed.state.answer.text
    assert replay_completed.trace == completed.trace
    assert len(model.requests) == 2
    assert len(trace_store.saved) == 1

    bundle = asyncio.run(
        service.download_trace_bundle(browser_id=browser_id, trace_id=completed.trace.trace_id)
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "trace.json",
            "model-calls.jsonl",
            "artifact-manifest.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        exported_trace = json.loads(archive.read("trace.json"))
        calls = [
            json.loads(line)
            for line in archive.read("model-calls.jsonl").decode().splitlines()
        ]
        artifact_manifest = json.loads(archive.read("artifact-manifest.json"))
    assert manifest["recording_mode"] == "test"
    assert manifest["status"] == "completed"
    assert manifest["session_id"] == run_trace.session_id
    assert manifest["request_id"] == run_trace.request_id
    assert manifest["recording_version"] == 1
    assert exported_trace["compaction_capacity_checks"] == [
        {
            "step": 4,
            "summary_kind": "history",
            "measurement": "canonical_json_utf8_bytes_ratio_estimate",
            "context_bytes": 600_000,
            "estimated_input_tokens": 300_000,
            "context_window_tokens": 1_048_576,
            "max_output_tokens": 13_107,
            "safety_margin_tokens": 1_024,
            "required_tokens": 314_131,
            "fits": True,
        }
    ]
    assert len(calls) == 2
    assert artifact_manifest["included_tool_observations"] is True
    assert artifact_manifest["includes_complete_artifact_store"] is False


def test_replay_after_service_recreation_does_not_rerun_model_and_keeps_trace_listed() -> None:
    async def exercise():
        repository = _Repository()
        trace_store = _TraceStore()
        browser_id = str(uuid4())
        session_id = uuid4()
        request_id = uuid4()
        request = {
            "browser_id": browser_id,
            "session_id": session_id,
            "request_id": request_id,
            "query": "question",
        }
        first_model = ScriptedModelClient(
            [
                ModelResponse.from_final("execution"),
                ModelResponse.from_final("completed answer"),
            ]
        )
        first_service = _service(
            repository,
            _runtime(first_model, ToolRegistry()),
            trace_store,
        )
        prepared = await first_service.prepare_turn(**request)
        first_events = [event async for event in first_service.stream_turn_states(prepared)]

        after_restart_model = ScriptedModelClient([])
        after_restart = _service(
            repository,
            _runtime(after_restart_model, ToolRegistry()),
            trace_store,
        )
        replay = await after_restart.prepare_turn(**request)
        replay_events = [event async for event in after_restart.stream_turn_states(replay)]
        listed = await after_restart.list_session_traces(
            browser_id=browser_id,
            session_id=session_id,
        )
        return first_events, replay_events, first_model, after_restart_model, listed

    first_events, replay_events, first_model, after_restart_model, listed = asyncio.run(exercise())

    assert first_events[-1].state.status == "completed"
    assert first_events[-1].state.answer.status == "ready"
    assert first_events[-1].trace is not None
    assert replay_events[-1].state.status == "completed"
    assert replay_events[-1].state.answer.text == first_events[-1].state.answer.text
    assert replay_events[-1].trace is None
    assert len(first_model.requests) == 2
    assert after_restart_model.requests == []
    assert [trace.trace_id for trace in listed] == [first_events[-1].trace.trace_id]


def test_failure_is_saved_in_test_mode_and_keeps_error_event_reference() -> None:
    repository = _Repository()
    trace_store = _TraceStore()
    runtime = _runtime(
        ScriptedModelClient([RuntimeError("synthetic provider failure")]),
        ToolRegistry(),
    )
    service = _service(repository, runtime, trace_store)

    async def run():
        prepared = await service.prepare_turn(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )
        return [event async for event in service.stream_turn_states(prepared)]

    events = asyncio.run(run())

    assert events[-1].state.status == "failed"
    assert events[-1].state.error is not None
    assert events[-1].trace is not None
    saved = trace_store.saved[events[-1].trace.trace_id]
    assert saved.status == "failed"
    assert saved.recording_mode == "test"
    assert saved.trace["model_calls"][0]["status"] == "failed"
    assert "synthetic provider failure" not in json.dumps(saved.trace["model_calls"])


def test_rejected_call_diagnostics_round_trip_through_test_trace_zip() -> None:
    raw_arguments = '{"hero":"斯温\n","quote":"他说"好"}'

    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "content": "partial answer",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-zip",
                                    "function": {
                                        "name": "task_checkpoint",
                                        "arguments": raw_arguments[:14],
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
                                    "function": {"arguments": raw_arguments[14:]},
                                }
                            ]
                        },
                        "finish_reason": "length",
                    }
                ]
            },
            {"choices": [], "usage": {"completion_tokens": 23}},
        ]
        body = "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
            for chunk in chunks
        ) + "data: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    async def exercise():
        repository = _Repository()
        trace_store = _TraceStore()
        model = OpenAICompatibleModelClient(
            api_key="offline-test-key",
            base_url="https://provider.test/v1",
            model="test-model",
            transport=httpx.MockTransport(handler),
        )
        service = _service(
            repository,
            _runtime(model, ToolRegistry()),
            trace_store,
        )
        browser_id = str(uuid4())
        session_id = uuid4()
        request_id = uuid4()
        prepared = await service.prepare_turn(
            browser_id=browser_id,
            session_id=session_id,
            request_id=request_id,
            query="diagnostic zip test",
        )
        events = [event async for event in service.stream_turn_states(prepared)]
        completed = events[-1]
        assert completed.state.status == "completed"
        assert completed.trace is not None
        bundle = await service.download_trace_bundle(
            browser_id=browser_id,
            trace_id=completed.trace.trace_id,
        )
        return trace_store, completed, bundle

    trace_store, completed, bundle = asyncio.run(exercise())
    saved = trace_store.saved[completed.trace.trace_id]
    assert saved.recording_mode == "test"
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "trace.json",
            "model-calls.jsonl",
            "artifact-manifest.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        exported_trace = json.loads(archive.read("trace.json"))
        model_calls = [
            json.loads(line)
            for line in archive.read("model-calls.jsonl").decode("utf-8").splitlines()
        ]

    assert manifest["recording_version"] == 1
    assert manifest["status"] == "completed"
    call_diagnostic = exported_trace["model_calls"][0]["failure_diagnostics"]
    assert len(model_calls) == 3
    assert model_calls[0]["failure_diagnostics"] == call_diagnostic
    assert call_diagnostic["tool_calls"][0]["raw_arguments"] == raw_arguments
    assert call_diagnostic["tool_calls"][0]["agent_name"] is None
    assert "model_failure_diagnostics" not in exported_trace["steps"][0]
    assert call_diagnostic["stage"] == "tool_arguments_decode"
    assert call_diagnostic["finish_reason"] == "length"
    assert call_diagnostic["usage"] == {"completion_tokens": 23}
    assert call_diagnostic["stream_done_received"] is True


def test_trace_store_write_failure_does_not_change_answer_or_runtime_error() -> None:
    class FailingTraceStore:
        async def put(self, _trace: RunTrace) -> None:
            raise OSError("trace store is unavailable")

    async def exercise_success():
        service = _service(
            _Repository(),
            _runtime(
                ScriptedModelClient(
                    [
                        ModelResponse.from_final("execution"),
                        ModelResponse.from_final("answer remains available"),
                    ]
                ),
                ToolRegistry(),
            ),
            FailingTraceStore(),  # type: ignore[arg-type]
        )
        prepared = await service.prepare_turn(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )
        return [event async for event in service.stream_turn_states(prepared)]

    async def exercise_failure():
        class FailingRuntime:
            async def run_stream(self, _messages, *, trace_collector=None):
                yield AgentFailed(
                    duration=0.1,
                    error_code="provider_failed",
                    error_message="original model failure",
                )

        service = _service(
            _Repository(),
            FailingRuntime(),
            FailingTraceStore(),  # type: ignore[arg-type]
        )
        prepared = await service.prepare_turn(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )
        return [event async for event in service.stream_turn_states(prepared)]

    success_events = asyncio.run(exercise_success())
    failure_events = asyncio.run(exercise_failure())

    assert success_events[-1].state.status == "completed"
    assert success_events[-1].state.answer.text == "answer remains available"
    assert success_events[-1].state.persistence == "saved"
    assert success_events[-1].trace is None
    assert failure_events[-1].state.status == "failed"
    assert failure_events[-1].state.error is not None
    assert failure_events[-1].state.error.code == "provider_failed"
    assert failure_events[-1].state.error.message == "本次回答未能完成，请重试。"


def test_disconnect_saves_cancelled_record_and_propagates_cancellation() -> None:
    async def exercise():
        started = asyncio.Event()
        cleaned = asyncio.Event()

        class WaitingRuntime:
            async def run_stream(
                self,
                _messages,
                *,
                request_id=None,
                execution_history=None,
                trace_collector=None,
            ):
                request = ModelRequest(messages=[UserMessage(content="question")], step=1)
                call_id = trace_collector.model_call_started(
                    request,
                    step=1,
                    purpose="execution",
                )
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    trace_collector.model_call_finished(
                        call_id,
                        status="cancelled",
                        duration_seconds=0.01,
                        error=asyncio.CancelledError(),
                    )
                    cleaned.set()
                    if False:
                        yield None

        repository = _Repository()
        trace_store = _TraceStore()
        service = _service(repository, WaitingRuntime(), trace_store)
        prepared = await service.prepare_turn(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )

        async def consume() -> None:
            async for _event in service.stream_turn_states(prepared):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        return trace_store, cleaned

    trace_store, cleaned = asyncio.run(exercise())

    assert cleaned.is_set()
    assert len(trace_store.saved) == 1
    saved = next(iter(trace_store.saved.values()))
    assert saved.status == "cancelled"
    assert saved.recording_mode == "test"
    assert saved.trace["model_calls"][0]["status"] == "cancelled"


def test_disconnect_after_runtime_completion_keeps_completed_trace_status() -> None:
    async def exercise():
        completed = asyncio.Event()
        save_started = asyncio.Event()
        release_save = asyncio.Event()

        class CompletedThenWaitingRuntime:
            async def run_stream(self, _messages, *, trace_collector=None):
                yield AnswerStageStarted()
                yield AnswerAttemptStarted(attempt_id="answer-1", answer_kind="primary")
                completed.set()
                yield AgentCompleted(
                    duration=0.1,
                    final=FinalMessage(content="done"),
                    attempt_id="answer-1",
                )

        class BlockingRepository(_Repository):
            async def append_dialogue_turn(self, **kwargs):
                save_started.set()
                await release_save.wait()
                return await super().append_dialogue_turn(**kwargs)

        repository = BlockingRepository()
        trace_store = _TraceStore()
        service = _service(repository, CompletedThenWaitingRuntime(), trace_store)
        prepared = await service.prepare_turn(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )

        async def consume() -> None:
            async for _event in service.stream_turn_states(prepared):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.wait_for(save_started.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_save.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        return trace_store, repository

    trace_store, repository = asyncio.run(exercise())

    assert len(trace_store.saved) == 1
    assert len(repository.results) == 1
    saved = next(iter(trace_store.saved.values()))
    assert saved.status == "completed"
    assert saved.trace["terminal"]["status"] == "completed"


def test_asgi_http_disconnect_cancels_runtime_and_saves_final_trace_snapshot() -> None:
    async def exercise():
        started = asyncio.Event()
        cleaned = asyncio.Event()

        class WaitingRuntime:
            async def run_stream(
                self,
                _messages,
                *,
                request_id=None,
                execution_history=None,
                trace_collector=None,
            ):
                request = ModelRequest(messages=[UserMessage(content="question")], step=1)
                call_id = trace_collector.model_call_started(
                    request,
                    step=1,
                    purpose="execution",
                )
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    trace_collector.model_call_finished(
                        call_id,
                        status="cancelled",
                        duration_seconds=0.01,
                        error=asyncio.CancelledError(),
                    )
                    cleaned.set()
                if False:
                    yield None

        repository = _Repository()
        trace_store = _TraceStore(put_delay=0.01)
        service = _service(repository, WaitingRuntime(), trace_store)
        app = FastAPI()
        app.include_router(chat_router)
        app.state.vnext_chat_service = service
        browser_id = str(uuid4())
        session_id = uuid4()
        request_id = uuid4()
        path = f"/chat/sessions/{session_id}/transport"
        requests: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        await requests.put(
            {
                "type": "http.request",
                "body": json.dumps(_transport_request(request_id, session_id, "question")).encode(),
                "more_body": False,
            }
        )
        sent: list[dict[str, object]] = []

        async def receive():
            return await requests.get()

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"x-dotamind-browser-id", browser_id.encode()),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(started.wait(), timeout=1)
        await requests.put({"type": "http.disconnect"})
        try:
            await asyncio.wait_for(task, timeout=2)
        except asyncio.CancelledError:
            pass
        return trace_store, cleaned, sent

    trace_store, cleaned, sent = asyncio.run(exercise())

    assert cleaned.is_set()
    assert any(message["type"] == "http.response.start" for message in sent)
    assert len(trace_store.saved) == 1
    saved = next(iter(trace_store.saved.values()))
    assert saved.status == "cancelled"
    assert saved.trace["terminal"]["status"] == "cancelled"
    assert saved.trace["model_calls"][0]["status"] == "cancelled"


def test_asgi_disconnect_times_out_blocked_trace_save_without_leaking_writer() -> None:
    async def exercise():
        started = asyncio.Event()
        cleaned = asyncio.Event()

        class WaitingRuntime:
            async def run_stream(
                self,
                _messages,
                *,
                request_id=None,
                execution_history=None,
                trace_collector=None,
            ):
                request = ModelRequest(messages=[UserMessage(content="question")], step=1)
                call_id = trace_collector.model_call_started(
                    request,
                    step=1,
                    purpose="execution",
                )
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    trace_collector.model_call_finished(
                        call_id,
                        status="cancelled",
                        duration_seconds=0.01,
                        error=asyncio.CancelledError(),
                    )
                    cleaned.set()
                if False:
                    yield None

        repository = _Repository()
        trace_store = _TraceStore(block_put=True)
        service = _service(repository, WaitingRuntime(), trace_store)
        sent = await _disconnect_asgi_chat(
            service,
            started=started,
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
        )
        return trace_store, cleaned, sent

    trace_store, cleaned, sent = asyncio.run(exercise())

    assert cleaned.is_set()
    assert any(message["type"] == "http.response.start" for message in sent)
    assert trace_store.put_calls == 1
    assert trace_store.active_puts == 0
    assert trace_store.saved == {}


def test_trace_listing_validates_session_owner_and_returns_metadata_only() -> None:
    repository = _Repository()
    trace_store = _TraceStore()
    now = datetime.now(UTC)
    trace_store.saved["trace-list"] = RunTrace(
        trace_id="trace-list",
        browser_id_hash=hashlib.sha256(b"browser-a").hexdigest(),
        session_id="00000000-0000-4000-8000-000000000001",
        request_id="request-list",
        created_at=now,
        expires_at=now + timedelta(hours=72),
        status="completed",
        recording_mode="test",
        trace={"private": "not returned"},
    )
    service = _service(repository, object(), trace_store)

    summaries = asyncio.run(
        service.list_session_traces(
            browser_id="browser-a",
            session_id=UUID("00000000-0000-4000-8000-000000000001"),
        )
    )

    assert repository.owner_calls == [
        ("browser-a", UUID("00000000-0000-4000-8000-000000000001"))
    ]
    assert [summary.trace_id for summary in summaries] == ["trace-list"]
    assert summaries[0].request_id == "request-list"
    assert summaries[0].status == "completed"
    assert "private" not in summaries[0].model_dump()

    with pytest.raises(ChatNotFoundError):
        asyncio.run(
            service.list_session_traces(
                browser_id="wrong-browser",
                session_id=UUID("00000000-0000-4000-8000-000000000001"),
            )
        )


def test_trace_listing_checks_session_ownership_even_without_a_trace_store() -> None:
    repository = _Repository()
    session_id = uuid4()
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
    )

    with pytest.raises(ChatNotFoundError):
        asyncio.run(
            service.list_session_traces(
                browser_id="wrong-browser",
                session_id=session_id,
            )
        )

    assert repository.owner_calls == [("wrong-browser", session_id)]


def test_completed_runtime_trace_stays_completed_when_chat_persistence_fails() -> None:
    class FailingRepository(_Repository):
        async def append_dialogue_turn(self, **_kwargs):
            raise RuntimeError("chat persistence failed")

    async def run():
        repository = FailingRepository()
        trace_store = _TraceStore()
        service = _service(
            repository,
            _runtime(
                ScriptedModelClient(
                    [
                        ModelResponse.from_final("execution"),
                        ModelResponse.from_final("completed answer"),
                    ]
                ),
                ToolRegistry(),
            ),
            trace_store,
        )
        prepared = await service.prepare_turn(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )
        events = [event async for event in service.stream_turn_states(prepared)]
        return events, trace_store

    events, trace_store = asyncio.run(run())

    assert events[-1].state.status == "completed"
    assert events[-1].state.answer.status == "ready"
    assert events[-1].state.answer.text == "completed answer"
    assert events[-1].state.persistence == "failed"
    assert events[-1].state.error is not None
    assert events[-1].state.error.scope == "persistence"
    assert events[-1].state.error.code == "chat_store_error"
    assert events[-1].trace is not None
    saved = trace_store.saved[events[-1].trace.trace_id]
    assert saved.status == "completed"
    assert saved.trace["terminal"]["status"] == "completed"


def test_visual_enrichment_failure_saves_answer_and_completed_runtime_trace() -> None:
    class FailingVisualEntityEnricher:
        def match(self, _content):
            raise RuntimeError("visual entity enrichment failed")

    async def run():
        repository = _Repository()
        trace_store = _TraceStore()
        service = _service(
            repository,
            _runtime(
                ScriptedModelClient(
                    [
                        ModelResponse.from_final("execution"),
                        ModelResponse.from_final("answer"),
                    ]
                ),
                ToolRegistry(),
            ),
            trace_store,
            visual_entity_enricher=FailingVisualEntityEnricher(),
        )
        browser_id = str(uuid4())
        prepared = await service.prepare_turn(
            browser_id=browser_id,
            session_id=uuid4(),
            request_id=uuid4(),
            query="question",
        )
        events = [event async for event in service.stream_turn_states(prepared)]
        completed = events[-1]
        bundle = None
        if completed.state.status == "completed" and completed.trace is not None:
            bundle = await service.download_trace_bundle(
                browser_id=browser_id,
                trace_id=completed.trace.trace_id,
            )
        return completed, repository, trace_store, bundle

    completed, repository, trace_store, bundle = asyncio.run(run())

    assert completed.state.status == "completed"
    assert completed.state.answer.status == "ready"
    assert completed.state.answer.text == "answer"
    assert completed.state.persistence == "saved"
    assert completed.turn_index == 1
    assert completed.catalog_visual_entities == []
    assert completed.trace is not None
    assert len(repository.results) == 1
    saved_turn = repository.results[next(iter(repository.results))]
    assert saved_turn.assistant_message == "answer"
    assert saved_turn.catalog_visual_entities == []
    assert len(trace_store.saved) == 1
    saved = trace_store.saved[completed.trace.trace_id]
    assert saved.status == "completed"
    assert saved.trace["terminal"]["status"] == "completed"
    assert bundle is not None
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["status"] == "completed"


def test_trace_download_is_browser_owned_and_list_omits_expired_records() -> None:
    now = datetime.now(UTC)
    trace_store = _TraceStore()
    session_id = str(uuid4())
    trace_store.saved["owned"] = RunTrace(
        trace_id="owned",
        browser_id_hash=hashlib.sha256(b"browser-a").hexdigest(),
        session_id=session_id,
        request_id="request-owned",
        created_at=now,
        expires_at=now + timedelta(hours=72),
        status="failed",
        recording_mode="diagnostic",
        trace={"steps": []},
    )
    trace_store.saved["expired"] = RunTrace(
        trace_id="expired",
        browser_id_hash=hashlib.sha256(b"browser-a").hexdigest(),
        session_id=session_id,
        request_id="request-expired",
        created_at=now - timedelta(hours=73),
        expires_at=now - timedelta(seconds=1),
        status="failed",
        recording_mode="diagnostic",
        trace={"steps": []},
    )
    trace_store.saved["other-browser"] = RunTrace(
        trace_id="other-browser",
        browser_id_hash=hashlib.sha256(b"browser-b").hexdigest(),
        session_id=session_id,
        request_id="request-other-browser",
        created_at=now,
        expires_at=now + timedelta(hours=72),
        status="completed",
        recording_mode="test",
        trace={"steps": []},
    )
    repository = _Repository()
    service = _service(repository, object(), trace_store)
    session_uuid = UUID(session_id)

    with pytest.raises(PermissionError):
        asyncio.run(service.download_trace_bundle(browser_id="browser-b", trace_id="owned"))

    listed = asyncio.run(
        service.list_session_traces(browser_id="browser-a", session_id=session_uuid)
    )
    assert [trace.trace_id for trace in listed] == ["owned"]
