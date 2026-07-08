from typing import Any

from app.integrations.stratz.transport import StratzTransport

# Player-domain GraphQL queries. See docs/technical/stratz_player_page_graphql_inventory.md.
# v1: steamAccountId direct (no name search); scope = bracket/position/days/take only
# (no region/game_mode — type mismatch with QueryContext, deferred).

_PLAYER_PROFILE_QUERY = """
query PlayerProfile($steamAccountId: Long!) {
  player(steamAccountId: $steamAccountId) {
    steamAccountId
    matchCount
    winCount
    imp
    firstMatchDate
    lastMatchDate
    steamAccount {
      id
      name
      avatar
      seasonRank
      smurfFlag
      proSteamAccount {
        name
      }
    }
  }
}
"""

_PLAYER_RECENT_MATCHES_QUERY = """
query PlayerRecentMatches(
  $steamAccountId: Long!,
  $request: PlayerMatchesRequestType!
) {
  player(steamAccountId: $steamAccountId) {
    matches(request: $request) {
      id
      startDateTime
      duration
      lobbyType
      gameMode
      players(steamAccountId: $steamAccountId) {
        isVictory
        isRadiant
        heroId
        kills
        deaths
        assists
        goldPerMinute
        experiencePerMinute
        position
        lane
        role
        imp
        level
        numLastHits
        numDenies
      }
    }
  }
}
"""


class StratzPlayers:
    """STRATZ player-domain client. Thin relay: normalize field names only;
    do not invent aggregates (ranking/aggregation is the agentic layer's job)."""

    def __init__(self, transport: StratzTransport) -> None:
        self.transport = transport

    async def get_profile(self, steam_account_id: int) -> dict[str, Any]:
        payload = await self.transport.graphql(
            "PlayerProfile",
            _PLAYER_PROFILE_QUERY,
            {"steamAccountId": steam_account_id},
        )
        raw = (payload.get("data") or {}).get("player")
        if not raw:
            return {"steam_account_id": steam_account_id, "found": False}
        return self._normalize_profile(raw, steam_account_id)

    async def get_recent_matches(
        self,
        steam_account_id: int,
        *,
        bracket_ids: list[int] | None = None,
        position_ids: list[str] | None = None,
        start_date_time: int | None = None,
        take: int = 20,
    ) -> list[dict[str, Any]]:
        request: dict[str, Any] = {"take": take}
        if bracket_ids:
            request["bracketIds"] = bracket_ids
        if position_ids:
            request["positionIds"] = position_ids
        if start_date_time is not None:
            request["startDateTime"] = start_date_time
        payload = await self.transport.graphql(
            "PlayerRecentMatches",
            _PLAYER_RECENT_MATCHES_QUERY,
            {"steamAccountId": steam_account_id, "request": request},
        )
        matches = ((payload.get("data") or {}).get("player") or {}).get("matches") or []
        rows = [
            row
            for match in matches
            if (row := self._normalize_recent_match(match, steam_account_id)) is not None
        ]
        # Defensive: STRATZ default order for player.matches is unconfirmed per
        # inventory — enforce newest-first locally and re-cap at `take` so the
        # days∩take intersection semantics do not depend on STRATZ's order.
        rows.sort(key=lambda r: r.get("start_time") or 0, reverse=True)
        return rows[:take]

    @staticmethod
    def _normalize_profile(raw: dict[str, Any], steam_account_id: int) -> dict[str, Any]:
        sa = raw.get("steamAccount") or {}
        pro = sa.get("proSteamAccount") or {}
        return {
            "steam_account_id": steam_account_id,
            "found": True,
            "name": sa.get("name"),
            "avatar": sa.get("avatar"),
            "season_rank": sa.get("seasonRank"),
            "smurf_flag": sa.get("smurfFlag"),
            "pro_name": pro.get("name"),
            "match_count": raw.get("matchCount"),
            "win_count": raw.get("winCount"),
            "imp": raw.get("imp"),
            "first_match_date": raw.get("firstMatchDate"),
            "last_match_date": raw.get("lastMatchDate"),
        }

    @staticmethod
    def _normalize_recent_match(
        match: dict[str, Any], steam_account_id: int
    ) -> dict[str, Any] | None:
        players = match.get("players") or []
        if not players:
            return None
        # players(steamAccountId) returns the queried player; if more than one
        # slipped through, pick the row whose id matches.
        player = next(
            (p for p in players if p.get("steamAccountId") == steam_account_id),
            players[0],
        )
        return {
            "match_id": match.get("id"),
            "start_time": match.get("startDateTime"),
            "duration": match.get("duration"),
            "lobby_type": match.get("lobbyType"),
            "game_mode": match.get("gameMode"),
            "hero_id": player.get("heroId"),
            # Native STRATZ victory flag — do NOT derive from radiant/dire.
            "win": player.get("isVictory"),
            "is_radiant": player.get("isRadiant"),
            "kills": player.get("kills"),
            "deaths": player.get("deaths"),
            "assists": player.get("assists"),
            "gold_per_minute": player.get("goldPerMinute"),
            "experience_per_minute": player.get("experiencePerMinute"),
            "position": player.get("position"),
            "lane": player.get("lane"),
            "role": player.get("role"),
            "imp": player.get("imp"),
            "level": player.get("level"),
            "last_hits": player.get("numLastHits"),
            "denies": player.get("numDenies"),
        }
