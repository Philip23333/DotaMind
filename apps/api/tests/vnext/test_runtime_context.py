import pytest

from app.vnext.agent.runtime_context import (
    ContextPressure,
    RuntimeContext,
    RuntimePhase,
    TimePressure,
    classify_time_pressure,
)


@pytest.mark.parametrize(
    ("remaining_seconds", "budget_seconds", "expected"),
    [
        (41, 100, TimePressure.HEALTHY),
        (40, 100, TimePressure.LIMITED),
        (21, 100, TimePressure.LIMITED),
        (20, 100, TimePressure.CRITICAL),
        (0, 100, TimePressure.CRITICAL),
        (-1, 100, TimePressure.CRITICAL),
        (None, None, TimePressure.HEALTHY),
        (None, 100, TimePressure.HEALTHY),
        (50, None, TimePressure.HEALTHY),
        (0, 0, TimePressure.CRITICAL),
    ],
)
def test_classify_time_pressure_boundaries(
    remaining_seconds: float | None,
    budget_seconds: float | None,
    expected: TimePressure,
) -> None:
    assert (
        classify_time_pressure(
            remaining_seconds=remaining_seconds,
            budget_seconds=budget_seconds,
        )
        is expected
    )


def test_runtime_context_is_exploring_with_remaining_budget() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        tools_available=True,
    )

    assert context.phase is RuntimePhase.EXPLORATION
    assert context.remaining_turns == 15
    assert context.time_pressure is TimePressure.HEALTHY
    assert context.context_pressure is ContextPressure.NORMAL
    assert context.tools_available is True


def test_runtime_context_is_converging_at_threshold() -> None:
    context = RuntimeContext.from_state(
        current_step=16,
        max_steps=20,
        tools_available=True,
    )

    assert context.phase is RuntimePhase.CONVERGING
    assert context.remaining_turns == 4


def test_limited_time_pressure_converges_before_turn_threshold() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        tools_available=True,
        time_pressure=TimePressure.LIMITED,
    )

    assert context.remaining_turns == 15
    assert context.phase is RuntimePhase.CONVERGING
    assert context.tools_available is True


def test_critical_time_pressure_converges_before_turn_threshold() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        tools_available=True,
        time_pressure=TimePressure.CRITICAL,
    )

    assert context.remaining_turns == 15
    assert context.phase is RuntimePhase.CONVERGING
    assert context.tools_available is True


def test_healthy_time_pressure_stays_exploratory_before_turn_threshold() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        tools_available=True,
        time_pressure=TimePressure.HEALTHY,
    )

    assert context.remaining_turns == 15
    assert context.phase is RuntimePhase.EXPLORATION


def test_runtime_context_keeps_tools_available_at_step_limit() -> None:
    context = RuntimeContext.from_state(
        current_step=20,
        max_steps=20,
        tools_available=True,
    )

    assert context.phase is RuntimePhase.CONVERGING
    assert context.remaining_turns == 0
    assert context.tools_available is True
