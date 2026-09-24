import pytest

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
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "Execution phase:\nconverging" in prompt
    assert "Remaining turns:\n4" in prompt
    assert "The execution budget is becoming constrained." in prompt
    assert "Use additional tools only when they materially improve the answer." in prompt


def test_converging_prompt_has_no_finalization_guidance() -> None:
    context = RuntimeContext.from_state(
        current_step=16,
        max_steps=20,
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "The execution budget is becoming constrained." in prompt
    assert "Further retrieval is unavailable." not in prompt
    assert "Do not infer or fabricate missing facts." not in prompt


def test_render_runtime_prompt_omits_remaining_turns_without_a_step_budget() -> None:
    context = RuntimeContext(
        phase=RuntimePhase.EXPLORATION,
        remaining_turns=None,
        time_pressure=TimePressure.HEALTHY,
        context_pressure=ContextPressure.NORMAL,
        tools_available=True,
    )

    prompt = render_runtime_prompt(context)

    assert "Remaining turns:" not in prompt
    assert "Remaining turns:\nNone" not in prompt


@pytest.mark.parametrize("pressure", ["healthy", "limited", "critical"])
def test_answer_runtime_prompt_has_answer_guidance_and_no_tools(pressure: str) -> None:
    context = RuntimeContext.from_state(
        current_step=22,
        tools_available=False,
        time_pressure=TimePressure(pressure),
    )

    prompt = render_runtime_prompt(context, stage="answer")

    assert "Stage:\nanswer" in prompt
    assert f"Time pressure:\n{pressure}" in prompt
    assert "Tools available:\nno" in prompt
    assert "Remaining turns:" not in prompt
    assert "continue gathering information" not in prompt
    assert "Use additional tools" not in prompt
    if pressure == "healthy":
        assert "Use the evidence already collected" in prompt
    else:
        assert "Prioritize the core conclusion" in prompt
        assert "clearly describe any evidence gaps" in prompt
