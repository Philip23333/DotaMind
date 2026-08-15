from __future__ import annotations

import asyncio

from app.integrations.opendota.leagues import OpenDotaLeagues


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get(self, cache_key: str, path: str):
        self.calls.append((cache_key, path))
        if path == "/leagues":
            return [{"leagueid": 19719, "name": "The International 2026", "tier": "premium"}]
        return [
            {
                "match_id": 8943244303,
                "leagueid": 19719,
                "series_id": 1130066,
                "start_time": 1786613552,
                "duration": 3227,
                "radiant_team_id": 10136357,
                "dire_team_id": 2586976,
                "radiant_win": True,
            }
        ]


def test_league_and_league_matches_use_shared_transport_paths() -> None:
    async def exercise():
        transport = FakeTransport()
        client = OpenDotaLeagues(transport)
        leagues = await client.get_all()
        matches = await client.get_matches(19719)
        return transport.calls, leagues, matches

    calls, leagues, matches = asyncio.run(exercise())
    assert calls == [("leagues", "/leagues"), ("league_matches_19719", "/leagues/19719/matches")]
    assert leagues[0].opendota_league_id == 19719
    assert matches[0].valve_match_id == 8943244303
    assert matches[0].opendota_series_id == 1130066
