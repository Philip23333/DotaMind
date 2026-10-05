from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.vnext.agent.answer_stage import _tool_evidence
from app.vnext.agent.errors import AgentCancelledError, ModelProviderError
from app.vnext.agent.events import AgentCompleted, AgentFailed, ToolStarted
from app.vnext.agent.generation_recovery import (
    NOT_EXECUTED_FEEDBACK,
    build_rejected_tool_call_history,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _has_reliable_tool_results
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.errors import ModelToolCallBatchRejected
from app.vnext.llm.protocol import (
    AssistantMessage,
    Message,
    ModelResponse,
    RawToolCall,
    RejectedAssistantMessage,
    RejectedToolCallBatch,
    ToolArgumentFailure,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolDefinition, ToolError, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class EchoInput(BaseModel):
    value: int


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _batch(
    *,
    call_ids: tuple[str, ...] = ("bad-call",),
    reason: str = "invalid_tool_arguments",
) -> RejectedToolCallBatch:
    calls = [
        RawToolCall(
            index=index,
            id=call_id,
            name="echo",
            provider_name="echo",
            raw_arguments=f'{{"value": {index}, "marker": "RAW_{call_id}"',
        )
        for index, call_id in enumerate(call_ids)
    ]
    failures = (
        [
            ToolArgumentFailure(
                call_index=0,
                kind="invalid_json",
                message="Expecting ',' delimiter",
                position=10,
                line=1,
                column=11,
            )
        ]
        if reason == "invalid_tool_arguments"
        else []
    )
    return RejectedToolCallBatch(
        reason=reason,  # type: ignore[arg-type]
        calls=calls,
        argument_failures=failures,
        finish_reason="length" if reason == "tool_response_truncated" else "tool_calls",
    )


def _provider_error(batch: RejectedToolCallBatch) -> ModelProviderError:
    return ModelProviderError(
        "model provider request failed",
        cause=ModelToolCallBatchRejected(batch=batch),
    )


def _registry(handler=None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo one integer.",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=handler or (lambda args: EchoOutput(value=args.value)),
        )
    )
    return registry


def _tool_turn(call_id: str, value: int) -> ModelResponse:
    return ModelResponse(
        message=AssistantMessage(
            tool_calls=[ToolCall(id=call_id, name="echo", arguments={"value": value})]
        )
    )


def test_rejected_batch_creates_complete_paired_non_execution_history() -> None:
    batch = _batch(call_ids=("invalid", "valid-peer"))

    assistant, results = build_rejected_tool_call_history(batch)

    assert isinstance(assistant, RejectedAssistantMessage)
    assert [call.raw_arguments for call in assistant.tool_calls] == [
        call.raw_arguments for call in batch.calls
    ]
    assert [result.tool_call_id for result in results] == ["invalid", "valid-peer"]
    assert [result.error.code for result in results if result.error] == [
        "model_tool_arguments_invalid",
        "model_tool_batch_rejected",
    ]
    assert all(result.status == "error" and result.executed is False for result in results)
    assert all(result.content == NOT_EXECUTED_FEEDBACK for result in results)
    assert results[0].error is not None
    assert results[0].error.details == {
        "reason": "invalid_tool_arguments",
        "kind": "invalid_json",
        "diagnostic": "Expecting ',' delimiter",
        "position": 10,
        "line": 1,
        "column": 11,
    }
    assert results[1].error is not None
    assert results[1].error.details["cause"] == "another_call_invalid"
    assert "RAW_" not in json.dumps([result.model_dump(mode="json") for result in results])
    assert TypeAdapter(Message).validate_python(assistant.model_dump(mode="json")) == assistant


def test_truncated_tool_response_marks_every_call_truncated() -> None:
    assistant, results = build_rejected_tool_call_history(
        _batch(call_ids=("one", "two"), reason="tool_response_truncated")
    )

    assert len(assistant.tool_calls) == len(results) == 2
    assert [result.error.code for result in results if result.error] == [
        "model_tool_response_truncated",
        "model_tool_response_truncated",
    ]
    assert all(result.executed is False for result in results)


def test_rejected_batch_is_corrected_without_tool_execution_and_kept_in_session_history() -> None:
    executed: list[int] = []

    def handler(args: EchoInput) -> EchoOutput:
        executed.append(args.value)
        return EchoOutput(value=args.value)

    model = ScriptedModelClient(
        [
            _provider_error(_batch()),
            _tool_turn("real-call", 4),
            ModelResponse.from_final("execution done"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(handler),
        limits=AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
    )
    collector = AgentTraceCollector(capture_full_calls=True)
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(request_id, "hello")
    events = []

    result = asyncio.run(
        runtime.run(
            messages,
            trace_collector=collector,
            execution_history=history,
            request_id=request_id,
            event_sink=events.append,
        )
    )

    assert result.content == "answer"
    assert executed == [4]
    assert len(model.requests) == 4
    retry_messages = model.requests[1].messages
    rejected_index = next(
        index for index, message in enumerate(retry_messages)
        if isinstance(message, RejectedAssistantMessage)
    )
    rejected = retry_messages[rejected_index]
    paired = retry_messages[rejected_index + 1]
    assert isinstance(rejected, RejectedAssistantMessage)
    assert rejected.tool_calls[0].raw_arguments == _batch().calls[0].raw_arguments
    assert isinstance(paired, ToolResultMessage)
    assert paired.tool_call_id == rejected.tool_calls[0].id
    assert paired.status == "error" and paired.executed is False
    assert [record.kind for record in history.records if record.kind == "assistant_rejected"] == [
        "assistant_rejected"
    ]
    assert [
        entry["correction_attempt"]
        for entry in collector.snapshot()["generation_recoveries"]
    ] == [0]
    assert collector.snapshot()["model_calls"][0]["status"] == "failed"
    assert "RAW_bad-call" not in json.dumps(collector.snapshot())
    assert sum(isinstance(event, ToolStarted) for event in events) == 1
    assert sum(isinstance(event, AgentFailed) for event in events) == 0
    assert sum(isinstance(event, AgentCompleted) for event in events) == 1


def test_exhaustion_answers_partially_only_after_current_request_evidence() -> None:
    model = ScriptedModelClient(
        [
            _tool_turn("evidence-call", 9),
            _provider_error(_batch(call_ids=("same-id",))),
            _provider_error(_batch(call_ids=("same-id",))),
            _provider_error(_batch(call_ids=("same-id",))),
            ModelResponse.from_final("partial answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
    )
    collector = AgentTraceCollector()

    result = asyncio.run(
        runtime.run(
            [UserMessage(content="hello")],
            trace_collector=collector,
        )
    )

    assert result.content == "partial answer"
    assert len(model.requests) == 5
    assert model.requests[-1].tools == []
    assert "evidence-call" in json.dumps(
        [message.model_dump(mode="json") for message in model.requests[-1].messages]
    )
    recovery = collector.snapshot()["generation_recoveries"]
    assert [entry["consecutive_rejections"] for entry in recovery] == [1, 2, 3]
    assert collector.snapshot()["answer_resolution"]["mode"] == "partial"


def test_successful_response_resets_consecutive_rejection_allowance() -> None:
    model = ScriptedModelClient(
        [
            _provider_error(_batch()),
            _tool_turn("first-success", 1),
            _provider_error(_batch()),
            _provider_error(_batch()),
            _tool_turn("second-success", 2),
            ModelResponse.from_final("execution done"),
            ModelResponse.from_final("answer"),
        ]
    )
    executed: list[int] = []
    runtime = AgentRuntime(
        model,
        _registry(lambda args: executed.append(args.value) or EchoOutput(value=args.value)),
        limits=AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
    )
    collector = AgentTraceCollector()

    assert asyncio.run(
        runtime.run([UserMessage(content="hello")], trace_collector=collector)
    ).content == "answer"

    assert executed == [1, 2]
    assert [
        entry["consecutive_rejections"]
        for entry in collector.snapshot()["generation_recoveries"]
    ] == [
        1,
        1,
        2,
    ]
    assert len(model.requests) == 7


def test_reused_call_id_keeps_later_successful_result_as_answer_evidence() -> None:
    model = ScriptedModelClient(
        [
            _provider_error(_batch(call_ids=("reused-id",))),
            _tool_turn("reused-id", 7),
            ModelResponse.from_final("execution done"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
    )

    assert asyncio.run(runtime.run([UserMessage(content="hello")])).content == "answer"

    answer_messages = model.requests[-1].messages
    matching_results = [
        message
        for message in answer_messages
        if isinstance(message, ToolResultMessage)
        and message.tool_call_id == "reused-id"
    ]
    assert [result.status for result in matching_results] == ["error", "ok"]
    assert _tool_evidence(answer_messages) == [{"tool": "echo", "content": {"value": 7}}]


def test_prior_turn_results_do_not_count_as_current_reliable_evidence() -> None:
    old_history = [
        AssistantMessage(
            tool_calls=[
                ToolCall(id="old-call", name="echo", arguments={"value": 3})
            ]
        ),
        ToolResultMessage(tool_call_id="old-call", content={"value": 3}),
        UserMessage(content="new question"),
    ]
    model = ScriptedModelClient(
        [_provider_error(_batch()), _provider_error(_batch()), _provider_error(_batch())]
    )
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
    )

    result = asyncio.run(runtime.run(old_history))

    assert len(model.requests) == 3
    assert "invalid or truncated tool-call batches" in result.content


def test_cancellation_after_rejection_prevents_correction_request() -> None:
    token = CancellationToken()

    class CancellingTraceCollector(AgentTraceCollector):
        def generation_recovery(self, **kwargs) -> None:
            super().generation_recovery(**kwargs)
            token.cancel()

    class OneRejectionModel:
        requests = []

        async def complete(self, request):
            self.requests.append(request)
            raise _provider_error(_batch())

    model = OneRejectionModel()
    collector = CancellingTraceCollector()
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(application_max_output_tokens=4096, deadline_seconds=2),
    )

    try:
        asyncio.run(
            runtime.run(
                [UserMessage(content="hello")],
                cancellation_token=token,
                trace_collector=collector,
            )
        )
    except AgentCancelledError:
        pass
    else:
        raise AssertionError("cancellation after rejection was not propagated")

    assert len(model.requests) == 1
    assert len(collector.snapshot()["generation_recoveries"]) == 1


def test_reliable_result_check_excludes_errors_control_results_and_receipts() -> None:
    assert _has_reliable_tool_results(
        [ToolCall(id="ok", name="echo", arguments={})],
        [ToolResultMessage(tool_call_id="ok", content={"value": 1})],
    )
    assert _has_reliable_tool_results(
        [ToolCall(id="read", name="artifact.read", arguments={})],
        [ToolResultMessage(tool_call_id="read", content={"value": 1})],
    )
    assert not _has_reliable_tool_results(
        [ToolCall(id="plan", name="task.plan", arguments={})],
        [ToolResultMessage(tool_call_id="plan", content={"planned": True})],
    )
    assert not _has_reliable_tool_results(
        [ToolCall(id="checkpoint", name="task.checkpoint", arguments={})],
        [ToolResultMessage(tool_call_id="checkpoint", content={"accepted": True})],
    )
    assert not _has_reliable_tool_results(
        [ToolCall(id="receipt", name="echo", arguments={})],
        [
            ToolResultMessage(
                tool_call_id="receipt",
                content={"_artifact_observation": {"state": "receipt_only"}},
            )
        ],
    )
    assert not _has_reliable_tool_results(
        [ToolCall(id="failed", name="echo", arguments={})],
        [
            ToolResultMessage(
                tool_call_id="failed",
                status="error",
                error=ToolError(code="tool_execution_error", message="failed"),
            )
        ],
    )
