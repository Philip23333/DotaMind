import asyncio
from typing import Any

from app.integrations.stratz.heroes import StratzHeroes


class FakeTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def graphql(
        self,
        _operation_name: str,
        _query: str,
        _variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.payload

    async def aclose(self) -> None:
        return None


def test_stratz_heroes_normalizes_hero_matchups() -> None:
    async def exercise() -> dict:
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
            return await heroes.hero_vs_hero_matchup(25, take=5)
        finally:
            await transport.aclose()

    result = asyncio.run(exercise())

    assert result["hero_id"] == 25
    assert result["advantage"][0]["hero_id"] == 66
    assert result["advantage"][0]["win_rate"] == 0.6
    assert result["disadvantage"][0]["hero_id"] == 94
    assert result["disadvantage"][0]["synergy"] == -2.0


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
