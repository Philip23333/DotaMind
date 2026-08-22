import asyncio
from typing import Any

from app.agentic.answer import AnswerSynthesizer
from app.agentic.evidence import (
    EvidenceDataQuality,
    EvidenceGraph,
    EvidenceItem,
    build_evidence_graph,
)
from app.agentic.models import ExecutionPlan, QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.runtime.streaming import (
    ObserverStreamEvent,
    bind_observer_attempt_index,
    bind_stream_event_publisher,
    reset_observer_attempt_index,
    reset_stream_event_publisher,
)
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


def test_answer_synthesizer_publishes_full_test_observer_exchange(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: Settings(test_observer_enabled=True),
    )
    plan = ExecutionPlan(
        intent="freeform",
        goal="Answer from evidence.",
        output_contract="natural_language_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())
    events: list[ObserverStreamEvent] = []
    token = bind_stream_event_publisher(events.append)
    attempt_token = bind_observer_attempt_index(1)
    try:
        answer = asyncio.run(
            AnswerSynthesizer(llm=FakeLLM(), llm_enabled=True).synthesize(
                plan,
                graph,
                current_query="question",
            )
        )
    finally:
        reset_observer_attempt_index(attempt_token)
        reset_stream_event_publisher(token)

    assert answer.summary == "Grounded answer."
    assert [event.kind for event in events] == ["model_prompt", "model_output"]
    assert events[0].stage == "answer"
    assert events[0].attempt_index == 1
    assert events[0].payload["messages"][-1]["content"]
    assert events[1].payload == {"format": "text", "content": "Grounded answer."}


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
    assert "snapshot patch and generated_at" in system
    assert "internal_name values" in system
    assert "Never infer item-build strength" not in system
    assert "`has_shard = true`" not in system
    assert "`special_bonus_*`" not in system
    assert "ability level arrays" not in system
    assert "level 10/15/20/25 and left/right side" not in system
    assert "组件（中文名（English）） | 价格 | 属性" not in system
    assert "pair_lane_outcome" not in system
    assert "filters.selection_mode" not in system
    assert "STRATZ `synergy`" not in system
    assert "calendar days" not in system
    assert '"kind": "hero_attributes"' in user
    assert '"strength_base"' in user
    assert '"strength_gain"' in user
    assert '"patch": "7.41e"' in user
    assert '"generated_at"' in user


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
    assert "requested facts are solely STRATZ statistics" in system
    assert "attribute each source's metadata locally" in system
    assert (
        "Do not infer gameplay causes, comeback ability, mid-game strength, late-game strength"
        in system
    )
    assert "组件（中文名（English）） | 价格 | 属性" not in system
    assert "For a complete hero ability-list query" not in system
    assert "pair_lane_outcome" in user
    assert "7.41e" in user
    assert "generated_at" in user


def test_pair_lane_answer_preserves_llm_wording_without_keyword_rewrite() -> None:
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
    llm = BoundaryPhraseCapturingFakeLLM()

    answer = asyncio.run(
        AnswerSynthesizer(llm=llm, llm_enabled=True).synthesize(plan, graph)
    )

    assert answer.status == "ok"
    assert answer.summary == (
        "蓝猫的对线胜率与整局胜率存在差异。\n"
        "这个差异不能证明其中后期更强，也不能证明其具有翻盘能力。"
    )


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


class BoundaryPhraseCapturingFakeLLM(CapturingFakeLLM):
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        self.messages.append([dict(message) for message in messages])
        return (
            "蓝猫的对线胜率与整局胜率存在差异。\n"
            "这个差异不能证明其中后期更强，也不能证明其具有翻盘能力。"
        )


def test_natural_language_prompt_selects_weekly_pair_lane_rules() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    graph = EvidenceGraph(
        intent="pair_lane_outcome",
        required_evidence=["pair_lane_outcome", "sample_size"],
        data_quality=EvidenceDataQuality(completeness=1.0),
    )

    prompt = render_natural_language_system_prompt(graph)
    assert "week_index" in prompt
    assert "week_epoch" in prompt
    assert "trend" in prompt
    assert "missing_week_epochs" in prompt
    assert "pair_lane_outcome" in prompt
    assert "lane_win_rate" in prompt
    assert "match_win_rate" in prompt
    assert "filters.position_ids" in prompt
    assert "multiple completed weeks" in prompt
    assert "Do not add unsupported gameplay interpretations or hypotheses" in prompt
    assert "attribute it to that evidence" in prompt
    assert "label it clearly as a hypothesis" not in prompt
    assert "组件（中文名（English）） | 价格 | 属性" not in prompt
    assert "For a complete hero ability-list query" not in prompt
    assert "filters.selection_mode" not in prompt


def test_natural_language_prompt_selects_ability_without_talent_or_item_rules() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    graph = EvidenceGraph(
        intent="hero_ability",
        required_evidence=["hero_identity", "hero_ability"],
        data_quality=EvidenceDataQuality(completeness=1.0),
    )

    prompt = render_natural_language_system_prompt(graph)

    assert "ability level arrays" in prompt
    assert "For a complete hero ability-list query" in prompt
    assert "For a single-ability query, output only the one ability" in prompt
    assert "full talent tree unless the user explicitly" in prompt
    assert "`has_shard = true`" in prompt
    assert "`special_bonus_*`" in prompt
    assert "魔晶升级, 神杖升级, or 先天技能" in prompt
    assert "level 10/15/20/25 and left/right side" not in prompt
    assert "组件（中文名（English）） | 价格 | 属性" not in prompt
    assert "pair_lane_outcome" not in prompt


def test_natural_language_prompt_adds_talent_rules_only_for_talent_evidence() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    graph = EvidenceGraph(
        intent="hero_abilities_and_talents",
        required_evidence=["hero_ability", "hero_talent_tree"],
        data_quality=EvidenceDataQuality(completeness=1.0),
    )

    prompt = render_natural_language_system_prompt(graph)

    assert "For a complete hero ability-list query" in prompt
    assert "level 10/15/20/25 and left/right side" in prompt
    assert "等级 | 左侧天赋（中文 / English） | 右侧天赋（中文 / English）" in prompt
    assert "组件（中文名（English）） | 价格 | 属性" not in prompt


def test_natural_language_prompt_selects_item_recipe_rules() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    graph = EvidenceGraph(
        intent="item_recipe",
        required_evidence=["item_definition", "item_recipe"],
        data_quality=EvidenceDataQuality(completeness=1.0),
    )

    prompt = render_natural_language_system_prompt(graph)

    assert "final item from a recipe item" in prompt
    assert "组件（中文名（English）） | 价格 | 属性" in prompt
    assert "include the recipe scroll as an explicit row" in prompt
    assert "Use cost_breakdown to verify and report the total price" in prompt
    assert "Never infer item-build strength" in prompt
    assert "For a complete hero ability-list query" not in prompt
    assert "pair_lane_outcome" not in prompt


def test_natural_language_prompt_keeps_catalog_and_stratz_metadata_local_in_mixed_answer() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    graph = EvidenceGraph(
        intent="mixed_definition_and_stats",
        required_evidence=["hero_ability", "pair_lane_outcome"],
        tool_results=[
            ToolResult(
                tool_call_id="stats",
                tool="stratz.pair_lane_outcome",
                status="ok",
                source=ToolSource(name="STRATZ", kind="public_graphql_api"),
                latency_ms=0,
                data={},
            )
        ],
        data_quality=EvidenceDataQuality(completeness=1.0),
    )

    prompt = render_natural_language_system_prompt(graph)

    assert "Disclose the Catalog snapshot patch and generated_at" in prompt
    assert "requested facts are solely STRATZ statistics" in prompt
    assert "attribute each source's metadata locally" in prompt
    assert "For a complete hero ability-list query" in prompt
    assert "For pair_lane_outcome evidence" in prompt


def test_natural_language_prompt_selects_ranking_and_daily_rules_independently() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    ranking_prompt = render_natural_language_system_prompt(
        EvidenceGraph(
            intent="hero_synergy",
            required_evidence=["hero_synergy_ranking_row", "sample_size"],
            data_quality=EvidenceDataQuality(completeness=1.0),
        )
    )
    daily_prompt = render_natural_language_system_prompt(
        EvidenceGraph(
            intent="hero_daily_trend",
            required_evidence=["hero_daily_trend"],
            data_quality=EvidenceDataQuality(completeness=1.0),
        )
    )

    assert "the PRIMARY ranking is STRATZ `synergy`" in ranking_prompt
    assert "pair_wilson_rating" in ranking_prompt
    assert "week_index" in ranking_prompt
    assert "calendar days" not in ranking_prompt
    assert "calendar days" in daily_prompt
    assert "do not invent week buckets" in daily_prompt
    assert "pair_wilson_rating" not in daily_prompt
    assert "week_index" not in daily_prompt


def test_natural_language_prompt_adds_aligned_ti_status_example_for_match_evidence() -> None:
    from app.agentic.prompts.answer import render_natural_language_system_prompt

    match_prompt = render_natural_language_system_prompt(
        EvidenceGraph(
            intent="competition_latest_status",
            required_evidence=[
                "competition_identity",
                "tournament_stage",
                "match_schedule",
                "match_state",
                "series_score",
            ],
            data_quality=EvidenceDataQuality(completeness=1.0),
        )
    )
    hero_prompt = render_natural_language_system_prompt(
        EvidenceGraph(
            intent="hero_attributes",
            required_evidence=["hero_attributes"],
            data_quality=EvidenceDataQuality(completeness=1.0),
        )
    )
    match_details_prompt = render_natural_language_system_prompt(
        EvidenceGraph(
            intent="match_details",
            required_evidence=[
                "match_result",
                "cross_source_match_mapping",
                "player_scoreboard",
                "match_draft",
            ],
            data_quality=EvidenceDataQuality(completeness=1.0),
        )
    )
    progress_prompt = render_natural_language_system_prompt(
        EvidenceGraph(
            intent="hero_build",
            required_evidence=[
                "match_result",
                "player_scoreboard",
                "player_match_progress",
            ],
            data_quality=EvidenceDataQuality(completeness=1.0),
        )
    )

    assert "presentation-only" in match_prompt
    assert "# {赛事名}最新战况" in match_prompt
    assert "group fixtures by their UTC calendar date" in match_prompt
    assert (
        "future dates in ascending order, then historical dates in descending order"
        in match_prompt
    )
    assert "## 后续赛程" in match_prompt
    assert "## 历史赛果" in match_prompt
    assert "Render each UTC date once" in match_prompt
    assert "# {赛事名}最新战况" not in hero_prompt
    assert "# {赛事全名} — {队伍A} vs {队伍B} 比赛详情" in match_details_prompt
    assert "compact game" in match_details_prompt
    assert "full draft, then player scoreboards" in match_details_prompt
    assert "##### {队伍A}（{天辉 / 夜魇}）" in match_details_prompt
    assert "Use the OpenDota draft `order` only" in match_details_prompt
    assert (
        "**{队伍A}（{队伍A系列赛得分}） ： {队伍B}（{队伍B系列赛得分}）**"
        in match_details_prompt
    )
    assert "| 顺序 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |" in match_details_prompt
    assert "| 选择 | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | — | — |" in match_details_prompt
    assert (
        "| 禁用 | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} | {英雄} |"
        in match_details_prompt
    )
    assert "（Ban 1）" not in match_details_prompt
    assert "（Pick 1）" not in match_details_prompt
    assert "| 选手 / 英雄 | K/D/A | 经济 | 装备 |" in match_details_prompt
    assert "| 选手 / 英雄 | K/D/A | 经济 | 装备 | 技能加点与天赋 |" not in match_details_prompt
    assert "| {选手} · {英雄}（{等级}） | {K}/{D}/{A} | {22,790} |" in match_details_prompt
    assert "主装备：{物品名称}" in match_details_prompt
    assert "Do not put skill-leveling or talent information" in match_details_prompt
    assert "standard thousands separators" in match_details_prompt
    assert "Do not emit raw HTML such as `<sub>` or `<br>`" in match_details_prompt
    assert "For a The International schedule or" not in match_details_prompt
    assert "#### 出装、加点与天赋" in progress_prompt
    assert "**出门装**" in progress_prompt
    assert "| 相对开局时间 | 购买 |" in progress_prompt
    assert "Aggregate every purchase" in progress_prompt
    assert "item_price` is at least 150" in progress_prompt
    assert "Do not apply the price filter to 出门装" in progress_prompt
    assert "omit that line when there is no" in progress_prompt
    assert "Render **技能加点** as one compact arrow sequence, not a table" in progress_prompt
    assert "`attribute_bonus` mapping is named `全属性 +2`" in progress_prompt
    assert "fixed 10/15/20/25-level talent timing" in progress_prompt
    assert "Do not treat historical purchases as a recommendation" in progress_prompt
    assert "do not infer historical" in progress_prompt
    assert "talent-tree sides or tiers" in progress_prompt
    assert "#### 出装、加点与天赋" not in match_details_prompt


def test_answer_messages_exclude_raw_tool_results_and_unrequired_match_progress() -> None:
    from app.agentic.prompts.answer import render_natural_language_answer_messages

    plan = ExecutionPlan(
        intent="match_details",
        goal="Show the match result and scoreboard.",
        output_contract="natural_language_answer",
        required_evidence=["match_result", "player_scoreboard"],
    )
    graph = EvidenceGraph(
        intent=plan.intent,
        required_evidence=plan.required_evidence,
        tool_results=[
            ToolResult(
                tool_call_id="details",
                tool="opendota.match_details",
                status="ok",
                latency_ms=0,
                data={"raw_tool_result_sentinel": "must-not-reach-answer"},
            )
        ],
        evidence=[
            EvidenceItem(
                id="result",
                kind="match_result",
                subject="match",
                value={"winner": "TEAM VISION"},
                tool_call_id="details",
                tool="opendota.match_details",
            ),
            EvidenceItem(
                id="scoreboard",
                kind="player_scoreboard",
                subject="match",
                value={"players": []},
                tool_call_id="details",
                tool="opendota.match_details",
            ),
            EvidenceItem(
                id="progress",
                kind="player_match_progress",
                subject="optional player progress sentinel",
                value={"players": []},
                tool_call_id="details",
                tool="dota.extract_match_player_progress",
            ),
        ],
        missing=["match_parse_status"],
        data_quality=EvidenceDataQuality(completeness=0.9),
    )

    messages = render_natural_language_answer_messages(plan, graph)

    assert "must-not-reach-answer" not in messages[1]["content"]
    assert "optional player progress sentinel" not in messages[1]["content"]
    assert '"winner": "TEAM VISION"' in messages[1]["content"]
    assert "match_parse_status" in messages[1]["content"]
    assert "#### 出装、加点与天赋" not in messages[0]["content"]


def test_answer_messages_include_complete_required_player_progress() -> None:
    from app.agentic.prompts.answer import render_natural_language_answer_messages

    plan = ExecutionPlan(
        intent="hero_build",
        goal="Show the purchase order.",
        output_contract="natural_language_answer",
        required_evidence=["player_match_progress"],
    )
    graph = EvidenceGraph(
        intent=plan.intent,
        required_evidence=plan.required_evidence,
        evidence=[
            EvidenceItem(
                id="progress",
                kind="player_match_progress",
                subject="complete progress sentinel",
                value={
                    "match": {"valve_match_id": 8943244303},
                    "players": [
                        {
                            "name": "Player 0",
                            "hero_name_zh": "莉娜",
                            "level": 30,
                            "final_inventory": {"main": [], "backpack": [], "neutral": {}},
                            "purchase_timeline": [],
                            "ability_upgrade_sequence": [],
                            "talent_selections": [],
                        }
                    ],
                },
                tool_call_id="details",
                tool="dota.extract_match_player_progress",
            ),
        ],
        data_quality=EvidenceDataQuality(completeness=1.0),
    )

    messages = render_natural_language_answer_messages(plan, graph)

    assert "complete progress sentinel" in messages[1]["content"]
    assert "purchase_timeline" in messages[1]["content"]
    assert "ability_upgrade_sequence" in messages[1]["content"]
    assert "talent_selections" in messages[1]["content"]
    assert "#### 出装、加点与天赋" in messages[0]["content"]
