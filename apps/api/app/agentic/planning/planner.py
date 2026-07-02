import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionPlan
from app.agentic.planning.contracts import (
    STRUCTURED_OUTPUT_CONTRACTS,
    render_planner_contracts,
    render_planner_tools,
    validate_plan_against_catalog,
)
from app.agentic.tools import ToolRegistry
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMJSONDecodeError, LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

PlannerStatus = Literal["planned", "insufficient_tools", "error"]

_PLANNER_SYSTEM_PROMPT = """You are the MetaMind v2.5 Planner.

You must decide whether the user query can be answered with the currently
registered tools. Return JSON only.

Schema obedience rules:
- Use exact names only. Tool names, args keys, output_contract, and
  required_evidence entries must be copied exactly from the catalogs below.
- Do not invent synonyms for args or evidence. For example, if the catalog says
  current_only, do not write current_roster; if it says recent_matches, do not
  write matches.
- For each tool call, args may contain only that tool's allowed_arg_keys.
- required_evidence may contain only exact evidence names produced by selected
  tools and allowed by the output contract.
- If a tool arg accepts a reference, use exactly the declared reference path.

Scope filter rules:
- Cross-cutting scope filters (bracket, week, position, region, game_mode)
  MUST be set on plan.context, NEVER on individual tool_call args.
- Tool input_models do not carry these fields. Putting them in args is a
  schema violation.
- Set each context field at most once per plan; the same scope applies to
  every tool call. Leave a field null when the user did not constrain it.
- STRATZ bracket values: HERALD_GUARDIAN, CRUSADER_ARCHON, LEGEND_ANCIENT,
  DIVINE_IMMORTAL. Map 冠绝/Immortal/Divine to DIVINE_IMMORTAL.
- STRATZ position values: POSITION_1 through POSITION_5.

QueryContext schema (set on plan.context):
- bracket: list[str] | null  — STRATZ RankBracketBasicEnum values.
- week: int | null           — STRATZ week epoch seconds.
- position_ids: list[str] | null — STRATZ MatchPlayerPositionType values.
- region_ids: list[str] | null   — reserved.
- game_mode_ids: list[str] | null — reserved.

Current allowed tools:
{tools}

Supported in this development version:
- enemy hero counter / hero matchup evidence queries
- lane outcome evidence queries
- team evidence collection queries
- role-based hero meta evidence queries
- patch impact evidence queries

Output contract catalog:
{contracts}

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
    "intent": "pair_lane_outcome",
    "goal": "Win rate of Wraith King laning with Ancient Apparition in Legend bracket.",
    "output_contract": "natural_language_answer",
    "context": {
      "bracket": ["LEGEND_ANCIENT"],
      "week": null,
      "position_ids": null,
      "region_ids": null,
      "game_mode_ids": null
    },
    "tool_calls": [
      {"id":"resolve_sk","tool":"resolve_hero","args":{"query":"骷髅王"}},
      {"id":"resolve_aa","tool":"resolve_hero","args":{"query":"冰魂"}},
      {
        "id":"pair_lane",
        "tool":"stratz.pair_lane_outcome",
        "args":{
          "hero_id":"$resolve_sk.data.hero.hero_id",
          "partner_hero_id":"$resolve_aa.data.hero.hero_id",
          "is_with":true
        }
      }
    ],
    "required_evidence":["hero_identity","pair_lane_winrate","sample_size"],
    "constraints":{"max_tool_calls":6,"allow_mock":false}
  }
}

When an arg accepts a reference, use "$<previous_call_id>.<declared_output_path>".
The call id may be any earlier tool call id you chose. The declared output path
must match the tool contract shown above.

If ambiguity cannot be resolved by tools, expose the candidates or return
insufficient_tools.

For patch impact evidence, use patch.get_records and include patch_records in
required_evidence. Add patch.hero_changes and patch.item_changes when the user
asks about hero or item changes.

For role_meta_report, required_evidence may only use hero_stats, role_fit, and
sample_size. Do not require field names like hero_id, hero_name, win_rate, or
pick_rate as evidence kinds.

Tool-specific notes:
- natural_language_answer has no contract-level required_evidence, so you must
  fill required_evidence explicitly based on what the chosen tools produce.
  Examples: pair_lane_outcome → ["hero_identity","pair_lane_winrate","sample_size"];
  hero_matchup_ranking → ["hero_identity","matchup_ranking_row","sample_size"];
  lane_meta_global → ["lane_meta_row","sample_size"];
  hero_position_stats → ["position_stat","sample_size"].
- stratz.hero_matchup_ranking.side only supports "vs" in this version. Ally
  synergy ("with") is not yet wired through the underlying GraphQL.
- stratz.lane_meta_global returns high-sample lane pair rows sorted by
  match_count; this surfaces COMMON pairs, not necessarily the STRONGEST by
  win rate. Frame any natural-language answer accordingly.
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
    raw_output: dict[str, Any] | None = None
    raw_content: str | None = None
    finish_reason: str | None = None
    prompt_messages: list[dict[str, str]] = Field(default_factory=list)


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
            messages = [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": f"game={game}\nquery={query}"},
            ]
            raw = await self.llm.complete_json(
                messages,
                temperature=self.policy.llm.orchestrator.temperature,
                max_tokens=max(self.policy.llm.orchestrator.max_tokens, 1200),
            )
            envelope = PlannerEnvelope.model_validate(raw)
        except LLMJSONDecodeError as exc:
            logger.warning("Agentic planner failed: %r", exc)
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner failed to return a valid planning envelope",
                errors=[f"{type(exc).__name__}: {exc}"],
                raw_content=exc.raw_content,
                finish_reason=exc.finish_reason,
                prompt_messages=messages if "messages" in locals() else [],
            )
        except Exception as exc:
            logger.warning("Agentic planner failed: %r", exc)
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner failed to return a valid planning envelope",
                errors=[f"{type(exc).__name__}: {exc}"],
                prompt_messages=messages if "messages" in locals() else [],
            )

        if envelope.status == "insufficient_tools":
            return AgenticPlannerResult(
                status="insufficient_tools",
                reason=envelope.reason,
                plan=None,
                raw_output=raw,
                prompt_messages=messages,
            )
        if envelope.status == "error":
            return AgenticPlannerResult(
                status="error",
                reason=envelope.reason or "LLM planner returned error",
                errors=[envelope.reason or "LLM planner returned error"],
                raw_output=raw,
                prompt_messages=messages,
            )
        if envelope.plan is None:
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner returned planned status without a plan",
                errors=["planned status requires plan"],
                raw_output=raw,
                prompt_messages=messages,
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
                raw_output=raw,
                prompt_messages=messages,
            )

        return AgenticPlannerResult(
            status="planned",
            reason=envelope.reason,
            plan=envelope.plan,
            raw_output=raw,
            prompt_messages=messages,
        )

    def validate_plan(self, plan: ExecutionPlan) -> list[str]:
        logger.info(
            "Agentic planner validate intent=%s output_contract=%s in_meta_list=%s",
            plan.intent,
            plan.output_contract,
            plan.output_contract in STRUCTURED_OUTPUT_CONTRACTS,
        )
        return validate_plan_against_catalog(plan, self.registry)

    def _system_prompt(self) -> str:
        tools = render_planner_tools(self.registry)
        contracts = render_planner_contracts(self.registry)
        return _PLANNER_SYSTEM_PROMPT.replace("{tools}", tools).replace(
            "{contracts}",
            contracts,
        )


def planner_payload(result: AgenticPlannerResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
