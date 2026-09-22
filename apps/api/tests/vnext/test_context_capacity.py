from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

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
    trigger_percent: int = 80,
) -> AgentLimits:
    return AgentLimits(
        context_window_tokens=window,
        context_output_reserve_tokens=reserve,
        context_safety_margin_tokens=margin,
        context_estimate_bytes_per_token=bytes_per_token,
        context_compaction_trigger_percent=trigger_percent,
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
        ("context_compaction_trigger_percent", 80.0),
        ("context_compaction_trigger_percent", 0),
        ("context_compaction_trigger_percent", 100),
    ],
)
def test_context_capacity_fields_are_strictly_validated(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AgentLimits(**{field: value})


def test_context_reserve_and_margin_must_fit_inside_configured_window() -> None:
    with pytest.raises(ValidationError, match="smaller than the context window"):
        _limits(window=30, reserve=20, margin=10)

    assert _limits(window=31, reserve=20, margin=10).context_window_tokens == 31


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
    default_result = assess_request_capacity(_request(), AgentLimits(context_window_tokens=10_000))
    explicit_result = assess_request_capacity(
        _request(max_output_tokens=123),
        AgentLimits(context_window_tokens=10_000),
    )

    assert default_result is not None
    assert explicit_result is not None
    assert default_result.reserved_output_tokens == 4096
    assert explicit_result.reserved_output_tokens == 123
    assert explicit_result.available_input_tokens == 10_000 - 123 - 1024


def test_normal_high_and_critical_pressure_boundaries() -> None:
    boundary_request = _request("x" * 100)
    lower_request = _request("x" * 99)
    estimated = assess_request_capacity(
        boundary_request,
        _limits(bytes_per_token=1, trigger_percent=99, window=10_000),
    )
    assert estimated is not None
    available_high = estimated.estimated_input_tokens + 1

    normal = assess_request_capacity(
        lower_request,
        _limits(
            bytes_per_token=1,
            trigger_percent=99,
            window=available_high + 30,
        ),
    )
    high = assess_request_capacity(
        boundary_request,
        _limits(
            bytes_per_token=1,
            trigger_percent=99,
            window=available_high + 30,
        ),
    )
    critical = assess_request_capacity(
        boundary_request,
        _limits(
            bytes_per_token=1,
            trigger_percent=99,
            window=estimated.estimated_input_tokens + 30,
        ),
    )

    assert normal is not None and normal.pressure is ContextPressure.NORMAL
    assert high is not None and high.pressure is ContextPressure.HIGH
    assert critical is not None and critical.pressure is ContextPressure.CRITICAL
    assert high.trigger_input_tokens == estimated.estimated_input_tokens
    assert critical.available_input_tokens == estimated.estimated_input_tokens


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
