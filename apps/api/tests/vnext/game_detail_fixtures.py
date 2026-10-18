"""Synthetic STRATZ facts for orchestration tests originally built with OpenDota fixtures.

These are test inputs, not a production conversion or a live STRATZ sample.
"""

from app.vnext.providers.stratz.game_detail import StratzGameRecord


def stratz_facts(source):
    players = None if source.get("players") is None else []
    for row in source.get("players") or []:
        fields = {
            "steamAccountId": "account_id",
            "playerSlot": "player_slot",
            "heroId": "hero_id",
            "isRadiant": "isRadiant",
            "kills": "kills",
            "deaths": "deaths",
            "assists": "assists",
            "level": "level",
            "numLastHits": "last_hits",
            "numDenies": "denies",
            "heroDamage": "hero_damage",
            "towerDamage": "tower_damage",
            "heroHealing": "hero_healing",
        }
        player = {key: row.get(value) for key, value in fields.items()}
        for prefix, count in (("item", 6), ("backpack", 3)):
            player.update({f"{prefix}{i}Id": row.get(f"{prefix}_{i}") for i in range(count)})
        players.append(player)
    return {
        "id": source["match_id"],
        "startDateTime": source.get("start_time"),
        "durationSeconds": source.get("duration"),
        "didRadiantWin": source.get("radiant_win"),
        "players": players,
    }


class StratzFixtureProvider:
    def __init__(self, source, retrieved_at):
        self.record = StratzGameRecord(
            match_id=source["match_id"], retrieved_at=retrieved_at, data=stratz_facts(source)
        )

    async def get_game_record(self, match_id):
        assert self.record.match_id == match_id
        return self.record.model_copy(deep=True)
