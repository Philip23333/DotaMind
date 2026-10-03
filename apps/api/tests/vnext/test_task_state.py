from __future__ import annotations

import pytest

from app.vnext.agent.task_state import (
    TaskCheckpoint,
    TaskItem,
    TaskItemStatus,
    TaskPlan,
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


def _record_read_owner(
    coordinator: TaskStateCoordinator,
    call_id: str,
    *,
    task_key: str | None,
) -> None:
    owner = coordinator.resolve_source_task_key(
        task_key,
        plan=coordinator.plan_snapshot(),
    )
    coordinator.record_tool_result(
        _read_call(call_id),
        _read_result(call_id),
        task_key=owner,
    )


def _inline_call(call_id: str = "inline-1", *, name: str = "esports.match.search") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


def _inline_result(
    call_id: str = "inline-1",
    *,
    content: object = {"items": [{"match_id": 1}]},
    status: str = "ok",
) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        content=content,
        status=status,  # type: ignore[arg-type]
        error=(
            {"code": "tool_execution_error", "message": "failed", "details": {}}
            if status == "error"
            else None
        ),
    )


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

    with pytest.raises(ValueError, match="active checkpointable"):
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
    [([], "empty"), (["call-1", "call-1"], "duplicates"), (["receipt"], "active checkpointable")],
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


def test_refresh_drops_owners_for_observations_outside_effective_history() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "first", "objective": "First"},
            {"key": "second", "objective": "Second"},
        ]
    )
    messages = _messages(
        (_read_call("call-1"), _read_result("call-1")),
        (_read_call("call-2"), _read_result("call-2")),
    )
    _record_read_owner(coordinator, "call-1", task_key=None)
    _record_read_owner(coordinator, "call-2", task_key=None)
    coordinator.refresh(messages)
    before_plan = coordinator.plan_snapshot()

    coordinator.refresh(_messages((_read_call("call-2"), _read_result("call-2"))))

    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "call-2", "tool_name": "artifact.read", "task_key": "first"}
    ]
    assert coordinator.plan_snapshot() == before_plan
    coordinator.refresh([])
    assert coordinator.source_owners_snapshot() == []


def test_source_owner_is_scoped_to_current_partition_and_consumed_by_checkpoint() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "2025", "objective": "retrieve 2025"},
            {"key": "2026", "objective": "retrieve 2026"},
        ]
    )
    messages = _messages((_read_call("call-1"), _read_result()))
    coordinator.refresh(messages)
    _record_read_owner(coordinator, "call-1", task_key=None)
    coordinator.refresh(messages)

    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "call-1", "tool_name": "artifact.read", "task_key": "2025"}
    ]
    assert coordinator.context_payload()["active_manifest"][0]["task_key"] == "2025"

    coordinator.create_checkpoint("2025", {"fact": "saved"}, ["call-1"])
    assert coordinator.plan_snapshot().current_key == "2026"  # type: ignore[union-attr]
    assert coordinator.source_owners_snapshot() == []


def test_failed_checkpoint_keeps_source_owner() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "2025", "objective": "retrieve 2025"},
            {"key": "2026", "objective": "retrieve 2026"},
        ]
    )
    coordinator.refresh(_messages((_read_call("call-1"), _read_result())))
    _record_read_owner(coordinator, "call-1", task_key=None)
    coordinator.refresh(_messages((_read_call("call-1"), _read_result())))

    with pytest.raises(ValueError, match="active checkpointable"):
        coordinator.create_checkpoint("2025", {"fact": "saved"}, ["missing"])

    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "call-1", "tool_name": "artifact.read", "task_key": "2025"}
    ]


def test_explicit_future_task_key_owns_source_instead_of_current_item() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    _record_read_owner(coordinator, "future", task_key="B")

    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "future", "tool_name": "artifact.read", "task_key": "B"}
    ]


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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    _record_read_owner(coordinator, "raw-b", task_key="B")
    coordinator.refresh(messages)

    assert coordinator.context_payload()["checkpoint_candidates"] == [
        {
            "tool_call_id": "raw-a",
            "tool_name": "artifact.read",
            "source_kind": "artifact_read",
            "task_key": "A",
            "status": "ACTIVE_RAW",
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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    coordinator.refresh(messages)
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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    _record_read_owner(coordinator, "raw-b", task_key="B")
    _record_read_owner(coordinator, "raw-c", task_key="C")
    coordinator.refresh(messages)

    candidates = coordinator.context_payload()["checkpoint_candidates"]
    assert [item["tool_call_id"] for item in candidates] == ["raw-a"]

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    coordinator.refresh(messages)

    candidates = coordinator.context_payload()["checkpoint_candidates"]
    assert [item["tool_call_id"] for item in candidates] == ["raw-b"]


def test_resolve_source_owner_uses_the_plan_snapshot_and_allows_completed_items() -> None:
    coordinator = TaskStateCoordinator()
    plan = coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )

    with pytest.raises(ValueError, match="not in the active task plan"):
        coordinator.resolve_source_task_key("missing", plan=plan)
    assert coordinator.resolve_source_task_key(None, plan=plan) == "A"
    assert coordinator.resolve_source_task_key("B", plan=plan) == "B"

    advanced_plan = TaskPlan(
        items=(
            TaskItem("A", "completed", TaskItemStatus.COMPLETED),
            TaskItem("B", "current", TaskItemStatus.IN_PROGRESS),
        ),
        current_key="B",
    )
    assert coordinator.resolve_source_task_key("A", plan=advanced_plan) == "A"
    assert coordinator.resolve_source_task_key(None, plan=advanced_plan) == "B"

    completed_plan = TaskPlan(
        items=(
            TaskItem("A", "completed", TaskItemStatus.COMPLETED),
            TaskItem("B", "completed", TaskItemStatus.COMPLETED),
        ),
        current_key=None,
    )
    assert coordinator.resolve_source_task_key(None, plan=completed_plan) is None
    assert coordinator.resolve_source_task_key("A", plan=completed_plan) == "A"
    assert coordinator.resolve_source_task_key("A", plan=None) is None


def test_checkpoint_consumes_only_selected_source_and_preserves_other_owner() -> None:
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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    _record_read_owner(coordinator, "raw-b", task_key="B")
    coordinator.refresh(messages)

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "raw-b", "tool_name": "artifact.read", "task_key": "B"}
    ]
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]

    coordinator.refresh(messages)
    coordinator.create_checkpoint("B", {"fact": "B"}, ["raw-b"])
    assert coordinator.plan_snapshot().current_key is None  # type: ignore[union-attr]
    assert coordinator.source_owners_snapshot() == []


def test_checkpoint_accepts_source_owned_by_checkpoint_item() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "retrieve A"},
            {"key": "B", "objective": "retrieve B"},
        ]
    )
    messages = _messages((_read_call("raw-a"), _read_result("raw-a")))
    _record_read_owner(coordinator, "raw-a", task_key="A")
    coordinator.refresh(messages)

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])

    assert coordinator.store.get("A") is not None
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]


def test_checkpoint_rejects_source_owned_by_different_task_item_atomically() -> None:
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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    _record_read_owner(coordinator, "raw-b", task_key="B")
    coordinator.refresh(messages)

    with pytest.raises(ValueError, match="belong to different task items: raw-b"):
        coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-b"])

    assert coordinator.plan_snapshot().current_key == "A"  # type: ignore[union-attr]
    assert coordinator.store.snapshot() == {}
    assert {item["tool_call_id"] for item in coordinator.context_payload()["active_manifest"]} == {
        "raw-a",
        "raw-b",
    }
    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "raw-a", "tool_name": "artifact.read", "task_key": "A"},
        {"tool_call_id": "raw-b", "tool_name": "artifact.read", "task_key": "B"},
    ]


def test_mixed_checkpoint_sources_reject_atomically_when_one_owner_mismatches() -> None:
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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    _record_read_owner(coordinator, "raw-b", task_key="B")
    coordinator.refresh(messages)

    with pytest.raises(ValueError, match="belong to different task items: raw-b"):
        coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a", "raw-b"])

    assert coordinator.plan_snapshot().current_key == "A"  # type: ignore[union-attr]
    assert coordinator.store.snapshot() == {}
    assert len(coordinator.source_owners_snapshot()) == 2


def test_rejected_owner_checkpoint_can_retry_a_then_b() -> None:
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
    _record_read_owner(coordinator, "raw-a", task_key="A")
    _record_read_owner(coordinator, "raw-b", task_key="B")
    coordinator.refresh(messages)

    with pytest.raises(ValueError, match="belong to different task items: raw-b"):
        coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-b"])

    coordinator.create_checkpoint("A", {"fact": "A"}, ["raw-a"])
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]
    assert coordinator.source_owners_snapshot() == [
        {"tool_call_id": "raw-b", "tool_name": "artifact.read", "task_key": "B"}
    ]

    coordinator.refresh(messages)
    coordinator.create_checkpoint("B", {"fact": "B"}, ["raw-b"])
    assert coordinator.plan_snapshot().current_key is None  # type: ignore[union-attr]
    assert coordinator.source_owners_snapshot() == []


def test_inline_source_is_a_checkpoint_candidate_without_copying_its_body() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "collect A"},
            {"key": "B", "objective": "collect B"},
        ]
    )
    call = _inline_call()
    result = _inline_result(content={"items": [{"match_id": 1, "title": "synthetic"}]})
    coordinator.record_tool_result(call, result, task_key="A")
    messages = [AssistantMessage(tool_calls=[call]), result]
    coordinator.refresh(messages)

    assert coordinator.context_payload()["active_manifest"] == [
        {
            "tool_call_id": "inline-1",
            "tool_name": "esports.match.search",
            "source_kind": "inline_tool_result",
            "task_key": "A",
        }
    ]
    assert coordinator.context_payload()["checkpoint_candidates"] == [
        {
            "tool_call_id": "inline-1",
            "tool_name": "esports.match.search",
            "source_kind": "inline_tool_result",
            "task_key": "A",
            "status": "ACTIVE_INLINE",
        }
    ]
    rendered = coordinator.render_context() or ""
    assert "synthetic" not in rendered
    assert '"source_kind":"inline_tool_result"' in rendered

    accepted = coordinator.create_checkpoint("A", {"matches": 1}, ["inline-1"])
    coordinator.refresh(messages)

    assert accepted.source_tool_call_ids == ("inline-1",)
    assert coordinator.context_payload()["active_manifest"] == []
    assert coordinator.context_payload()["checkpoint_candidates"] == []
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]


def test_inline_and_artifact_sources_can_be_checkpointed_together() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "collect A"},
            {"key": "B", "objective": "collect B"},
        ]
    )
    inline_call = _inline_call("inline")
    inline_result = _inline_result("inline")
    read_call = _read_call("raw")
    read_result = _read_result("raw")
    messages = [
        AssistantMessage(tool_calls=[inline_call, read_call]),
        inline_result,
        read_result,
    ]
    coordinator.record_tool_result(inline_call, inline_result, task_key="A")
    coordinator.record_tool_result(read_call, read_result, task_key="A")
    coordinator.refresh(messages)

    checkpoint = coordinator.create_checkpoint("A", {"matches": 1}, ["inline", "raw"])
    coordinator.refresh(messages)

    assert checkpoint.source_tool_call_ids == ("inline", "raw")
    assert coordinator.context_payload()["active_manifest"] == []
    assert coordinator.context_payload()["checkpoint_candidates"] == []
    assert coordinator.plan_snapshot().current_key == "B"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("name", "content", "status"),
    [
        ("artifact.grep", {"matches": []}, "ok"),
        ("task.plan", {"item_count": 2}, "ok"),
        ("task.checkpoint", {"checkpoint_id": "checkpoint:x"}, "ok"),
        ("esports.match.search", {"error": "no"}, "error"),
        (
            "esports.match.search",
            {"externalized": True, "artifact_ref": "artifact:tool:x", "value": {}},
            "ok",
        ),
        (
            "esports.match.search",
            {"items": [{"_artifact_path": "matches.0", "kind": "object"}]},
            "ok",
        ),
        (
            "esports.match.search",
            {"_context_materialization": {"state": "deferred"}},
            "ok",
        ),
        (
            "esports.match.search",
            {"_artifact_observation": {"state": "receipt_only"}},
            "ok",
        ),
    ],
)
def test_ineligible_inline_results_never_enter_checkpoint_candidates(
    name: str,
    content: object,
    status: str,
) -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "collect A"},
            {"key": "B", "objective": "collect B"},
        ]
    )
    call = _inline_call(name=name)
    result = _inline_result(content=content, status=status)
    coordinator.record_tool_result(call, result, task_key="A")
    coordinator.refresh([AssistantMessage(tool_calls=[call]), result])

    assert coordinator.context_payload()["active_manifest"] == []
    assert coordinator.context_payload()["checkpoint_candidates"] == []
    with pytest.raises(ValueError, match="active checkpointable"):
        coordinator.create_checkpoint("A", {"matches": 1}, [call.id])

    assert coordinator.store.snapshot() == {}
    assert coordinator.plan_snapshot().current_key == "A"  # type: ignore[union-attr]


def test_inline_source_ownership_rejects_mixed_cross_task_checkpoint_atomically() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "collect A"},
            {"key": "B", "objective": "collect B"},
        ]
    )
    inline_a, inline_b = _inline_call("inline-a"), _inline_call("inline-b")
    result_a, result_b = _inline_result("inline-a"), _inline_result("inline-b")
    coordinator.record_tool_result(inline_a, result_a, task_key="A")
    coordinator.record_tool_result(inline_b, result_b, task_key="B")
    messages = [
        AssistantMessage(tool_calls=[inline_a, inline_b]),
        result_a,
        result_b,
    ]
    coordinator.refresh(messages)

    assert [
        item["tool_call_id"]
        for item in coordinator.context_payload()["checkpoint_candidates"]
    ] == ["inline-a"]
    with pytest.raises(ValueError, match="belong to different task items: inline-b") as raised:
        coordinator.create_checkpoint("A", {"matches": 2}, ["inline-a", "inline-b"])

    assert raised.value.details == {
        "checkpoint_key": "A",
        "invalid_sources": ["inline-b"],
        "available_sources": ["inline-a"],
    }
    assert coordinator.store.snapshot() == {}
    assert coordinator.plan_snapshot().current_key == "A"  # type: ignore[union-attr]


def test_unplanned_inline_sources_remain_unowned_and_request_reset_clears_them() -> None:
    coordinator = TaskStateCoordinator()
    call = _inline_call("reused")
    result = _inline_result("reused")
    old_request = [AssistantMessage(tool_calls=[call]), result]
    coordinator.record_tool_result(call, result, task_key=None)
    coordinator.refresh(old_request)
    assert coordinator.context_payload()["checkpoint_candidates"] == [
        {
            "tool_call_id": "reused",
            "tool_name": "esports.match.search",
            "source_kind": "inline_tool_result",
            "task_key": None,
            "status": "ACTIVE_INLINE",
        }
    ]
    coordinator.create_checkpoint("free-form", {"matches": 1}, ["reused"])
    assert coordinator.store.get("free-form") is not None

    coordinator.reset()
    coordinator.refresh([AssistantMessage(tool_calls=[call]), result])

    assert coordinator.context_payload()["active_manifest"] == []
    with pytest.raises(ValueError, match="active checkpointable"):
        coordinator.create_checkpoint("free-form", {"matches": 1}, ["reused"])


def test_refresh_rejects_inline_sources_outside_effective_request_scope() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "A", "objective": "collect A"},
            {"key": "B", "objective": "collect B"},
        ]
    )
    call = _inline_call("previous-request")
    result = _inline_result("previous-request")
    messages = [AssistantMessage(tool_calls=[call]), result]
    coordinator.record_tool_result(call, result, task_key="A")
    coordinator.refresh(messages)
    assert coordinator.context_payload()["checkpoint_candidates"]

    coordinator.set_request_scope(2)
    coordinator.refresh([*messages, AssistantMessage(content="new request")])

    assert coordinator.context_payload()["active_manifest"] == []
    assert coordinator.context_payload()["checkpoint_candidates"] == []
    with pytest.raises(ValueError, match="active checkpointable"):
        coordinator.create_checkpoint("A", {"matches": 1}, ["previous-request"])
