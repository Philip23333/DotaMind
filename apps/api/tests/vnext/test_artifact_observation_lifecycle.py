from __future__ import annotations

import asyncio

from pydantic import BaseModel

from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import ArtifactObservationTranscriptRewriter, ArtifactReadResult
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools import ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


def _call(call_id: str, *, path: str = "rows", offset: int = 0, limit: int = 6) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="artifact.read",
        arguments={
            "ref": "artifact:test",
            "mode": "read",
            "path": path,
            "offset": offset,
            "limit": limit,
        },
    )


def _result(
    call_id: str,
    value: object,
    *,
    ref: str = "artifact:test",
    path: str | None = "rows",
    offset: int | None = 0,
    limit: int | None = 6,
) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        content=ArtifactReadResult(
            ref=ref,
            path=path,
            value=value,
            offset=offset,
            limit=limit,
            total=20 if isinstance(value, list) else None,
            truncated=isinstance(value, list),
        ).model_dump(mode="json"),
    )


def _checkpoint(
    call_id: str,
    source_tool_call_ids: list[str],
    *,
    checkpoint_id: str = "checkpoint:one",
    status: str = "ok",
    content: object | None = None,
) -> ToolResultMessage:
    if content is None:
        content = {
            "checkpoint_id": checkpoint_id,
            "key": "part",
            "accepted_source_tool_call_ids": source_tool_call_ids,
        }
    return ToolResultMessage(
        tool_call_id=call_id,
        content=content,
        status=status,  # type: ignore[arg-type]
        error=(
            {"code": "invalid_arguments", "message": "invalid", "details": {}}
            if status == "error"
            else None
        ),
    )


def _checkpoint_call(call_id: str = "checkpoint-call") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="task.checkpoint",
        arguments={
            "key": "part",
            "value": {"fact": "saved"},
            "source_tool_call_ids": ["old"],
        },
    )


def _rewrite(*pairs: tuple[ToolCall, ToolResultMessage]):
    messages = []
    for call, result in pairs:
        messages.extend(
            [AssistantMessage(content=None, tool_calls=[call]), result]
        )
    return ArtifactObservationTranscriptRewriter().rewrite(messages)


def test_exact_duplicate_keeps_newest_raw_and_is_idempotent() -> None:
    result = _rewrite(
        (_call("old"), _result("old", [1, 2])),
        (_call("new"), _result("new", [1, 2])),
    )

    assert result.messages[1].content["_artifact_observation"]["reason"] == "duplicate"  # type: ignore[index]
    assert result.messages[3].content["value"] == [1, 2]  # type: ignore[index]
    assert result.events[0].tool_call_id == "old"
    assert result.events[0].reason == "duplicate"
    assert result.events[0].metadata["raw_bytes"] > 0
    assert result.events[0].metadata["receipt_bytes"] > 0
    assert result.events[0].metadata["saved_bytes"] == max(
        0,
        result.events[0].metadata["raw_bytes"]
        - result.events[0].metadata["receipt_bytes"],
    )
    repeated = ArtifactObservationTranscriptRewriter().rewrite(result.messages)
    assert repeated.messages == result.messages
    assert repeated.events == []


def test_full_superset_replaces_multiple_older_reads_using_actual_range() -> None:
    values = list(range(20))
    result = _rewrite(
        (_call("one", offset=0, limit=40), _result("one", values[:3], limit=40)),
        (_call("two", offset=3, limit=40), _result("two", values[3:6], offset=3, limit=40)),
        (_call("three", offset=0, limit=40), _result("three", values[:6], limit=40)),
    )

    reasons = [
        message.content["_artifact_observation"]["reason"]  # type: ignore[index]
        for message in result.messages[1:4:2]
    ]
    assert reasons == [
        "superseded",
        "superseded",
    ]
    assert result.messages[5].content["value"] == values[:6]  # type: ignore[index]


def test_partial_overlap_subset_disjoint_and_changed_payload_stay_raw() -> None:
    cases = [
        (_result("old", [0, 1], offset=0), _result("new", [1, 2], offset=1)),
        (_result("old", [0, 1, 2], offset=0), _result("new", [1], offset=1)),
        (_result("old", [0, 1], offset=0), _result("new", [2, 3], offset=2)),
        (_result("old", [0, 1], offset=0), _result("new", [9, 9], offset=0)),
    ]
    for old_result, new_result in cases:
        old_call = _call("old", offset=old_result.content["offset"])  # type: ignore[index]
        new_call = _call("new", offset=new_result.content["offset"])  # type: ignore[index]
        rewritten = _rewrite((old_call, old_result), (new_call, new_result))
        assert rewritten.events == []
        assert rewritten.messages[1] == old_result
        assert rewritten.messages[3] == new_result


def test_different_ref_path_failed_and_non_artifact_results_are_untouched() -> None:
    old = _result("old", [1, 2])
    new_ref = _result("new", [1, 2], ref="artifact:other")
    new_path = _result("new-path", [1, 2], path="other")
    failed = ToolResultMessage(
        tool_call_id="failed",
        status="error",
        error={"code": "invalid_arguments", "message": "x", "details": {}},
    )
    non_artifact = ToolResultMessage(tool_call_id="echo", content={"value": 1})
    messages = [
        AssistantMessage(tool_calls=[_call("old")]), old,
        AssistantMessage(tool_calls=[_call("new")]), new_ref,
        AssistantMessage(tool_calls=[_call("new-path", path="other")]), new_path,
        AssistantMessage(tool_calls=[_call("failed")]), failed,
        AssistantMessage(tool_calls=[ToolCall(id="echo", name="echo")]), non_artifact,
    ]
    rewritten = ArtifactObservationTranscriptRewriter().rewrite(messages)
    assert rewritten.events == []
    assert rewritten.messages == messages


def test_outline_receipt_is_rereadable_without_raw_value() -> None:
    result = _rewrite(
        (
            ToolCall(id="old", name="artifact.read"),
            _result(
                "old",
                {"paths": [{"path": "rows", "kind": "collection"}]},
                path=None,
                offset=None,
                limit=None,
            ),
        ),
        (
            ToolCall(id="new", name="artifact.read"),
            _result(
                "new",
                {"paths": [{"path": "rows", "kind": "collection"}]},
                path=None,
                offset=None,
                limit=None,
            ),
        ),
    )
    receipt = result.messages[1].content["_artifact_observation"]  # type: ignore[index]
    assert receipt == {
        "state": "receipt_only",
        "reason": "duplicate",
        "re_readable": True,
        "mode": "outline",
        "ref": "artifact:test",
    }


def test_parallel_same_turn_duplicate_replaces_earlier_result_only() -> None:
    calls = [_call("old"), _call("new")]
    messages = [
        AssistantMessage(tool_calls=calls),
        _result("old", [1, 2]),
        _result("new", [1, 2]),
    ]

    result = ArtifactObservationTranscriptRewriter().rewrite(messages)

    assert result.messages[1].content["_artifact_observation"]["reason"] == "duplicate"  # type: ignore[index]
    assert result.messages[2].content["value"] == [1, 2]  # type: ignore[index]


def test_reread_creates_a_new_raw_observation_after_an_old_receipt() -> None:
    first = _rewrite(
        (_call("one"), _result("one", [1, 2])),
        (_call("two"), _result("two", [1, 2])),
    )
    messages = [
        *first.messages,
        AssistantMessage(tool_calls=[_call("three")]),
        _result("three", [1, 2]),
    ]

    result = ArtifactObservationTranscriptRewriter().rewrite(messages)

    receipts = [message for message in result.messages if isinstance(message, ToolResultMessage)]
    assert "_artifact_observation" in receipts[0].content
    assert "_artifact_observation" in receipts[1].content
    assert receipts[2].content["value"] == [1, 2]  # type: ignore[index]


def test_checkpoint_claim_replaces_only_claimed_raw_with_checkpoint_receipt() -> None:
    messages = [
        AssistantMessage(tool_calls=[_call("old"), _call("other")]),
        _result("old", [1, 2]),
        _result("other", [3, 4], path="other"),
        AssistantMessage(tool_calls=[_checkpoint_call()]),
        _checkpoint("checkpoint-call", ["old"], checkpoint_id="checkpoint:one"),
    ]

    result = ArtifactObservationTranscriptRewriter().rewrite(messages)

    old = result.messages[1]
    other = result.messages[2]
    assert old.content == {  # type: ignore[union-attr]
        "_artifact_observation": {
            "state": "receipt_only",
            "reason": "checkpointed",
            "re_readable": True,
            "mode": "read",
            "ref": "artifact:test",
            "path": "rows",
            "offset": 0,
            "limit": 6,
            "checkpoint_id": "checkpoint:one",
        }
    }
    assert other.content["value"] == [3, 4]  # type: ignore[index]
    assert result.events[0].reason == "checkpointed"
    assert result.events[0].metadata["checkpoint_id"] == "checkpoint:one"


def test_checkpoint_claim_has_priority_over_redundancy_and_does_not_release_older_raw() -> None:
    messages = [
        AssistantMessage(tool_calls=[_call("old"), _call("new")]),
        _result("old", [1, 2]),
        _result("new", [1, 2]),
        AssistantMessage(tool_calls=[_checkpoint_call()]),
        _checkpoint("checkpoint-call", ["new"]),
    ]

    result = ArtifactObservationTranscriptRewriter().rewrite(messages)

    assert result.messages[1].content["value"] == [1, 2]  # type: ignore[index]
    assert result.messages[2].content["_artifact_observation"]["reason"] == "checkpointed"  # type: ignore[index]
    assert [event.reason for event in result.events] == ["checkpointed"]


def test_malformed_or_failed_checkpoint_does_not_claim_observations() -> None:
    for checkpoint_result in (
        _checkpoint("checkpoint-call", ["old"], status="error"),
        _checkpoint(
            "checkpoint-call",
            ["old"],
            content={"checkpoint_id": "", "accepted_source_tool_call_ids": ["old"]},
        ),
        _checkpoint(
            "checkpoint-call",
            ["old"],
            content={"checkpoint_id": "checkpoint:one", "accepted_source_tool_call_ids": "old"},
        ),
    ):
        messages = [
            AssistantMessage(tool_calls=[_call("old")]),
            _result("old", [1, 2]),
            AssistantMessage(tool_calls=[_checkpoint_call()]),
            checkpoint_result,
        ]
        result = ArtifactObservationTranscriptRewriter().rewrite(messages)
        assert result.events == []
        assert result.messages[1] == messages[1]


def test_checkpoint_rewrite_is_idempotent_and_receipt_does_not_claim_again() -> None:
    messages = [
        AssistantMessage(tool_calls=[_call("old")]),
        _result("old", [1, 2]),
        AssistantMessage(tool_calls=[_checkpoint_call()]),
        _checkpoint("checkpoint-call", ["old"]),
    ]
    first = ArtifactObservationTranscriptRewriter().rewrite(messages)
    second = ArtifactObservationTranscriptRewriter().rewrite(first.messages)
    assert second.messages == first.messages
    assert second.events == []


def test_checkpoint_receipt_preserves_locator_requested_range_and_is_rereadable() -> None:
    messages = [
        AssistantMessage(tool_calls=[_call("old", offset=4, limit=9)]),
        _result("old", [4, 5], offset=4, limit=9),
        AssistantMessage(tool_calls=[_checkpoint_call()]),
        _checkpoint("checkpoint-call", ["old"]),
    ]
    result = ArtifactObservationTranscriptRewriter().rewrite(messages)
    marker = result.messages[1].content["_artifact_observation"]  # type: ignore[index]
    assert marker["ref"] == "artifact:test"
    assert marker["path"] == "rows"
    assert marker["offset"] == 4
    assert marker["limit"] == 9
    assert marker["re_readable"] is True


def test_closed_partition_replaces_unclaimed_reads_and_keeps_newer_partition_raw() -> None:
    messages = [
        AssistantMessage(tool_calls=[_call("old"), _call("new")]),
        _result("old", [1, 2]),
        _result("new", [3, 4], offset=2),
    ]
    result = ArtifactObservationTranscriptRewriter(
        closed_partition_lookup=lambda tool_call_id: "2025" if tool_call_id == "old" else None
    ).rewrite(messages)

    marker = result.messages[1].content["_artifact_observation"]  # type: ignore[index]
    assert marker == {
        "state": "receipt_only",
        "reason": "partition_closed",
        "re_readable": True,
        "mode": "read",
        "ref": "artifact:test",
        "path": "rows",
        "offset": 0,
        "limit": 6,
        "partition_key": "2025",
    }
    assert result.messages[2].content["value"] == [3, 4]  # type: ignore[index]
    assert result.events[0].reason == "partition_closed"


def test_closed_partition_has_precedence_over_duplicate_rewrite() -> None:
    result = ArtifactObservationTranscriptRewriter(
        closed_partition_lookup=lambda tool_call_id: "2025" if tool_call_id == "old" else None
    ).rewrite(
        [
            AssistantMessage(tool_calls=[_call("old"), _call("new")]),
            _result("old", [1, 2]),
            _result("new", [1, 2]),
        ]
    )

    assert result.messages[1].content["_artifact_observation"]["reason"] == "partition_closed"  # type: ignore[index]
    assert result.messages[2].content["value"] == [1, 2]  # type: ignore[index]


def test_rewrite_event_reports_positive_savings_for_large_raw_observation() -> None:
    result = _rewrite(
        (_call("old"), _result("old", [{"evidence": "x" * 2000}])),
        (_call("new"), _result("new", [{"evidence": "x" * 2000}])),
    )

    event = result.events[0]
    assert event.metadata["raw_bytes"] > event.metadata["receipt_bytes"]
    assert event.metadata["saved_bytes"] > 0


class ReadInput(BaseModel):
    ref: str
    mode: str
    path: str
    offset: int
    limit: int


def test_runtime_rewrites_previous_result_but_trace_keeps_raw_result() -> None:
    rows = list(range(100))

    def read(args: ReadInput) -> ArtifactReadResult:
        return ArtifactReadResult(
            ref=args.ref,
            path=args.path,
            value=rows[args.offset : args.offset + args.limit],
            offset=args.offset,
            limit=args.limit,
            total=len(rows),
            truncated=args.offset + args.limit < len(rows),
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="artifact.read",
            description="read",
            input_model=ReadInput,
            output_model=ArtifactReadResult,
            handler=read,
            parallel_safe=True,
            externalize_result=False,
        )
    )
    model = ScriptedModelClient(
        [
            ModelResponse(message=AssistantMessage(tool_calls=[_call("one", limit=100)])),
            ModelResponse(message=AssistantMessage(tool_calls=[_call("two", limit=100)])),
            ModelResponse(message=FinalMessage(content="done")),
        ]
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        registry,
        transcript_rewriter=ArtifactObservationTranscriptRewriter(),
    )

    asyncio.run(runtime.run([UserMessage(content="read")], trace_collector=trace))

    second_request = model.requests[1]
    assert second_request.messages[-1].content["value"] == rows  # type: ignore[index]
    third_request = model.requests[2]
    tool_results = [
        message for message in third_request.messages if isinstance(message, ToolResultMessage)
    ]
    first_result = tool_results[0]
    second_result = tool_results[1]
    assert "_artifact_observation" in first_result.content
    assert second_result.content["value"] == rows  # type: ignore[index]
    step = trace.snapshot()["steps"][1]
    assert step["transcript_rewrites"][0]["reason"] == "duplicate"
    assert trace.snapshot()["steps"][0]["tool_results"][0]["result"]["content"]["value"] == rows
    assert len(str(first_result.content)) < len(str(second_result.content))
