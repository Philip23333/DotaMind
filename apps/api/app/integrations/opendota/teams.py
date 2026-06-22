import asyncio
import time
from typing import Any

from app.integrations.opendota.heroes import OpenDotaHeroes
from app.integrations.opendota.transport import OpenDotaTransport

HARD_MAX_DETAIL_SAMPLE_SIZE = 100
HARD_MAX_DETAIL_CONCURRENCY = 15


class OpenDotaTeams:
    def __init__(
        self,
        transport: OpenDotaTransport,
        heroes: OpenDotaHeroes,
        *,
        detail_sample_size: int = 50,
        max_detail_sample_size: int = 100,
        detail_concurrency: int = 10,
        match_detail_cache_ttl_seconds: int = 30 * 24 * 60 * 60,
    ) -> None:
        self.transport = transport
        self.heroes = heroes
        self.max_detail_sample_size = min(
            max(1, max_detail_sample_size),
            HARD_MAX_DETAIL_SAMPLE_SIZE,
        )
        self.detail_sample_size = min(
            max(1, detail_sample_size),
            self.max_detail_sample_size,
        )
        self.detail_concurrency = min(
            max(1, detail_concurrency),
            HARD_MAX_DETAIL_CONCURRENCY,
        )
        self.match_detail_cache_ttl_seconds = max(1, match_detail_cache_ttl_seconds)

    async def get_all(self) -> list[dict[str, Any]]:
        return await self.transport.get("teams_list", "/teams")

    async def search(self, team_name: str) -> dict[str, Any] | None:
        teams = await self.get_all()
        name_lower = team_name.lower().strip()
        for field in ("name", "tag"):
            for team in teams:
                if team.get(field, "").lower() == name_lower:
                    return team
        for field in ("name", "tag"):
            for team in teams:
                if name_lower in team.get(field, "").lower():
                    return team
        return None

    async def get_matches(self, team_id: int) -> list[dict[str, Any]]:
        return await self.transport.get(
            f"team_matches_{team_id}",
            f"/teams/{team_id}/matches",
        )

    async def get_heroes(self, team_id: int) -> list[dict[str, Any]]:
        return await self.transport.get(
            f"team_heroes_{team_id}",
            f"/teams/{team_id}/heroes",
        )

    async def get_players(self, team_id: int) -> list[dict[str, Any]]:
        return await self.transport.get(
            f"team_players_{team_id}",
            f"/teams/{team_id}/players",
        )

    async def get_match_detail(self, match_id: int) -> dict[str, Any]:
        return await self.transport.get(
            f"match_{match_id}",
            f"/matches/{match_id}",
            cache_ttl_seconds=self.match_detail_cache_ttl_seconds,
        )

    async def aggregate_heroes(
        self, matches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        match_ids = [match["match_id"] for match in matches if "match_id" in match]
        if not match_ids:
            return []

        semaphore = asyncio.Semaphore(self.detail_concurrency)

        async def get_detail(match_id: int) -> dict[str, Any]:
            async with semaphore:
                return await self.get_match_detail(match_id)

        details = await asyncio.gather(
            *(get_detail(match_id) for match_id in match_ids),
            return_exceptions=True,
        )
        hero_stats: dict[int, dict[str, int]] = {}
        for match, match_meta in zip(details, matches, strict=False):
            if isinstance(match, Exception) or not match:
                continue
            team_is_radiant = match_meta.get("radiant", False)
            radiant_win = match.get("radiant_win", False)
            team_won = (team_is_radiant and radiant_win) or (
                not team_is_radiant and not radiant_win
            )
            for player in match.get("players", []):
                if player.get("isRadiant") != team_is_radiant:
                    continue
                hero_id = player.get("hero_id")
                if hero_id is None:
                    continue
                stats = hero_stats.setdefault(hero_id, {"games": 0, "wins": 0})
                stats["games"] += 1
                if team_won:
                    stats["wins"] += 1

        hero_names = await self.heroes.name_map()
        result = [
            {
                "hero_id": hero_id,
                "localized_name": hero_names.get(hero_id, f"Hero {hero_id}"),
                "games_played": stats["games"],
                "wins": stats["wins"],
            }
            for hero_id, stats in hero_stats.items()
        ]
        result.sort(key=lambda hero: hero["games_played"], reverse=True)
        return result

    async def get_report_data(
        self,
        team_name: str,
        *,
        days: int = 30,
        detail_sample_size: int | None = None,
        resolved_team: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        team = resolved_team or await self.search(team_name)
        if team is None:
            return None

        team_id = team["team_id"]
        all_matches = await self.get_matches(team_id)
        if days > 0:
            cutoff = time.time() - days * 86400
            matches = [match for match in all_matches if match.get("start_time", 0) >= cutoff]
        else:
            matches = list(all_matches)
        matches.sort(key=lambda match: int(match.get("start_time") or 0), reverse=True)

        if not matches:
            return self._empty_report(team, team_name)

        requested_sample_size = detail_sample_size or self.detail_sample_size
        sample_size = min(
            max(1, requested_sample_size),
            self.max_detail_sample_size,
        )
        detail_matches = matches[:sample_size]

        players = await self.get_players(team_id)
        current_players = [
            player
            for player in players
            if player.get("is_current_team_member") is True
        ]
        key_players = [
            player["name"] for player in current_players[:5] if player.get("name")
        ]
        heroes = await self.aggregate_heroes(detail_matches)

        wins = sum(1 for match in matches if self._is_team_win(match))
        losses = len(matches) - wins
        recent_win_rate = wins / max(len(matches), 1)
        hero_pool_depth = sum(1 for hero in heroes if hero.get("games_played", 0) >= 2)
        draft_flexibility = min(hero_pool_depth / 25, 1.0)
        patch_adaptation = int(
            min(
                100,
                recent_win_rate * 50
                + draft_flexibility * 30
                + min(len(matches) / 30, 1) * 20,
            )
        )

        win_durations = [
            match.get("duration", 0) for match in matches if self._is_team_win(match)
        ]
        loss_durations = [
            match.get("duration", 0) for match in matches if not self._is_team_win(match)
        ]
        win_patterns = self._duration_patterns(win_durations, "winning")
        loss_patterns = self._duration_patterns(loss_durations, "losing")
        if recent_win_rate >= 0.6:
            win_patterns.append("Strong recent form with consistent execution.")
        if recent_win_rate < 0.5:
            loss_patterns.append(
                "Below 50% win rate in recent matches suggests meta adaptation issues."
            )

        opponents = list(
            {
                match.get("opposing_team_name", "")
                for match in matches
                if match.get("opposing_team_name")
            }
        )
        return {
            "team_name": team.get("name", team_name),
            "team_id": team_id,
            "rating": team.get("rating"),
            "matches_in_window": len(matches),
            "match_details_analyzed": len(detail_matches),
            "recent_record": f"{wins}-{losses} in last {len(matches)} matches",
            "wins": wins,
            "losses": losses,
            "signature_heroes": [
                hero["localized_name"] for hero in heroes[:5] if "localized_name" in hero
            ],
            "hero_pool_depth": hero_pool_depth,
            "draft_flexibility": round(draft_flexibility, 2),
            "patch_adaptation_score": patch_adaptation,
            "win_patterns": win_patterns,
            "loss_patterns": loss_patterns,
            "key_players": key_players,
            "opponents_faced": opponents[:5],
            "recent_win_rate": round(recent_win_rate, 3),
        }

    @staticmethod
    def _is_team_win(match: dict[str, Any]) -> bool:
        return bool(
            (match.get("radiant") and match.get("radiant_win"))
            or (not match.get("radiant") and not match.get("radiant_win"))
        )

    @staticmethod
    def _duration_patterns(durations: list[int], result: str) -> list[str]:
        if not durations:
            return []
        average_minutes = sum(durations) / len(durations) / 60
        return [f"Average {result} game duration: {average_minutes:.0f} minutes."]

    @staticmethod
    def _empty_report(team: dict[str, Any], fallback_name: str) -> dict[str, Any]:
        return {
            "team_name": team.get("name", fallback_name),
            "team_id": team["team_id"],
            "rating": team.get("rating"),
            "matches_in_window": 0,
            "match_details_analyzed": 0,
            "recent_record": "0-0 in last 0 matches",
            "wins": 0,
            "losses": 0,
            "signature_heroes": [],
            "hero_pool_depth": 0,
            "draft_flexibility": 0.0,
            "patch_adaptation_score": 0,
            "win_patterns": [],
            "loss_patterns": [],
            "key_players": [],
            "opponents_faced": [],
            "recent_win_rate": 0.0,
        }
