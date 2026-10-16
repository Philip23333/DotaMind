"""Render the ephemeral runtime context instruction for one model turn."""

from __future__ import annotations

from typing import Literal

from app.vnext.agent.runtime_context import (
    REQUEST_TIMEZONE,
    RuntimeContext,
    RuntimePhase,
    TimePressure,
)

_GUIDANCE: dict[RuntimePhase, str] = {
    RuntimePhase.EXPLORATION: (
        "You may continue gathering information when needed.\n"
        "Prefer efficient progress toward answering the user's request."
    ),
    RuntimePhase.CONVERGING: (
        "The execution budget is becoming constrained.\n\n"
        "Prioritize completing the user's request.\n"
        "Avoid optional exploration or redundant verification.\n\n"
        "Use additional tools only when they materially improve the answer."
    ),
}

_ANSWER_GUIDANCE: dict[TimePressure, str] = {
    TimePressure.HEALTHY: "Use the evidence already collected to answer the user's request.",
    TimePressure.LIMITED: (
        "Prioritize the core conclusion from the available evidence.\n"
        "Simplify optional detail and clearly describe any evidence gaps."
    ),
    TimePressure.CRITICAL: (
        "Prioritize the core conclusion from the available evidence.\n"
        "Simplify optional detail and clearly describe any evidence gaps."
    ),
}


def render_runtime_prompt(
    context: RuntimeContext,
    *,
    stage: Literal["execution", "answer"] = "execution",
) -> str:
    """Render one runtime snapshot without reading or mutating runtime state."""

    if stage == "answer":
        sections = [
            "Runtime state:",
            "",
            "Stage:",
            "answer",
            "",
            "Time pressure:",
            context.time_pressure.value,
            "",
            "Tools available:",
            "yes" if context.tools_available else "no",
            "",
            "Guidance:",
            _ANSWER_GUIDANCE[context.time_pressure],
        ]
        return "\n".join([*sections, *_request_time_sections(context)])

    sections = [
        "Runtime state:",
        "",
        "Execution phase:",
        context.phase.value,
    ]
    if context.remaining_turns is not None:
        sections.extend(["", "Remaining turns:", str(context.remaining_turns)])
    sections.extend(
        [
            "",
            "Time pressure:",
            context.time_pressure.value,
            "",
            "Tools available:",
            "yes" if context.tools_available else "no",
            "",
            "Guidance:",
            _GUIDANCE[context.phase],
        ]
    )
    return "\n".join([*sections, *_request_time_sections(context)])


def _request_time_sections(context: RuntimeContext) -> list[str]:
    if context.request_time is None:
        return []
    return [
        "",
        "Request time anchor:",
        "Date: " + context.request_time[:10],
        "Datetime: " + context.request_time,
        "Timezone: " + REQUEST_TIMEZONE,
        "Interpret relative dates using this request-start anchor in both stages. "
        "It is not a source update time or a match timestamp.",
    ]


__all__ = ["render_runtime_prompt"]
