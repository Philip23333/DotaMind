"""Controller feedback renderers with separate validation and recovery contracts."""

from collections.abc import Sequence


def render_validation_retry_feedback(errors: Sequence[str]) -> str:
    return (
        "Your previous response was rejected. Return the FULL corrected "
        "ControllerDecision JSON again, fixing every issue:\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\nDo not explain; only return the corrected JSON."
    )


def render_recovery_rules() -> str:
    """Return dormant V3.2-3 recovery guidance without wiring it into V3.2-2."""

    return """Recovery/replan rules (V3.2-3 only):
- Apply these rules only when the server supplies explicit recovery feedback.
- Return a full ControllerDecision; preserve every successful prior call's
  id, tool, and args, then append only legal evidence-producing calls.
- Do not weaken the output contract, required evidence, or explicit user
  constraints to make a recovery succeed.
- Do not use changed call ids to repeat an equivalent successful call."""
