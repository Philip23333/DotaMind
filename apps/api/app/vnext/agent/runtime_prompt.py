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
        "Produce the final user-facing answer now.\n"
        "Use the information already available."
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
