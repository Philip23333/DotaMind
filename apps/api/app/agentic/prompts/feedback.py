"""Controller feedback renderers with separate validation and recovery contracts."""

import json
from collections.abc import Sequence

from app.agentic.runtime.models import RecoveryFeedback


def render_validation_retry_feedback(errors: Sequence[str]) -> str:
    return (
        "Your previous response was rejected. Return the FULL corrected "
        "ControllerDecision JSON again, fixing every issue:\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\nPreserve every explicit subject, requested result count, and scope "
        "constraint from the current request. Never fix an invalid plan by "
        "dropping or weakening a user requirement; return capability_boundary "
        "if the registered tools cannot honor it."
        + "\nDo not explain; only return the corrected JSON."
    )


def render_recovery_rules() -> str:
    """Return the fixed rules for one missing-evidence replan."""

    return """Recovery/replan rules:
- Apply these rules only when the server supplies explicit recovery feedback.
- Return a full ControllerDecision; preserve every successful prior call's
  id, tool, and args, then append only legal evidence-producing calls.
- Preserve intent, goal, output contract, context, constraints, and required
  evidence exactly.
- Do not use changed call ids to repeat an equivalent successful call."""


def render_recovery_feedback(feedback: RecoveryFeedback) -> str:
    payload = json.dumps(
        feedback.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{render_recovery_rules()}\n\nRecovery feedback:\n{payload}"
