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
  DIVINE_IMMORTAL. Map 冠绝/Immortal/Divine to DIVINE_IMMORTAL.
- STRATZ position values: POSITION_1 through POSITION_5.
- weeks_back (STRATZ only) = number of recent completed weeks to fetch as
  separate per-week buckets, 1..8; set it for window queries ("最近两周" -> 2).
  Leave null for the default (latest completed week). STRATZ returns per-week
  evidence so the answer can describe trend; prefer phrasing 最近 N 个已完成周
  over 本周 (the current STRATZ week is partial). Never emit raw week epochs.

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
- lane outcome evidence queries (含对线补刀 cs_count / 碾压度 stomp_win_count/stomp_loss_count — pair_lane_outcome / lane_meta_global)
- global lane-pair meta evidence queries (强势 / 常见对线组合 -> stratz.lane_meta_global)
- hero position stats with win rate (某位置胜率最高/出场最多、某英雄最强位置 -> stratz.hero_position_stats; uses selection_mode strong/popular like lane_meta)
- team evidence collection queries
- role-based hero meta evidence queries
- patch impact evidence queries

Lane-pair meta selection_mode (stratz.lane_meta_global):
- selection_mode maps to user intent. 强势 / 胜率高 / 上分 -> "strong"
  (sort by match_win_rate desc, tie-break match_count desc); for "strong"
  raise min_sample_size (e.g. 500-800) so small-sample high win-rate noise is
  dropped before ranking. 常见 / 出场多 / 热门 -> "popular" (sort by match_count
  desc). Default is "strong"; pass "popular" explicitly for pick-volume queries.

Position stats selection_mode (stratz.hero_position_stats):
- same strong/popular semantics, applies to BOTH hero_id and position_id branches.
  'strong' = match_win_rate desc (某位置胜率最高 / 某英雄最强位置); 'popular' =
  match_count desc (出场最多 / 常见位置). Raise min_sample_size for 'strong' to
  drop small-sample noise; lower it (or 0) for 'popular' to keep the full
  position distribution.

Unsupported for now:
- claim verification

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
        return _PLANNER_SYSTEM_PROMPT.replace("{tools}", tools).replace(
            "{contracts}",
            contracts,
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
