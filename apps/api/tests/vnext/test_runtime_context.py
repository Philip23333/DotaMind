from app.vnext.agent.runtime_context import (
    ContextPressure,
    RuntimeContext,
    RuntimePhase,
    TimePressure,
)


def test_runtime_context_is_exploring_with_remaining_budget() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        finalizing=False,
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
        finalizing=False,
        tools_available=True,
    )

    assert context.phase is RuntimePhase.CONVERGING
    assert context.remaining_turns == 4


def test_runtime_context_forces_tools_off_during_finalization() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        finalizing=True,
        tools_available=True,
    )

    assert context.phase is RuntimePhase.FINALIZATION
    assert context.tools_available is False
