from types import SimpleNamespace

from app.vnext.agent.runtime_context import (
    ContextPressure,
    RuntimeContext,
    RuntimePhase,
    TimePressure,
)


def _runtime(
    *,
    finalizing: bool = False,
    remaining_turns: int | None = None,
    tools_available: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        finalizing=finalizing,
        remaining_turns=remaining_turns,
        tools_available=tools_available,
    )


def test_runtime_context_is_exploring_with_remaining_budget() -> None:
    context = RuntimeContext.from_runtime(
        _runtime(finalizing=False, remaining_turns=10)
    )

    assert context.phase is RuntimePhase.EXPLORATION
    assert context.remaining_turns == 10
    assert context.time_pressure is TimePressure.HEALTHY
    assert context.context_pressure is ContextPressure.NORMAL
    assert context.tools_available is True


def test_runtime_context_is_converging_at_threshold() -> None:
    context = RuntimeContext.from_runtime(_runtime(remaining_turns=3))

    assert context.phase is RuntimePhase.CONVERGING
    assert context.remaining_turns == 3


def test_runtime_context_forces_tools_off_during_finalization() -> None:
    context = RuntimeContext.from_runtime(
        _runtime(finalizing=True, remaining_turns=10, tools_available=True)
    )

    assert context.phase is RuntimePhase.FINALIZATION
    assert context.tools_available is False
