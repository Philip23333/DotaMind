from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.vnext_chat_routes import router as chat_router
from app.application.chat_repository import (
    ChatDialogueTurnResult,
    ChatIdempotencyConflictError,
    ChatNotFoundError,
)
from app.vnext.agent.events import (
    AgentCompleted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
    TextDelta,
)
from app.vnext.llm.protocol import FinalMessage
from app.vnext.product.assistant_transport import product_state_envelope
from app.vnext.product.chat import (
    PreparedVNextChatTurn,
    ProductChatState,
    VNextChatService,
)
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.product.presentation import DotaVisualEntityEnricher


class _Repository:
    def __init__(self) -> None:
        self.saved: dict[UUID, tuple[str, ChatDialogueTurnResult]] = {}
        self.appended: list[dict[str, Any]] = []
        self.append_started = asyncio.Event()
        self.append_finalized = asyncio.Event()
        self.write_release: asyncio.Event | None = None
        self.active_appends = 0
        self.lookups = 0

    async def lookup_dialogue_request(
        self,
        browser_id: str,
        _session_id: UUID,
        request_id: UUID,
        query: str,
    ) -> ChatDialogueTurnResult | None:
        self.lookups += 1
        if browser_id != "browser":
            raise ChatNotFoundError()
        existing = self.saved.get(request_id)
        if existing is None:
            return None
        if existing[0] != query:
            raise ChatIdempotencyConflictError()
        return existing[1]

    async def get_all_dialogue_turns(self, browser_id: str, _session_id: UUID):
        if browser_id != "browser":
            raise ChatNotFoundError()
        return [], 1

    async def append_dialogue_turn(self, **kwargs) -> ChatDialogueTurnResult:
        self.appended.append(kwargs)
        self.active_appends += 1
        self.append_started.set()
        try:
            if self.write_release is not None:
                await self.write_release.wait()
            request_id = kwargs["request_id"]
            query = str(kwargs["user_query"])
            existing = self.saved.get(request_id)
            if existing is not None:
                if existing[0] != query:
                    raise ChatIdempotencyConflictError()
                return existing[1]
            result = ChatDialogueTurnResult(
                status="executed",
                turn_index=len(self.saved) + 1,
                assistant_message=str(kwargs["assistant_message"]),
                catalog_visual_entities=list(kwargs["catalog_visual_entities"]),
            )
            self.saved[request_id] = (query, result)
            return result
        finally:
            self.active_appends -= 1
            self.append_finalized.set()


class _Runtime:
    def __init__(
        self,
        *,
        mode: str = "immediate",
        release_final: asyncio.Event | None = None,
    ) -> None:
        self.mode = mode
        self.release_final = release_final
        self.started = asyncio.Event()
        self.final_released = asyncio.Event()
        self.closed = asyncio.Event()
        self.run_count = 0
        self.queries: list[str] = []

    async def run_stream(self, messages, *, trace_collector=None) -> AsyncIterator[object]:
        del trace_collector
        self.run_count += 1
        self.queries.append(messages[-1].content)
        query = messages[-1].content
        try:
            yield AnswerStageStarted()
            if self.mode == "fallback":
                yield AnswerAttemptStarted(attempt_id="primary", answer_kind="primary")
                yield TextDelta(text="primary fragment", attempt_id="primary")
                self.started.set()
                assert self.release_final is not None
                await self.release_final.wait()
                self.final_released.set()
                yield AnswerAttemptFailed(attempt_id="primary", error_code="primary_failed")
                yield AnswerAttemptStarted(attempt_id="fallback", answer_kind="degraded")
                yield TextDelta(text="fallback fragment", attempt_id="fallback")
                final = "fallback fragment complete"
                yield AgentCompleted(
                    duration=0.1,
                    final=FinalMessage(content=final),
                    attempt_id="fallback",
                )
                return

            yield AnswerAttemptStarted(attempt_id="primary", answer_kind="primary")
            yield TextDelta(text="first fragment", attempt_id="primary")
            self.started.set()
            if self.mode == "waiting":
                assert self.release_final is not None
                await self.release_final.wait()
            self.final_released.set()
            yield AgentCompleted(
                duration=0.1,
                final=FinalMessage(content=f"answer:{query}"),
                attempt_id="primary",
            )
        finally:
            self.closed.set()


class _RecordingService(VNextChatService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.product_updates: dict[UUID, list[ProductChatState]] = {}

    async def stream_turn_states(
        self,
        prepared: PreparedVNextChatTurn,
    ) -> AsyncIterator[ProductChatState]:
        async for update in super().stream_turn_states(prepared):
            self.product_updates.setdefault(prepared.request_id, []).append(update)
            yield update


def _service(repository, runtime, *, runtime_factory=None, persistence_timeout_seconds=15.0):
    return _RecordingService(
        repository,  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
        runtime_factory=runtime_factory,
        persistence_timeout_seconds=persistence_timeout_seconds,
    )


def _app(service) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")
    app.state.vnext_chat_service = service
    return app


def _request_body(
    session_id: UUID,
    request_id: UUID,
    parts: list[dict[str, Any]],
    **overrides: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_id": str(request_id),
        "commands": [
            {
                "type": "add-message",
                "message": {"role": "user", "parts": parts},
                "parentId": "assistant:previous",
                "sourceId": None,
            }
        ],
        "threadId": str(session_id),
        "parentId": "assistant:previous",
    }
    body.update(overrides)
    return body


class _SseReader:
    def __init__(self, response: httpx.Response) -> None:
        self._chunks = response.aiter_raw()
        self.pending = ""
        self.raw = bytearray()

    async def next_data(self) -> str:
        while True:
            newline = self.pending.find("\n")
            if newline >= 0:
                line = self.pending[:newline].removesuffix("\r")
                self.pending = self.pending[newline + 1 :]
                if line.startswith("data:"):
                    return line[5:].lstrip()
                continue
            chunk = await anext(self._chunks)
            self.raw.extend(chunk)
            self.pending += chunk.decode("utf-8")


def _has_operation(payload: str, predicate) -> bool:
    if payload == "[DONE]":
        return False
    chunk = json.loads(payload)
    return chunk.get("type") == "update-state" and any(
        predicate(operation) for operation in chunk.get("operations", [])
    )


async def _start_server(app: FastAPI):
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            lifespan="off",
            log_level="critical",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve())
    deadline = asyncio.get_running_loop().time() + 5
    while not server.started:
        if task.done():
            await task
            raise RuntimeError("loopback ASGI server stopped before startup")
        if asyncio.get_running_loop().time() > deadline:
            server.should_exit = True
            await task
            raise TimeoutError("loopback ASGI server did not start")
        await asyncio.sleep(0.001)
    assert server.servers
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, f"http://127.0.0.1:{port}"


async def _stop_server(server: uvicorn.Server, task: asyncio.Task[None]) -> None:
    server.should_exit = True
    await asyncio.wait_for(task, timeout=3)


def test_official_transport_endpoint_streams_live_fallback_and_final_save_state() -> None:
    async def run():
        release_final = asyncio.Event()
        runtime = _Runtime(mode="fallback", release_final=release_final)
        repository = _Repository()
        service = _service(repository, runtime)
        app = _app(service)
        server, server_task, base_url = await _start_server(app)
        session_id = uuid4()
        request_id = uuid4()
        body = _request_body(
            session_id,
            request_id,
            [{"type": "text", "text": "team "}, {"type": "text", "text": "Spirit"}],
            state={"run": {"status": "completed", "answer": {"text": "forged"}}},
            system="",
            tools={},
            callSettings={},
            config={},
        )
        payloads: list[str] = []
        early_primary = False
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            async with client.stream(
                "POST",
                f"{base_url}/api/v1/chat/sessions/{session_id}/transport",
                headers={"X-DotaMind-Browser-Id": "browser"},
                json=body,
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["cache-control"] == "no-cache, no-transform"
                assert response.headers["x-accel-buffering"] == "no"
                reader = _SseReader(response)
                while True:
                    payload = await reader.next_data()
                    payloads.append(payload)
                    if _has_operation(
                        payload,
                        lambda operation: operation.get("type") == "append-text"
                        and operation.get("path") == ["run", "answer", "text"]
                        and operation.get("value") == "primary fragment",
                    ):
                        early_primary = True
                        assert not runtime.final_released.is_set()
                        break
                release_final.set()
                while payloads[-1] != "[DONE]":
                    payloads.append(await reader.next_data())
                wire = bytes(reader.raw).decode("utf-8")
        await _stop_server(server, server_task)

        updates = service.product_updates[request_id]
        final_envelope = product_state_envelope(
            PreparedVNextChatTurn(
                browser_id="browser",
                session_id=session_id,
                request_id=request_id,
                query="team Spirit",
                history=[],
            ),
            updates[-1],
        )
        capture_path = os.environ.get("DOTAMIND_ASSISTANT_TRANSPORT_CAPTURE")
        if capture_path:
            Path(capture_path).write_text(
                json.dumps({"wire": wire, "expected_state": final_envelope}),
                encoding="utf-8",
            )
        return payloads, final_envelope, runtime, repository, early_primary

    payloads, final, runtime, repository, early_primary = asyncio.run(run())
    assert early_primary
    assert payloads[-1] == "[DONE]"
    assert runtime.queries == ["team Spirit"]
    assert runtime.run_count == 1
    assert len(repository.appended) == 1
    assert final["user_message"] == {"id": f"user:{final['request_id']}", "text": "team Spirit"}
    assert final["run"]["status"] == "completed"
    assert final["run"]["answer"]["status"] == "ready"
    assert final["run"]["answer"]["text"] == "fallback fragment complete"
    assert final["run"]["persistence"] == "saved"
    assert set(final) == {
        "session_id",
        "request_id",
        "user_message",
        "run",
        "turn_index",
        "trace",
    }


@pytest.mark.parametrize(
    "body,expected_code",
    [
        (
            {"commands": []},
            "unsupported_transport_command",
        ),
        (
            {"commands": [{"type": "add-tool-result", "toolCallId": "tool-1", "result": {}}]},
            "invalid_transport_request",
        ),
        (
            {
                "commands": [
                    {
                        "type": "add-message",
                        "message": {"role": "assistant", "parts": [{"type": "text", "text": "x"}]},
                        "parentId": None,
                        "sourceId": None,
                    }
                ]
            },
            "invalid_transport_request",
        ),
        (
            {
                "commands": [
                    {
                        "type": "add-message",
                        "message": {"role": "user", "parts": [{"type": "image", "image": "x"}]},
                        "parentId": None,
                        "sourceId": None,
                    }
                ]
            },
            "invalid_transport_request",
        ),
        (
            {
                "commands": [
                    {
                        "type": "add-message",
                        "message": {"role": "user", "parts": [{"type": "text", "text": "one"}]},
                        "parentId": None,
                        "sourceId": None,
                    },
                    {
                        "type": "add-message",
                        "message": {"role": "user", "parts": [{"type": "text", "text": "two"}]},
                        "parentId": None,
                        "sourceId": None,
                    },
                ]
            },
            "unsupported_transport_command",
        ),
        (
            {
                "commands": [
                    {
                        "type": "add-message",
                        "message": {"role": "user", "parts": [{"type": "text", "text": "edit"}]},
                        "parentId": None,
                        "sourceId": "assistant:old",
                    }
                ]
            },
            "unsupported_transport_command",
        ),
    ],
)
def test_transport_rejects_unsupported_commands_without_preparing_a_turn(
    body, expected_code
) -> None:
    session_id = uuid4()
    request_id = uuid4()
    valid_body = _request_body(
        session_id,
        request_id,
        [{"type": "text", "text": "valid"}],
    )
    valid_body.update(body)

    class _NeverPrepare:
        def __init__(self) -> None:
            self.prepare_calls = 0

        async def prepare_turn(self, **_kwargs):
            self.prepare_calls += 1
            raise AssertionError("invalid transport input reached prepare_turn")

    service = _NeverPrepare()
    app = _app(service)
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/transport",
            headers={"X-DotaMind-Browser-Id": "browser"},
            json=valid_body,
        )
    assert response.status_code == 422
    assert response.json()["error_code"] == expected_code
    assert service.prepare_calls == 0
    assert "valid" not in response.json()["reason"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"system": "client system prompt"},
        {"tools": {"client.tool": {}}},
        {"config": {"modelName": "client-model"}},
        {"callSettings": {"temperature": 0}},
        {"apiKey": "never forwarded"},
    ],
)
def test_transport_rejects_nonempty_client_model_configuration(overrides) -> None:
    session_id = uuid4()
    service = type(
        "NeverPrepare",
        (),
        {"prepare_turn": lambda *_args, **_kwargs: pytest.fail("must reject before prepare")},
    )()
    app = _app(service)
    body = _request_body(session_id, uuid4(), [{"type": "text", "text": "question"}], **overrides)
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/transport",
            headers={"X-DotaMind-Browser-Id": "browser"},
            json=body,
        )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_transport_request"
    assert "never forwarded" not in response.text


def test_transport_rejects_thread_mismatch_and_preserves_append_parent_metadata() -> None:
    session_id = uuid4()

    class _NeverPrepare:
        async def prepare_turn(self, **_kwargs):
            raise AssertionError("thread mismatch must be rejected before session lookup")

    app = _app(_NeverPrepare())
    mismatch = _request_body(
        session_id,
        uuid4(),
        [{"type": "text", "text": "question"}],
        threadId=str(uuid4()),
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/transport",
            headers={"X-DotaMind-Browser-Id": "browser"},
            json=mismatch,
        )
    assert response.status_code == 409
    assert response.json()["error_code"] == "thread_mismatch"


def test_transport_replay_uses_repository_without_runtime_or_duplicate_append() -> None:
    async def run():
        repository = _Repository()
        request_id = uuid4()
        query = "replay this"
        repository.saved[request_id] = (
            query,
            ChatDialogueTurnResult(
                status="replay",
                turn_index=9,
                assistant_message="saved answer",
            ),
        )
        runtime = _Runtime()
        service = _service(repository, runtime)
        app = _app(service)
        session_id = uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/chat/sessions/{session_id}/transport",
                headers={"X-DotaMind-Browser-Id": "browser"},
                json=_request_body(
                    session_id,
                    request_id,
                    [{"type": "text", "text": query}],
                ),
            )
        return response, runtime, repository

    response, runtime, repository = asyncio.run(run())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.endswith("data: [DONE]\n\n")
    assert runtime.run_count == 0
    assert repository.appended == []
    assert '"persistence": "saved"' in response.text
    assert '"text": "saved answer"' in response.text


def test_actual_loopback_disconnect_cancels_runtime_generation() -> None:
    async def run():
        repository = _Repository()
        release_final = asyncio.Event()
        runtime = _Runtime(mode="waiting", release_final=release_final)
        service = _service(repository, runtime)
        server, server_task, base_url = await _start_server(_app(service))
        session_id = uuid4()
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            context = client.stream(
                "POST",
                f"{base_url}/api/v1/chat/sessions/{session_id}/transport",
                headers={"X-DotaMind-Browser-Id": "browser"},
                json=_request_body(
                    session_id,
                    uuid4(),
                    [{"type": "text", "text": "disconnect during generation"}],
                ),
            )
            response = await context.__aenter__()
            reader = _SseReader(response)
            await asyncio.wait_for(reader.next_data(), timeout=2)
            await asyncio.wait_for(runtime.started.wait(), timeout=2)
            await response.aclose()
            await asyncio.wait_for(runtime.closed.wait(), timeout=1)
            await context.__aexit__(None, None, None)
        await _stop_server(server, server_task)
        return repository, runtime, service

    repository, runtime, service = asyncio.run(run())
    assert runtime.closed.is_set()
    assert repository.appended == []
    assert service._sessions
    assert all(not session.lock.locked() for session in service._sessions.values())


def test_loopback_disconnect_during_save_uses_original_persistence_budget() -> None:
    async def run():
        budget = 0.25
        repository = _Repository()
        repository.write_release = asyncio.Event()
        runtime = _Runtime()
        service = _service(
            repository,
            runtime,
            persistence_timeout_seconds=budget,
        )
        server, server_task, base_url = await _start_server(_app(service))
        session_id = uuid4()
        request_id = uuid4()
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            context = client.stream(
                "POST",
                f"{base_url}/api/v1/chat/sessions/{session_id}/transport",
                headers={"X-DotaMind-Browser-Id": "browser"},
                json=_request_body(
                    session_id,
                    request_id,
                    [{"type": "text", "text": "disconnect while saving"}],
                ),
            )
            response = await context.__aenter__()
            reader = _SseReader(response)
            saw_saving = False
            while not saw_saving:
                payload = await asyncio.wait_for(reader.next_data(), timeout=2)
                saw_saving = _has_operation(
                    payload,
                    lambda operation: operation.get("type") == "set"
                    and operation.get("path") == ["run", "persistence"]
                    and operation.get("value") == "saving",
                )
            await asyncio.wait_for(repository.append_started.wait(), timeout=1)
            await asyncio.sleep(budget * 0.72)
            disconnected_at = asyncio.get_running_loop().time()
            await response.aclose()
            await asyncio.wait_for(repository.append_finalized.wait(), timeout=budget * 0.78)
            cleanup_elapsed = asyncio.get_running_loop().time() - disconnected_at
            await context.__aexit__(None, None, None)
        await _stop_server(server, server_task)
        return repository, runtime, service, cleanup_elapsed

    repository, runtime, service, cleanup_elapsed = asyncio.run(run())
    assert repository.active_appends == 0
    assert repository.append_finalized.is_set()
    assert cleanup_elapsed < 0.25 * 0.78
    assert runtime.closed.is_set()
    observed = service.product_updates[next(iter(service.product_updates))]
    assert observed[-1].state.persistence == "saving"
    assert all(not session.lock.locked() for session in service._sessions.values())


def test_two_loopback_sessions_keep_transport_states_separate() -> None:
    async def run():
        repository = _Repository()
        created: list[_Runtime] = []

        def runtime_factory():
            runtime = _Runtime()
            created.append(runtime)
            return runtime

        service = _service(repository, _Runtime(), runtime_factory=runtime_factory)
        server, server_task, base_url = await _start_server(_app(service))
        sessions = [(uuid4(), uuid4(), "question one"), (uuid4(), uuid4(), "question two")]

        async def collect(session_id: UUID, request_id: UUID, query: str):
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/api/v1/chat/sessions/{session_id}/transport",
                    headers={"X-DotaMind-Browser-Id": "browser"},
                    json=_request_body(
                        session_id,
                        request_id,
                        [{"type": "text", "text": query}],
                    ),
                ) as response:
                    assert response.status_code == 200
                    return [
                        line
                        async for line in response.aiter_lines()
                        if line.startswith("data: ")
                    ]

        results = await asyncio.gather(*(collect(*values) for values in sessions))
        await _stop_server(server, server_task)
        return sessions, results, created

    sessions, results, created = asyncio.run(run())
    assert len(created) == 2
    for (session_id, request_id, query), frames in zip(sessions, results, strict=True):
        assert all(frame.startswith("data: ") for frame in frames)
        assert frames[-1] == "data: [DONE]"
        state_payloads = [
            json.loads(frame.removeprefix("data: ").strip())
            for frame in frames
            if frame != "data: [DONE]"
        ]
        root_state = next(
            operation["value"]
            for chunk in state_payloads
            if chunk.get("type") == "update-state"
            for operation in chunk["operations"]
            if operation.get("type") == "set" and operation.get("path") == []
        )
        assert root_state["session_id"] == str(session_id)
        assert root_state["request_id"] == str(request_id)
        assert root_state["user_message"]["text"] == query
        assert f"answer:{query}" in "".join(frames)
