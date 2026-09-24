from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.vnext.agent.compaction_budget import resolve_compaction_output_tokens
from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.context_capacity import (
    CAPACITY_MEASUREMENT,
    assess_request_capacity,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime_context import ContextPressure
from app.vnext.llm.protocol import ModelRequest, ModelTool, SystemMessage, UserMessage


def _request(content: str = "x", *, max_output_tokens: int | None = None) -> ModelRequest:
    return ModelRequest(
        messages=[UserMessage(content=content)],
        max_output_tokens=max_output_tokens,
    )


def _limits(
    *,
    window: int = 10_000,
    reserve: int = 20,
    margin: int = 10,
    bytes_per_token: int = 2,
    test_trigger_percent: int | None = None,
    compaction_reserve: int = 20,
) -> AgentLimits:
    return AgentLimits(
        context_window_tokens=window,
        context_output_reserve_tokens=reserve,
        context_safety_margin_tokens=margin,
        context_estimate_bytes_per_token=bytes_per_token,
        context_compaction_test_trigger_percent=test_trigger_percent,
        compaction_reserve_tokens=compaction_reserve,
    )


def test_unconfigured_context_window_disables_capacity_assessment() -> None:
    assert assess_request_capacity(_request(), AgentLimits()) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context_window_tokens", True),
        ("context_output_reserve_tokens", "20"),
        ("context_safety_margin_tokens", 1.5),
        ("context_estimate_bytes_per_token", False),
        ("context_compaction_test_trigger_percent", True),
        ("context_compaction_test_trigger_percent", 80.0),
        ("context_compaction_test_trigger_percent", "30"),
        ("context_compaction_test_trigger_percent", 0),
        ("context_compaction_test_trigger_percent", 100),
    ],
)
def test_context_capacity_fields_are_strictly_validated(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AgentLimits(**{field: value})


def test_context_reserve_and_margin_must_fit_inside_configured_window() -> None:
    with pytest.raises(ValidationError, match="smaller than the context window"):
        _limits(window=30, reserve=20, margin=10)

    assert _limits(window=31, reserve=20, margin=10).context_window_tokens == 31


@pytest.mark.parametrize("compaction_reserve", [100, 101])
def test_compaction_reserve_must_be_smaller_than_configured_window(
    compaction_reserve: int,
) -> None:
    with pytest.raises(ValidationError, match="compaction reserve must be smaller"):
        _limits(
            window=100,
            reserve=20,
            margin=10,
            compaction_reserve=compaction_reserve,
        )


def test_capacity_uses_utf8_bytes_and_ceiling_ratio() -> None:
    request = _request("中文")
    context_bytes = measure_request_context_bytes(request)
    result = assess_request_capacity(
        request,
        _limits(bytes_per_token=7),
    )

    assert result is not None
    assert result.measurement == CAPACITY_MEASUREMENT
    assert result.context_bytes == context_bytes
    assert result.estimated_input_tokens == (context_bytes + 6) // 7


def test_default_and_explicit_output_reserves_are_reported_separately() -> None:
    default_limits = AgentLimits(
        context_window_tokens=10_000,
        compaction_reserve_tokens=1000,
    )
    default_result = assess_request_capacity(_request(), default_limits)
    explicit_result = assess_request_capacity(
        _request(max_output_tokens=123),
        default_limits,
    )

    assert default_result is not None
    assert explicit_result is not None
    assert default_result.reserved_output_tokens == 4096
    assert explicit_result.reserved_output_tokens == 123
    assert explicit_result.available_input_tokens == 10_000 - 123 - 1024


def _request_with_estimated_input_tokens(target: int) -> ModelRequest:
    base = _request("", max_output_tokens=4096)
    base_capacity = assess_request_capacity(
        base,
        _limits(window=100_000, bytes_per_token=1, compaction_reserve=16_384),
    )
    assert base_capacity is not None
    return _request("x" * (target - base_capacity.estimated_input_tokens), max_output_tokens=4096)


def test_production_trigger_uses_first_integer_above_window_minus_reserve() -> None:
    limits = _limits(
        window=100_000,
        reserve=4096,
        margin=1024,
        bytes_per_token=1,
        compaction_reserve=16_384,
    )
    capacities = [
        assess_request_capacity(_request_with_estimated_input_tokens(tokens), limits)
        for tokens in (83_615, 83_616, 83_617, 94_880)
    ]

    assert all(capacity is not None for capacity in capacities)
    assert [capacity.pressure for capacity in capacities if capacity is not None] == [
        ContextPressure.NORMAL,
        ContextPressure.NORMAL,
        ContextPressure.HIGH,
        ContextPressure.CRITICAL,
    ]
    assert capacities[2] is not None
    assert capacities[2].production_trigger_input_tokens == 83_617
    assert capacities[2].trigger_input_tokens == 83_617
    assert capacities[2].available_input_tokens == 94_880


def test_test_trigger_uses_ceiling_and_can_only_advance_production_trigger() -> None:
    limits = _limits(
        window=100_001,
        reserve=4096,
        margin=1024,
        bytes_per_token=1,
        compaction_reserve=16_384,
        test_trigger_percent=30,
    )
    result = assess_request_capacity(_request_with_estimated_input_tokens(28_465), limits)
    assert result is not None
    assert result.available_input_tokens == 94_881
    assert result.test_trigger_percent == 30
    assert result.production_trigger_input_tokens == 83_618
    assert result.trigger_input_tokens == 28_465
    assert result.pressure is ContextPressure.HIGH

    high_test_threshold = assess_request_capacity(
        _request_with_estimated_input_tokens(93_933),
        _limits(
            window=100_000,
            reserve=4096,
            margin=1024,
            bytes_per_token=1,
            compaction_reserve=16_384,
            test_trigger_percent=99,
        ),
    )
    assert high_test_threshold is not None
    assert high_test_threshold.production_trigger_input_tokens == 83_617
    assert (
        high_test_threshold.available_input_tokens * 99 + 99
    ) // 100 > high_test_threshold.production_trigger_input_tokens
    assert high_test_threshold.trigger_input_tokens == 83_617
    assert high_test_threshold.pressure is ContextPressure.HIGH

    critical = assess_request_capacity(
        _request_with_estimated_input_tokens(94_880),
        _limits(
            window=100_000,
            reserve=4096,
            margin=1024,
            bytes_per_token=1,
            compaction_reserve=16_384,
            test_trigger_percent=1,
        ),
    )
    assert critical is not None
    assert critical.pressure is ContextPressure.CRITICAL


def test_unconfigured_window_disables_test_override_and_output_budget_is_unchanged() -> None:
    assert (
        assess_request_capacity(
            _request(),
            AgentLimits(context_compaction_test_trigger_percent=30),
        )
        is None
    )
    limits = _limits(test_trigger_percent=30)
    assert limits.context_output_reserve_tokens == 20
    assert limits.compaction_reserve_tokens == 20
    production_limits = limits.model_copy(update={"context_compaction_test_trigger_percent": None})
    for kind in ("history", "turn_prefix"):
        assert resolve_compaction_output_tokens(
            kind=kind,
            reserve_tokens=limits.compaction_reserve_tokens,
            model_max_output_tokens=None,
        ) == resolve_compaction_output_tokens(
            kind=kind,
            reserve_tokens=production_limits.compaction_reserve_tokens,
            model_max_output_tokens=None,
        )


def test_explicit_output_reserve_can_exhaust_input_budget() -> None:
    result = assess_request_capacity(
        _request("small", max_output_tokens=1_000),
        _limits(window=100, reserve=20, margin=10),
    )

    assert result is not None
    assert result.available_input_tokens == 0
    assert result.pressure is ContextPressure.CRITICAL


def test_tools_and_projected_context_increase_estimated_occupancy() -> None:
    tool = ModelTool(
        name="artifact.read",
        description="Read one artifact.",
        input_schema={"type": "object", "properties": {"ref": {"type": "string"}}},
    )
    base = ModelRequest(messages=[UserMessage(content="query")])
    projected = ModelRequest(
        messages=[
            SystemMessage(
                content=json.dumps(
                    {
                        "summary": "compressed background",
                        "artifact_locators": [{"ref": "artifact:tool:" + "a" * 32}],
                        "task_state": {"part": {"status": "active"}},
                        "runtime_prompt": "converging",
                    },
                    ensure_ascii=False,
                )
            ),
            UserMessage(content="query"),
        ],
        tools=[tool],
    )

    base_result = assess_request_capacity(base, _limits(bytes_per_token=1))
    projected_result = assess_request_capacity(projected, _limits(bytes_per_token=1))

    assert base_result is not None and projected_result is not None
    assert projected_result.context_bytes > base_result.context_bytes
    assert projected_result.estimated_input_tokens > base_result.estimated_input_tokens


def test_capacity_assessment_is_repeatable_and_has_no_side_effects() -> None:
    request = _request("unchanged", max_output_tokens=77)
    limits = _limits()
    request_before = request.model_dump(mode="json")
    limits_before = limits.model_dump(mode="json")

    first = assess_request_capacity(request, limits)
    second = assess_request_capacity(request, limits)

    assert first == second
    assert request.model_dump(mode="json") == request_before
    assert limits.model_dump(mode="json") == limits_before
