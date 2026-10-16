from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.vnext.agent.answer_tools import AnswerToolSession
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts import ArtifactReader, SessionArtifactStore, serialized_size
from app.vnext.artifacts.query import ArtifactQuerier, ArtifactQueryInput
from app.vnext.artifacts.retrieval import ArtifactReadValidationError
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.artifacts import register_artifact_query_tool
from app.vnext.tools.registry import ToolRegistry


def run_query(document, expression="$.rows[*]", fields=None, *, max_bytes=35 * 1024, **kwargs):
    async def run():
        store = SessionArtifactStore()
        ref = await store.put(document)
        args = ArtifactQueryInput(ref=ref, expression=expression, fields=fields or ["n"], **kwargs)
        return await ArtifactQuerier(store, observation_max_bytes=max_bytes).query(args)

    return asyncio.run(run())


def test_exact_player_time_and_fields_round_trip_without_mutation():
    async def run():
        store = SessionArtifactStore()
        document = {
            "data": {
                "players": [
                    {
                        "identity": {"account_id": 1},
                        "minute_timeline": [{"time_seconds": 1500, "net_worth": 99}],
                    },
                    {
                        "identity": {"account_id": 106305042},
                        "minute_timeline": [
                            {
                                "time_seconds": 1200,
                                "time_label": "20:00",
                                "net_worth": 8657,
                                "deaths": 2,
                            },
                            {
                                "time_seconds": 1500,
                                "time_label": "25:00",
                                "net_worth": 10730,
                                "deaths": 2,
                            },
                            {
                                "time_seconds": 1800,
                                "time_label": "30:00",
                                "net_worth": 13885,
                                "deaths": 2,
                            },
                        ],
                    },
                ]
            }
        }
        ref = await store.put(document)
        expression = (
            "$.data.players[?@.identity.account_id == 106305042].minute_timeline"
            "[?@.time_seconds == 1500]"
        )
        result = await ArtifactQuerier(store).query(
            ArtifactQueryInput(
                ref=ref,
                expression=expression,
                fields=["time_seconds", "net_worth", "deaths"],
            )
        )
        assert result.expression == expression
        assert result.returned == 1 and result.next_offset is None and not result.truncated
        record = result.matches[0]
        assert record.path == "data.players.1.minute_timeline.1"
        assert record.value == {"time_seconds": 1500, "net_worth": 10730, "deaths": 2}
        original = await ArtifactReader(store).read(ref, record.path)
        assert original.value["time_label"] == "25:00"
        assert await store.get(ref) == document

    asyncio.run(run())


def test_missing_null_false_zero_and_nested_values_are_distinct():
    result = run_query(
        {
            "rows": [
                {
                    "null": None,
                    "zero": 0,
                    "false": False,
                    "empty": "",
                    "array": [],
                    "object": {"source": [1, None]},
                }
            ]
        },
        fields=["absent", "null", "zero", "false", "empty", "array", "object"],
    )
    assert result.matches[0].missing_fields == ["absent"]
    assert result.matches[0].value == {
        "null": None,
        "zero": 0,
        "false": False,
        "empty": "",
        "array": [],
        "object": {"source": [1, None]},
    }
    absent = run_query({"rows": [{}]})
    assert absent.returned == 1 and absent.matches[0].value == {}


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ("@.n == 2", [2]),
        ("@.n != 2", [1, 3]),
        ("@.n < 2", [1]),
        ("@.n <= 2", [1, 2]),
        ("@.n > 2", [3]),
        ("@.n >= 2", [2, 3]),
        ("(@.n == 1 || @.n == 3) && @.n > 1", [3]),
    ],
)
def test_comparisons_and_logical_conditions(predicate, expected):
    result = run_query({"rows": [{"n": n} for n in [1, 2, 3]]}, f"$.rows[?{predicate}]")
    assert [m.value["n"] for m in result.matches] == expected


@pytest.mark.parametrize(
    ("literal", "expected"), [("1", [1]), ("true", [True]), ('"1"', ["1"]), ("null", [None])]
)
def test_filter_types_do_not_coerce_and_missing_is_not_null(literal, expected):
    result = run_query(
        {"rows": [{"n": 1}, {"n": True}, {"n": "1"}, {"n": None}, {}]}, f"$.rows[?@.n == {literal}]"
    )
    assert [m.value["n"] for m in result.matches] == expected
    assert len(result.matches) == 1


def test_filter_then_paginate_and_keep_source_indexes():
    document = {"rows": [{"n": n} for n in range(10)]}
    page = run_query(document, "$.rows[?@.n >= 5]", offset=1, limit=2)
    assert [m.path for m in page.matches] == ["rows.6", "rows.7"]
    assert page.next_offset == 3 and page.truncated and page.returned == 2
    tail = run_query(document, "$.rows[?@.n >= 5]", offset=3, limit=2)
    assert [m.path for m in tail.matches] == ["rows.8", "rows.9"]
    assert tail.next_offset is None and not tail.truncated
    empty = run_query(document, "$.rows[?@.n == 1230]")
    assert empty.matches == [] and empty.returned == 0 and not empty.truncated
    assert run_query(document, offset=1000).matches == []


@pytest.mark.parametrize(
    "expression",
    [
        "$..rows",
        "$.rows[-1]",
        "$.rows[0:2]",
        "$.rows[0,1]",
        "$.rows[?@.n]",
        "$.rows[?length(@.n) == 1]",
        "$.rows[?match(@.n, 'x')]",
        "$.rows[?@.n == $.x]",
        "$.rows[?@.n == @.other]",
        "$.rows[?@.n[*] == 1]",
        "$.rows[?!(@.n == 1)]",
        "$.rows[?@.n + 1 == 2]",
        "$.rows[?@.n == [1,2]]",
        "$.rows[?@ == 1]",
        "$.rows[?@.n == 1e999]",
        "rows[*]",
        " $.rows[*]",
        "$.rows[",
        "$" + ".a" * 17,
    ],
)
def test_unsupported_language_is_an_error(expression):
    with pytest.raises(ArtifactReadValidationError):
        run_query({"rows": [{"n": 1}]}, expression)


@pytest.mark.parametrize(
    ("document", "expression"),
    [
        ({"rows": {"one": {"n": 1}}}, "$.rows[*]"),
        ({"rows": {"one": {"n": 1}}}, "$.rows[?@.n == 1]"),
        ({"rows": [1]}, "$.rows[*]"),
        ({"rows": [{"n": 1}, 2]}, "$.rows[*]"),
        ({"rows": {"n": 1}}, "$"),
        ({"a.b": {"n": 1}}, "$['a.b']"),
        ({"": {"n": 1}}, "$['']"),
    ],
)
def test_object_enumeration_result_shapes_and_unreadable_locations_fail(document, expression):
    with pytest.raises(ArtifactReadValidationError):
        run_query(document, expression)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fields": []},
        {"fields": [""]},
        {"fields": ["a", "a"]},
        {"fields": [2]},
        {"fields": [str(n) for n in range(17)]},
        {"offset": True},
        {"offset": "1"},
        {"offset": -1},
        {"offset": 10001},
        {"limit": 0},
        {"limit": 101},
        {"limit": 1.5},
        {"expression": "x" * 1025},
    ],
)
def test_strict_input_validation(kwargs):
    with pytest.raises(ValidationError):
        ArtifactQueryInput(
            **{"ref": "fixture", "expression": "$.rows[*]", "fields": ["n"], **kwargs}
        )


def test_byte_admission_reduces_whole_rows_and_obeys_smaller_configuration():
    document = {"rows": [{"n": "中" * 200} for _ in range(6)]}
    page = run_query(document, max_bytes=1600)
    assert 0 < page.returned < 6 and page.truncated
    assert serialized_size(page.model_dump(mode="json")) <= 1600
    assert page.next_offset == page.returned
    assert all(m.value["n"] == "中" * 200 for m in page.matches)
    with pytest.raises(ArtifactReadValidationError, match="byte limit"):
        run_query({"rows": [{"n": "x" * 40_000}]})
    with pytest.raises(ArtifactReadValidationError, match="byte limit"):
        run_query({"rows": []}, max_bytes=1)


def test_offset_cap_never_emits_an_invalid_continuation():
    document = {"rows": [{"n": i} for i in range(10002)]}
    with pytest.raises(ArtifactReadValidationError, match="offset range"):
        run_query(document, offset=10000, limit=1)
    tail = run_query(document, offset=10000, limit=2)
    assert tail.returned == 2 and tail.next_offset is None and not tail.truncated


def test_document_and_condition_complexity_limits():
    with pytest.raises(ArtifactReadValidationError, match="100000"):
        run_query({"rows": [], "large": [None] * 100000})

    # Balanced groups permit testing the comparison cap independently of depth.
    def balanced(terms):
        if len(terms) == 1:
            return terms[0]
        middle = len(terms) // 2
        return f"({balanced(terms[:middle])} && {balanced(terms[middle:])})"

    with pytest.raises(ArtifactReadValidationError, match="32 comparisons"):
        run_query({"rows": []}, f"$.rows[?{balanced(['@.n==1'] * 33)}]")
    with pytest.raises(ArtifactReadValidationError, match="nesting"):
        run_query({"rows": []}, "$.rows[?" + " && ".join(["@.n==1"] * 12) + "]")


def test_registry_session_isolation_and_answer_permissions():
    async def run():
        store = SessionArtifactStore()
        ref = await store.put({"rows": [{"n": 7}]})
        registry = ToolRegistry()
        register_artifact_query_tool(registry, ArtifactQuerier(store))
        definition = registry.get("artifact.query")
        assert definition.read_only and not definition.externalize_result
        session = AnswerToolSession(registry)
        assert [s.name for s in session.schemas()] == ["artifact.query"]
        call = ToolCall(
            id="query",
            name="artifact.query",
            arguments={
                "ref": ref,
                "expression": "$.rows[*]",
                "fields": ["n"],
            },
        )
        result = await session.execute(call, timeout=1)
        assert result.status == "ok" and result.content["matches"][0]["value"] == {"n": 7}
        assert (await session.execute(call, timeout=1)).status == "error"
        other = ToolRegistry()
        register_artifact_query_tool(other, ArtifactQuerier(SessionArtifactStore()))
        assert (await other.execute(call)).error.code == "artifact_not_found"
        invalid = call.model_copy(update={"arguments": {**call.arguments, "expression": "$..n"}})
        assert (await registry.execute(invalid)).error.code == "invalid_arguments"

    asyncio.run(run())


@pytest.mark.parametrize("answer_stage", [False, True])
def test_runtime_query_is_available_in_both_stages(answer_stage):
    from tests.vnext.fakes import ScriptedModelClient

    async def run():
        store = SessionArtifactStore()
        ref = await store.put(
            {
                "rows": [
                    {"time_seconds": 1200, "net_worth": 8657},
                    {"time_seconds": 1500, "net_worth": 10730},
                ]
            }
        )
        registry = ToolRegistry()
        register_artifact_query_tool(registry, ArtifactQuerier(store))
        call = ModelResponse.from_assistant(
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        id="query",
                        name="artifact.query",
                        arguments={
                            "ref": ref,
                            "expression": "$.rows[?@.time_seconds == 1200]",
                            "fields": ["time_seconds", "net_worth"],
                        },
                    )
                ]
            )
        )
        responses = (
            [ModelResponse.from_final("execution"), call]
            if answer_stage
            else [call, ModelResponse.from_final("execution")]
        )
        model = ScriptedModelClient([*responses, ModelResponse.from_final("answer")])
        result = await AgentRuntime(
            model, registry, limits=AgentLimits(application_max_output_tokens=1024)
        ).run([UserMessage(content="query minute 20")])
        assert result.content == "answer"
        observed = next(m for m in model.requests[-1].messages if isinstance(m, ToolResultMessage))
        assert observed.status == "ok"
        assert observed.content["matches"][0]["value"] == {"time_seconds": 1200, "net_worth": 8657}
        assert all(any(t.name == "artifact.query" for t in r.tools) for r in model.requests)

    asyncio.run(run())


def test_maximum_document_nodes_and_late_match_are_supported():
    document = {"rows": [{"n": i} for i in range(49999)]}  # Exactly 100000 nodes.
    result = run_query(document, "$.rows[?@.n == 49998]")
    assert result.returned == 1 and result.matches[0].path == "rows.49998"


def test_query_timeout_keeps_event_loop_responsive_without_claiming_worker_stopped(monkeypatch):
    from threading import Event

    from app.vnext.artifacts import query as module

    gate = Event()
    started = Event()
    finished = Event()
    evaluate = module._evaluate

    def delayed(*args):
        started.set()
        gate.wait(1)
        try:
            return evaluate(*args)
        finally:
            finished.set()

    monkeypatch.setattr(module, "_evaluate", delayed)

    async def run():
        store = SessionArtifactStore()
        ref = await store.put({"rows": [{"n": 1}]})
        registry = ToolRegistry()
        register_artifact_query_tool(registry, ArtifactQuerier(store))
        task = asyncio.create_task(
            registry.execute(
                ToolCall(
                    id="timeout",
                    name="artifact.query",
                    arguments={"ref": ref, "expression": "$.rows[*]", "fields": ["n"]},
                ),
                timeout=0.02,
            )
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            result = await task
            assert result.status == "error" and result.error.code == "tool_timeout"
            assert not finished.is_set()
        finally:
            gate.set()

    asyncio.run(run())
    assert finished.is_set()
