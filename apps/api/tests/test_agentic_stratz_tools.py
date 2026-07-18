import asyncio

import pytest

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
                    "win_count": 138,
                    "matchup_win_rate": 0.55,
                    "synergy": 5.1,
                },
                {
                    "hero_id": 71,
                    "target_hero_id": hero_id,
                    "match_count": 120,
                    "win_count": 62,
                    "matchup_win_rate": 0.52,
                    "synergy": 2.0,
                },
                {
                    "hero_id": 80,
                    "target_hero_id": hero_id,
                    "match_count": 50,
                    "win_count": 26,
                    "matchup_win_rate": 0.51,
                    "synergy": 0.5,
                },
            ],
            "disadvantage": [
                {
                    "hero_id": 10,
                    "target_hero_id": hero_id,
                    "match_count": 300,
                    "win_count": 135,
                    "matchup_win_rate": 0.45,
                    "synergy": -5.5,
                },
            ],
        }

    async def hero_synergy_matchup(self, hero_id, **kwargs) -> dict:
        return {
            "hero_id": hero_id,
            "advantage": [
                {
                    "hero_id": 65,
                    "target_hero_id": hero_id,
                    "match_count": 250,
                    "win_count": 150,
                    "pair_win_rate": 0.6,
                    "synergy": 5.1,
                },
                {
                    "hero_id": 71,
                    "target_hero_id": hero_id,
                    "match_count": 120,
                    "win_count": 70,
                    "pair_win_rate": 0.5833,
                    "synergy": 2.0,
                },
            ],
            "disadvantage": [
                {
                    "hero_id": 10,
                    "target_hero_id": hero_id,
                    "match_count": 300,
                    "win_count": 120,
                    "pair_win_rate": 0.4,
                    "synergy": -5.5,
                },
            ],
        }

    async def hero_win_day(self, hero_id, *, take=12, bracket_ids=None, **kwargs) -> dict:
        return {
            "hero_id": hero_id,
            "daily": [
                {
                    "day": 1783209600,
                    "hero_id": hero_id,
                    "win_count": 5042,
                    "match_count": 9756,
                    "win_rate": 0.5168,
                },
                {
                    "day": 1783123200,
                    "hero_id": hero_id,
                    "win_count": 4755,
                    "match_count": 9229,
                    "win_rate": 0.5149,
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
                    "match_win_count": 660,
                    "match_win_rate": 0.55,
                },
                {
                    "hero_id": 50,
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 800,
                    "match_win_count": 416,
                    "match_win_rate": 0.52,
                },
                {
                    "hero_id": 68,
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 50,
                    "match_win_count": 20,
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

    async def hero_position_stats(
        self, *, hero_ids=None, position_ids=None, **kwargs
    ) -> list[dict]:
        # Emulate integration-layer normalize output (win_count + match_win_rate).
        if hero_ids:
            hid = hero_ids[0]
            return [
                {
                    "hero_id": hid,
                    "position": "POSITION_1",
                    "match_count": 31000,
                    "win_count": 15500,
                    "match_win_rate": 0.5,
                },
                {
                    "hero_id": hid,
                    "position": "POSITION_2",
                    "match_count": 1500,
                    "win_count": 870,
                    "match_win_rate": 0.58,
                },
                {
                    "hero_id": hid,
                    "position": "POSITION_3",
                    "match_count": 400,
                    "win_count": 220,
                    "match_win_rate": 0.55,
                },
                {
                    "hero_id": hid,
                    "position": "POSITION_4",
                    "match_count": 120,
                    "win_count": 60,
                    "match_win_rate": 0.5,
                },
                {
                    "hero_id": hid,
                    "position": "POSITION_5",
                    "match_count": 80,
                    "win_count": 50,
                    "match_win_rate": 0.625,
                },
            ]
        pos = position_ids[0] if position_ids else "POSITION_1"
        return [
            {
                "hero_id": 8,
                "position": pos,
                "match_count": 5000,
                "win_count": 2600,
                "match_win_rate": 0.52,
            },
            {
                "hero_id": 7,
                "position": pos,
                "match_count": 4000,
                "win_count": 2300,
                "match_win_rate": 0.575,
            },
            {
                "hero_id": 11,
                "position": pos,
                "match_count": 3000,
                "win_count": 1650,
                "match_win_rate": 0.55,
            },
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
    # candidate_rows: latest completed week flattened across advantage/disadvantage.
    assert len(result.data["candidate_rows"]) == 3  # 2 advantage + 1 disadvantage
    assert all("source_side" in r for r in result.data["candidate_rows"])
    # Phase-2: the handler computes pair_wilson_rating from the fixture's win_count
    # (a real value, not wilson_lower_bound(0, n) == 0) and carries it on every row.
    from app.integrations.stratz.wilson import wilson_lower_bound

    assert all(r.get("pair_wilson_rating") is not None for r in rows)
    row66 = next(r for r in advantage if r["hero_id"] == 66)
    assert row66["pair_wilson_rating"] == pytest.approx(wilson_lower_bound(138, 250))
    assert row66["pair_wilson_rating"] > 0  # non-degenerate: win_count reached the handler


def test_filter_heroes_by_position_joins_and_drops(monkeypatch) -> None:
    """Thin-relay join: keep candidates that have enough position sample; carry
    the ORIGINAL ranking row + attach position sample; no composite score."""
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    candidate_rows = [
        {
            "source_side": "advantage",
            "hero_id": 7,
            "target_hero_id": 25,
            "match_count": 250,
            "matchup_win_rate": 0.6,
            "synergy": 5.1,
        },
        {
            "source_side": "advantage",
            "hero_id": 11,
            "target_hero_id": 25,
            "match_count": 120,
            "matchup_win_rate": 0.5833,
            "synergy": 2.0,
        },
        {
            "source_side": "advantage",
            "hero_id": 99,
            "target_hero_id": 25,
            "match_count": 100,
            "matchup_win_rate": 0.55,
            "synergy": 1.0,
        },
    ]
    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="filter",
                tool="stratz.filter_heroes_by_position",
                args={
                    "candidate_rows": candidate_rows,
                    "position_id": "POSITION_1",
                    "min_position_match_count": 0,
                },
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    # FakeHeroes.hero_position_stats(POSITION_1) returns hero 8/7/11.
    # candidate {7,11,99} ∩ position {8,7,11} = {7,11}; 99 dropped.
    filtered = result.data["filtered_rows"]
    assert [r["hero_id"] for r in filtered] == [7, 11]
    assert result.data["dropped_hero_ids"] == [99]
    # Original ranking row preserved + position sample attached.
    row7 = filtered[0]
    assert row7["source_side"] == "advantage"
    assert row7["matchup_win_rate"] == 0.6
    assert row7["synergy"] == 5.1
    assert row7["position_match_count"] == 4000
    assert row7["position_match_win_rate"] == 0.575
    assert row7["position"] == "POSITION_1"
    assert "role_fit_basis" in row7

    # min_position_match_count raises the floor: hero 11 (3000) dropped at 3500.
    result2 = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="filter2",
                tool="stratz.filter_heroes_by_position",
                args={
                    "candidate_rows": candidate_rows,
                    "position_id": "POSITION_1",
                    "min_position_match_count": 3500,
                },
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )
    assert [r["hero_id"] for r in result2.data["filtered_rows"]] == [7]
    assert result2.data["dropped_hero_ids"] == [11, 99]


def test_filter_heroes_by_position_evidence_preserves_original_row() -> None:
    from app.agentic.tools.stratz_tools import filter_heroes_by_position_evidence

    tool_result = ToolResult(
        tool_call_id="filter",
        tool="stratz.filter_heroes_by_position",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "position_id": "POSITION_4",
            "filtered_rows": [
                {
                    "source_side": "advantage",
                    "hero_id": 7,
                    "target_hero_id": 25,
                    "match_count": 250,
                    "matchup_win_rate": 0.6,
                    "synergy": 5.1,
                    "position": "POSITION_4",
                    "position_match_count": 4000,
                    "position_match_win_rate": 0.575,
                    "role_fit_basis": "position_sample: matchCount@POSITION_4",
                }
            ],
            "dropped_hero_ids": [],
            "filters": {"position_id": "POSITION_4", "min_position_match_count": 300},
        },
    )

    evidence = filter_heroes_by_position_evidence(tool_result)
    assert len(evidence) == 1
    row = evidence[0]
    assert row.kind == "role_filtered_candidate_row"
    # Original ranking row preserved.
    assert row.value["source_side"] == "advantage"
    assert row.value["matchup_win_rate"] == 0.6
    assert row.value["synergy"] == 5.1
    # Position sample attached.
    assert row.value["position_match_count"] == 4000
    # Caliber detected from matchup_win_rate; mirrored to filters.
    assert row.value["win_rate_basis"] == "matchup: winCount/matchCount"
    assert row.value["filters"]["win_rate_basis"] == "matchup: winCount/matchCount"


def test_hero_synergy_ranking_keeps_groups_separate(monkeypatch) -> None:
    """Ally synergy ranking mirrors matchup ranking shape but from .with (allies).
    required_evidence must use hero_synergy_ranking_row (not v2.5 legacy synergy_win_rate)."""
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="syn",
                tool="stratz.hero_synergy_ranking",
                args={"hero_id": 8, "side": "with", "take": 5, "min_sample_size": 100},
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    advantage = [row for row in rows if row["source_side"] == "advantage"]
    disadvantage = [row for row in rows if row["source_side"] == "disadvantage"]
    # Sorted by synergy desc within each group; groups kept separate.
    assert [row["hero_id"] for row in advantage] == [65, 71]
    assert [row["hero_id"] for row in disadvantage] == [10]
    # Caliber is ally-pair, distinct from matchup's matchup_win_rate.
    assert advantage[0]["pair_win_rate"] == 0.6
    assert "matchup_win_rate" not in advantage[0]
    # Phase-2: pair_wilson_rating is computed from the ally-pair win_count and
    # carried on every row (synergy stays primary; pair_wilson is the co-signal).
    from app.integrations.stratz.wilson import wilson_lower_bound

    assert all(r.get("pair_wilson_rating") is not None for r in rows)
    assert advantage[0]["pair_wilson_rating"] == pytest.approx(wilson_lower_bound(150, 250))


def test_hero_synergy_ranking_evidence_uses_ally_pair_basis() -> None:
    from app.agentic.tools.stratz_tools import hero_synergy_ranking_evidence

    tool_result = ToolResult(
        tool_call_id="syn",
        tool="stratz.hero_synergy_ranking",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "hero_id": 8,
            "side": "with",
            "filters": {"take": 10, "min_sample_size": 100, "bracket_basic_ids": None},
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "latest_completed_week",
                    "rows": [
                        {
                            "source_side": "advantage",
                            "hero_id": 65,
                            "target_hero_id": 8,
                            "match_count": 250,
                            "win_count": 150,
                            "pair_win_rate": 0.6,
                            "synergy": 5.1,
                        }
                    ],
                }
            ],
        },
    )

    evidence = hero_synergy_ranking_evidence(tool_result)
    by_kind = {item.kind: item for item in evidence}

    row = by_kind["hero_synergy_ranking_row"]
    assert row.value["pair_win_rate"] == 0.6
    assert row.value["win_rate_basis"] == "ally_pair: winCount/matchCount"
    assert row.value["filters"]["win_rate_basis"] == "ally_pair: winCount/matchCount"
    assert " with " in row.subject


def test_hero_daily_trends_translates_bracket_and_returns_daily(monkeypatch) -> None:
    """winDay only accepts RankBracket (full); context.bracket (basic) must be
    expanded. day-grain: weeks_back is not used; no week_epochs in filters."""
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="trend",
                tool="stratz.hero_daily_trends",
                args={"hero_id": 8, "take": 5},
            ),
            QueryContext(bracket=["DIVINE_IMMORTAL"]),
        )
    )

    assert result.status == "ok"
    daily = result.data["daily_buckets"]
    assert len(daily) == 2
    assert daily[0]["day"] == 1783209600
    # bracket basic -> full translation reaches filters.
    assert result.data["filters"]["bracket_basic_ids"] == ["DIVINE_IMMORTAL"]
    assert result.data["filters"]["bracket_full_ids"] == ["DIVINE", "IMMORTAL"]
    assert result.data["filters"]["grain"] == "day"
    # day-grain: weeks_back / week_epochs are not part of this tool.
    assert "week_epochs" not in result.data["filters"]


def test_hero_daily_trends_evidence_uses_day_basis() -> None:
    from app.agentic.tools.stratz_tools import hero_daily_trends_evidence

    tool_result = ToolResult(
        tool_call_id="trend",
        tool="stratz.hero_daily_trends",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "hero_id": 8,
            "daily_buckets": [
                {
                    "day": 1783209600,
                    "hero_id": 8,
                    "win_count": 5042,
                    "match_count": 9756,
                    "win_rate": 0.5168,
                },
            ],
            "filters": {
                "take": 5,
                "bracket_basic_ids": ["DIVINE_IMMORTAL"],
                "bracket_full_ids": ["DIVINE", "IMMORTAL"],
                "grain": "day",
            },
        },
    )

    evidence = hero_daily_trends_evidence(tool_result)
    # Single kind per day; no per-day sample_size evidence.
    assert len(evidence) == 1
    row = evidence[0]
    assert row.kind == "hero_daily_trend"
    assert row.value["win_rate"] == 0.5168
    assert row.value["win_rate_basis"] == "day: winCount/matchCount"
    assert row.value["filters"]["win_rate_basis"] == "day: winCount/matchCount"
    assert row.value["filters"]["grain"] == "day"


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
    # Default selection_mode is "strong": ranks by wilson_rating (Wilson lower
    # bound of match win rate), so 86 (0.55 over 1200) leads 50 (0.52 over 800).
    assert result.data["filters"]["selection_mode"] == "strong"
    assert "wilson_rating" in result.data["selection_policy"]
    assert result.data["filters"]["bracket_basic_ids"] == ["LEGEND_ANCIENT"]
    # Row-level: every strong-mode row carries a computed wilson_rating (not just
    # the selection_policy string mentioning it). Reverse-overtake discrimination
    # is covered by test_lane_meta_global_strong_reverse_overtakes_high_winrate_small_sample.
    assert all(row.get("wilson_rating") is not None for row in rows)


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
                    "match_win_count": 1023,
                    "match_win_rate": 0.5767,
                },
                {
                    "hero_id": 2,
                    "target_hero_id": 22,
                    "position": "POSITION_1",
                    "match_count": 1685,
                    "match_win_count": 960,
                    "match_win_rate": 0.5697,
                },
                {
                    "hero_id": 6,
                    "target_hero_id": 14,
                    "position": "POSITION_1",
                    "match_count": 1699,
                    "match_win_count": 933,
                    "match_win_rate": 0.5491,
                },
                {
                    "hero_id": 14,
                    "target_hero_id": 6,
                    "position": "POSITION_1",
                    "match_count": 1809,
                    "match_win_count": 974,
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
                    "match_win_count": 900,
                    "match_win_rate": 0.45,
                },
                {
                    "hero_id": 12,
                    "target_hero_id": 13,
                    "position": "POSITION_1",
                    "match_count": 800,
                    "match_win_count": 480,
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
    assert "wilson_rating" not in result.data["selection_policy"]


def test_lane_meta_global_strong_ranks_larger_sample_higher_at_same_win_rate(monkeypatch) -> None:
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
                    "match_win_count": 275,
                    "match_win_rate": 0.55,
                },
                {
                    "hero_id": 22,
                    "target_hero_id": 23,
                    "position": "POSITION_1",
                    "match_count": 900,
                    "match_win_count": 495,
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
    # Same 0.55 win rate on both pairs; the larger sample (900) yields a higher
    # Wilson lower bound, so 22 leads 20. This proves Wilson rewards sample size
    # at equal win rate. (The match_count tiebreak itself is non-firing: Wilson is
    # injective on (wins, match_count), so equal wilson implies equal match_count
    # — there is nothing left to tie-break. Reverse-overtake across DIFFERENT win
    # rates is covered by test_lane_meta_global_strong_reverse_overtakes_high_winrate_small_sample.)
    assert [row["hero_id"] for row in rows] == [22, 20]


def test_lane_meta_global_strong_reverse_overtakes_high_winrate_small_sample(monkeypatch) -> None:
    """Lane 'strong' (wilson_rating) must let a LOWER win rate on a LARGE sample
    overtake a HIGHER win rate on a tiny sample — the whole reason Wilson replaces
    raw match_win_rate. Raw win-rate DESC would put hero 30 (0.60) first; this test
    fails if the sort key ever reverts to match_win_rate."""
    from app.integrations.stratz.wilson import wilson_lower_bound

    class OvertakeHeroes:
        def __init__(self, transport):
            self.transport = transport

        async def lane_outcome(self, hero_id, *, is_with, **kwargs):
            return [
                {
                    "hero_id": 30,  # 0.60 win rate, but only 50 matches (tiny sample)
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 50,
                    "match_win_count": 30,
                    "match_win_rate": 0.60,
                },
                {
                    "hero_id": 40,  # 0.55 win rate over 2000 matches (large sample)
                    "target_hero_id": 1,
                    "position": "POSITION_1",
                    "match_count": 2000,
                    "match_win_count": 1100,
                    "match_win_rate": 0.55,
                },
            ]

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", OvertakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="meta",
                tool="stratz.lane_meta_global",
                args={
                    "is_with": True,
                    "min_sample_size": 0,
                    "highlight_top": 10,
                    "selection_mode": "strong",
                },
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    # Wilson penalises hero 30's tiny sample despite its higher 0.60 rate, so the
    # large-sample 0.55 (hero 40) leads. Raw win-rate DESC would order [30, 40].
    assert [row["hero_id"] for row in rows] == [40, 30]
    # Row-level proof: every row carries wilson_rating, the observed order equals
    # wilson_rating DESC, and the values match Wilson of match_win_count (the exact
    # integer the lane handler feeds in — NOT a rate-derived count).
    assert all(row.get("wilson_rating") is not None for row in rows)
    assert rows[0]["wilson_rating"] > rows[1]["wilson_rating"]
    assert rows[0]["wilson_rating"] == pytest.approx(wilson_lower_bound(1100, 2000))
    assert rows[1]["wilson_rating"] == pytest.approx(wilson_lower_bound(30, 50))


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
                        {
                            "hero_id": 8,
                            "position": "POSITION_1",
                            "match_count": 31000,
                            "win_count": 15500,
                            "match_win_rate": 0.5,
                        },
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
    assert stat.value["match_win_rate"] == 0.5
    assert stat.value["win_rate_basis"] == "match: winCount/matchCount"
    assert stat.value["filters"]["win_rate_basis"] == "match: winCount/matchCount"

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
                args={"hero_id": 8, "min_sample_size": 0},
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


def test_hero_position_stats_hero_id_strong_ranks_by_wilson(monkeypatch) -> None:
    """hero_id branch: selection_mode strong ranks by wilson_rating desc (Wilson
    lower bound of win rate, confidence-aware; tie-break match_count desc), NOT
    truncated by take."""
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pos",
                tool="stratz.hero_position_stats",
                args={"hero_id": 8, "selection_mode": "strong", "min_sample_size": 0},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    # hero_id branch returns the full distribution, not truncated by take.
    assert len(rows) == 5
    # strong = wilson_rating desc, tie-break match_count desc. POSITION_2 (0.58
    # over 1500) leads; POSITION_1 (0.50 over 31000) drops below POSITION_5/3
    # because Wilson penalises the lower win rate despite its huge sample.
    assert [r["position"] for r in rows] == [
        "POSITION_2", "POSITION_5", "POSITION_3", "POSITION_1", "POSITION_4",
    ]
    assert "selection_policy" in result.data
    assert "wilson_rating desc" in result.data["selection_policy"]


def test_hero_position_stats_position_id_strong_truncates(monkeypatch) -> None:
    """position_id branch: selection_mode strong ranks by match_win_rate desc,
    then truncated to `take`."""
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pos",
                tool="stratz.hero_position_stats",
                args={
                    "position_id": "POSITION_1",
                    "selection_mode": "strong",
                    "take": 2,
                    "min_sample_size": 0,
                },
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )

    assert result.status == "ok"
    rows = result.data["weekly_buckets"][0]["rows"]
    # Truncated to take=2; strong ranks by wilson_rating: hero 7 (0.575) >
    # hero 11 (0.55) > hero 8 (0.52) — Wilson preserves this order here.
    assert [r["hero_id"] for r in rows] == [7, 11]


def test_position_handler_computes_wilson_from_win_count(monkeypatch) -> None:
    """Every strong-mode row carries a computed wilson_rating (popular mode too).
    Source discrimination — raw win_count vs round(match_win_rate * match_count) —
    is covered by test_position_handler_uses_raw_win_count_not_rounded_rate; the
    shared fixture here happens to satisfy win_count == round(rate * count), so
    this test guards presence/computation, not the input source."""
    from app.integrations.stratz.wilson import wilson_lower_bound

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pos",
                tool="stratz.hero_position_stats",
                args={"hero_id": 8, "selection_mode": "strong", "min_sample_size": 0},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )
    by_pos = {r["position"]: r for r in result.data["weekly_buckets"][0]["rows"]}
    # POSITION_2 fixture: win_count=870, match_count=1500.
    assert by_pos["POSITION_2"]["wilson_rating"] == pytest.approx(
        wilson_lower_bound(870, 1500)
    )
    # every row carries a computed wilson_rating, in both strong and popular
    assert all(r.get("wilson_rating") is not None for r in by_pos.values())


def test_position_handler_uses_raw_win_count_not_rounded_rate(monkeypatch) -> None:
    """wilson_rating must come from the raw win_count, NOT round(match_win_rate *
    match_count). The fixture deliberately makes those disagree (win_count=900 but
    round(0.58 * 1500) == 870), so the assertion is only satisfiable by reading
    win_count directly — a rate-derived implementation would fail it."""
    from app.integrations.stratz.wilson import wilson_lower_bound

    class DisagreeHeroes:
        def __init__(self, transport):
            self.transport = transport

        async def hero_position_stats(self, *, hero_ids=None, position_ids=None, **kwargs):
            return [
                {
                    "hero_id": hero_ids[0],
                    "position": "POSITION_2",
                    "match_count": 1500,
                    "win_count": 900,  # != round(0.58 * 1500) == 870
                    "match_win_rate": 0.58,
                }
            ]

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", DisagreeHeroes)

    result = asyncio.run(
        ToolExecutor(_registry(token="token")).execute(
            ToolCall(
                id="pos",
                tool="stratz.hero_position_stats",
                args={"hero_id": 8, "selection_mode": "strong", "min_sample_size": 0},
            ),
            QueryContext(bracket=["LEGEND_ANCIENT"]),
        )
    )
    row = result.data["weekly_buckets"][0]["rows"][0]
    # Equals Wilson of the RAW win_count (900); a buggy impl deriving wins via
    # round(0.58 * 1500) = 870 would compute a different value and fail here.
    assert row["wilson_rating"] == pytest.approx(wilson_lower_bound(900, 1500))
    assert row["wilson_rating"] != pytest.approx(wilson_lower_bound(870, 1500))


def test_position_and_lane_evidence_relay_wilson_rating() -> None:
    """wilson_rating + wilson_provenance reach the answer layer via evidence
    values (the NL answer LLM ranks hero recommendations by this field)."""
    from app.agentic.tools.stratz_tools import (
        hero_position_stats_evidence,
        lane_meta_global_evidence,
    )

    pos_result = ToolResult(
        tool_call_id="pos",
        tool="stratz.hero_position_stats",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "filters": {},
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "latest_completed_week",
                    "rows": [
                        {
                            "hero_id": 8,
                            "position": "POSITION_2",
                            "match_count": 1500,
                            "win_count": 870,
                            "match_win_rate": 0.58,
                            "wilson_rating": 0.5548,
                        },
                    ],
                }
            ],
        },
    )
    pos_row = next(
        i for i in hero_position_stats_evidence(pos_result) if i.kind == "position_stat"
    )
    assert pos_row.value["wilson_rating"] == pytest.approx(0.5548)
    assert "wilson" in pos_row.value["wilson_provenance"]

    lane_result = ToolResult(
        tool_call_id="lane",
        tool="stratz.lane_meta_global",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "is_with": True,
            "filters": {},
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
                            "wilson_rating": 0.5238,
                        },
                    ],
                }
            ],
        },
    )
    lane_row = next(
        i for i in lane_meta_global_evidence(lane_result) if i.kind == "lane_meta_row"
    )
    assert lane_row.value["wilson_rating"] == pytest.approx(0.5238)
    assert "wilson" in lane_row.value["wilson_provenance"]
    # Provenance names the ACTUAL count field each handler feeds into Wilson:
    # position -> winCount; lane -> matchWinCount (match-level, distinct — the lane
    # handler sources match_win_count, not win_count). Guards against lane
    # provenance drifting back to the winCount string.
    assert "winCount" in pos_row.value["wilson_provenance"]
    assert "matchWinCount" in lane_row.value["wilson_provenance"]


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
    assert "DOTAMIND_STRATZ_TOKEN is required" in result.error


def test_filter_matchup_rows_keeps_synergy_primary_and_tags_pair_wilson() -> None:
    """_filter_matchup_rows ranks by synergy (primary, unchanged) and tags each
    row with pair_wilson_rating (Wilson lower bound of the pairing win rate) as
    a sample-confidence co-signal — the two are NOT merged into one score."""
    from app.agentic.tools.stratz_tools import _filter_matchup_rows
    from app.integrations.stratz.wilson import wilson_lower_bound

    rows = [
        # high synergy but tiny sample vs low synergy huge sample
        {"hero_id": 1, "synergy": 5.0, "win_count": 6, "match_count": 10},
        {"hero_id": 2, "synergy": 2.0, "win_count": 600, "match_count": 1000},
        {"hero_id": 3, "synergy": 4.0, "win_count": 3, "match_count": 5},
    ]
    out = _filter_matchup_rows(rows, min_sample_size=0, take=10)
    # primary sort = synergy desc: 1 (5.0) > 3 (4.0) > 2 (2.0) — sample size
    # does NOT override synergy (that is the whole point of keeping it primary).
    assert [r["hero_id"] for r in out] == [1, 3, 2]
    # every row carries a pair_wilson_rating computed from win_count/match_count
    assert out[0]["pair_wilson_rating"] == pytest.approx(wilson_lower_bound(6, 10))
    # the co-signal flags that hero 1's high synergy rests on a tiny sample:
    # its pair_wilson is far below hero 2's, even though hero 1 ranks above it.
    assert out[0]["pair_wilson_rating"] < out[2]["pair_wilson_rating"]


def test_matchup_and_synergy_evidence_relay_pair_wilson() -> None:
    from app.agentic.tools.stratz_tools import (
        hero_matchup_ranking_evidence,
        hero_synergy_ranking_evidence,
    )

    matchup_result = ToolResult(
        tool_call_id="m",
        tool="stratz.hero_matchup_ranking",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "hero_id": 1,
            "filters": {},
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "w",
                    "rows": [
                        {
                            "source_side": "advantage",
                            "hero_id": 66,
                            "target_hero_id": 1,
                            "matchup_win_rate": 0.55,
                            "match_count": 250,
                            "synergy": 5.1,
                            "pair_wilson_rating": 0.51,
                        }
                    ],
                }
            ],
        },
    )
    m = next(
        i
        for i in hero_matchup_ranking_evidence(matchup_result)
        if i.kind == "matchup_ranking_row"
    )
    assert m.value["pair_wilson_rating"] == pytest.approx(0.51)
    assert "wilson" in m.value["wilson_provenance"]
    assert m.value["synergy"] == 5.1  # primary signal still present

    synergy_result = ToolResult(
        tool_call_id="s",
        tool="stratz.hero_synergy_ranking",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "hero_id": 1,
            "filters": {},
            "weekly_buckets": [
                {
                    "week_epoch": 1782345600,
                    "week_index": 1,
                    "window_label": "w",
                    "rows": [
                        {
                            "source_side": "advantage",
                            "hero_id": 65,
                            "target_hero_id": 1,
                            "pair_win_rate": 0.6,
                            "match_count": 250,
                            "synergy": 5.1,
                            "pair_wilson_rating": 0.56,
                        }
                    ],
                }
            ],
        },
    )
    s = next(
        i
        for i in hero_synergy_ranking_evidence(synergy_result)
        if i.kind == "hero_synergy_ranking_row"
    )
    assert s.value["pair_wilson_rating"] == pytest.approx(0.56)
    assert "wilson" in s.value["wilson_provenance"]


def test_filter_heroes_by_position_passes_pair_wilson_through() -> None:
    """The position filter spreads {**row}, so pair_wilson_rating survives the
    join and reaches role_filtered_candidate_row evidence alongside synergy."""
    from app.agentic.tools.stratz_tools import filter_heroes_by_position_evidence

    result = ToolResult(
        tool_call_id="f",
        tool="stratz.filter_heroes_by_position",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "filters": {},
            "filtered_rows": [
                {
                    "hero_id": 66,
                    "position": "POSITION_2",
                    "source_side": "advantage",
                    "synergy": 5.1,
                    "matchup_win_rate": 0.55,
                    "match_count": 250,
                    "pair_wilson_rating": 0.51,
                    "position_match_count": 4000,
                }
            ],
        },
    )
    row = next(
        i
        for i in filter_heroes_by_position_evidence(result)
        if i.kind == "role_filtered_candidate_row"
    )
    assert row.value["pair_wilson_rating"] == pytest.approx(0.51)
    assert row.value["synergy"] == 5.1


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
