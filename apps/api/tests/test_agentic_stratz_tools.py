import asyncio

from app.agentic.models import QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.tools import ToolExecutor
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


class FakeTransport:
    def __init__(self, graphql_url: str, token: str) -> None:
        self.graphql_url = graphql_url
        self.token = token

    async def aclose(self) -> None:
        return None


class FakeHeroes:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport

    async def hero_vs_hero_matchup(self, hero_id, **kwargs) -> dict:
        return {
            "hero_id": hero_id,
            "advantage": [
                {
                    "hero_id": 66,
                    "target_hero_id": hero_id,
                    "match_count": 250,
                    "matchup_win_rate": 0.55,
                    "synergy": 5.1,
                },
                {
                    "hero_id": 71,
                    "target_hero_id": hero_id,
                    "match_count": 120,
                    "matchup_win_rate": 0.52,
                    "synergy": 2.0,
                },
                {
                    "hero_id": 80,
                    "target_hero_id": hero_id,
                    "match_count": 50,
                    "matchup_win_rate": 0.51,
                    "synergy": 0.5,
                },
            ],
            "disadvantage": [
                {
                    "hero_id": 10,
                    "target_hero_id": hero_id,
                    "match_count": 300,
                    "matchup_win_rate": 0.45,
                    "synergy": -5.5,
                },
            ],
        }

    async def lane_outcome(self, hero_id, *, is_with, **kwargs) -> list[dict]:
        if hero_id is None:
            return [
                {
                    "hero_id": 86,
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 1200,
                    "match_win_rate": 0.55,
                },
                {
                    "hero_id": 50,
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 800,
                    "match_win_rate": 0.52,
                },
                {
                    "hero_id": 68,
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 50,
                    "match_win_rate": 0.40,
                },
            ]
        return [
            {
                "hero_id": 68,
                "target_hero_id": hero_id,
                "position": "POSITION_1",
                "match_count": 797,
                "match_win_rate": 0.5797,
            },
            {
                "hero_id": 86,
                "target_hero_id": hero_id,
                "position": "POSITION_1",
                "match_count": 13,
                "match_win_rate": 0.4615,
            },
        ]

    async def hero_position_stats(self, **kwargs) -> list[dict]:
        return [
            {"hero_id": 8, "position": "POSITION_1", "match_count": 31000},
            {"hero_id": 8, "position": "POSITION_2", "match_count": 1500},
            {"hero_id": 8, "position": "POSITION_3", "match_count": 400},
            {"hero_id": 8, "position": "POSITION_4", "match_count": 120},
            {"hero_id": 8, "position": "POSITION_5", "match_count": 80},
        ]


def test_pair_lane_outcome_filters_to_partner(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pair",
                tool="stratz.pair_lane_outcome",
                args={"hero_id": 42, "partner_hero_id": 68, "is_with": True},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    assert result.data["hero_id"] == 42
    assert result.data["partner_hero_id"] == 68
    buckets = result.data["weekly_buckets"]
    assert len(buckets) == 1
    assert buckets[0]["week_index"] == 1
    rows = buckets[0]["rows"]
    assert len(rows) == 1
    assert rows[0]["match_count"] == 797
    assert rows[0]["match_win_rate"] == 0.5797
    assert result.data["weeks_with_record"] == 1
    assert result.data["missing_week_epochs"] == []
    assert result.data["filters"]["bracket_basic_ids"] == ["LEGEND_ANCIENT"]
    assert result.data["filters"]["weeks_back"] == 1


def test_pair_lane_outcome_missing_partner_returns_empty_bucket(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pair",
                tool="stratz.pair_lane_outcome",
                args={"hero_id": 42, "partner_hero_id": 999, "is_with": True},
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    buckets = result.data["weekly_buckets"]
    assert len(buckets) == 1
    assert buckets[0]["rows"] == []
    assert result.data["weeks_with_record"] == 0
    assert buckets[0]["week_epoch"] in result.data["missing_week_epochs"]


def test_hero_matchup_ranking_keeps_groups_separate(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="rank",
                tool="stratz.hero_matchup_ranking",
                args={"hero_id": 25, "side": "vs", "take": 2, "min_sample_size": 100},
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    advantage = [row for row in rows if row["source_side"] == "advantage"]
    disadvantage = [row for row in rows if row["source_side"] == "disadvantage"]
    assert [row["hero_id"] for row in advantage] == [66, 71]
    assert [row["hero_id"] for row in disadvantage] == [10]
    assert result.data["filters"]["min_sample_size"] == 100


def test_lane_meta_global_truncates_to_highlight_top(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="meta",
                tool="stratz.lane_meta_global",
                args={"is_with": True, "min_sample_size": 100, "highlight_top": 2},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    assert [row["hero_id"] for row in rows] == [86, 50]
    assert all("position" not in row for row in rows)
    assert "position_ids" not in result.data["filters"]
    assert "selection_policy" in result.data
    # Default selection_mode is "strong": ranks by win rate, so 86 (0.55) leads
    # 50 (0.52), and the policy string records the win-rate basis.
    assert result.data["filters"]["selection_mode"] == "strong"
    assert "match_win_rate" in result.data["selection_policy"]
    assert result.data["filters"]["bracket_basic_ids"] == ["LEGEND_ANCIENT"]


def test_lane_meta_global_dedupes_mirror_pairs(monkeypatch) -> None:
    class MirrorHeroes:
        def __init__(self, transport):
            self.transport = transport

        async def lane_outcome(self, hero_id, *, is_with, **kwargs):
            return [
                {
                    "hero_id": 22,
                    "target_hero_id": 2,
                    "position": "POSITION_1",
                    "match_count": 1774,
                    "match_win_rate": 0.5767,
                },
                {
                    "hero_id": 2,
                    "target_hero_id": 22,
                    "position": "POSITION_1",
                    "match_count": 1685,
                    "match_win_rate": 0.5697,
                },
                {
                    "hero_id": 6,
                    "target_hero_id": 14,
                    "position": "POSITION_1",
                    "match_count": 1699,
                    "match_win_rate": 0.5491,
                },
                {
                    "hero_id": 14,
                    "target_hero_id": 6,
                    "position": "POSITION_1",
                    "match_count": 1809,
                    "match_win_rate": 0.5384,
                },
            ]

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", MirrorHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="meta",
                tool="stratz.lane_meta_global",
                args={"is_with": True, "min_sample_size": 100, "highlight_top": 10},
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    pairs = {(row["hero_id"], row["target_hero_id"]) for row in rows}
    # No mirror duplicates: each canonical pair appears once
    canonical = {tuple(sorted(p)) for p in pairs}
    assert len(canonical) == len(pairs)
    # The larger-sample mirror is kept for each pair
    pair_by_canonical = {
        tuple(sorted((row["hero_id"], row["target_hero_id"]))): row
        for row in rows
    }
    assert pair_by_canonical[(2, 22)]["match_count"] == 1774
    assert pair_by_canonical[(6, 14)]["match_count"] == 1809
    assert len(rows) == 2
    assert "deduped" in result.data["selection_policy"]


def test_lane_meta_global_popular_sorts_by_match_count(monkeypatch) -> None:
    # match_count order != win-rate order, so popular and strong diverge.
    class CountLeadsHeroes:
        def __init__(self, transport):
            self.transport = transport

        async def lane_outcome(self, hero_id, *, is_with, **kwargs):
            return [
                {
                    "hero_id": 10,
                    "target_hero_id": 11,
                    "position": "POSITION_1",
                    "match_count": 2000,
                    "match_win_rate": 0.45,
                },
                {
                    "hero_id": 12,
                    "target_hero_id": 13,
                    "position": "POSITION_1",
                    "match_count": 800,
                    "match_win_rate": 0.60,
                },
            ]

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", CountLeadsHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="meta",
                tool="stratz.lane_meta_global",
                args={
                    "is_with": True,
                    "min_sample_size": 100,
                    "highlight_top": 10,
                    "selection_mode": "popular",
                },
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    # popular ranks by match_count desc: 2000 before 800, even though 0.45 < 0.60
    assert [row["hero_id"] for row in rows] == [10, 12]
    assert result.data["filters"]["selection_mode"] == "popular"
    assert "match_count desc" in result.data["selection_policy"]
    assert "match_win_rate" not in result.data["selection_policy"]


def test_lane_meta_global_strong_tiebreaks_by_match_count(monkeypatch) -> None:
    class TiedWinRateHeroes:
        def __init__(self, transport):
            self.transport = transport

        async def lane_outcome(self, hero_id, *, is_with, **kwargs):
            return [
                {
                    "hero_id": 20,
                    "target_hero_id": 21,
                    "position": "POSITION_1",
                    "match_count": 500,
                    "match_win_rate": 0.55,
                },
                {
                    "hero_id": 22,
                    "target_hero_id": 23,
                    "position": "POSITION_1",
                    "match_count": 900,
                    "match_win_rate": 0.55,
                },
            ]

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", TiedWinRateHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="meta",
                tool="stratz.lane_meta_global",
                args={
                    "is_with": True,
                    "min_sample_size": 100,
                    "highlight_top": 10,
                    "selection_mode": "strong",
                },
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    # win rate ties at 0.55 -> tie-break by match_count desc: 900 before 500
    assert [row["hero_id"] for row in rows] == [22, 20]


def test_lane_meta_global_propagates_selection_mode_to_evidence() -> None:
    from app.agentic.tools.stratz_tools import lane_meta_global_evidence

    tool_result = ToolResult(
        tool_call_id="meta",
        tool="stratz.lane_meta_global",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "is_with": True,
            "filters": {
                "weeks_back": 1,
                "bracket_basic_ids": None,
                "is_with": True,
                "min_sample_size": 800,
                "highlight_top": 15,
                "selection_mode": "strong",
                "week_epochs": [1782345600],
                "weeks_resolved": 1,
                "skipped_current_week": True,
            },
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "latest_completed_week",
                    "rows": [
                        {
                            "hero_id": 86,
                            "target_hero_id": 1,
                            "match_count": 1200,
                            "match_win_rate": 0.55,
                        },
                    ],
                },
            ],
        },
    )

    evidence = lane_meta_global_evidence(tool_result)
    row = next(item for item in evidence if item.kind == "lane_meta_row")
    # selection_mode reaches the answer layer via evidence value["filters"]
    assert row.value["filters"]["selection_mode"] == "strong"


def test_lane_meta_global_evidence_maps_hero_names() -> None:
    from app.agentic.tools.stratz_tools import lane_meta_global_evidence

    tool_result = ToolResult(
        tool_call_id="meta",
        tool="stratz.lane_meta_global",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "is_with": True,
            "filters": {
                "weeks_back": 1,
                "bracket_basic_ids": None,
                "is_with": True,
                "week_epochs": [1782345600],
                "weeks_resolved": 1,
                "skipped_current_week": True,
            },
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "latest_completed_week",
                    "rows": [
                        {
                            "hero_id": 86,
                            "target_hero_id": 1,
                            "match_count": 1200,
                            "match_win_rate": 0.55,
                        },
                    ],
                },
            ],
        },
    )

    evidence = lane_meta_global_evidence(tool_result)
    by_kind = {item.kind: item for item in evidence}

    row = by_kind["lane_meta_row"]
    assert row.subject == "Rubick + Anti-Mage (latest_completed_week)"
    assert row.value["hero_id"] == 86
    assert row.value["hero_name"] == "Rubick"
    assert row.value["target_hero_id"] == 1
    assert row.value["target_hero_name"] == "Anti-Mage"
    assert row.value["week_epoch"] == 1782345600
    assert "position" not in row.value

    sample = by_kind["sample_size"]
    assert sample.value["hero_name"] == "Rubick"
    assert sample.value["target_hero_name"] == "Anti-Mage"


def test_hero_position_stats_evidence_maps_hero_names() -> None:
    from app.agentic.tools.stratz_tools import hero_position_stats_evidence

    tool_result = ToolResult(
        tool_call_id="pos",
        tool="stratz.hero_position_stats",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "filters": {
                "weeks_back": 1,
                "bracket_basic_ids": None,
                "week_epochs": [1782345600],
                "weeks_resolved": 1,
                "skipped_current_week": True,
            },
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "latest_completed_week",
                    "rows": [
                        {"hero_id": 8, "position": "POSITION_1", "match_count": 31000},
                    ],
                },
            ],
        },
    )

    evidence = hero_position_stats_evidence(tool_result)
    by_kind = {item.kind: item for item in evidence}

    stat = by_kind["position_stat"]
    assert stat.subject == "Juggernaut at POSITION_1 (latest_completed_week)"
    assert stat.value["hero_id"] == 8
    assert stat.value["hero_name"] == "Juggernaut"
    assert stat.value["week_epoch"] == 1782345600

    sample = by_kind["sample_size"]
    assert sample.value["hero_name"] == "Juggernaut"


def test_hero_position_stats_requires_exactly_one_filter(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pos",
                tool="stratz.hero_position_stats",
                args={"hero_id": 8},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    assert rows[0]["hero_id"] == 8
    assert len(rows) == 5


def test_hero_position_stats_rejects_both_filters(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pos",
                tool="stratz.hero_position_stats",
                args={"hero_id": 8, "position_id": "POSITION_1"},
            ),
            QueryContext(),
        )
    )

    assert result.status == "error"
    assert "exactly one of" in result.error


def test_stratz_pair_lane_outcome_requires_token() -> None:
    result = asyncio.run(
        ToolExecutor(_registry(token=None)).execute(
            ToolCall(
                id="pair",
                tool="stratz.pair_lane_outcome",
                args={"hero_id": 42, "partner_hero_id": 68, "is_with": True},
            ),
            QueryContext(),
        )
    )

    assert result.status == "error"
    assert "METAMIND_STRATZ_TOKEN is required" in result.error


def _registry(token: str | None):
    return build_default_tool_registry(
        Settings(
            stratz_graphql_url="https://stratz.test/graphql",
            stratz_token=token,
        )
    )


def test_resolve_recent_completed_weeks_skips_current_week() -> None:
    from app.agentic.tools.stratz_tools import resolve_recent_completed_weeks

    # 2026-07-03 ~12:00 UTC; current week idx 2948 (epoch 1782950400); the
    # latest *completed* week is 2947 (1782345600), the verified STRATZ epoch.
    now = 1783048000.0
    assert resolve_recent_completed_weeks(0, now=now) == []
    assert resolve_recent_completed_weeks(1, now=now) == [1782345600]
    assert resolve_recent_completed_weeks(2, now=now) == [1782345600, 1781740800]
    assert resolve_recent_completed_weeks(3, now=now) == [
        1782345600,
        1781740800,
        1781136000,
    ]


def test_pair_lane_outcome_fans_out_per_week(monkeypatch) -> None:
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pair",
                tool="stratz.pair_lane_outcome",
                args={"hero_id": 42, "partner_hero_id": 68, "is_with": True},
            ),
            QueryContext(weeks_back=2),
        )
    )

    assert result.status == "ok"
    buckets = result.data["weekly_buckets"]
    assert len(buckets) == 2
    assert [b["week_index"] for b in buckets] == [1, 2]
    # newest completed week first
    assert buckets[0]["week_epoch"] > buckets[1]["week_epoch"]
    assert all(b["rows"][0]["match_count"] == 797 for b in buckets)
    assert result.data["filters"]["weeks_back"] == 2
    assert len(result.data["filters"]["week_epochs"]) == 2
