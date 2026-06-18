from typing import Any

from app.integrations.opendota.transport import OpenDotaTransport

_HIGH_MMR_BRACKETS = [5, 6, 7, 8]

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


class OpenDotaHeroes:
    def __init__(self, transport: OpenDotaTransport) -> None:
        self.transport = transport

    async def get_stats(self) -> list[dict[str, Any]]:
        return await self.transport.get("hero_stats", "/heroStats")

    async def get_stats_for_role(
        self,
        role: str,
        *,
        min_pub_pick: int = 100,
    ) -> list[dict[str, Any]]:
        all_heroes = await self.get_stats()
        role_lower = role.lower()
        results = []
        for hero in all_heroes:
            hero_name = hero.get("localized_name") or ""
            if self.infer_role(hero.get("roles", []), hero_name) != role_lower:
                continue
            if (hero.get("pub_pick") or 0) < min_pub_pick:
                continue
            enriched = self.enrich(hero)
            if enriched is not None:
                results.append(enriched)
        results.sort(key=lambda hero: hero["win_rate"], reverse=True)
        return results

    async def name_map(self) -> dict[int, str]:
        heroes = await self.get_stats()
        return {
            hero["id"]: hero["localized_name"]
            for hero in heroes
            if "id" in hero and "localized_name" in hero
        }

    @staticmethod
    def infer_role(tags: list[str], hero_name: str = "") -> str:
        if hero_name and hero_name in _ROLE_OVERRIDES:
            return _ROLE_OVERRIDES[hero_name]

        tags_lower = [tag.lower() for tag in tags]
        if "carry" in tags_lower:
            return "carry"
        if any(tag in tags_lower for tag in ("support", "healer")):
            return "support"
        if "nuker" in tags_lower and "escape" in tags_lower:
            return "mid"
        if "nuker" in tags_lower and "disabler" not in tags_lower:
            return "mid"
        if any(tag in tags_lower for tag in ("initiator", "durable")):
            return "offlane"
        if "disabler" in tags_lower:
            return "support"
        if "pusher" in tags_lower:
            return "offlane"
        return "other"

    @staticmethod
    def enrich(hero: dict[str, Any]) -> dict[str, Any] | None:
        name: str = hero.get("localized_name") or hero.get("name", "unknown")
        total_pick = sum(hero.get(f"{bracket}_pick") or 0 for bracket in _HIGH_MMR_BRACKETS)
        total_win = sum(hero.get(f"{bracket}_win") or 0 for bracket in _HIGH_MMR_BRACKETS)
        if total_pick == 0:
            return None

        win_rate = total_win / total_pick
        pub_pick: int = hero.get("pub_pick") or 0
        pub_pick_trend = hero.get("pub_pick_trend") or 0
        pick_rate = min(pub_pick / 1_000_000, 1.0)

        pro_pick: int = hero.get("pro_pick") or 0
        pro_win: int = hero.get("pro_win") or 0
        pro_ban: int = hero.get("pro_ban") or 0
        ban_rate = pro_ban / (pro_pick + pro_ban + 1)
        pro_presence = min(pro_pick / 50, 1.0)

        if isinstance(pub_pick_trend, list) and len(pub_pick_trend) >= 2:
            trend_delta = pub_pick_trend[-1] - pub_pick_trend[0]
            trend_score = 0.5 + min(max(trend_delta / (pub_pick + 1), -0.5), 0.5)
        elif isinstance(pub_pick_trend, (int, float)) and pub_pick > 0:
            trend_score = 0.5 + min(max(pub_pick_trend / pub_pick, -0.5), 0.5)
        else:
            trend_score = 0.5

        return {
            "hero": name,
            "role": OpenDotaHeroes.infer_role(hero.get("roles", []), name),
            "win_rate": round(win_rate, 4),
            "pick_rate": round(pick_rate, 4),
            "ban_rate": round(ban_rate, 4),
            "pro_presence": round(pro_presence, 4),
            "pro_pick": pro_pick,
            "pro_win": pro_win,
            "pro_ban": pro_ban,
            "trend_score": round(trend_score, 4),
            "patch_impact_score": 0.5,
            "recommendation": "B",
            "reasons": [],
            "practice_advice": [],
        }
