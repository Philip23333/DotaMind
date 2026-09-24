from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
    serialized_size,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolContextEffect, ToolDefinition, ToolRegistry
from app.vnext.tools.artifacts import register_artifact_tools

_OLD_RAW_LIMIT = 160 * 1024
_ROW_PAYLOAD_BYTES = 29_500
_ROWS = 7


class _LookupInput(BaseModel):
    edition: str


class _LookupOutput(BaseModel):
    edition: str
    rows: list[dict[str, str]]
    small: str


def _document() -> dict[str, Any]:
    return {
        "edition": "synthetic",
        "rows": [
            {"marker": f"SYNTHETIC_ROW_{index}", "payload": "x" * _ROW_PAYLOAD_BYTES}
            for index in range(_ROWS)
        ],
        "small": "s" * 250,
    }


def _registry(
    store: SessionArtifactStore,
    *,
    lookup_count: list[int] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    async def lookup(_: _LookupInput) -> _LookupOutput:
        if lookup_count is not None:
            lookup_count[0] += 1
        return _LookupOutput.model_validate(_document())

    registry.register(
        ToolDefinition(
            name="fixture.lookup",
            description="Return one fixed synthetic document.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
            externalize_result=True,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    return registry


def _call(call_id: str, name: str, arguments: dict[str, Any]) -> ModelResponse:
    return ModelResponse.from_assistant(
        AssistantMessage(tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])
    )


def _read_call(call_id: str, ref: str, path: str, *, offset: int | None = None) -> ToolCall:
    args: dict[str, Any] = {"ref": ref, "mode": "read", "path": path}
    if offset is not None:
        args.update(offset=offset, limit=1)
    return ToolCall(id=call_id, name="artifact.read", arguments=args)


def _results(request: ModelRequest) -> list[ToolResultMessage]:
    return [message for message in request.messages if isinstance(message, ToolResultMessage)]


def _lookup_ref(request: ModelRequest) -> str:
    result = next(
        result
        for result in _results(request)
        if isinstance(result.content, dict) and result.content.get("artifact_ref")
    )
    ref = result.content["artifact_ref"]
    assert isinstance(ref, str)
    return ref


def _read_results(request: ModelRequest) -> list[ToolResultMessage]:
    return [
        result
        for result in _results(request)
        if isinstance(result.content, dict) and result.content.get("path") is not None
    ]


def _run(awaitable: Any) -> Any:
    return asyncio.run(asyncio.wait_for(awaitable, timeout=10))


class _LargeRawModel:
    """Strict local model script that exercises real Artifact reads."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.read_ref: str | None = None
        self.phase = "lookup"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if not request.tools:
            assert self.phase == "done"
            return ModelResponse.from_final("verified synthetic document")

        if self.phase == "lookup":
            self.phase = "batch"
            return _call("lookup", "fixture.lookup", {"edition": "synthetic"})

        if self.phase == "batch":
            self.read_ref = _lookup_ref(request)
            self.phase = "small"
            return ModelResponse.from_assistant(
                AssistantMessage(
                    tool_calls=[
                        _read_call(f"row-{index}", self.read_ref, "rows", offset=index)
                        for index in range(6)
                    ]
                )
            )

        if self.phase == "small":
            reads = _read_results(request)
            assert len(reads) == 6
            sizes = [serialized_size(result.model_dump(mode="json")) for result in reads]
            assert sum(sizes) > _OLD_RAW_LIMIT
            assert max(sizes) < 35 * 1024
            for index, result in enumerate(reads):
                assert result.status == "ok"
                assert result.content["value"][0]["marker"] == f"SYNTHETIC_ROW_{index}"  # type: ignore[index]
                assert len(result.content["value"][0]["payload"]) == _ROW_PAYLOAD_BYTES  # type: ignore[index]
            self.phase = "finish"
            return _call(
                "small-field",
                "artifact.read",
                {
                    "ref": self.read_ref,
                    "mode": "read",
                    "path": "small",
                },
            )

        assert self.phase == "finish"
        small = _read_results(request)[-1]
        assert small.status == "ok"
        assert small.content["value"] == "s" * 250  # type: ignore[index]
        self.phase = "done"
        return ModelResponse.from_final("all bounded observations remain available")


def test_multiple_bounded_reads_and_small_read_survive_old_cumulative_limit() -> None:
    store = SessionArtifactStore()
    lookup_count = [0]
    model = _LargeRawModel()
    runtime = AgentRuntime(model, _registry(store, lookup_count=lookup_count))
    history = SessionExecutionHistory()
    request_id = uuid4()
    query = "inspect one synthetic document"
    messages = history.begin_request(request_id, query)

    final = _run(runtime.run(messages, execution_history=history, request_id=request_id))

    assert final.content == "verified synthetic document"
    assert model.phase == "done"
    assert lookup_count == [1]
    assert len(model.requests) == 5
    business_requests = [request for request in model.requests if request.tools]
    assert all(
        sum(message == UserMessage(content=query) for message in request.messages) == 1
        for request in business_requests
    )
    batch_call_ids = [
        call
        for record in history.records
        if record.kind == "assistant_tool_call"
        for message in [record.message]
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
        if call.name == "artifact.read"
    ]
    assert [call.id for call in batch_call_ids] == [
        *(f"row-{index}" for index in range(6)),
        "small-field",
    ]
    assert [result.tool_call_id for result in _read_results(model.requests[2])] == [
        f"row-{index}" for index in range(6)
    ]
    assert all(result.status == "ok" for result in _read_results(model.requests[2]))
    small_result = _read_results(model.requests[3])[-1]
    assert small_result.content["value"] == "s" * 250  # type: ignore[index]
    assert not any(
        isinstance(result.content, dict) and result.content.get("_context_materialization")
        for request in model.requests
        for result in _results(request)
    )
    stored = _run(store.get(model.read_ref))
    assert stored == _document()


class _TwoRequestRawModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.phase = 0
        self.ref: str | None = None

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if not request.tools:
            assert self.phase in {3, 6}
            self.phase += 1
            return ModelResponse.from_final(f"answer-{self.phase}")
        if self.phase == 0:
            self.phase = 1
            return _call("lookup", "fixture.lookup", {"edition": "synthetic"})
        if self.phase == 1:
            self.ref = _lookup_ref(request)
            self.phase = 2
            return ModelResponse.from_assistant(
                AssistantMessage(
                    tool_calls=[
                        _read_call(f"first-{index}", self.ref, "rows", offset=index)
                        for index in range(6)
                    ]
                )
            )
        if self.phase == 2:
            assert (
                sum(
                    serialized_size(item.model_dump(mode="json")) for item in _read_results(request)
                )
                > _OLD_RAW_LIMIT
            )
            self.phase = 3
            return ModelResponse.from_final("first execution")
        if self.phase == 4:
            assert self.ref is not None
            assert (
                sum(
                    serialized_size(item.model_dump(mode="json")) for item in _read_results(request)
                )
                > _OLD_RAW_LIMIT
            )
            assert (
                sum(
                    message == UserMessage(content="second question")
                    for message in request.messages
                )
                == 1
            )
            self.phase = 5
            return ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_read_call("second-read", self.ref, "rows", offset=6)])
            )
        assert self.phase == 5
        current = _read_results(request)[-1]
        assert current.content["value"][0]["marker"] == "SYNTHETIC_ROW_6"  # type: ignore[index]
        self.phase = 6
        return ModelResponse.from_final("second execution")


def test_large_raw_history_does_not_block_reads_in_a_followup_user_request() -> None:
    store = SessionArtifactStore()
    model = _TwoRequestRawModel()
    runtime = AgentRuntime(model, _registry(store))
    history = SessionExecutionHistory()

    first_id = uuid4()
    first_messages = history.begin_request(first_id, "first question")
    first = _run(runtime.run(first_messages, execution_history=history, request_id=first_id))
    assert first.content == "answer-4"

    second_id = uuid4()
    second_messages = history.begin_request(second_id, "second question")
    second = _run(runtime.run(second_messages, execution_history=history, request_id=second_id))

    assert second.content == "answer-7"
    assert model.phase == 7
    assert len(model.requests) == 7
    assert model.ref is not None
    assert _run(store.get(model.ref)) == _document()


class _AutomaticCompactionModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.read_count = 0
        self.lookup_count = 0
        self.ref: str | None = None

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if request.metadata.get("purpose") == "context_compaction":
            return ModelResponse.from_final("synthetic summary", finish_reason="stop")
        if not request.tools:
            return ModelResponse.from_final("completed after automatic compaction")

        tool_results = _results(request)
        lookup_result = next(
            (
                result
                for result in tool_results
                if isinstance(result.content, dict) and result.content.get("artifact_ref")
            ),
            None,
        )
        if lookup_result is None:
            if self.ref is None:
                self.lookup_count += 1
                return _call("lookup", "fixture.lookup", {"edition": "synthetic"})
        else:
            self.ref = lookup_result.content["artifact_ref"]  # type: ignore[index]
        if self.read_count < _ROWS:
            assert self.ref is not None
            index = self.read_count
            self.read_count += 1
            return ModelResponse.from_assistant(
                AssistantMessage(
                    tool_calls=[_read_call(f"automatic-{index}", self.ref, "rows", offset=index)]
                )
            )
        return ModelResponse.from_final("execution complete")


def test_high_full_request_still_triggers_automatic_compaction_with_large_raw_results() -> None:
    store = SessionArtifactStore()
    model = _AutomaticCompactionModel()
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(request_id, "read all synthetic rows")
    trace = AgentTraceCollector()
    limits = AgentLimits(
        deadline_seconds=20,
        answer_timeout_seconds=10,
        context_window_tokens=300_000,
        context_output_reserve_tokens=512,
        context_safety_margin_tokens=128,
        context_estimate_bytes_per_token=1,
        context_compaction_test_trigger_percent=25,
        compaction_keep_recent_tokens=1_500,
        compaction_max_input_bytes=200_000,
        compaction_reserve_tokens=50_000,
    )
    runtime = AgentRuntime(model, _registry(store), limits=limits)

    result = _run(
        runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
            trace_collector=trace,
        )
    )

    snapshot = trace.snapshot()
    commits = snapshot["compaction_commits"]
    assert result.content == "completed after automatic compaction"
    assert model.read_count == _ROWS
    assert model.lookup_count == 1
    assert commits
    assert all(commit["trigger"] == "watermark" for commit in commits)
    checks = [
        check
        for check in snapshot["context_capacity_checks"]
        if check["stage"] == "execution" and check["phase"] == "before_compaction"
    ]
    assert checks and all(check["capacity"]["pressure"] in {"high", "critical"} for check in checks)
    assert (
        len(
            [
                result
                for step in snapshot["steps"]
                for result in step.get("tool_results", [])
                if result["result"]["tool_call_id"].startswith("automatic-")
            ]
        )
        == _ROWS
    )
