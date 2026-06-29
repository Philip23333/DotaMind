import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionPlan
from app.agentic.registry import ToolRegistry
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

PlannerStatus = Literal["planned", "insufficient_tools", "error"]
STRUCTURED_OUTPUT_CONTRACTS = {
    "patch_impact_report",
    "role_meta_report",
    "team_recent_report",
    "hero_matchup_report",
    "draft_advice",
}
ALLOWED_OUTPUT_CONTRACTS = STRUCTURED_OUTPUT_CONTRACTS | {"natural_language_answer"}
KNOWN_EVIDENCE_KINDS = {
    "hero_identity",
    "matchup_win_rate",
    "lane_outcome",
    "team_identity",
    "recent_matches",
    "current_players",
    "team_hero_usage",
    "match_detail_sample",
    "hero_stats",
    "role_fit",
    "sample_size",
    "patch_records",
    "hero_patch_changes",
    "item_patch_changes",
    "patch_buff_count",
    "patch_nerf_count",
}
ROLE_META_EVIDENCE_KINDS = {"hero_stats", "role_fit", "sample_size"}

_PLANNER_SYSTEM_PROMPT = """You are the MetaMind v2.5 Planner.

You must decide whether the user query can be answered with the currently
registered tools. Return JSON only.

Current allowed tools:
{tools}

Supported in this development version:
- enemy hero counter / hero matchup evidence queries
- lane outcome evidence queries
- team evidence collection queries
- role-based hero meta evidence queries
- patch impact evidence queries

Allowed output_contract values:
- patch_impact_report
- role_meta_report
- team_recent_report
- hero_matchup_report
- draft_advice
- natural_language_answer

Do not output meta_list. meta_list is only the internal whitelist of structured
contracts. If the user asks for an answer outside that whitelist but the
registered tools can provide relevant evidence, use output_contract
"natural_language_answer".

Unsupported for now:
- claim verification
- hero synergy / teammate combo advice

If unsupported, return:
{"status":"insufficient_tools","reason":"...","plan":null}

If supported, return:
{
  "status": "planned",
  "reason": "...",
  "plan": {
    "intent": "counter_pick",
    "goal": "...",
    "output_contract": "draft_advice",
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

For stratz.hero_vs_hero_matchup and stratz.lane_outcome, hero_id MUST come
from resolve_hero using "$resolve_target.data.hero.hero_id". Do not hardcode
hero ids.

For OpenDota team evidence, resolve the team first, then use
"$resolve_team.data.team.team_id" for team tools. If ambiguity cannot be
resolved by tools, expose the candidates or return insufficient_tools.

For patch impact evidence, use patch.get_records and include patch_records in
required_evidence. Add patch.hero_changes and patch.item_changes when the user
asks about hero or item changes.

For role_meta_report, required_evidence may only use hero_stats, role_fit, and
sample_size. Do not require field names like hero_id, hero_name, win_rate, or
pick_rate as evidence kinds.
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
                    {"role": "system", "content": self._system_prompt()},
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

        logger.info(
            "Agentic planner produced intent=%s output_contract=%s tools=%s",
            envelope.plan.intent,
            envelope.plan.output_contract,
            len(envelope.plan.tool_calls),
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
        logger.info(
            "Agentic planner validate intent=%s output_contract=%s in_meta_list=%s",
            plan.intent,
            plan.output_contract,
            plan.output_contract in STRUCTURED_OUTPUT_CONTRACTS,
        )
        if plan.output_contract not in ALLOWED_OUTPUT_CONTRACTS:
            errors.append(f"unknown output_contract: {plan.output_contract}")

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
        unknown_evidence = sorted(required - KNOWN_EVIDENCE_KINDS)
        if unknown_evidence:
            errors.append(
                "unknown required_evidence: " + ", ".join(unknown_evidence)
            )

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
        if plan.intent == "counter_pick" and plan.output_contract != "draft_advice":
            errors.append("counter_pick plan must use output_contract=draft_advice")

        if plan.output_contract == "patch_impact_report":
            tools = {call.tool for call in plan.tool_calls}
            if "patch.get_records" not in tools:
                errors.append("patch_impact_report plan must use patch.get_records")
            if "patch_records" not in required:
                errors.append(
                    "patch_impact_report plan must require patch_records evidence"
                )

        if plan.output_contract == "role_meta_report":
            invalid_role_meta_evidence = sorted(required - ROLE_META_EVIDENCE_KINDS)
            if invalid_role_meta_evidence:
                errors.append(
                    "role_meta_report required_evidence must use only "
                    "hero_stats, role_fit, sample_size; got "
                    + ", ".join(invalid_role_meta_evidence)
                )
            if "hero_stats" not in required:
                errors.append("role_meta_report plan must require hero_stats evidence")

        for call in plan.tool_calls:
            if call.tool in {"stratz.hero_vs_hero_matchup", "stratz.lane_outcome"}:
                hero_id = call.args.get("hero_id")
                if hero_id != "$resolve_target.data.hero.hero_id":
                    errors.append(
                        f"{call.tool}.hero_id must be "
                        "$resolve_target.data.hero.hero_id"
                    )

        return errors

    def _system_prompt(self) -> str:
        tools = "\n".join(
            f"- {definition.name}: {definition.description}"
            for definition in self.registry.list()
        )
        return _PLANNER_SYSTEM_PROMPT.replace("{tools}", tools)


def planner_payload(result: AgenticPlannerResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
