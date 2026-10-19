from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.vnext.agent.answer_tools import AnswerToolSession
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts import ArtifactReader, SessionArtifactStore, serialized_size
from app.vnext.artifacts.query import (
    ArtifactQuerier,
    ArtifactQueryInput,
    QueryBudgetExceeded,
    QueryFieldsUnavailable,
)
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


def run_query(
    document,
    expression="$.rows[*]",
    fields=None,
    *,
    max_bytes=35 * 1024,
    max_work=100_000,
    **kwargs,
):
    async def run():
        store = SessionArtifactStore()
        ref = await store.put(document)
        args = ArtifactQueryInput(ref=ref, expression=expression, fields=fields or ["n"], **kwargs)
        return await ArtifactQuerier(
            store, observation_max_bytes=max_bytes, max_work=max_work
        ).query(args)

    return asyncio.run(run())


def test_exact_player_time_and_fields_round_trip_without_mutation():
    async def run():
        store = SessionArtifactStore()
        document = {
            "data": {
                "players": [
                    {
                        "identity": {"account_id": 1},
                        "minute_timeline": [{"time_seconds": 1500, "cumulative_gold_earned": 99}],
                    },
                    {
                        "identity": {"account_id": 106305042},
                        "minute_timeline": [
                            {
                                "time_seconds": 1200,
                                "time_label": "20:00",
                                "cumulative_gold_earned": 8767,
                                "known_deaths": 2,
                            },
                            {
                                "time_seconds": 1500,
                                "time_label": "25:00",
                                "cumulative_gold_earned": 10840,
                                "known_deaths": 2,
                            },
                            {
                                "time_seconds": 1800,
                                "time_label": "30:00",
                                "cumulative_gold_earned": 14105,
                                "known_deaths": 2,
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
                fields=["time_seconds", "cumulative_gold_earned", "known_deaths"],
            )
        )
        assert result.expression == expression
        assert result.returned == 1 and result.next_offset is None and not result.truncated
        record = result.matches[0]
        assert record.path == "data.players.1.minute_timeline.1"
        assert record.value == {
            "time_seconds": 1500,
            "cumulative_gold_earned": 10840,
            "known_deaths": 2,
        }
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
                },
                {"absent": "present on another record"},
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
    with pytest.raises(QueryFieldsUnavailable) as error:
        run_query({"rows": [{}]})
    assert error.value.details["missing_fields"] == ["n"]
    assert error.value.details["available_fields"] == []


def test_wrong_building_fields_fail_whole_projection_with_observed_sample_fields():
    document = {"rows": [
        {"time_seconds": 627, "target_unit": {"side": "radiant"}, "actor_unit": None},
        {"time_seconds": 663, "target_unit": {"side": "dire"}},
    ]}
    with pytest.raises(QueryFieldsUnavailable) as error:
        run_query(document, fields=["time_seconds", "side", "building", "owner"])
    assert error.value.details == {
        "missing_fields": ["side", "building", "owner"],
        "sample_path": "rows.0",
        "available_fields": ["time_seconds", "target_unit", "actor_unit"],
        "available_fields_truncated": False,
    }
    assert "this page" in str(error.value)
    assert "does not establish absence" in str(error.value)


def test_heterogeneous_missing_and_present_null_follow_the_four_branch_contract():
    document = {"rows": [
        {"time_seconds": 627, "actor_unit": {"kind": "hero"}},
        {"time_seconds": 663},
        {"time_seconds": 793, "actor_unit": None},
    ]}
    result = run_query(document, fields=["time_seconds", "actor_unit"])
    assert result.returned == 3
    assert [m.missing_fields for m in result.matches] == [[], ["actor_unit"], []]
    assert result.matches[-1].value["actor_unit"] is None
    only_null = run_query(document, "$.rows[2]", fields=["actor_unit"])
    assert only_null.matches[0].value == {"actor_unit": None}
    assert only_null.matches[0].missing_fields == []
    empty = run_query(document, "$.rows[?@.time_seconds == 1200]", fields=["typo"])
    assert empty.matches == [] and empty.next_offset is None and empty.returned == 0


def test_field_availability_uses_only_the_returned_page_not_other_records_or_lookahead():
    document = {"rows": [{"n": 0}, {"other": 1}, {"n": 2}]}
    with pytest.raises(QueryFieldsUnavailable) as error:
        run_query(document, offset=1, limit=1)
    assert error.value.details["sample_path"] == "rows.1"
    assert error.value.details["available_fields"] == ["other"]
    assert run_query(document, offset=1, limit=2).matches[0].missing_fields == ["n"]


def test_byte_trimmed_records_do_not_count_as_field_availability_on_the_returned_page():
    document = {"rows": [{"tag": "中" * 200}, {"tag": "中" * 200, "rare": 1}]}
    first = run_query(document, fields=["tag"], limit=1)
    max_bytes = serialized_size(first.model_dump(mode="json")) + 100
    with pytest.raises(QueryFieldsUnavailable) as error:
        run_query(document, fields=["tag", "rare"], max_bytes=max_bytes)
    assert error.value.details["missing_fields"] == ["rare"]
    assert error.value.details["sample_path"] == "rows.0"


@pytest.mark.parametrize("answer_stage", [False, True])
def test_projection_error_is_structured_and_allows_corrected_retry_in_both_stages(answer_stage):
    async def run():
        store = SessionArtifactStore()
        document = {"rows": [{"time_seconds": 627, "target_unit": {"side": "radiant"}}]}
        ref = await store.put(document)
        registry = ToolRegistry()
        register_artifact_query_tool(registry, ArtifactQuerier(store))
        session = AnswerToolSession(registry)

        async def execute(call):
            if answer_stage:
                return await session.execute(call, timeout=1)
            return await registry.execute(call)

        call = ToolCall(id="wrong", name="artifact.query", arguments={
            "ref": ref, "expression": "$.rows[*]", "fields": ["time_seconds", "side"],
        })
        failed = await execute(call)
        assert failed.status == "error" and failed.content is None
        assert failed.error.code == "invalid_arguments"
        assert failed.error.details["available_fields"] == ["time_seconds", "target_unit"]
        corrected = call.model_copy(update={"id": "retry", "arguments": {
            **call.arguments, "fields": ["time_seconds", "target_unit"],
        }})
        recovered = await execute(corrected)
        assert recovered.status == "ok"
        assert recovered.content["matches"][0]["value"] == document["rows"][0]
        assert await store.get(ref) == document

    asyncio.run(run())


def test_available_field_hints_are_whole_names_count_and_utf8_bounded():
    with pytest.raises(QueryFieldsUnavailable) as error:
        run_query({"rows": [{f"field_{i}": None for i in range(100)}]})
    assert error.value.details["available_fields"] == [f"field_{i}" for i in range(64)]
    assert error.value.details["available_fields_truncated"] is True

    async def run():
        store = SessionArtifactStore()
        names = [f"字段{i}" + "甲" * 100 for i in range(100)]
        ref = await store.put({"rows": [{key: None for key in names}]})
        registry = ToolRegistry(observation_max_bytes=1000)
        register_artifact_query_tool(registry, ArtifactQuerier(store, observation_max_bytes=1000))
        result = await registry.execute(ToolCall(id="hints", name="artifact.query", arguments={
            "ref": ref, "expression": "$.rows[*]", "fields": ["unknown"],
        }))
        assert result.error.code == "invalid_arguments"
        assert registry.result_size(result) <= 1000
        hints = result.error.details
        assert hints["missing_fields"] == ["unknown"]
        assert hints["available_fields_truncated"] is True
        assert 0 < len(hints["available_fields"]) < 64
        assert all(key in names for key in hints["available_fields"])

    asyncio.run(run())


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


def test_condition_complexity_limits():
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
                    {"time_seconds": 1200, "cumulative_gold_earned": 8767},
                    {"time_seconds": 1500, "cumulative_gold_earned": 10840},
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
                            "fields": ["time_seconds", "cumulative_gold_earned"],
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
        assert observed.content["matches"][0]["value"] == {
            "time_seconds": 1200,
            "cumulative_gold_earned": 8767,
        }
        assert all(any(t.name == "artifact.query" for t in r.tools) for r in model.requests)

    asyncio.run(run())


def test_late_match_within_work_budget_is_supported():
    document = {"rows": [{"n": i} for i in range(49999)]}
    result = run_query(document, "$.rows[?@.n == 49998]")
    assert result.returned == 1 and result.matches[0].path == "rows.49998"


def test_large_unrelated_branches_and_nested_values_do_not_consume_query_work():
    document = {
        "data": {
            "players": [
                {
                    "identity": {"account_id": i},
                    "final_stats": {"kills": i},
                    "minute_timeline": [None] * 12000,
                }
                for i in range(10)
            ],
            "unrelated": [None] * 1_000_000,
        }
    }
    result = run_query(document, "$.data.players[*]", ["identity", "final_stats"], max_work=12)
    assert result.returned == 10 and result.next_offset is None
    assert result.matches[-1].value == {"identity": {"account_id": 9}, "final_stats": {"kills": 9}}
    assert result.matches[-1].path == "data.players.9"


@pytest.mark.parametrize(
    "expression",
    [
        "$.rows[?@.n == 10001]",
        "$.rows[?@.n == 10001 && @.other == 2]",
        "$.rows[?@.missing.field == 10001]",
    ],
)
def test_nonmatching_filters_consume_work(expression):
    with pytest.raises(QueryBudgetExceeded) as error:
        run_query({"rows": [{"n": 0, "other": 2}] * 10000}, expression, max_work=50)
    assert error.value.limit == error.value.used == 50


def test_intermediate_wildcards_offset_skips_and_missing_indexes_consume_work():
    with pytest.raises(QueryBudgetExceeded):
        run_query({"rows": [{"items": []}] * 10000}, "$.rows[*].items[*]", max_work=20)
    with pytest.raises(QueryBudgetExceeded):
        run_query({"rows": [{"n": 0}] * 10000}, offset=100, max_work=20)
    with pytest.raises(QueryBudgetExceeded):
        run_query({"rows": []}, "$.rows[0]", max_work=1)


@pytest.mark.parametrize("max_work", [True, False, 0, -1, 1.5, "100"])
def test_querier_rejects_invalid_work_budget(max_work):
    with pytest.raises(ValueError, match="max_work"):
        ArtifactQuerier(SessionArtifactStore(), max_work=max_work)


def test_work_budget_is_per_call_and_safe_for_concurrent_queries():
    async def run():
        store = SessionArtifactStore()
        ref = await store.put({"rows": [{"n": 1}]})
        querier = ArtifactQuerier(store, max_work=2)
        args = ArtifactQueryInput(ref=ref, expression="$.rows[*]", fields=["n"])
        first, second = await asyncio.gather(querier.query(args), querier.query(args))
        assert first == second and first.returned == 1
        assert await querier.query(args) == first

    asyncio.run(run())


@pytest.mark.parametrize("answer_stage", [False, True])
def test_work_exhaustion_is_structured_and_never_returns_partial_results(answer_stage):
    async def run():
        store = SessionArtifactStore()
        ref = await store.put({"rows": [{"n": 1}] * 10})
        registry = ToolRegistry()
        register_artifact_query_tool(registry, ArtifactQuerier(store, max_work=3))
        call = ToolCall(
            id="work",
            name="artifact.query",
            arguments={
                "ref": ref,
                "expression": "$.rows[*]",
                "fields": ["n"],
            },
        )
        result = (
            await AnswerToolSession(registry).execute(call, timeout=1)
            if answer_stage
            else await registry.execute(call)
        )
        assert result.status == "error" and result.content is None
        assert result.error.code == "query_budget_exceeded"
        assert result.error.details == {"limit": 3, "used": 3}
        assert "narrow" in result.error.message

    asyncio.run(run())


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
