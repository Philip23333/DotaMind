from app.vnext.agent.runtime_context import (
    ContextPressure,
    RuntimeContext,
    RuntimePhase,
    TimePressure,
)
from app.vnext.agent.runtime_prompt import render_runtime_prompt


def test_render_runtime_prompt_for_exploration() -> None:
    context = RuntimeContext.from_state(
        current_step=5,
        max_steps=20,
        finalizing=False,
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "Execution phase:\nexploration" in prompt
    assert "Remaining turns:\n15" in prompt
    assert "Time pressure:\nhealthy" in prompt
    assert "Context pressure:\nnormal" in prompt
    assert "Tools available:\nyes" in prompt
    assert "You may continue gathering information when needed." in prompt
    assert "RuntimePhase.EXPLORATION" not in prompt


def test_render_runtime_prompt_for_converging() -> None:
    context = RuntimeContext.from_state(
        current_step=16,
        max_steps=20,
        finalizing=False,
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "Execution phase:\nconverging" in prompt
    assert "Remaining turns:\n4" in prompt
    assert "The execution budget is becoming constrained." in prompt
    assert "Use additional tools only when they materially improve the answer." in prompt


def test_render_runtime_prompt_for_finalization() -> None:
    context = RuntimeContext.from_state(
        current_step=20,
        max_steps=20,
        finalizing=True,
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "Execution phase:\nfinalization" in prompt
    assert "Remaining turns:\n0" in prompt
    assert "Tools available:\nno" in prompt
    assert "Produce the final user-facing answer now." in prompt
    assert "Tool-use time budget is exhausted." not in prompt


def test_render_runtime_prompt_shows_unknown_remaining_turns() -> None:
    context = RuntimeContext(
        phase=RuntimePhase.EXPLORATION,
        remaining_turns=None,
        time_pressure=TimePressure.HEALTHY,
        context_pressure=ContextPressure.NORMAL,
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "Remaining turns:\nunknown" in prompt
    assert "Remaining turns:\nNone" not in prompt
