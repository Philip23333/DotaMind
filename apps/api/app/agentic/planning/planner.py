import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.agentic.models import ExecutionPlan
from app.agentic.planning.contracts import (
    STRUCTURED_OUTPUT_CONTRACTS,
    render_planner_contracts,
    render_planner_tools,
    validate_plan_against_catalog,
)
from app.agentic.planning.sample_policy import (
    apply_sample_policy,
    render_sample_policy,
)
from app.agentic.tools import ToolRegistry
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMJSONDecodeError, LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

PlannerStatus = Literal["planned", "insufficient_tools", "error"]

_PLANNER_SYSTEM_PROMPT = """You are the MetaMind v2.5 Planner.

Decide whether the user query can be answered with the currently registered
tools. Return JSON only.

Schema obedience rules:
- Do not invent aliases or synonyms. Copy names exactly from the catalogs
  below: tool names, arg keys, output_contract, and required_evidence entries.
  For example, if the catalog says recent_matches, do not write matches.
- For each tool call, args may contain only that tool's listed arg keys.
- required_evidence may contain only evidence names a selected tool produces,
  and must satisfy the chosen output_contract.
- When an arg accepts a reference, use the declared path shown under that arg.

Scope filters:
- Cross-cutting scope (bracket, weeks_back, position_ids, region_ids,
  game_mode_ids) goes on plan.context ONLY, never on individual tool_call args;
  tool inputs do not carry these fields.
- Set each context field at most once per plan; the same scope applies to every
  call. Leave a field null when the user did not constrain it.
- STRATZ bracket values: HERALD_GUARDIAN, CRUSADER_ARCHON, LEGEND_ANCIENT,
  DIVINE_IMMORTAL, UNCALIBRATED. Map 冠绝/Immortal/Divine to DIVINE_IMMORTAL.
- STRATZ position values + aliases (write into context.position_ids):
  POSITION_1 = carry / 一号位 / 大哥 / safelane core / pos1;
  POSITION_2 = mid / 中单 / 二号位 / pos2;
  POSITION_3 = offlane / 劣势路核心 / 三号位 / pos3;
  POSITION_4 = soft support / 游走 / 四号位 / pos4;
  POSITION_5 = hard support / 硬辅 / 五号位 / pos5.
  Note: "support" alone (without 四号位/五号位/soft/hard qualifier) is ambiguous —
  do NOT default it to POSITION_4; return insufficient_tools or ask the user to
  clarify which support position.
- weeks_back (STRATZ only) = number of recent completed weeks to fetch as
  separate per-week buckets, 1..8; set it for window queries ("最近两周" -> 2).
  Leave null for the default (latest completed week). STRATZ returns per-week
  evidence so the answer can describe trend; prefer phrasing 最近 N 个已完成周
  over 本周 (the current STRATZ week is partial). Never emit raw week epochs.
- region_ids / game_mode_ids: ONLY stratz.hero_daily_trends supports them
  (STRATZ schema limit — laneOutcome/heroVsHeroMatchup/stats do not accept these
  args). If the user asks for region/mode filtering on any other tool, return
  insufficient_tools and state the filter is unavailable; do NOT set
  context.region_ids/game_mode_ids and hand them to an unsupported tool (the
  handler would silently ignore them, producing a misleading answer).
- position_ids: honored by pair_lane_outcome / hero_position_stats;
  stratz.lane_meta_global IGNORES position by design (global lane-pair view). If
  the user wants a position-scoped lane query, re-route to pair_lane_outcome or
  return insufficient_tools — do not set position_ids on a lane_meta_global plan
  expecting it to filter.

References:
- Use "$<previous_call_id>.<declared_output_path>". The call id is any earlier
  tool call id you chose; the path must be a declared_output_path of that call.

Output contract:
- output_contract must be one of the contracts listed below; do not invent
  values like meta_list or tool_results.
- For natural_language_answer there is no preset required_evidence — list the
  evidence kinds your chosen tools produce.

Decision:
- If the registered tools can produce relevant evidence, plan the calls.
- If they cannot, return insufficient_tools.
- If a name is ambiguous and tools cannot resolve it, expose candidates or
  return insufficient_tools.

Supported in this development version:
- enemy hero counter / hero matchup evidence queries
- hero ally synergy / teammate combo evidence queries (队友 X 选什么配合 -> stratz.hero_synergy_ranking; distinct from hero_matchup_ranking which is enemy counter-pick)
- position-filtered candidate ranking (4 号位克制 Lina -> 先 matchup/synergy，再 stratz.filter_heroes_by_position，candidate_rows 用 ref $<rank>.data.candidate_rows；保留原 ranking 证据 + 附位置样本)
- lane outcome evidence queries (含对线补刀 cs_count / 碾压度 stomp_win_count/stomp_loss_count — pair_lane_outcome / lane_meta_global)
- global lane-pair meta evidence queries (强势 / 常见对线组合 -> stratz.lane_meta_global)
- hero position stats with win rate (某位置胜率最高/出场最多、某英雄最强位置 -> stratz.hero_position_stats; uses selection_mode strong/popular like lane_meta)
- hero daily win-rate trend (Lina 最近还强吗 / 胜率走势 -> stratz.hero_daily_trends; day-grain, NOT weeks_back — do not set weeks_back for this tool)
- team evidence collection queries
- player evidence queries (查某玩家战绩 / 近 N 场什么英雄胜率高 -> stratz.player_profile / player_recent_matches / player_hero_performance; numeric Steam32 id only, no name search in v1)
- role-based hero meta evidence queries
- patch impact evidence queries

Lane-pair meta selection_mode (stratz.lane_meta_global):
- selection_mode maps to user intent. 强势 / 胜率高 / 上分 -> "strong"
  (sort by wilson_rating desc — Wilson lower bound of the match win rate,
  confidence-aware; tie-break match_count desc). 常见 / 出场多 / 热门 ->
  "popular" (sort by match_count desc). Default is "strong"; pass "popular"
  explicitly for pick-volume queries.
- Sample-size floor: pick the mode from the Sample-size policy table below
  (strict for 'strong' to drop small-sample high-winrate noise; relaxed for
  'popular' to keep the full pick distribution). Write the chosen number into
  min_sample_size explicitly.

Position stats selection_mode (stratz.hero_position_stats):
- same strong/popular semantics, applies to BOTH hero_id and position_id branches.
  'strong' = wilson_rating desc (某位置胜率最高 / 某英雄最强位置); 'popular' =
  match_count desc (出场最多 / 常见位置).
- Sample-size floor: same as lane_meta — strict for 'strong', relaxed for
  'popular', per the Sample-size policy table.

Hero matchup/synergy ranking (stratz.hero_matchup_ranking / hero_synergy_ranking):
- primary ranking is STRATZ `synergy` (the advantage/synergy formula) — do NOT
  re-rank these by win rate. Each row also carries `pair_wilson_rating` (Wilson
  lower bound of the pairing's win rate) as a sample-confidence CO-SIGNAL: among
  comparable synergy prefer higher pair_wilson, and flag low pair_wilson as
  small-sample/uncertain. Never merge synergy and pair_wilson into one score.
- `wilson_rating`/`pair_wilson_rating` use z=1.96 (95% CI); STRATZ documents the
  method but not its z, so treat the value as "same method", not "identical".

Player evidence queries (stratz.player_profile / player_recent_matches /
player_hero_performance):
- v1 takes a numeric Steam32 id (steamAccountId) directly — NO name search. If
  the query names a player without a numeric id (e.g. "查 Arteezy 的战绩"),
  return insufficient_tools stating name search is not supported; do NOT invent
  an id. Pull the digits verbatim from queries like "853634884 近期战绩".
- player_profile = identity/overview ("这个 ID 是谁 / 概览"). Pick it when the
  question is about the player; pair OPTIONALLY with recent_matches or
  hero_performance for match questions — do NOT force a full chain, only call
  what the question needs.
- player_recent_matches = per-match rows + win/loss summary ("最近 N 场战绩 /
  战绩"); win is native isVictory, not derived.
- player_hero_performance = per-hero win rates ("近 N 场什么英雄胜率高 / 胜率
  最高的英雄"). win_rate is locally derived (winCount/matchCount).
- Param semantics (easy to confuse — map carefully):
  - "近 N 场" / "最近 N 场" stats -> match_take=N (the per-hero match SAMPLE
    size), NOT the outer take.
  - "返回前 N 个英雄" / "top N heroes" -> take=N (hero rows returned).
  - "最近一周" / "最近 7 天" / "within last D days" -> days=D.
  - "至少玩过 N 场" -> min_match_count=N.
- Player tools do NOT set weeks_back (that is STRATZ per-week bucketing for hero
  meta tools only). bracket on plan.context applies as usual (recent_matches ->
  bracketIds 0-8; hero_performance -> rankIds 0-80); position_ids applies too.
  region_ids/game_mode_ids are NOT supported on player tools — same rule as
  other non-hero_daily_trends tools (return insufficient_tools if the user
  insists on them).

Unsupported for now:
- claim verification

{sample_policy}

Tools:
{tools}

Output contracts:
{contracts}

Return JSON in one of these shapes.

If unsupported:
{"status":"insufficient_tools","reason":"...","plan":null}

If supported:
{
  "status": "planned",
  "reason": "...",
  "plan": {
    "intent": "pair_lane_outcome",
    "goal": "Win rate of Wraith King laning with Ancient Apparition in Legend bracket.",
    "output_contract": "natural_language_answer",
    "context": {
      "bracket": ["LEGEND_ANCIENT"],
      "weeks_back": null,
      "position_ids": null,
      "region_ids": null,
      "game_mode_ids": null
    },
    "tool_calls": [
      {"id":"resolve_sk","tool":"resolve_hero","args":{"query":"骷髅王"}},
      {"id":"resolve_aa","tool":"resolve_hero","args":{"query":"冰魂"}},
      {"id":"pair_lane","tool":"stratz.pair_lane_outcome","args":{
        "hero_id":"$resolve_sk.data.hero.hero_id",
        "partner_hero_id":"$resolve_aa.data.hero.hero_id",
        "is_with":true
      }}
    ],
    "required_evidence":["hero_identity","pair_lane_winrate","sample_size"],
    "constraints":{"max_tool_calls":6,"allow_mock":false}
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
        planner_max_retries: int | None = None,
    ) -> None:
        self.registry = registry
        self.policy = get_policy()
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

    async def plan(self, query: str, game: str = "dota2") -> AgenticPlannerResult:
        if not self.llm_enabled or self.llm is None:
            return AgenticPlannerResult(
                status="error",
                reason="LLM planner is disabled",
                errors=["METAMIND_LLM_ENABLED must be true for /api/v1/plan"],
            )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": f"game={game}\nquery={query}"},
        ]
        temperature = self.policy.llm.orchestrator.temperature
        max_tokens = max(self.policy.llm.orchestrator.max_tokens, 1200)
        max_attempts = 1 + self.planner_max_retries
        last: AgenticPlannerResult | None = None

        for attempt in range(max_attempts):
            is_last_attempt = attempt == max_attempts - 1
            try:
                raw = await self.llm.complete_json(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
            except LLMJSONDecodeError as exc:
                logger.warning("Agentic planner JSON decode error: %r", exc)
                if not is_last_attempt:
                    _append_retry_turns(
                        messages,
                        exc.raw_content or "",
                        _retry_feedback(
                            [f"Previous response was not valid JSON: {exc}"]
                        ),
                    )
                last = AgenticPlannerResult(
                    status="error",
                    reason="LLM planner failed to return a valid planning envelope",
                    errors=[f"{type(exc).__name__}: {exc}"],
                    raw_content=exc.raw_content,
                    finish_reason=exc.finish_reason,
                    prompt_messages=messages,
                )
                continue
            except Exception as exc:
                # Unexpected transport/runtime error: terminal, do not retry.
                logger.warning("Agentic planner call failed: %r", exc)
                return AgenticPlannerResult(
                    status="error",
                    reason="LLM planner call failed",
                    errors=[f"{type(exc).__name__}: {exc}"],
                    prompt_messages=messages,
                )

            try:
                envelope = PlannerEnvelope.model_validate(raw)
            except ValidationError as exc:
                logger.warning("Agentic planner envelope shape error: %r", exc)
                if not is_last_attempt:
                    _append_retry_turns(
                        messages,
                        json.dumps(raw, ensure_ascii=False),
                        _retry_feedback([f"Invalid envelope shape: {exc}"]),
                    )
                last = AgenticPlannerResult(
                    status="error",
                    reason="LLM planner failed to return a valid planning envelope",
                    errors=[f"ValidationError: {exc}"],
                    raw_output=raw,
                    prompt_messages=messages,
                )
                continue

            # Intentional terminal states — do not retry.
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

            # status == "planned": a missing plan is a shape error, not terminal.
            if envelope.plan is None:
                if not is_last_attempt:
                    _append_retry_turns(
                        messages,
                        json.dumps(raw, ensure_ascii=False),
                        _retry_feedback(
                            ["status 'planned' requires a non-null plan"]
                        ),
                    )
                last = AgenticPlannerResult(
                    status="error",
                    reason="LLM planner returned planned status without a plan",
                    errors=["planned status requires plan"],
                    raw_output=raw,
                    prompt_messages=messages,
                )
                continue

            # Sample-size policy backfill (stage 1): fills the policy `default`
            # for any sample arg the LLM omitted/nulled, recording each under
            # plan.metadata["policy_applied"]. Done here, inside plan() and
            # before validate, so AgenticPlannerResult.plan IS the final plan —
            # no graph node rewrites it afterwards.
            envelope.plan = apply_sample_policy(envelope.plan, self.policy)

            validation_errors = self.validate_plan(envelope.plan)
            if not validation_errors:
                logger.info(
                    "Agentic planner produced intent=%s output_contract=%s tools=%s",
                    envelope.plan.intent,
                    envelope.plan.output_contract,
                    len(envelope.plan.tool_calls),
                )
                return AgenticPlannerResult(
                    status="planned",
                    reason=envelope.reason,
                    plan=envelope.plan,
                    raw_output=raw,
                    prompt_messages=messages,
                )

            logger.warning("Agentic planner plan invalid: %s", validation_errors)
            if not is_last_attempt:
                _append_retry_turns(
                    messages,
                    json.dumps(raw, ensure_ascii=False),
                    _retry_feedback(validation_errors),
                )
            last = AgenticPlannerResult(
                status="error",
                reason="LLM planner returned an invalid plan",
                plan=envelope.plan,
                errors=validation_errors,
                raw_output=raw,
                prompt_messages=messages,
            )

        # Retries exhausted. Every non-returning iteration assigned `last`.
        assert last is not None
        logger.warning(
            "Agentic planner exhausted retries attempts=%s", max_attempts
        )
        return last

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
        sample_policy = render_sample_policy(self.policy, self.registry)
        return (
            _PLANNER_SYSTEM_PROMPT.replace("{tools}", tools)
            .replace("{contracts}", contracts)
            .replace("{sample_policy}", sample_policy)
        )


def _append_retry_turns(
    messages: list[dict[str, str]],
    assistant_content: str,
    feedback: str,
) -> None:
    """Echo the model's previous output and the structured feedback, then the
    caller re-invokes the LLM with the grown message list."""
    messages.append({"role": "assistant", "content": assistant_content})
    messages.append({"role": "user", "content": feedback})


def _retry_feedback(errors: list[str]) -> str:
    return (
        "Your previous response was rejected. Return the FULL corrected plan "
        "JSON again (same envelope shape), fixing every issue:\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\nDo not explain; only return the corrected JSON."
    )


def planner_payload(result: AgenticPlannerResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
