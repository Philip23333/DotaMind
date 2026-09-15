"""Render the ephemeral runtime context instruction for one model turn."""

from __future__ import annotations

from app.vnext.agent.runtime_context import RuntimeContext, RuntimePhase

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
    RuntimePhase.FINALIZATION: (
        "Further retrieval is unavailable.\n\n"
        "Produce the final user-facing answer now using the evidence already available.\n\n"
        "Prioritize delivering a useful answer within the remaining execution time.\n\n"
        "Preserve the user's requested scope when feasible.\n"
        "If the available evidence is incomplete, clearly distinguish verified results\n"
        "from parts that could not be completed. Do not infer or fabricate missing facts.\n\n"
        "If exhaustive presentation would prevent completing the response, compress the\n"
        "presentation while preserving the most important verified results and clearly\n"
        "state any omitted coverage."
    ),
}


def render_runtime_prompt(context: RuntimeContext) -> str:
    """Render one runtime snapshot without reading or mutating runtime state."""

    remaining_turns = (
        str(context.remaining_turns)
        if context.remaining_turns is not None
        else "unknown"
    )
    return "\n".join(
        [
            "Runtime state:",
            "",
            "Execution phase:",
            context.phase.value,
            "",
            "Remaining turns:",
            remaining_turns,
            "",
            "Time pressure:",
            context.time_pressure.value,
            "",
            "Context pressure:",
            context.context_pressure.value,
            "",
            "Tools available:",
            "yes" if context.tools_available else "no",
            "",
            "Guidance:",
            _GUIDANCE[context.phase],
        ]
    )


__all__ = ["render_runtime_prompt"]
