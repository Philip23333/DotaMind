import asyncio
from typing import Any

from app.agentic.answer import AnswerSynthesizer
from app.agentic.evidence import build_evidence_graph
from app.agentic.models import ExecutionPlan, QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.tools.dota_catalog_tools import HeroAttributesInput, ResolveHeroInput
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.llm.provider import ToolCallResult


def test_answer_synthesizer_reports_unsupported_output_contract() -> None:
    plan = ExecutionPlan(
        intent="team_report",
        goal="Explain a team.",
        output_contract="team_report_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())

    answer = _synthesize(plan, graph)

    assert answer.status == "unsupported_output_contract"
    assert answer.confidence == 0


def test_answer_synthesizer_exposes_mock_data_note() -> None:
    plan = ExecutionPlan(
        intent="patch_impact",
        goal="Patch summary.",
        output_contract="patch_impact_report",
        required_evidence=["patch_records"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="patch",
                tool="patch.get_records",
                status="error",
                source=ToolSource(name="Fixture", kind="fixture", status="mocked"),
                latency_ms=1,
                error="boom",
            )
        ],
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert any(note.code == "mock_source_detected" for note in answer.data_notes)


def test_answer_synthesizer_builds_patch_impact_report() -> None:
    plan = ExecutionPlan(
        intent="patch_impact",
        goal="Summarize latest patch.",
        output_contract="patch_impact_report",
        required_evidence=["patch_records"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="patch",
                tool="patch.get_records",
                status="ok",
                latency_ms=1,
                source=ToolSource(name="Local", kind="local_json"),
                data={
                    "patch": "7.41d",
                    "released_at": "2026-06-05",
                    "changes": [],
                    "change_count": 3,
                    "buff_count": 2,
                    "nerf_count": 1,
                },
            )
        ],
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert answer.status == "ok"
    assert answer.answer_type == "patch_impact_report"
    assert "7.41d" in answer.summary


def test_answer_synthesizer_builds_role_meta_report() -> None:
    plan = ExecutionPlan(
        intent="role_meta",
        goal="Find strong offlane heroes.",
        output_contract="role_meta_report",
        required_evidence=["hero_stats"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="meta",
                tool="opendota.hero_stats_by_role",
                status="ok",
                latency_ms=1,
                source=ToolSource(name="OpenDota", kind="public_api"),
                data={
                    "role": "offlane",
                    "hero_count": 1,
                    "heroes": [{"localized_name": "Tidehunter", "win_rate": 0.55}],
                },
            )
        ],
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert answer.status == "ok"
    assert answer.recommendations[0].subject == "Tidehunter"
    assert graph.data_quality.min_sample_size == 1


def test_answer_synthesizer_natural_language_answer_uses_llm() -> None:
    plan = ExecutionPlan(
        intent="freeform",
        goal="Answer from evidence.",
        output_contract="natural_language_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())

    answer = asyncio.run(
        AnswerSynthesizer(llm=FakeLLM(), llm_enabled=True).synthesize(plan, graph)
    )

    assert answer.status == "ok"
    assert answer.summary == "Grounded answer."


def test_answer_synthesizer_natural_language_answer_errors_when_llm_disabled() -> None:
    plan = ExecutionPlan(
        intent="freeform",
        goal="Answer from evidence.",
        output_contract="natural_language_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())

    answer = asyncio.run(AnswerSynthesizer(llm_enabled=False).synthesize(plan, graph))

    assert answer.status == "error"
    assert answer.confidence == 0


def test_answer_synthesizer_streams_natural_language_deltas() -> None:
    plan = ExecutionPlan(
        intent="freeform",
        goal="Answer from evidence.",
        output_contract="natural_language_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())
    deltas: list[str] = []

    answer = asyncio.run(
        AnswerSynthesizer(llm=StreamingFakeLLM(), llm_enabled=True).synthesize(
            plan,
            graph,
            on_delta=deltas.append,
        )
    )

    assert deltas == ["Grounded", " answer."]
    assert answer.summary == "Grounded answer."


def test_natural_language_answer_receives_catalog_rules_and_real_evidence() -> None:
    registry = _registry()
    resolve_definition = registry.get("resolve_hero")
    attributes_definition = registry.get("dota.hero_attributes")
    resolve_data = resolve_definition.handler(
        ResolveHeroInput(query="Lina"), QueryContext()
    )
    attributes_data = attributes_definition.handler(
        HeroAttributesInput(hero_id=25), QueryContext()
    )
    plan = ExecutionPlan(
        intent="hero_attributes",
        goal="Explain Lina's base attributes and gains.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="attributes",
                tool="dota.hero_attributes",
                args={"hero_id": "$resolve.data.hero.hero_id"},
            ),
        ],
        required_evidence=["hero_identity", "hero_attributes"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="resolve",
                tool="resolve_hero",
                status="ok",
                data=resolve_data,
                source=resolve_definition.source,
                latency_ms=0,
            ),
            ToolResult(
                tool_call_id="attributes",
                tool="dota.hero_attributes",
                status="ok",
                data=attributes_data,
                source=attributes_definition.source,
                latency_ms=0,
            ),
        ],
        registry,
    )
    llm = CapturingFakeLLM()

    answer = asyncio.run(
        AnswerSynthesizer(llm=llm, llm_enabled=True).synthesize(
            plan,
            graph,
            current_query="莉娜的基础属性是什么？",
        )
    )

    assert answer.status == "ok"
    assert len(llm.messages) == 1
    system = llm.messages[0][0]["content"]
    user = llm.messages[0][1]["content"]
    assert "Use current_query for the user's latest presentation wording" in system
    assert "reconstructed_goal for the complete request" in system
    assert "Preserve explicit focus, exclusions, requested result count" in system
    assert '"current_query": "莉娜的基础属性是什么？"' in user
    assert '"reconstructed_goal": "Explain Lina\'s base attributes and gains."' in user
    assert "goal=Explain Lina's base attributes and gains." not in user
    assert "use only normalized text and values" in system
    assert "base attribute values from per-level gains" in system
    assert "ability level arrays" in system
    assert "level 10/15/20/25 and left/right side" in system
    assert "Scepter grants/upgrades" in system
    assert "final item from a recipe item" in system
    assert "snapshot patch and generated_at" in system
    assert (
        "When the user is asking for Catalog-backed hero, ability, talent, or item definitions"
        in system
    )
    assert (
        "Do not disclose Catalog patch/generated_at in an answer whose requested facts are "
        "STRATZ statistics"
        in system
    )
    assert "must never be labeled as a STRATZ patch" in system
    assert "Catalog patch/generated_at metadata describes only Catalog snapshots" not in system
    assert "Never infer item-build strength" in system
    assert "组件（中文名（English）） | 价格 | 属性" in system
    assert "include the recipe scroll as an explicit row" in system
    assert "Use cost_breakdown to verify and report the total price" in system
    assert "explain a mismatch in natural language only when" in system
    assert "row with no display attributes may say `无`" in system
    assert "never claim that the item has no recipe scroll" in system
    assert "For a basic item, show only" in system
    assert "must never expose internal schema or token names" in system
    assert "`has_shard = true`" in system
    assert "`special_bonus_*`" in system
    assert "魔晶升级, 神杖升级, or 先天技能" in system
    assert "must not create a separate 相关天赋 section" in system
    assert "For a complete hero ability-list query" in system
    assert "技能分类汇总 or 相关天赋" in system
    assert "等级 | 左侧天赋（中文 / English） | 右侧天赋（中文 / English）" in system
    assert "For a single-ability query, output only the one ability" in system
    assert "full talent tree unless the user explicitly" in system
    assert "Hero recommendations are ranked by `wilson_rating`" not in system
    assert "When lane_meta_row/position_stat evidence carries filters.selection_mode" in system
    assert "the PRIMARY ranking is STRATZ `synergy`" in system
    assert "'kind':'hero_attributes'" in user.replace(" ", "")
    assert "'strength_base'" in user
    assert "'strength_gain'" in user
    assert "'patch':'7.41e'" in user.replace(" ", "")
    assert "'generated_at'" in user


def test_natural_language_prompt_separates_catalog_metadata_from_stratz_lane_stats() -> None:
    registry = _registry()
    resolve_definition = registry.get("resolve_hero")
    pair_definition = registry.get("stratz.pair_lane_outcome")
    resolve_data = resolve_definition.handler(
        ResolveHeroInput(query="Lina"), QueryContext()
    )
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Compare Storm Spirit and Lina lane and match outcomes.",
        output_contract="natural_language_answer",
        context=QueryContext(
            bracket=["DIVINE_IMMORTAL"],
            position_ids=["POSITION_2"],
        ),
        required_evidence=["hero_identity", "pair_lane_outcome", "sample_size"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="resolve_lina",
                tool="resolve_hero",
                status="ok",
                data=resolve_data,
                source=resolve_definition.source,
                latency_ms=0,
            ),
            ToolResult(
                tool_call_id="pair_lane",
                tool="stratz.pair_lane_outcome",
                status="ok",
                source=pair_definition.source,
                latency_ms=0,
                data={
                    "hero_id": 17,
                    "partner_hero_id": 25,
                    "is_with": False,
                    "filters": {
                        "bracket_basic_ids": ["DIVINE_IMMORTAL"],
                        "position_ids": ["POSITION_2"],
                        "weeks_back": 1,
                    },
                    "weekly_buckets": [
                        {
                            "week_epoch": 1785369600,
                            "week_index": 1,
                            "window_label": "latest_completed_week",
                            "rows": [
                                {
                                    "match_count": 1479,
                                    "win_count": 159,
                                    "loss_count": 799,
                                    "draw_count": 362,
                                    "stomp_win_count": 14,
                                    "stomp_loss_count": 145,
                                    "lane_win_count": 173,
                                    "lane_loss_count": 944,
                                    "lane_draw_count": 362,
                                    "lane_win_rate": 0.117,
                                    "lane_loss_rate": 0.6383,
                                    "lane_draw_rate": 0.2448,
                                    "match_win_count": 684,
                                    "match_win_rate": 0.4625,
                                    "cs_count": 78118,
                                }
                            ],
                        }
                    ],
                },
            ),
        ],
        registry,
    )
    llm = CapturingFakeLLM()

    answer = asyncio.run(
        AnswerSynthesizer(llm=llm, llm_enabled=True).synthesize(plan, graph)
    )

    assert answer.status == "ok"
    system = llm.messages[0][0]["content"]
    user = llm.messages[0][1]["content"]
    assert (
        "Do not disclose Catalog patch/generated_at in an answer whose requested facts are "
        "STRATZ statistics"
        in system
    )
    assert (
        "Do not infer gameplay causes, comeback ability, mid-game strength, late-game strength"
        in system
    )
    assert "pair_lane_outcome" in user
    assert "7.41e" in user
    assert "generated_at" in user


def test_pair_lane_answer_removes_catalog_metadata_and_unsupported_causal_claim() -> None:
    registry = _registry()
    resolve_definition = registry.get("resolve_hero")
    pair_definition = registry.get("stratz.pair_lane_outcome")
    resolve_data = resolve_definition.handler(
        ResolveHeroInput(query="Lina"), QueryContext()
    )
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Compare Storm Spirit and Lina lane and match outcomes.",
        output_contract="natural_language_answer",
        required_evidence=["hero_identity", "pair_lane_outcome"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="resolve_lina",
                tool="resolve_hero",
                status="ok",
                data=resolve_data,
                source=resolve_definition.source,
                latency_ms=0,
            ),
            ToolResult(
                tool_call_id="pair_lane",
                tool="stratz.pair_lane_outcome",
                status="ok",
                source=pair_definition.source,
                latency_ms=0,
                data={
                    "hero_id": 17,
                    "partner_hero_id": 25,
                    "is_with": False,
                    "filters": {"position_ids": ["POSITION_2"]},
                    "weekly_buckets": [
                        {
                            "week_epoch": 1785369600,
                            "week_index": 1,
                            "window_label": "latest_completed_week",
                            "rows": [
                                {
                                    "match_count": 100,
                                    "lane_win_count": 12,
                                    "lane_loss_count": 60,
                                    "lane_draw_count": 28,
                                    "lane_win_rate": 0.12,
                                    "lane_loss_rate": 0.6,
                                    "lane_draw_rate": 0.28,
                                    "match_win_count": 46,
                                    "match_win_rate": 0.46,
                                }
                            ],
                        }
                    ],
                },
            ),
        ],
        registry,
    )
    llm = UnsafeCapturingFakeLLM()

    answer = asyncio.run(
        AnswerSynthesizer(llm=llm, llm_enabled=True).synthesize(plan, graph)
    )

    assert answer.status == "ok"
    assert "7.41e" not in answer.summary
    assert "2026-08-09" not in answer.summary
    assert "中后期" not in answer.summary
    assert "翻盘能力" not in answer.summary
    assert "不能据此判断具体比赛阶段或后续表现" in answer.summary


def _synthesize(plan: ExecutionPlan, graph):
    return asyncio.run(AnswerSynthesizer(llm_enabled=False).synthesize(plan, graph))


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )


class FakeLLM:
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        return "Grounded answer."

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        return {
            "summary": "Grounded answer.",
            "claims": [],
            "recommendations": [],
            "limitations": [],
            "confidence": 0.7,
        }

    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> ToolCallResult | None:
        return None


class StreamingFakeLLM(FakeLLM):
    async def stream_complete(self, *args, **kwargs):
        yield "Grounded"
        yield " answer."


class CapturingFakeLLM(FakeLLM):
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        self.messages.append([dict(message) for message in messages])
        return "Grounded answer."


class UnsafeCapturingFakeLLM(CapturingFakeLLM):
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        self.messages.append([dict(message) for message in messages])
        return (
            "根据 Catalog 快照版本 7.41e（2026-08-09T19:05:36.363376+00:00），"
            "蓝猫对线劣势但说明中后期有较强的翻盘能力。"
        )


def test_natural_language_prompt_asks_for_weekly_trend() -> None:
    from app.agentic.prompts.answer import NATURAL_LANGUAGE_SYSTEM_PROMPT

    prompt = NATURAL_LANGUAGE_SYSTEM_PROMPT
    assert "week_index" in prompt
    assert "week_epoch" in prompt
    assert "trend" in prompt
    assert "missing_week_epochs" in prompt
    assert "pair_lane_outcome" in prompt
    assert "lane_win_rate" in prompt
    assert "match_win_rate" in prompt
    assert "filters.position_ids" in prompt
    assert "multiple completed weeks" in prompt
