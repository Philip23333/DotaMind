import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionPlan
from app.agentic.registry import ToolRegistry
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

PlannerStatus = Literal["planned", "insufficient_tools", "error"]

_PLANNER_SYSTEM_PROMPT = """You are the MetaMind v2.5 Planner.

You must decide whether the user query can be answered with the currently
registered tools. Return JSON only.

Current allowed tools:
- resolve_hero: resolves a Dota 2 hero name or alias to a canonical hero id.
- stratz.hero_vs_hero_matchup: returns hero-vs-hero matchup statistics. Its
  hero_id argument MUST come from resolve_hero using the reference
  "$resolve_target.data.hero.hero_id".

Supported in this development version:
- enemy hero counter / hero matchup evidence queries.

Unsupported for now:
- team reports
- meta hero rankings
- patch impact
- claim verification
- hero synergy / teammate combo advice
- final natural-language recommendations

If unsupported, return:
{"status":"insufficient_tools","reason":"...","plan":null}

If supported, return:
{
  "status": "planned",
  "reason": "...",
  "plan": {
    "intent": "counter_pick",
    "goal": "...",
    "output_contract": "tool_results",
    "tool_calls": [
      {"id":"resolve_target","tool":"resolve_hero","args":{"query":"<enemy hero>"}},
      {
        "id":"get_matchups",
        "tool":"stratz.hero_vs_hero_matchup",
        "args":{"hero_id":"$resolve_target.data.hero.hero_id","take":5}
      }
    ],
    "required_evidence": ["hero_identity","matchup_win_rate","sample_size"],
    "constraints": {"max_tool_calls": 6, "allow_mock": false}
  }
}
"""


class PlannerEnvelope(BaseModel):
    status: PlannerStatus
    reason: str = ""
    plan: ExecutionPlan | None = None


class AgenticPlannerResult(BaseModel):
    status: PlannerStatus
    reason: str
    plan: ExecutionPlan | None = None
    errors: list[str] = Field(default_factory=list)


class AgenticPlanner:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        llm: LLMProvider | None = None,
        llm_enabled: bool | None = None,
    ) -> None:
        self.registry = registry
        self.policy = get_policy()
        settings = get_settings()
        self.llm_enabled = settings.llm_enabled if llm_enabled is None else llm_enabled
        self.llm = llm
        if self.llm is None and self.llm_enabled:
            self.llm = get_llm_provider()

    async def plan(self, query: str, game: str = "dota2") -> AgenticPlannerResult:
        if not self.llm_enabled or self.llm is None:
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner is disabled",
                errors=["METAMIND_LLM_ENABLED must be true for /api/v1/plan"],
            )

        try:
            raw = await self.llm.complete_json(
                [
                    {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"game={game}\nquery={query}"},
                ],
                temperature=self.policy.llm.orchestrator.temperature,
                max_tokens=max(self.policy.llm.orchestrator.max_tokens, 1200),
            )
            envelope = PlannerEnvelope.model_validate(raw)
        except Exception as exc:
            logger.warning("Agentic planner failed: %r", exc)
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner failed to return a valid planning envelope",
                errors=[f"{type(exc).__name__}: {exc}"],
            )

        if envelope.status == "insufficient_tools":
            return AgenticPlannerResult(
                status="insufficient_tools",
                reason=envelope.reason,
                plan=None,
            )
        if envelope.status == "error":
            return AgenticPlannerResult(
                status="error",
                reason=envelope.reason or "LLM planner returned error",
                errors=[envelope.reason or "LLM planner returned error"],
            )
        if envelope.plan is None:
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner returned planned status without a plan",
                errors=["planned status requires plan"],
            )

        validation_errors = self.validate_plan(envelope.plan)
        if validation_errors:
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner returned an invalid plan",
                plan=envelope.plan,
                errors=validation_errors,
            )

        return AgenticPlannerResult(
            status="planned",
            reason=envelope.reason,
            plan=envelope.plan,
        )

    def validate_plan(self, plan: ExecutionPlan) -> list[str]:
        errors = []
        registered = {definition.name for definition in self.registry.list()}
        for call in plan.tool_calls:
            if call.tool not in registered:
                errors.append(f"unknown tool: {call.tool}")

        if plan.constraints.allow_mock:
            errors.append("constraints.allow_mock must be false")
        if len(plan.tool_calls) > plan.constraints.max_tool_calls:
            errors.append(
                "plan exceeds max_tool_calls "
                f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
            )

        required = set(plan.required_evidence)
        missing_required = {
            "hero_identity",
            "matchup_win_rate",
            "sample_size",
        } - required
        if plan.intent == "counter_pick" and missing_required:
            errors.append(
                "counter_pick plan missing required evidence: "
                + ", ".join(sorted(missing_required))
            )

        for call in plan.tool_calls:
            if call.tool == "stratz.hero_vs_hero_matchup":
                hero_id = call.args.get("hero_id")
                if hero_id != "$resolve_target.data.hero.hero_id":
                    errors.append(
                        "stratz.hero_vs_hero_matchup.hero_id must be "
                        "$resolve_target.data.hero.hero_id"
                    )

        return errors


def planner_payload(result: AgenticPlannerResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
