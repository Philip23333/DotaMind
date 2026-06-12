import logging

from app.api.v1.schemas import Source
from app.core.config import get_settings
from app.data.mock_data import MOCK_HERO_STATS, MOCK_SOURCES
from app.integrations.opendota import OpenDotaClient
from app.integrations.patch_notes import compute_hero_patch_score

logger = logging.getLogger(__name__)

_ROLE_ALIASES: dict[str, str] = {
    "position 1": "carry",
    "position 2": "mid",
    "position 3": "offlane",
    "position 4": "support",
    "position 5": "support",
    "safe lane": "carry",
    "hard lane": "offlane",
    "midlane": "mid",
    "off lane": "offlane",
}


def _normalize_role(role: str) -> str:
    r = role.lower().strip()
    return _ROLE_ALIASES.get(r, r)


class DataAgent:
    """
    Data facade.

    Priority:
      1. Live OpenDota /heroStats (async)
      2. Mock fixtures (fallback when live fetch fails)

    Patch impact scores are injected from the local patch JSON.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._opendota = OpenDotaClient(settings.opendota_base_url)

    # ------------------------------------------------------------------
    # Async (preferred)
    # ------------------------------------------------------------------

    async def hero_stats_for_role_async(
        self, role: str, patch: str = "latest"
    ) -> tuple[list[dict[str, object]], str]:
        """
        Returns (hero_stats, data_source) where data_source is
        "opendota" or "mock".

        Enriches each hero with patch_impact_score from the patch JSON.
        """
        normalized = _normalize_role(role)
        try:
            heroes = await self._opendota.get_hero_stats_for_role(normalized)
            if heroes:
                heroes = self._inject_patch_scores(heroes, patch)
                logger.info(
                    "OpenDota returned %d heroes for role=%s", len(heroes), normalized
                )
                return heroes, "opendota"
            logger.warning(
                "OpenDota returned 0 heroes for role=%s, falling back to mock",
                normalized,
            )
        except Exception as exc:
            logger.warning("OpenDota fetch failed (%s), falling back to mock", exc)

        return self._mock_for_role(normalized), "mock"

    # ------------------------------------------------------------------
    # Sync fallback (backwards compat)
    # ------------------------------------------------------------------

    def hero_stats_for_role(self, role: str) -> list[dict[str, object]]:
        """Sync fallback — returns mock data only."""
        return self._mock_for_role(_normalize_role(role))

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def sources(self, data_source: str = "mock") -> list[Source]:
        sources = []
        for s in MOCK_SOURCES:
            entry = dict(s)
            if entry["name"] == "OpenDota":
                entry["status"] = "live" if data_source == "opendota" else "mocked"
            sources.append(Source(**entry))
        return sources

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _mock_for_role(self, role: str) -> list[dict[str, object]]:
        return [h for h in MOCK_HERO_STATS if h["role"] == role]

    @staticmethod
    def _inject_patch_scores(
        heroes: list[dict[str, object]], patch: str
    ) -> list[dict[str, object]]:
        """
        Replace the placeholder patch_impact_score (0.5) with real values
        computed from the patch JSON.

        Hero name matching: OpenDota uses display names like "Anti-Mage",
        patch JSON uses "anti_mage". We normalise both to lowercase with
        spaces/hyphens replaced by underscores for matching.
        """
        scores = compute_hero_patch_score(patch)
        if not scores:
            return heroes  # no patch data, keep defaults

        def _key(name: str) -> str:
            return name.lower().replace("-", "_").replace(" ", "_").replace("'", "")

        score_lookup = {_key(k): v for k, v in scores.items()}

        for hero in heroes:
            hero_key = _key(str(hero.get("hero", "")))
            if hero_key in score_lookup:
                hero["patch_impact_score"] = score_lookup[hero_key]

        return heroes
