from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.vnext.artifacts import (
    ArtifactGrepMatch,
    ArtifactGrepResult,
    ArtifactReadResult,
    SessionArtifactStore,
)
from app.vnext.llm.protocol import FinalMessage, ToolCall, ToolResultMessage, UserMessage
from app.vnext.product.session_history import ArtifactLocator, SessionExecutionHistory


def _ref(index: int) -> str:
    return f"artifact:tool:{index:032x}"


def _call(
    call_id: str = "call-1",
    name: str = "lookup",
    arguments: dict[str, object] | None = None,
) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        arguments={"query": "value"} if arguments is None else arguments,
    )


def _result(call: ToolCall, content: object, *, status: str = "ok") -> ToolResultMessage:
    return ToolResultMessage(tool_call_id=call.id, content=content, status=status)


def _observation(ref: str) -> dict[str, object]:
    return {"externalized": True, "artifact_ref": ref, "value": {}}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_locator_capacity", 0),
        ("artifact_locator_capacity", -1),
        ("artifact_locator_capacity", True),
        ("artifact_locator_capacity", False),
        ("artifact_locator_hint_chars", 0),
        ("artifact_locator_hint_chars", -1),
        ("artifact_locator_hint_chars", True),
        ("artifact_locator_hint_chars", False),
    ],
)
def test_locator_limits_must_be_positive_real_integers(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        SessionExecutionHistory(**{field: value})


def test_generic_externalized_observations_are_recorded_once() -> None:
    history = SessionExecutionHistory()
    call = _call(arguments={"z": 1, "query": "汉字"})
    ref = _ref(1)

    history.remember_artifact_locators(call, _result(call, _observation(ref)))

    assert history.artifact_locators == (
        ArtifactLocator(
            ref=ref,
            source_tool="lookup",
            query_hint='{"query":"汉字","z":1}',
        ),
    )


def test_only_top_level_generic_refs_are_accepted() -> None:
    history = SessionExecutionHistory()
    call = _call()

    history.remember_artifact_locators(
        call,
        _result(
            call,
            {
                "externalized": True,
                "value": {"artifact_ref": _ref(1)},
            },
        ),
    )
    history.remember_artifact_locators(
        call,
        _result(call, {"externalized": False, "artifact_ref": _ref(2)}),
    )

    assert history.artifact_locators == ()


def test_artifact_read_requires_a_valid_read_result_and_ignores_manual_refs() -> None:
    history = SessionExecutionHistory()
    valid_call = _call(
        name="artifact.read",
        arguments={"ref": _ref(1), "path": "items"},
    )
    valid = ArtifactReadResult(ref=_ref(1), path="items", value=[1]).model_dump(
        mode="json"
    )
    history.remember_artifact_locators(valid_call, _result(valid_call, valid))

    invalid_call = _call(name="artifact.read")
    history.remember_artifact_locators(
        invalid_call,
        _result(invalid_call, {"ref": _ref(2)}),
    )
    manual_call = _call(name="artifact.read")
    manual = ArtifactReadResult(
        ref="manual:context",
        path="content",
        value="manual",
    ).model_dump(mode="json")
    history.remember_artifact_locators(manual_call, _result(manual_call, manual))

    assert [locator.ref for locator in history.artifact_locators] == [_ref(1)]


def test_artifact_grep_records_unique_session_refs_in_result_order() -> None:
    history = SessionExecutionHistory()
    call = _call(name="artifact.grep")
    content = ArtifactGrepResult(
        matches=[
            ArtifactGrepMatch(ref=_ref(3), path="a", preview="a"),
            ArtifactGrepMatch(ref=_ref(1), path="b", preview="b"),
            ArtifactGrepMatch(ref=_ref(3), path="c", preview="c"),
            ArtifactGrepMatch(ref="manual:context", path="content", preview="d"),
        ],
        returned=4,
        truncated=False,
    ).model_dump(mode="json")

    history.remember_artifact_locators(call, _result(call, content))

    assert [locator.ref for locator in history.artifact_locators] == [_ref(3), _ref(1)]


@pytest.mark.parametrize(
    "ref",
    [
        "manual:context",
        "artifact:tool:short",
        f"artifact:tool:{'A' * 32}",
        f"artifact:tool:{'g' * 32}",
    ],
)
def test_invalid_or_manual_refs_are_ignored(ref: str) -> None:
    history = SessionExecutionHistory()
    call = _call()

    history.remember_artifact_locators(call, _result(call, _observation(ref)))

    assert history.artifact_locators == ()


def test_mismatched_and_failed_results_do_not_create_locators() -> None:
    history = SessionExecutionHistory()
    call = _call()

    history.remember_artifact_locators(
        call,
        ToolResultMessage(tool_call_id="other", content=_observation(_ref(1))),
    )
    history.remember_artifact_locators(
        call,
        ToolResultMessage(
            tool_call_id=call.id,
            content=_observation(_ref(2)),
            status="error",
            error={"code": "tool_execution_error", "message": "failed"},
        ),
    )

    assert history.artifact_locators == ()


def test_locator_order_is_fifo_and_duplicates_keep_the_first_metadata() -> None:
    history = SessionExecutionHistory(artifact_locator_capacity=2)
    first = _call("first", arguments={"query": "first"})
    second = _call("second", name="second_tool", arguments={"query": "second"})
    third = _call("third", name="third_tool", arguments={"query": "third"})

    history.remember_artifact_locators(first, _result(first, _observation(_ref(1))))
    history.remember_artifact_locators(second, _result(second, _observation(_ref(2))))
    history.remember_artifact_locators(
        third,
        _result(third, _observation(_ref(1))),
    )
    history.remember_artifact_locators(third, _result(third, _observation(_ref(3))))

    assert history.artifact_locators == (
        ArtifactLocator(
            ref=_ref(2),
            source_tool="second_tool",
            query_hint='{"query":"second"}',
        ),
        ArtifactLocator(
            ref=_ref(3),
            source_tool="third_tool",
            query_hint='{"query":"third"}',
        ),
    )


def test_evicted_ref_can_be_remembered_again_as_a_new_fifo_entry() -> None:
    history = SessionExecutionHistory(artifact_locator_capacity=2)
    for index in (1, 2, 3):
        call = _call(str(index))
        history.remember_artifact_locators(call, _result(call, _observation(_ref(index))))

    call = _call("again", name="again")
    history.remember_artifact_locators(call, _result(call, _observation(_ref(1))))

    assert [locator.ref for locator in history.artifact_locators] == [_ref(3), _ref(1)]


def test_query_hints_are_sorted_unicode_json_and_character_truncated() -> None:
    history = SessionExecutionHistory(artifact_locator_hint_chars=10)
    call = _call(arguments={"z": "末尾", "a": "中文"})

    history.remember_artifact_locators(call, _result(call, _observation(_ref(1))))

    locator = history.artifact_locators[0]
    expected = '{"a":"中文","z":"末尾"}'
    assert locator.query_hint == expected[:10]
    assert len(locator.query_hint) == 10
    assert len(locator.ref) == len("artifact:tool:") + 32


def test_query_hint_serialization_failure_is_empty() -> None:
    history = SessionExecutionHistory()
    call = _call(arguments={"unserializable": object()})

    history.remember_artifact_locators(call, _result(call, _observation(_ref(1))))

    assert history.artifact_locators[0].query_hint == ""


def test_locator_state_is_independent_from_context_state_and_records() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "question",
        initial_messages=[UserMessage(content="old")],
    )
    call = _call()
    history.remember_artifact_locators(call, _result(call, _observation(_ref(1))))
    locators_before = history.artifact_locators
    records_before = history.records
    revision_before = history.revision

    history.set_effective(
        [
            UserMessage(content="old"),
            UserMessage(content="question"),
            FinalMessage(content="answer"),
        ]
    )
    history.commit_compaction(
        request_id=request_id,
        base_revision=history.revision,
        summary="summary",
        cut_index=2,
    )

    assert history.artifact_locators == locators_before
    assert history.records == records_before
    assert history.revision == revision_before + 2


def test_locator_state_is_not_shared_between_history_instances() -> None:
    first = SessionExecutionHistory()
    second = SessionExecutionHistory()
    call = _call()

    first.remember_artifact_locators(call, _result(call, _observation(_ref(1))))

    assert first.artifact_locators != second.artifact_locators
    assert second.artifact_locators == ()


def test_locator_eviction_does_not_remove_stored_artifacts() -> None:
    store = SessionArtifactStore()
    refs = [asyncio.run(store.put({"index": index})) for index in range(3)]
    history = SessionExecutionHistory(artifact_locator_capacity=2)

    for index, ref in enumerate(refs):
        call = _call(str(index))
        history.remember_artifact_locators(call, _result(call, _observation(ref)))

    assert [locator.ref for locator in history.artifact_locators] == refs[1:]
    assert asyncio.run(store.get(refs[0])) == {"index": 0}
