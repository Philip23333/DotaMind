import asyncio
from typing import Any

from app.integrations.stratz.heroes import StratzHeroes


class FakeTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_query: str | None = None

    async def graphql(
        self,
        _operation_name: str,
        query: str,
        _variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_query = query
        return self.payload

    async def aclose(self) -> None:
        return None


def test_stratz_heroes_normalizes_hero_matchups() -> None:
    async def exercise() -> tuple[dict, FakeTransport]:
        transport = FakeTransport(
            {
                "data": {
                    "heroStats": {
                        "heroVsHeroMatchup": {
                            "advantage": [
                                {
                                    "heroId": 25,
                                    "matchCountVs": 100,
                                    "vs": [
                                        {
                                            "heroId1": 25,
                                            "heroId2": 66,
                                            "matchCount": 20,
                                            "winCount": 12,
                                            "synergy": 3.5,
                                            "winRateHeroId1": 0.49,
                                            "winRateHeroId2": 0.52,
                                        }
                                    ],
                                }
                            ],
                            "disadvantage": [
                                {
                                    "heroId": 25,
                                    "matchCountVs": 100,
                                    "vs": [
                                        {
                                            "heroId1": 25,
                                            "heroId2": 94,
                                            "matchCount": 50,
                                            "winCount": 20,
                                            "synergy": -2.0,
                                            "winRateHeroId1": 0.49,
                                            "winRateHeroId2": 0.5,
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                }
            }
        )
        heroes = StratzHeroes(transport)
        try:
            result = await heroes.hero_vs_hero_matchup(25, take=5)
        finally:
            await transport.aclose()
        return result, transport

    result, transport = asyncio.run(exercise())

    assert result["hero_id"] == 25
    assert result["advantage"][0]["hero_id"] == 66
    assert result["advantage"][0]["win_rate"] == 0.6
    assert result["disadvantage"][0]["hero_id"] == 94
    assert result["disadvantage"][0]["synergy"] == -2.0
    # Integration layer must not over-fetch provider native win rates —
    # target_win_rate / hero_win_rate were dropped as dead fields (never
    # reached evidence), so the GraphQL query must not request them.
    assert transport.last_query is not None
    assert "winRateHeroId1" not in transport.last_query
    assert "winRateHeroId2" not in transport.last_query


def test_stratz_heroes_normalizes_lane_outcomes() -> None:
    async def exercise() -> list[dict]:
        transport = FakeTransport(
            {
                "data": {
                    "heroStats": {
                        "laneOutcome": [
                            {
                                "heroId1": 104,
                                "heroId2": 86,
                                "position": "POSITION_4",
                                "matchCount": 25,
                                "winCount": 10,
                                "lossCount": 8,
                                "drawCount": 7,
                                "matchWinCount": 15,
                            }
                        ]
                    }
                }
            }
        )
        heroes = StratzHeroes(transport)
        try:
            return await heroes.lane_outcome(104, is_with=True, position_ids=["POSITION_4"])
        finally:
            await transport.aclose()

    result = asyncio.run(exercise())

    assert result[0]["target_hero_id"] == 104
    assert result[0]["hero_id"] == 86
    assert result[0]["position"] == "POSITION_4"
    assert result[0]["match_win_rate"] == 0.6


def test_stratz_heroes_matchup_preserves_stratz_order() -> None:
    """Integration layer normalizes field names only — it must NOT sort.
    STRATZ's raw iteration order is preserved; ranking by synergy happens
    in the agentic layer `_filter_matchup_rows`. See P0-2."""
    transport = FakeTransport(
        {
            "data": {
                "heroStats": {
                    "heroVsHeroMatchup": {
                        "advantage": [
                            {
                                "heroId": 25,
                                "matchCountVs": 300,
                                "vs": [
                                    # Deliberately NOT in synergy-desc order:
                                    # hero 66 (synergy 2.0) precedes hero 71
                                    # (synergy 5.1). If the integration layer
                                    # sorted by synergy desc, 71 would lead.
                                    {
                                        "heroId1": 25,
                                        "heroId2": 66,
                                        "matchCount": 200,
                                        "winCount": 110,
                                        "synergy": 2.0,
                                    },
                                    {
                                        "heroId1": 25,
                                        "heroId2": 71,
                                        "matchCount": 100,
                                        "winCount": 60,
                                        "synergy": 5.1,
                                    },
                                ],
                            }
                        ],
                        "disadvantage": [],
                    }
                }
            }
        }
    )
    heroes = StratzHeroes(transport)

    async def exercise() -> dict:
        try:
            return await heroes.hero_vs_hero_matchup(25, take=5)
        finally:
            await transport.aclose()

    result = asyncio.run(exercise())
    # Raw STRATZ order preserved — NOT reordered by synergy desc.
    assert [row["hero_id"] for row in result["advantage"]] == [66, 71]
