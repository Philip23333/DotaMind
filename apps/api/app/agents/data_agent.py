from app.api.v1.schemas import Source
from app.data.mock_data import MOCK_HERO_STATS, MOCK_SOURCES


class DataAgent:
    """Data facade. Live integrations can replace fixtures behind this contract."""

    def sources(self) -> list[Source]:
        return [Source(**source) for source in MOCK_SOURCES]

    def hero_stats_for_role(self, role: str) -> list[dict[str, object]]:
        normalized_role = role.lower().replace("position 3", "offlane")
        return [hero for hero in MOCK_HERO_STATS if hero["role"] == normalized_role]
