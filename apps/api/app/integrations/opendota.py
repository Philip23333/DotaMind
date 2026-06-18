"""
OpenDota API client.

Endpoints used:
  GET /heroStats  — hero stats + win/pick rates by MMR bracket and pro matches
  GET /heroes     — hero metadata (localized names, roles)

Rate limit: 60 req/min without API key, 1200/min with key.
All data is fetched once and cached in memory for CACHE_TTL seconds.
"""

import asyncio
import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Role mapping
# OpenDota "roles" tags → our canonical role keys
# A hero can have multiple tags; we pick the first match in priority order.
# ---------------------------------------------------------------------------
_ROLE_PRIORITY = ["carry", "support", "offlane", "mid", "jungle"]

_ROLE_TAG_MAP: dict[str, str] = {
    # carry
    "carry": "carry",
    # mid
    "nuker": "mid",
    # offlane / initiator
    "initiator": "offlane",
    "durable": "offlane",
    # support
    "support": "support",
    "disabler": "support",
    "healer": "support",
    # fallback
    "pusher": "offlane",
    "escape": "carry",
    "jungler": "jungle",
}

# High-MMR brackets used for ranked stats: Crusader(3) through Immortal(8)
_HIGH_MMR_BRACKETS = [5, 6, 7, 8]  # Ancient, Divine, Immortal

# Override for heroes whose OpenDota role tags don't match
# their actual position in competitive play.
_ROLE_OVERRIDES: dict[str, str] = {
    "Mars": "offlane",
    "Tidehunter": "offlane",
    "Underlord": "offlane",
    "Sand King": "offlane",
    "Centaur Warrunner": "offlane",
    "Axe": "offlane",
    "Bristleback": "offlane",
    "Doom": "offlane",
    "Legion Commander": "offlane",
    "Night Stalker": "offlane",
    "Spirit Breaker": "offlane",
    "Slardar": "offlane",
    "Pangolier": "offlane",
    "Brewmaster": "offlane",
    "Timbersaw": "offlane",
    "Pudge": "offlane",
    "Invoker": "mid",
    "Puck": "mid",
    "Storm Spirit": "mid",
    "Ember Spirit": "mid",
    "Templar Assassin": "mid",
    "Shadow Fiend": "mid",
    "Queen of Pain": "mid",
    "Lina": "mid",
    "Zeus": "mid",
    "Outworld Destroyer": "mid",
    "Tinker": "mid",
    "Void Spirit": "mid",
    "Anti-Mage": "carry",
    "Juggernaut": "carry",
    "Phantom Assassin": "carry",
    "Faceless Void": "carry",
    "Spectre": "carry",
    "Morphling": "carry",
    "Terrorblade": "carry",
    "Luna": "carry",
    "Medusa": "carry",
    "Troll Warlord": "carry",
    "Wraith King": "carry",
    "Slark": "carry",
}

CACHE_TTL = 3600  # seconds (1 hour)


class OpenDotaClient:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._cache: dict[str, tuple[float, Any]] = {}  # key -> (expires_at, data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_hero_stats(self) -> list[dict[str, Any]]:
        """
        Fetch /heroStats with in-memory cache.

        Returns raw list of hero stat dicts from OpenDota.
        Each entry has fields like:
          localized_name, roles, pro_pick, pro_win, pro_ban,
          pub_pick, pub_win, {1..8}_pick, {1..8}_win
        """
        return await self._cached("hero_stats", "/heroStats")

    async def get_hero_stats_for_role(
        self,
        role: str,
        *,
        min_pub_pick: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Return hero stats filtered to the given role, enriched with
        computed winrate/pickrate/ban-rate fields ready for DataAgent.

        Args:
            role: canonical role string, e.g. "offlane", "carry", "mid", "support"
            min_pub_pick: minimum total public picks to include a hero (filters noise)
        """
        all_heroes = await self.get_hero_stats()
        role_lower = role.lower()

        results = []
        for hero in all_heroes:
            hero_name = hero.get("localized_name") or ""
            hero_role = self._infer_role(hero.get("roles", []), hero_name)
            if hero_role != role_lower:
                continue

            pub_pick: int = hero.get("pub_pick") or 0
            if pub_pick < min_pub_pick:
                continue

            enriched = self._enrich(hero)
            if enriched is not None:
                results.append(enriched)

        # sort by high-MMR win rate descending
        results.sort(key=lambda h: h["win_rate"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Team APIs
    # ------------------------------------------------------------------

    async def search_team(self, team_name: str) -> dict[str, Any] | None:
        """
        Search for a team by name or tag in the /teams endpoint.
        Returns the best match or None.
        """
        teams = await self._cached("teams_list", "/teams")
        name_lower = team_name.lower().strip()
        # Exact name match
        for t in teams:
            if t.get("name", "").lower() == name_lower:
                return t
        # Exact tag match
        for t in teams:
            if t.get("tag", "").lower() == name_lower:
                return t
        # Partial name match
        for t in teams:
            if name_lower in t.get("name", "").lower():
                return t
        # Partial tag match
        for t in teams:
            if name_lower in t.get("tag", "").lower():
                return t
        return None

    async def get_team_matches(self, team_id: int) -> list[dict[str, Any]]:
        """Fetch all matches for a team. Sorted newest-first by match_id.

        NOTE: OpenDota's ?limit= query param is unreliable and ignored.
        Do client-side slicing after fetching.
        """
        return await self._cached(f"team_matches_{team_id}", f"/teams/{team_id}/matches")

    async def get_team_heroes(self, team_id: int) -> list[dict[str, Any]]:
        """Fetch hero stats for a team (all time). Kept for backward compat."""
        return await self._cached(f"team_heroes_{team_id}", f"/teams/{team_id}/heroes")

    async def get_team_players(self, team_id: int) -> list[dict[str, Any]]:
        """Fetch roster / players for a team."""
        return await self._cached(f"team_players_{team_id}", f"/teams/{team_id}/players")

    async def _get_match_detail(self, match_id: int) -> dict[str, Any]:
        """Fetch full match detail (includes per-player hero picks)."""
        return await self._cached(f"match_{match_id}", f"/matches/{match_id}")

    async def _aggregate_team_heroes(
        self, matches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Aggregate hero pick/win stats from match details for the given match list."""
        match_ids = [m["match_id"] for m in matches if "match_id" in m]
        if not match_ids:
            return []

        details = await asyncio.gather(
            *(self._get_match_detail(mid) for mid in match_ids),
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
                player_radiant = player.get("isRadiant")
                if player_radiant != team_is_radiant:
                    continue
                hero_id = player.get("hero_id")
                if hero_id is None:
                    continue
                if hero_id not in hero_stats:
                    hero_stats[hero_id] = {"games": 0, "wins": 0}
                hero_stats[hero_id]["games"] += 1
                if team_won:
                    hero_stats[hero_id]["wins"] += 1

        hero_map = await self._hero_name_map()
        result = []
        for hero_id, stats in hero_stats.items():
            result.append(
                {
                    "hero_id": hero_id,
                    "localized_name": hero_map.get(hero_id, f"Hero {hero_id}"),
                    "games_played": stats["games"],
                    "wins": stats["wins"],
                }
            )
        result.sort(key=lambda h: h["games_played"], reverse=True)
        return result

    async def _hero_name_map(self) -> dict[int, str]:
        """Build hero_id -> localized_name mapping from cached heroStats."""
        heroes = await self.get_hero_stats()
        return {
            h["id"]: h["localized_name"]
            for h in heroes
            if "id" in h and "localized_name" in h
        }

    async def get_team_report_data(
        self, team_name: str, *, match_limit: int = 30, days: int = 30
    ) -> dict[str, Any] | None:
        """
        High-level: fetch team info + time-windowed matches + roster + heroes.
        Returns structured data for TeamReportService, or None if team not found.
        """
        team = await self.search_team(team_name)
        if team is None:
            return None

        team_id = team["team_id"]

        # --- Fetch all matches, then filter client-side (server ?limit is broken) ---
        all_matches = await self.get_team_matches(team_id)

        # Time-window filter via start_time
        if days > 0:
            cutoff = time.time() - days * 86400
            matches = [m for m in all_matches if m.get("start_time", 0) >= cutoff]
        else:
            matches = list(all_matches)

        # Cap to most recent N (already sorted newest-first by match_id)
        matches = matches[:match_limit]

        if not matches:
            return {
                "team_name": team.get("name", team_name),
                "team_id": team_id,
                "rating": team.get("rating"),
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

        # --- Roster ---
        players = await self.get_team_players(team_id)
        key_players = [p["name"] for p in players[:5] if p.get("name")]

        # --- Heroes aggregated from the time-windowed match details ---
        heroes = await self._aggregate_team_heroes(matches)

        # --- Recent record ---
        wins = sum(
            1
            for m in matches
            if (m.get("radiant") and m.get("radiant_win"))
            or (not m.get("radiant") and not m.get("radiant_win"))
        )
        losses = len(matches) - wins
        recent_record = f"{wins}-{losses} in last {len(matches)} matches"

        # --- Signature heroes (top 5 by games played within window) ---
        signature_heroes = [
            h["localized_name"] for h in heroes[:5] if "localized_name" in h
        ]

        # --- Hero pool depth (heroes played >= 2 games in the window) ---
        hero_pool_depth = len([h for h in heroes if h.get("games_played", 0) >= 2])

        # --- Draft flexibility (scaled for ~30-match window) ---
        draft_flex = min(hero_pool_depth / 25, 1.0)

        # --- Patch adaptation ---
        recent_wr = wins / max(len(matches), 1)
        patch_adaptation = int(
            min(100, (recent_wr * 50 + draft_flex * 30 + min(len(matches) / 30, 1) * 20))
        )

        # --- Opposing teams faced ---
        opponents = list(
            {m.get("opposing_team_name", "") for m in matches if m.get("opposing_team_name")}
        )

        # --- Win/loss patterns (duration-based heuristic) ---
        win_durations = []
        loss_durations = []
        for m in matches:
            is_win = (m.get("radiant") and m.get("radiant_win")) or (
                not m.get("radiant") and not m.get("radiant_win")
            )
            dur = m.get("duration", 0)
            if is_win:
                win_durations.append(dur)
            else:
                loss_durations.append(dur)

        win_patterns = []
        loss_patterns = []
        if win_durations:
            avg_win = sum(win_durations) / len(win_durations) / 60
            win_patterns.append(f"Average winning game duration: {avg_win:.0f} minutes.")
        if loss_durations:
            avg_loss = sum(loss_durations) / len(loss_durations) / 60
            loss_patterns.append(f"Average losing game duration: {avg_loss:.0f} minutes.")
        if recent_wr >= 0.6:
            win_patterns.append("Strong recent form with consistent execution.")
        if recent_wr < 0.5:
            loss_patterns.append(
                "Below 50% win rate in recent matches suggests meta adaptation issues."
            )

        return {
            "team_name": team.get("name", team_name),
            "team_id": team_id,
            "rating": team.get("rating"),
            "recent_record": recent_record,
            "wins": wins,
            "losses": losses,
            "signature_heroes": signature_heroes,
            "hero_pool_depth": hero_pool_depth,
            "draft_flexibility": round(draft_flex, 2),
            "patch_adaptation_score": patch_adaptation,
            "win_patterns": win_patterns,
            "loss_patterns": loss_patterns,
            "key_players": key_players,
            "opponents_faced": opponents[:5],
            "recent_win_rate": round(recent_wr, 3),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _cached(self, key: str, path: str) -> Any:
        now = time.monotonic()
        if key in self._cache:
            expires_at, data = self._cache[key]
            if now < expires_at:
                return data

        params = {"api_key": self.api_key} if self.api_key else None
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            data = response.json()

        self._cache[key] = (now + CACHE_TTL, data)
        return data

    @staticmethod
    def _infer_role(tags: list[str], hero_name: str = "") -> str:
        """
        Map OpenDota role tags to a canonical role string.

        Checks _ROLE_OVERRIDES first (for heroes whose tags are misleading),
        then falls back to tag-based heuristics.
        """
        # Override table takes priority
        if hero_name and hero_name in _ROLE_OVERRIDES:
            return _ROLE_OVERRIDES[hero_name]

        tags_lower = [t.lower() for t in tags]

        # Explicit carry tag wins
        if "carry" in tags_lower:
            return "carry"
        # Support / healer / disabler
        if any(t in tags_lower for t in ("support", "healer")):
            return "support"
        # Mid typically has nuker + escape or nuker without carry
        if "nuker" in tags_lower and "escape" in tags_lower:
            return "mid"
        if "nuker" in tags_lower and "disabler" not in tags_lower:
            return "mid"
        # Initiator / durable → offlane
        if any(t in tags_lower for t in ("initiator", "durable")):
            return "offlane"
        # Disabler alone → support
        if "disabler" in tags_lower:
            return "support"
        # Pusher without other strong signals → offlane
        if "pusher" in tags_lower:
            return "offlane"

        return "other"

    @staticmethod
    def _enrich(hero: dict[str, Any]) -> dict[str, Any] | None:
        """
        Compute derived stats from raw OpenDota heroStats entry.

        win_rate    — average win rate across high-MMR brackets (Ancient+)
        pick_rate   — pub_pick normalised to [0,1] relative to total pub matches
                      (OpenDota returns absolute counts, not rates)
        ban_rate    — pro_ban / (pro_pick + pro_ban + 1) as a rough proxy
        pro_presence — pro_pick / (pro_pick + 1) normalised 0–1 (soft)
        """
        name: str = hero.get("localized_name") or hero.get("name", "unknown")

        # High-MMR win rate: sum wins / sum picks across brackets 5-8
        total_pick = 0
        total_win = 0
        for b in _HIGH_MMR_BRACKETS:
            picks = hero.get(f"{b}_pick") or 0
            wins = hero.get(f"{b}_win") or 0
            total_pick += picks
            total_win += wins

        if total_pick == 0:
            return None  # no data for this hero in high MMR

        win_rate = total_win / total_pick

        # Public pick count (absolute) — used as relative proxy
        pub_pick: int = hero.get("pub_pick") or 0
        pub_pick_trend: int = hero.get("pub_pick_trend") or 0

        # Normalise pick_rate: 0.20 pub_pick_fraction → 1.0
        # OpenDota doesn't expose total match count directly in /heroStats,
        # so we use a fixed denominator heuristic (1_000_000 pub matches/week).
        TOTAL_MATCHES_ESTIMATE = 1_000_000
        pick_rate = min(pub_pick / TOTAL_MATCHES_ESTIMATE, 1.0)

        # Pro stats
        pro_pick: int = hero.get("pro_pick") or 0
        pro_win: int = hero.get("pro_win") or 0
        pro_ban: int = hero.get("pro_ban") or 0
        pro_total = pro_pick + pro_ban
        ban_rate = pro_ban / (pro_total + 1)  # +1 avoids div-by-zero
        pro_presence = min(pro_pick / 50, 1.0)  # 50 pro picks → presence = 1.0

        # Trend: pub_pick_trend can be a list of recent data points or an int.
        # We treat it as a rising signal if the last value > first value.
        if isinstance(pub_pick_trend, list) and len(pub_pick_trend) >= 2:
            trend_delta = pub_pick_trend[-1] - pub_pick_trend[0]
            trend_score = 0.5 + min(max(trend_delta / (pub_pick + 1), -0.5), 0.5)
        elif isinstance(pub_pick_trend, (int, float)) and pub_pick > 0:
            trend_score = 0.5 + min(max(pub_pick_trend / pub_pick, -0.5), 0.5)
        else:
            trend_score = 0.5

        return {
            "hero": name,
            "role": OpenDotaClient._infer_role(hero.get("roles", []), name),
            "win_rate": round(win_rate, 4),
            "pick_rate": round(pick_rate, 4),
            "ban_rate": round(ban_rate, 4),
            "pro_presence": round(pro_presence, 4),
            "pro_pick": pro_pick,
            "pro_win": pro_win,
            "pro_ban": pro_ban,
            "trend_score": round(trend_score, 4),
            # placeholders — downstream can override
            "patch_impact_score": 0.5,
            "recommendation": "B",
            "reasons": [],
            "practice_advice": [],
        }
