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
                    "win_rate": 0.55,
                    "synergy": 5.1,
                },
                {
                    "hero_id": 71,
                    "target_hero_id": hero_id,
                    "match_count": 120,
                    "win_rate": 0.52,
                    "synergy": 2.0,
                },
                {
                    "hero_id": 80,
                    "target_hero_id": hero_id,
                    "match_count": 50,
                    "win_rate": 0.51,
                    "synergy": 0.5,
                },
            ],
            "disadvantage": [
                {
                    "hero_id": 10,
                    "target_hero_id": hero_id,
                    "match_count": 300,
                    "win_rate": 0.45,
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
    assert result.data["pair_record"]["match_count"] == 797
    assert result.data["pair_record"]["match_win_rate"] == 0.5797
    assert result.data["total_partner_matches"] == 1
    assert result.data["filters"]["bracket_basic_ids"] == ["LEGEND_ANCIENT"]


def test_pair_lane_outcome_missing_partner_returns_null_record(monkeypatch) -> None:
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
    assert result.data["pair_record"] is None
    assert result.data["total_partner_matches"] == 0


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
    advantage = result.data["advantage"]
    disadvantage = result.data["disadvantage"]
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
    assert result.data["total_available"] == 2
    assert result.data["returned_count"] == 2
    assert [row["hero_id"] for row in result.data["rows"]] == [86, 50]
    assert all("position" not in row for row in result.data["rows"])
    assert "position_ids" not in result.data["filters"]
    assert "selection_policy" in result.data
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
    pairs = {
        (row["hero_id"], row["target_hero_id"])
        for row in result.data["rows"]
    }
    # No mirror duplicates: each canonical pair appears once
    canonical = {tuple(sorted(p)) for p in pairs}
    assert len(canonical) == len(pairs)
    # The larger-sample mirror is kept for each pair
    pair_by_canonical = {
        tuple(sorted((row["hero_id"], row["target_hero_id"]))): row
        for row in result.data["rows"]
    }
    assert pair_by_canonical[(2, 22)]["match_count"] == 1774
    assert pair_by_canonical[(6, 14)]["match_count"] == 1809
    assert result.data["total_available"] == 2
    assert result.data["returned_count"] == 2
    assert "deduped" in result.data["selection_policy"]


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
            "filters": {"week": None, "bracket_basic_ids": None, "is_with": True},
            "rows": [
                {
                    "hero_id": 86,
                    "target_hero_id": 1,
                    "match_count": 1200,
                    "match_win_rate": 0.55,
                },
            ],
        },
    )

    evidence = lane_meta_global_evidence(tool_result)
    by_kind = {item.kind: item for item in evidence}

    row = by_kind["lane_meta_row"]
    assert row.subject == "Rubick + Anti-Mage"
    assert row.value["hero_id"] == 86
    assert row.value["hero_name"] == "Rubick"
    assert row.value["target_hero_id"] == 1
    assert row.value["target_hero_name"] == "Anti-Mage"
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
            "filters": {"week": None, "bracket_basic_ids": None},
            "rows": [
                {"hero_id": 8, "position": "POSITION_1", "match_count": 31000},
            ],
        },
    )

    evidence = hero_position_stats_evidence(tool_result)
    by_kind = {item.kind: item for item in evidence}

    stat = by_kind["position_stat"]
    assert stat.subject == "Juggernaut at POSITION_1"
    assert stat.value["hero_id"] == 8
    assert stat.value["hero_name"] == "Juggernaut"

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
    assert result.data["rows"][0]["hero_id"] == 8
    assert len(result.data["rows"]) == 5


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
