from __future__ import annotations

import asyncio
import copy
import json
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel

from app.vnext.agent.context_accounting import build_context_accounting
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolContextEffect, ToolDefinition, ToolRegistry
from app.vnext.tools.artifacts import register_artifact_tools


class _LookupInput(BaseModel):
    edition: str


class _LookupOutput(BaseModel):
    edition: str
    champion: str
    evidence: list[dict[str, str]]
    revisit_detail: str


def _synthetic_documents() -> dict[str, dict[str, Any]]:
    return {
        edition: {
            "edition": f"synthetic {edition} edition",
            "champion": f"SYNTHETIC_{edition.upper()}_CHAMPION",
            "evidence": [
                {"record": f"{edition}-synthetic-evidence-{index}-" + "x" * 240}
                for index in range(56)
            ],
            "revisit_detail": f"{edition.upper()}_SYNTHETIC_REVISIT_DETAIL " + edition * 80,
        }
        for edition in ("first", "second", "third")
    }


def _registry(store: SessionArtifactStore, documents: dict[str, dict[str, Any]]) -> ToolRegistry:
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    async def lookup(args: _LookupInput) -> _LookupOutput:
        return _LookupOutput.model_validate(documents[args.edition])

    registry.register(
        ToolDefinition(
            name="fixture.lookup",
            description="Look up one synthetic esports edition.",
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


def _tool_results(request: ModelRequest) -> list[ToolResultMessage]:
    return [message for message in request.messages if isinstance(message, ToolResultMessage)]


def _session_payload(request: ModelRequest) -> dict[str, Any]:
    marker = "Session context data:\n"
    for message in request.messages:
        if isinstance(message, SystemMessage) and marker in message.content:
            payload, _ = json.JSONDecoder().raw_decode(message.content.split(marker, 1)[1])
            return payload
    raise AssertionError("request did not contain the Runtime session projection")


class _ThreeEditionModel:
    """Strict deterministic model script; every business turn is consumed once."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.phase = 0
        self.read_refs: dict[str, str] = {}
        self.recovered_first_detail = False

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if request.metadata.get("purpose") == "context_compaction":
            summary_index = sum(
                item.metadata.get("purpose") == "context_compaction" for item in self.requests
            )
            return ModelResponse.from_final(
                f"synthetic comparison progress summary {summary_index}; no artifact refs",
                finish_reason="stop",
            )

        query = "compare three synthetic esports editions and verify the champion details"
        assert sum(message == UserMessage(content=query) for message in request.messages) == 1
        if self.phase >= 1:
            payload = _session_payload(request)
            if payload["summary"]:
                assert not any(
                    isinstance(message, FinalMessage)
                    and "older synthetic answer" in message.content
                    for message in request.messages
                )
        if not request.tools:
            assert self.phase == 8
            assert "synthetic comparison progress summary" in json.dumps(
                request.model_dump(mode="json"), ensure_ascii=False
            )
            assert self.recovered_first_detail
            return ModelResponse.from_final(
                "Synthetic comparison: "
                "SYNTHETIC_first_REVISIT_DETAIL was reread from the original Artifact."
            )

        if self.phase in {0, 2, 4}:
            edition = {0: "first", 2: "second", 4: "third"}[self.phase]
            expected_step = {0: 1, 2: 3, 4: 5}[self.phase]
            assert request.step == expected_step
            self.phase += 1
            return _call(
                f"lookup-{edition}",
                "fixture.lookup",
                {"edition": edition},
            )

        if self.phase in {1, 3, 5}:
            edition = {1: "first", 3: "second", 5: "third"}[self.phase]
            expected_step = {1: 2, 3: 4, 5: 6}[self.phase]
            assert request.step == expected_step
            lookup_result = _tool_results(request)[-1].content
            assert isinstance(lookup_result, dict)
            ref = lookup_result.get("artifact_ref")
            assert isinstance(ref, str)
            self.read_refs[edition] = ref
            self.phase += 1
            return _call(
                f"read-{edition}",
                "artifact.read",
                {
                    "ref": ref,
                    "mode": "read",
                    "path": "evidence",
                    "offset": 0,
                    "limit": 5,
                },
            )

        if self.phase == 6:
            assert request.step == 7
            payload = _session_payload(request)
            first_locator = next(
                item
                for item in payload["artifact_locators"]
                if '"edition":"first"' in item["query_hint"]
            )
            first_ref = first_locator["ref"]
            assert first_ref == self.read_refs["first"]
            self.phase += 1
            self.recovered_first_detail = True
            return _call(
                "reread-first-detail",
                "artifact.read",
                {
                    "ref": first_ref,
                    "mode": "read",
                    "path": "revisit_detail",
                },
            )

        assert self.phase == 7
        assert request.step == 8
        read_result = _tool_results(request)[-1].content
        assert isinstance(read_result, dict)
        assert "FIRST_SYNTHETIC_REVISIT_DETAIL" in json.dumps(read_result)
        self.phase += 1
        return ModelResponse.from_final("execution has complete synthetic comparison evidence")


def _run(awaitable: Any) -> Any:
    return asyncio.run(asyncio.wait_for(awaitable, timeout=5))


def test_automatic_watermarks_keep_artifacts_rereadable_across_two_compactions() -> None:
    documents = _synthetic_documents()
    original_documents = copy.deepcopy(documents)
    store = SessionArtifactStore()
    model = _ThreeEditionModel()
    limits = AgentLimits(
        deadline_seconds=10,
        answer_timeout_seconds=10,
        context_window_tokens=12_000,
        context_output_reserve_tokens=256,
        context_safety_margin_tokens=128,
        context_estimate_bytes_per_token=1,
        context_compaction_test_trigger_percent=70,
        compaction_keep_recent_tokens=1_000,
        compaction_max_input_bytes=100_000,
        compaction_reserve_tokens=160,
        max_materialized_context_bytes=100_000,
    )
    runtime = AgentRuntime(model, _registry(store, documents), limits=limits)
    history = SessionExecutionHistory()
    request_id = uuid4()
    query = "compare three synthetic esports editions and verify the champion details"
    history.begin_request(
        request_id,
        query,
        initial_messages=[
            UserMessage(content="older synthetic conversation"),
            FinalMessage(content="older synthetic answer " + "history " * 80),
        ],
    )
    trace = AgentTraceCollector()

    final = _run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            trace_collector=trace,
        )
    )

    snapshot = trace.snapshot()
    commits = snapshot["compaction_commits"]
    assert len(commits) >= 2, (
        [
            (
                item["step"],
                item["trigger"],
                item["materialized_bytes_before"],
                item["materialized_bytes_after"],
            )
            for item in commits
        ],
        [
            (
                item["step"],
                item["stage"],
                item["phase"],
                item["capacity"]["context_bytes"],
                item["capacity"]["pressure"],
            )
            for item in snapshot.get("context_capacity_checks", [])
        ],
        [(request.step, request.metadata, len(request.tools)) for request in model.requests],
        model.phase,
    )
    assert all(commit["trigger"] == "watermark" for commit in commits[:2])
    assert all(
        commit["materialized_bytes_before"] > commit["materialized_bytes_after"] > 0
        for commit in commits[:2]
    ), (
        [
            (item["step"], item["materialized_bytes_before"], item["materialized_bytes_after"])
            for item in commits
        ],
        [
            (item["step"], item.get("materialization_budget"))
            for item in snapshot["steps"]
            if item.get("materialization_budget")
        ],
    )
    assert model.phase == 8
    assert model.recovered_first_detail
    assert final.content.startswith("Synthetic comparison:")
    assert "SYNTHETIC_first_REVISIT_DETAIL" in final.content
    assert [
        result["result"]["tool_call_id"]
        for step in snapshot["steps"]
        for result in step.get("tool_results", [])
    ] == [
        "lookup-first",
        "read-first",
        "lookup-second",
        "read-second",
        "lookup-third",
        "read-third",
        "reread-first-detail",
    ]
    assert len(history.compaction_records) >= 2
    assert history.summary and "artifact refs" in history.summary
    assert not any(isinstance(message, SystemMessage) for message in history.effective_messages())
    assert (
        sum(
            record.kind == "delivery_answer" and record.request_id == request_id
            for record in history.records
        )
        == 1
    )
    assert sum(
        message == UserMessage(content=query)
        for request in model.requests
        if request.metadata.get("purpose") != "context_compaction"
        for message in request.messages
    ) == len(
        [
            request
            for request in model.requests
            if request.metadata.get("purpose") != "context_compaction"
        ]
    )

    for edition in ("first", "second", "third"):
        ref = model.read_refs[edition]
        stored = _run(store.get(ref))
        assert stored == _LookupOutput.model_validate(original_documents[edition]).model_dump(
            mode="json"
        )
        assert original_documents[edition]["evidence"] == documents[edition]["evidence"]

    business_requests = [
        request
        for request in model.requests
        if request.metadata.get("purpose") != "context_compaction"
    ]
    raw_bytes = [
        build_context_accounting(request).artifact_observations.active_raw.serialized_bytes
        for request in business_requests
    ]
    assert max(raw_bytes) > 0
    assert any(later > earlier for earlier, later in zip(raw_bytes, raw_bytes[1:], strict=False))
    assert any(
        0 < later < earlier for earlier, later in zip(raw_bytes, raw_bytes[1:], strict=False)
    ), raw_bytes
    successful_steps = [item for item in snapshot["steps"] if "context_accounting" in item]
    by_step = {item["step"]: item["context_accounting"] for item in successful_steps}
    assert len(business_requests) == len(successful_steps)
    for request in business_requests:
        traced_bytes = by_step[request.step]["effective_request"]["serialized_bytes"]
        measured = build_context_accounting(request).to_dict()["effective_request"][
            "serialized_bytes"
        ]
        assert traced_bytes == measured


def _sse(content: str) -> str:
    chunks = [
        {"choices": [{"delta": {"role": "assistant", "content": content}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def test_real_adapter_overflow_classification_compacts_and_retries_same_step() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={"error": {"code": "context_length_exceeded"}},
                request=request,
            )
        if payload["messages"][0].get("role") == "system" and any(
            marker in payload["messages"][0].get("content", "")
            for marker in (
                "Update the supplied previous summary",
                "Summarize only the supplied prefix",
            )
        ):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse("provider recovery summary without artifact references"),
                request=request,
            )
        content = (
            "execution complete" if payload.get("tools") else "final answer after provider recovery"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(content),
            request=request,
        )

    client = OpenAICompatibleModelClient(
        api_key="test-key",
        base_url="https://provider.test/v1",
        model="synthetic-model",
        transport=httpx.MockTransport(handler),
    )
    limits = AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        context_window_tokens=100_000,
        context_output_reserve_tokens=256,
        context_safety_margin_tokens=128,
        context_estimate_bytes_per_token=1,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=100_000,
        compaction_reserve_tokens=160,
    )
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current synthetic question",
        initial_messages=[
            UserMessage(content="old synthetic evidence question"),
            FinalMessage(content="old synthetic evidence " + "x" * 1_200),
        ],
    )
    trace = AgentTraceCollector()
    registry = ToolRegistry()
    runtime = AgentRuntime(client, registry, limits=limits)

    final = _run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            trace_collector=trace,
        )
    )

    snapshot = trace.snapshot()
    assert final.content == "final answer after provider recovery"
    assert len(requests) == 4
    assert len(snapshot["compaction_calls"]) == 1
    assert len(snapshot["compaction_commits"]) == 1
    assert snapshot["compaction_commits"][0]["trigger"] == "overflow"
    assert snapshot["overflow_recoveries"] == [
        {
            "step": 1,
            "stage": "execution",
            "status": "retry_succeeded",
            "error_code": None,
        }
    ]
    assert snapshot["steps"][0]["failed_model_attempts"][0]["error_code"] == (
        "model_context_window_exceeded"
    )
    execution_step = next(item for item in snapshot["steps"] if item["step"] == 1)
    assert execution_step["model_request"]["step"] == 1
    retry_payload = requests[2]
    assert any(
        "provider recovery summary without artifact references" in message.get("content", "")
        for message in retry_payload["messages"]
    )
