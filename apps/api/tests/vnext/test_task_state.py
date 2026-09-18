from __future__ import annotations

import pytest

from app.vnext.agent.task_state import (
    TaskCheckpoint,
    TaskStateCoordinator,
    TaskStateStore,
)
from app.vnext.artifacts.lifecycle import collect_active_artifact_observations
from app.vnext.artifacts.retrieval import ArtifactReadResult
from app.vnext.llm.protocol import AssistantMessage, ToolCall, ToolResultMessage


def _read_call(call_id: str = "call-1", *, path: str = "rows") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="artifact.read",
        arguments={"ref": "artifact:test", "mode": "read", "path": path},
    )


def _read_result(
    call_id: str = "call-1",
    *,
    value: object = [{"fact": "秘密"}],
    path: str | None = "rows",
    offset: int | None = 0,
    limit: int | None = 4,
    status: str = "ok",
) -> ToolResultMessage:
    content = (
        ArtifactReadResult(
            ref="artifact:test",
            path=path,
            value=value,
            offset=offset,
            limit=limit,
        ).model_dump(mode="json")
        if status == "ok"
        else None
    )
    return ToolResultMessage(
        tool_call_id=call_id,
        content=content,
        status=status,  # type: ignore[arg-type]
        error=(
            {"code": "artifact_not_found", "message": "not found", "details": {}}
            if status == "error"
            else None
        ),
    )


def _messages(*pairs: tuple[ToolCall, ToolResultMessage]):
    messages = []
    for call, result in pairs:
        messages.extend([AssistantMessage(tool_calls=[call]), result])
    return messages


def test_store_put_get_and_deterministic_snapshot() -> None:
    store = TaskStateStore()
    second = TaskCheckpoint("checkpoint:2", "b", {"value": 2}, ("call-2",))
    first = TaskCheckpoint("checkpoint:1", "a", {"value": 1}, ("call-1",))

    store.put(second)
    store.put(first)

    assert store.get("a") == first
    assert [item.key for item in store.list()] == ["a", "b"]
    assert list(store.snapshot()) == ["a", "b"]
    snapshot = store.snapshot()
    snapshot.pop("a")
    assert store.get("a") == first


def test_store_same_key_is_whole_value_replacement() -> None:
    store = TaskStateStore()
    first = TaskCheckpoint("checkpoint:1", "part", {"old": 1}, ("call-1",))
    second = TaskCheckpoint("checkpoint:2", "part", {"new": 2}, ("call-2",))

    store.put(first)
    store.put(second)

    assert store.get("part") == second
    assert store.list() == [second]


def test_active_manifest_excludes_receipts_failed_reads_and_non_artifact_results() -> None:
    raw_call = _read_call("raw")
    receipt_call = _read_call("receipt")
    failed_call = _read_call("failed")
    non_artifact_call = ToolCall(id="echo", name="echo")
    messages = [
        *_messages((raw_call, _read_result("raw"))),
        AssistantMessage(tool_calls=[receipt_call]),
        ToolResultMessage(
            tool_call_id="receipt",
            content={"_artifact_observation": {"state": "receipt_only"}},
        ),
        AssistantMessage(tool_calls=[failed_call]),
        _read_result("failed", status="error"),
        AssistantMessage(tool_calls=[non_artifact_call]),
        ToolResultMessage(tool_call_id="echo", content={"value": 1}),
        ToolResultMessage(tool_call_id="invalid", content={"ref": "missing"}),
    ]

    observations = collect_active_artifact_observations(messages)

    assert [observation.tool_call_id for observation in observations] == ["raw"]


def test_checkpoint_validation_is_atomic_and_requires_active_raw_sources() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(_messages((_read_call(), _read_result())))
    accepted = coordinator.create_checkpoint("part", {"fact": "A"}, ["call-1"])

    with pytest.raises(ValueError, match="active raw"):
        coordinator.create_checkpoint("part", {"fact": "B"}, ["missing"])

    assert coordinator.store.get("part") == accepted


def test_checkpoint_claims_sources_once_and_refresh_excludes_them() -> None:
    coordinator = TaskStateCoordinator()
    messages = _messages(
        (_read_call("call-1"), _read_result("call-1")),
        (_read_call("call-2"), _read_result("call-2")),
    )
    coordinator.refresh(messages)
    coordinator.create_checkpoint("part", {"fact": "A"}, ["call-1"])

    with pytest.raises(ValueError, match="already been claimed"):
        coordinator.create_checkpoint("part-2", {"fact": "A"}, ["call-1"])

    coordinator.refresh(messages)
    context = coordinator.render_context()
    assert context is not None
    assert '"tool_call_id":"call-1"' not in context
    assert '"tool_call_id":"call-2"' in context


def test_checkpoint_can_claim_multiple_sources_atomically() -> None:
    coordinator = TaskStateCoordinator()
    messages = _messages(
        (_read_call("call-1"), _read_result("call-1")),
        (_read_call("call-2"), _read_result("call-2")),
    )
    coordinator.refresh(messages)
    checkpoint = coordinator.create_checkpoint(
        "part", {"fact": "A"}, ["call-1", "call-2"]
    )
    coordinator.refresh(messages)

    assert checkpoint.source_tool_call_ids == ("call-1", "call-2")
    assert '"tool_call_id"' not in (coordinator.render_context() or "")


@pytest.mark.parametrize(
    "sources",
    [([], "empty"), (["call-1", "call-1"], "duplicates"), (["receipt"], "active raw")],
)
def test_checkpoint_rejects_invalid_source_lists(
    sources: tuple[list[str], str],
) -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(_messages((_read_call(), _read_result())))

    with pytest.raises(ValueError, match=sources[1]):
        coordinator.create_checkpoint("part", {"fact": "A"}, sources[0])

    assert coordinator.store.snapshot() == {}


def test_rendered_context_has_latest_state_and_locator_only_manifest() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(
        _messages(
            (
                _read_call(),
                _read_result(value=[{"fact": "秘密"}, {"fact": "第二条"}]),
            ),
            (_read_call("call-2"), _read_result("call-2", value=[{"fact": "第三条"}])),
        )
    )
    coordinator.create_checkpoint("part", {"事实": "已保存"}, ["call-1"])

    context = coordinator.render_context()

    assert context is not None
    assert '"part":{"事实":"已保存"}' in context
    assert '"tool_call_id":"call-2"' in context
    assert '"tool_call_id":"call-1"' not in context
    assert '"ref":"artifact:test"' in context
    assert '"path":"rows"' in context
    assert '"actual_start":0' in context
    assert '"actual_end":1' in context
    assert "秘密" not in context
    assert '"value"' not in context
    assert coordinator.render_context() == context


def test_rendered_context_uses_utf8_json_and_omits_ranges_for_scalar_reads() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.refresh(
        _messages(
            (
                _read_call(path="summary"),
                _read_result(path="summary", value={"标题": "最近赛事"}, offset=None, limit=None),
            )
        )
    )

    context = coordinator.render_context()

    assert context is not None
    assert "最近赛事" not in context
    assert "actual_start" not in context
    assert "actual_end" not in context
    assert "\\u6700" not in context


def test_evidence_lease_is_scoped_to_current_partition_and_released_on_checkpoint() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "2025", "objective": "retrieve 2025"},
            {"key": "2026", "objective": "retrieve 2026"},
        ]
    )
    messages = _messages((_read_call("call-1"), _read_result()))
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("call-1", task_key=None, raw_bytes=1234)

    assert coordinator.active_evidence_lease() == {
        "task_key": "2025",
        "observation_count": 1,
        "raw_bytes": 1234,
    }
    assert coordinator.context_payload()["active_manifest"][0]["lease_key"] == "2025"

    coordinator.create_checkpoint("2025", {"fact": "saved"}, ["call-1"])
    release = coordinator.consume_partition_release()
    assert release is not None
    assert release.task_key == "2025"
    assert release.checkpointed_count == 1
    assert release.partition_closed_count == 0
    assert release.released_bytes == 1234
    assert coordinator.active_evidence_lease() is None
    assert coordinator.closed_partition_for_tool_call("call-1") == "2025"


def test_failed_checkpoint_keeps_active_evidence_lease() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "2025", "objective": "retrieve 2025"},
            {"key": "2026", "objective": "retrieve 2026"},
        ]
    )
    coordinator.refresh(_messages((_read_call("call-1"), _read_result())))
    coordinator.record_evidence_lease("call-1", task_key=None, raw_bytes=321)

    with pytest.raises(ValueError, match="active raw"):
        coordinator.create_checkpoint("2025", {"fact": "saved"}, ["missing"])

    assert coordinator.active_evidence_lease() == {
        "task_key": "2025",
        "observation_count": 1,
        "raw_bytes": 321,
    }
    assert coordinator.consume_partition_release() is None


def test_explicit_future_task_key_owns_lease_instead_of_current_item() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    coordinator.record_evidence_lease("future", task_key="B", raw_bytes=456)

    assert coordinator.active_evidence_lease() == {
        "task_key": "B",
        "observation_count": 1,
        "raw_bytes": 456,
    }


def test_checkpoint_candidates_filter_to_current_task_active_raw_sources() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages(
        (_read_call("raw-a"), _read_result("raw-a")),
        (_read_call("raw-b"), _read_result("raw-b")),
        (
            _read_call("receipt"),
            ToolResultMessage(
                tool_call_id="receipt",
                content={"_artifact_observation": {"state": "receipt_only"}},
            ),
        ),
    )
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    coordinator.record_evidence_lease("raw-b", task_key="B", raw_bytes=200)

    assert coordinator.context_payload()["checkpoint_candidates"] == [
        {
            "tool_call_id": "raw-a",
            "task_key": "A",
            "status": "ACTIVE_RAW",
            "bytes": 100,
        }
    ]
    rendered = coordinator.render_context()
    assert rendered is not None
    candidates = rendered.split("Checkpoint candidates:\n", 1)[1]
    assert '"tool_call_id":"raw-a"' in candidates
    assert '"status":"ACTIVE_RAW"' in candidates
    assert '"tool_call_id":"raw-b"' not in candidates


def test_checkpoint_candidates_disappear_after_checkpoint_claim() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages((_read_call("raw-a"), _read_result("raw-a")))
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    candidates = coordinator.context_payload()["checkpoint_candidates"]
    assert [item["tool_call_id"] for item in candidates] == ["raw-a"]

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    coordinator.refresh(messages)

    assert coordinator.context_payload()["checkpoint_candidates"] == []


def test_checkpoint_candidates_follow_current_partition_after_batched_reads() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
            {"key": "C", "objective": "retrieve C"},
        ]
    )
    messages = _messages(
        (_read_call("raw-a"), _read_result("raw-a")),
        (_read_call("raw-b"), _read_result("raw-b")),
        (_read_call("raw-c"), _read_result("raw-c")),
    )
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    coordinator.record_evidence_lease("raw-b", task_key="B", raw_bytes=200)
    coordinator.record_evidence_lease("raw-c", task_key="C", raw_bytes=300)

    candidates = coordinator.context_payload()["checkpoint_candidates"]
    assert [item["tool_call_id"] for item in candidates] == ["raw-a"]

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    coordinator.refresh(messages)

    candidates = coordinator.context_payload()["checkpoint_candidates"]
    assert [item["tool_call_id"] for item in candidates] == ["raw-b"]


def test_unknown_and_completed_task_keys_are_rejected_without_creating_leases() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )

    with pytest.raises(ValueError, match="not in the active task plan"):
        coordinator.record_evidence_lease("unknown", task_key="missing", raw_bytes=1)
    assert coordinator.active_evidence_lease() is None

    coordinator.refresh(_messages((_read_call("raw-a"), _read_result("raw-a"))))
    coordinator.create_checkpoint("A", {"fact": "saved"}, ["raw-a"])

    with pytest.raises(ValueError, match="already completed"):
        coordinator.record_evidence_lease("completed", task_key="A", raw_bytes=1)
    assert coordinator.active_evidence_lease() is None


def test_cross_partition_leases_survive_an_earlier_checkpoint() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages(
        (_read_call("raw-a"), _read_result("raw-a")),
        (_read_call("raw-b"), _read_result("raw-b", value=[{"fact": "B"}])),
    )
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    coordinator.record_evidence_lease("raw-b", task_key="B", raw_bytes=200)

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    assert coordinator.closed_partition_for_tool_call("raw-a") == "A"
    assert coordinator.closed_partition_for_tool_call("raw-b") is None
    assert coordinator.active_evidence_lease() == {
        "task_key": "B",
        "observation_count": 1,
        "raw_bytes": 200,
    }
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]

    coordinator.refresh(messages)
    coordinator.create_checkpoint("B", {"fact": "B"}, ["raw-b"])
    assert coordinator.closed_partition_for_tool_call("raw-b") == "B"


def test_checkpoint_accepts_source_lease_owned_by_checkpoint_item() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    coordinator.refresh(_messages((_read_call("raw-a"), _read_result("raw-a"))))
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])

    assert coordinator.store.get("A") is not None
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]


def test_checkpoint_rejects_source_leased_to_different_task_item_atomically() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages(
        (_read_call("raw-a"), _read_result("raw-a")),
        (_read_call("raw-b"), _read_result("raw-b")),
    )
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    coordinator.record_evidence_lease("raw-b", task_key="B", raw_bytes=200)

    with pytest.raises(ValueError, match="different task items: raw-b"):
        coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-b"])

    assert coordinator.plan_snapshot().current_key == "A"  # type: ignore[union-attr]
    assert coordinator.store.snapshot() == {}
    assert {item["tool_call_id"] for item in coordinator.context_payload()["active_manifest"]} == {
        "raw-a",
        "raw-b",
    }
    assert coordinator.closed_partition_for_tool_call("raw-b") is None
    assert coordinator.consume_partition_release() is None
    assert coordinator.active_evidence_lease()["task_key"] is None  # type: ignore[index]


def test_mixed_checkpoint_sources_reject_atomically_when_one_lease_mismatches() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages(
        (_read_call("raw-a"), _read_result("raw-a")),
        (_read_call("raw-b"), _read_result("raw-b")),
    )
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    coordinator.record_evidence_lease("raw-b", task_key="B", raw_bytes=200)

    with pytest.raises(ValueError, match="different task items: raw-b"):
        coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a", "raw-b"])

    assert coordinator.plan_snapshot().current_key == "A"  # type: ignore[union-attr]
    assert coordinator.store.snapshot() == {}
    assert coordinator.closed_partition_for_tool_call("raw-a") is None
    assert coordinator.closed_partition_for_tool_call("raw-b") is None
    assert coordinator.consume_partition_release() is None


def test_rejected_lease_owner_checkpoint_can_retry_a_then_b() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages(
        (_read_call("raw-a"), _read_result("raw-a")),
        (_read_call("raw-b"), _read_result("raw-b")),
    )
    coordinator.refresh(messages)
    coordinator.record_evidence_lease("raw-a", task_key="A", raw_bytes=100)
    coordinator.record_evidence_lease("raw-b", task_key="B", raw_bytes=200)

    with pytest.raises(ValueError, match="different task items: raw-b"):
        coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-b"])

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]
    assert coordinator.consume_partition_release() is not None

    coordinator.refresh(messages)
    coordinator.create_checkpoint("B", {"fact": "B"}, ["raw-b"])
    assert coordinator.plan_snapshot().current_key is None  # type: ignore[union-attr]
    assert coordinator.closed_partition_for_tool_call("raw-b") == "B"
