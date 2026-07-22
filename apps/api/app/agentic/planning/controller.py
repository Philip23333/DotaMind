import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.agentic.conversation.models import Turn
from app.agentic.planning.decisions import (
    ControllerDecision,
    DirectAnswerDecision,
    RequiredEvidenceResolution,
    ToolPlanDecision,
    normalize_controller_decision,
    resolve_required_evidence,
    validate_controller_decision,
)
from app.agentic.planning.sample_policy import apply_sample_policy
from app.agentic.prompts.controller import (
    ControllerPromptBundle,
    build_controller_prompt,
    render_controller_user_message,
)
from app.agentic.prompts.feedback import render_validation_retry_feedback
from app.agentic.tools import ToolRegistry
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMJSONDecodeError, LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

ControllerResultStatus = Literal["decided", "error"]
ControllerFailureType = Literal["planning_error", "decision_validation_error"]

class AgentControllerResult(BaseModel):
    status: ControllerResultStatus
    reason: str
    decision: ControllerDecision | None = None
    evidence_resolution: RequiredEvidenceResolution = Field(
        default_factory=RequiredEvidenceResolution
    )
    failure_type: ControllerFailureType | None = None
    errors: list[str] = Field(default_factory=list)
    raw_output: dict[str, Any] | None = None
    raw_content: str | None = None
    finish_reason: str | None = None
    prompt_messages: list[dict[str, str]] = Field(default_factory=list)


class AgentController:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        llm: LLMProvider | None = None,
        llm_enabled: bool | None = None,
        planner_max_retries: int | None = None,
    ) -> None:
        self.registry = registry
        self.registry.freeze()
        self.policy = get_policy()
        self._prompt_bundle: ControllerPromptBundle = build_controller_prompt(
            self.registry,
            self.policy,
        )
        settings = get_settings()
        self.llm_enabled = settings.llm_enabled if llm_enabled is None else llm_enabled
        self.llm = llm
        if self.llm is None and self.llm_enabled:
            self.llm = get_llm_provider()
        self.planner_max_retries = (
            planner_max_retries
            if planner_max_retries is not None
            else self.policy.llm.orchestrator.planner_max_retries
        )

    async def decide(
        self,
        query: str,
        game: str = "dota2",
        history: list[Turn] | None = None,
    ) -> AgentControllerResult:
        if not self.llm_enabled or self.llm is None:
            return AgentControllerResult(
                status="error",
                reason="LLM controller is disabled",
                failure_type="planning_error",
                errors=["DOTAMIND_LLM_ENABLED must be true for /api/v1/plan"],
            )

        history_block, user_content = render_controller_user_message(
            query,
            game,
            history or [],
            history_max_chars=self.policy.conversation.history_max_chars,
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._prompt_bundle.system_prompt},
            {"role": "user", "content": user_content},
        ]
        temperature = self.policy.llm.orchestrator.temperature
        max_tokens = max(self.policy.llm.orchestrator.max_tokens, 1200)
        max_attempts = 1 + self.planner_max_retries
        last: AgentControllerResult | None = None
        adapter = TypeAdapter(ControllerDecision)

        for attempt in range(max_attempts):
            is_last_attempt = attempt == max_attempts - 1
            try:
                raw = await self.llm.complete_json(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
            except LLMJSONDecodeError as exc:
                logger.warning("Agent controller JSON decode error: %r", exc)
                if not is_last_attempt:
                    _append_retry_turns(
                        messages,
                        exc.raw_content or "",
                        render_validation_retry_feedback(
                            [f"Previous response was not valid JSON: {exc}"]
                        ),
                    )
                last = AgentControllerResult(
                    status="error",
                    reason="LLM controller failed to return valid JSON",
                    failure_type="planning_error",
                    errors=[f"{type(exc).__name__}: {exc}"],
                    raw_content=exc.raw_content,
                    finish_reason=exc.finish_reason,
                    prompt_messages=_redact_history_from_messages(messages, history_block),
                )
                continue
            except Exception as exc:
                # Unexpected transport/runtime error: terminal, do not retry.
                logger.warning("Agent controller call failed: %r", exc)
                return AgentControllerResult(
                    status="error",
                    reason="LLM controller call failed",
                    failure_type="planning_error",
                    errors=[f"{type(exc).__name__}: {exc}"],
                    prompt_messages=_redact_history_from_messages(messages, history_block),
                )

            try:
                decision = adapter.validate_python(raw)
            except ValidationError as exc:
                logger.warning("Agent controller decision shape error: %r", exc)
                if not is_last_attempt:
                    _append_retry_turns(
                        messages,
                        json.dumps(raw, ensure_ascii=False),
                        render_validation_retry_feedback(
                            [f"Invalid ControllerDecision shape: {exc}"]
                        ),
                    )
                last = AgentControllerResult(
                    status="error",
                    reason="LLM controller returned an invalid decision",
                    failure_type="decision_validation_error",
                    errors=[f"ValidationError: {exc}"],
                    raw_output=raw,
                    prompt_messages=_redact_history_from_messages(messages, history_block),
                )
                continue

            discard_recall_answer = (
                isinstance(decision, DirectAnswerDecision)
                and decision.response_mode != "social"
                and decision.answer is not None
            )
            decision = normalize_controller_decision(decision)
            if discard_recall_answer:
                logger.info(
                    "Agent controller discarded recall answer mode=%s",
                    decision.response_mode,
                )
            if isinstance(decision, ToolPlanDecision):
                # Preserve the established ordering: sample policy mutates the
                # final executable plan exactly once, before its first validation.
                final_plan = apply_sample_policy(decision.plan, self.policy)
                decision = decision.model_copy(update={"plan": final_plan})
                evidence = resolve_required_evidence(
                    final_plan,
                    self.registry,
                )
            else:
                evidence = RequiredEvidenceResolution()

            validation_errors = validate_controller_decision(
                decision,
                history or [],
                self.registry,
                evidence,
            )
            if not validation_errors:
                logger.info(
                    "Agent controller produced kind=%s tools=%s",
                    decision.kind,
                    len(decision.plan.tool_calls)
                    if isinstance(decision, ToolPlanDecision)
                    else 0,
                )
                return AgentControllerResult(
                    status="decided",
                    reason="decision accepted",
                    decision=decision,
                    evidence_resolution=evidence,
                    raw_output=raw,
                    prompt_messages=_redact_history_from_messages(messages, history_block),
                )

            logger.warning("Agent controller decision invalid: %s", validation_errors)
            if not is_last_attempt:
                _append_retry_turns(
                    messages,
                    json.dumps(raw, ensure_ascii=False),
                    render_validation_retry_feedback(validation_errors),
                )
            last = AgentControllerResult(
                status="error",
                reason="LLM controller returned an invalid decision",
                decision=decision,
                evidence_resolution=evidence,
                failure_type="decision_validation_error",
                errors=validation_errors,
                raw_output=raw,
                prompt_messages=_redact_history_from_messages(messages, history_block),
            )

        # Retries exhausted. Every non-returning iteration assigned `last`.
        assert last is not None
        logger.warning(
            "Agent controller exhausted retries attempts=%s", max_attempts
        )
        return last

    @property
    def prompt_versions(self) -> dict[str, str]:
        return dict(self._prompt_bundle.prompt_versions)

    def _system_prompt(self) -> str:
        return self._prompt_bundle.system_prompt

def _redact_history_from_messages(
    messages: list[dict[str, str]],
    history_block: str,
) -> list[dict[str, str]]:
    """Replace the injected history block in the first user message with metadata.

    The full conversation history must not be returned to API clients
    (privacy + response-size).  The controller still used it for its decision;
    this only affects the stored ``prompt_messages`` field in the response.
    """
    if not history_block:
        return list(messages)
    result = list(messages)
    # The initial user message is always at index 1 (after the system message).
    if len(result) > 1 and result[1]["role"] == "user":
        content = result[1]["content"]
        if content.startswith(history_block):
            tail = content[len(history_block):].lstrip("\n")
            n_turns = history_block.count("[第")
            result[1] = {
                "role": "user",
                "content": (
                    f"[conversation_history_redacted: {n_turns} turns injected]\n{tail}"
                ),
            }
    return result


def _append_retry_turns(
    messages: list[dict[str, str]],
    assistant_content: str,
    feedback: str,
) -> None:
    """Echo the model's previous output and the structured feedback, then the
    caller re-invokes the LLM with the grown message list."""
    messages.append({"role": "assistant", "content": assistant_content})
    messages.append({"role": "user", "content": feedback})
