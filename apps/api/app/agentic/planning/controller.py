import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.agentic.conversation.models import (
    ControllerContextExecutionSummary,
    ConversationMessage,
)
from app.agentic.planning.decisions import (
    ControllerDecision,
    RequiredEvidenceResolution,
    ToolPlanDecision,
    normalize_controller_decision,
    resolve_required_evidence,
    validate_controller_decision,
)
from app.agentic.planning.recovery import validate_replan_decision
from app.agentic.planning.sample_policy import apply_sample_policy
from app.agentic.prompts.controller import (
    ControllerPromptBundle,
    build_controller_prompt,
    render_controller_messages,
    render_controller_system_prompt,
)
from app.agentic.prompts.feedback import (
    render_recovery_feedback,
    render_validation_retry_feedback,
)
from app.agentic.runtime.models import RecoveryFeedback
from app.agentic.tools import ToolRegistry
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMJSONDecodeError, LLMProvider, get_llm_provider
from app.observability import emit_event, record_controller

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
        runtime_context: Mapping[str, str] | None = None,
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
        self.runtime_context = dict(runtime_context or {})
        self._default_request_time = datetime.now(UTC).isoformat()
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
        recent_messages: list[ConversationMessage] | None = None,
        *,
        retrieved_messages: list[ConversationMessage] | None = None,
        controller_context_summaries: list[
            ControllerContextExecutionSummary
        ] | None = None,
        recovery_feedback: RecoveryFeedback | None = None,
        recovery_baseline_decision: ToolPlanDecision | None = None,
        request_time: str | None = None,
    ) -> AgentControllerResult:
        if (recovery_feedback is None) != (recovery_baseline_decision is None):
            raise ValueError(
                "recovery feedback and baseline decision must be provided together"
            )
        if not self.llm_enabled or self.llm is None:
            return AgentControllerResult(
                status="error",
                reason="LLM controller is disabled",
                failure_type="planning_error",
                errors=["DOTAMIND_LLM_ENABLED must be true for /api/v1/plan"],
            )

        conversation_messages = render_controller_messages(
            query,
            game,
            recent_messages or [],
            retrieved_messages,
        )

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": render_controller_system_prompt(
                    self._prompt_bundle.system_prompt,
                    game,
                    self.runtime_context,
                    request_time or self._default_request_time,
                    controller_context_summaries,
                ),
            },
            *conversation_messages,
        ]
        history_message_count = len(conversation_messages) - 1
        if recovery_feedback is not None and recovery_baseline_decision is not None:
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            recovery_baseline_decision.model_dump(mode="json"),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                    {
                        "role": "user",
                        "content": render_recovery_feedback(recovery_feedback),
                    },
                ]
            )
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
                record_controller("error", "planning_error")
                emit_event(
                    logger,
                    "controller_failed",
                    status="error",
                    failure_code="planning_error",
                )
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
                    prompt_messages=_redact_history_from_messages(messages, history_message_count),
                )
                continue
            except Exception as exc:
                # Unexpected transport/runtime error: terminal, do not retry.
                record_controller("error", "planning_error")
                emit_event(
                    logger,
                    "controller_failed",
                    status="error",
                    failure_code="planning_error",
                )
                return AgentControllerResult(
                    status="error",
                    reason="LLM controller call failed",
                    failure_type="planning_error",
                    errors=[f"{type(exc).__name__}: {exc}"],
                    prompt_messages=_redact_history_from_messages(messages, history_message_count),
                )

            try:
                decision = adapter.validate_python(raw)
            except ValidationError as exc:
                record_controller("error", "decision_validation_error")
                emit_event(
                    logger,
                    "controller_failed",
                    status="error",
                    failure_code="decision_validation_error",
                )
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
                    prompt_messages=_redact_history_from_messages(messages, history_message_count),
                )
                continue

            decision = normalize_controller_decision(decision)
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
                [
                    *list(retrieved_messages or []),
                    *list(recent_messages or []),
                ],
                self.registry,
                evidence,
                current_query=query,
            )
            if (
                recovery_feedback is not None
                and recovery_baseline_decision is not None
            ):
                validation_errors.extend(
                    validate_replan_decision(
                        decision,
                        recovery_baseline_decision,
                        recovery_feedback,
                        self.registry,
                        remaining_tool_budget=recovery_feedback.remaining_tool_budget,
                    )
                )
            if not validation_errors:
                record_controller("ok")
                emit_event(logger, "controller_completed", status="ok")
                return AgentControllerResult(
                    status="decided",
                    reason="decision accepted",
                    decision=decision,
                    evidence_resolution=evidence,
                    raw_output=raw,
                    prompt_messages=_redact_history_from_messages(messages, history_message_count),
                )

            record_controller("error", "decision_validation_error")
            emit_event(
                logger,
                "controller_failed",
                status="error",
                failure_code="decision_validation_error",
            )
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
                prompt_messages=_redact_history_from_messages(messages, history_message_count),
            )

        # Retries exhausted. Every non-returning iteration assigned `last`.
        assert last is not None
        return last

    @property
    def prompt_versions(self) -> dict[str, str]:
        return dict(self._prompt_bundle.prompt_versions)

    def _system_prompt(self) -> str:
        return self._prompt_bundle.system_prompt

def _redact_history_from_messages(
    messages: list[dict[str, str]],
    history_message_count: int,
) -> list[dict[str, str]]:
    """Replace injected prior messages with metadata before public persistence.

    The full conversation history must not be returned to API clients
    (privacy + response-size).  The controller still used it for its decision;
    this only affects the stored ``prompt_messages`` field in the response.
    """
    if history_message_count <= 0:
        return list(messages)
    result = list(messages)
    start = 1
    end = min(start + history_message_count, len(result) - 1)
    result[start:end] = [
        {
            "role": "user",
            "content": (
                f"[conversation_history_redacted: {history_message_count} messages injected]"
            ),
        }
    ]
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
