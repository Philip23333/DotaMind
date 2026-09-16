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
            )
        )
    )
    coordinator.create_checkpoint("part", {"事实": "已保存"}, ["call-1"])
    coordinator.create_checkpoint("part", {"事实": "最新"}, ["call-1"])

    context = coordinator.render_context()

    assert context is not None
    assert '"part":{"事实":"最新"}' in context
    assert "已保存" not in context
    assert '"tool_call_id":"call-1"' in context
    assert '"ref":"artifact:test"' in context
    assert '"path":"rows"' in context
    assert '"actual_start":0' in context
    assert '"actual_end":2' in context
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
