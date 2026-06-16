import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.config import get_settings
from app.integrations.opendota import OpenDotaClient
from app.integrations.patch_notes import load_patch

logger = logging.getLogger(__name__)

TaskType = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


@dataclass(frozen=True)
class EvidenceBundle:
    task_type: TaskType
    query: dict[str, Any]
    records: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    data_source: str = "unknown"  # "opendota" | "patch_json" | "mock" | "mixed"


class RetrieverTool:
    """Deterministic evidence assembly from OpenDota and patch JSON."""

    def __init__(self) -> None:
        settings = get_settings()
        self._opendota = OpenDotaClient(settings.opendota_base_url)

    async def retrieve_meta(self, role: str, patch: str = "latest") -> EvidenceBundle:
        """
        Retrieve hero stats for meta report.
        
        Returns EvidenceBundle with:
        - records: list of hero stat dicts (win_rate, pick_rate, etc.)
        - sources: ["opendota", "patch_json"] or ["mock"]
        """
        try:
            heroes = await self._opendota.get_hero_stats_for_role(role)
            sources = ["opendota"]
            data_source = "opendota"
            
            # Inject patch impact scores
            patch_data = load_patch(patch)
            if patch_data:
                heroes = self._inject_patch_scores(heroes, patch_data)
                sources.append("patch_json")
                data_source = "mixed"
            
            logger.info(f"Retrieved {len(heroes)} heroes for role={role}")
            
            return EvidenceBundle(
                task_type="meta_report",
                query={"role": role, "patch": patch},
                records=heroes,
                sources=sources,
                data_source=data_source,
            )
        except Exception as exc:
            logger.warning(f"retrieve_meta failed: {exc}, returning empty bundle")
            return EvidenceBundle(
                task_type="meta_report",
                query={"role": role, "patch": patch},
                records=[],
                sources=["error"],
                data_source="error",
            )

    async def retrieve_patch(self, patch: str = "latest") -> EvidenceBundle:
        """
        Retrieve patch notes for patch impact report.
        
        Returns EvidenceBundle with:
        - records: list of change dicts (hero, change_type, description, polarity)
        - sources: ["patch_json"]
        """
        patch_data = load_patch(patch)
        if not patch_data:
            logger.warning(f"No patch data found for {patch}")
            return EvidenceBundle(
                task_type="patch_impact",
                query={"patch": patch},
                records=[],
                sources=["error"],
                data_source="error",
            )
        
        changes = patch_data.get("changes", [])
        logger.info(f"Retrieved {len(changes)} patch changes for {patch}")
        
        return EvidenceBundle(
            task_type="patch_impact",
            query={"patch": patch},
            records=changes,
            sources=["patch_json"],
            data_source="patch_json",
        )

    async def retrieve_team(self, team_name: str) -> EvidenceBundle:
        """
        Retrieve team data for team report.
        
        Returns EvidenceBundle with:
        - records: [team_info, recent_matches, hero_stats]
        - sources: ["opendota"]
        """
        try:
            team = await self._opendota.search_team(team_name)
            if not team:
                logger.warning(f"Team not found: {team_name}")
                return EvidenceBundle(
                    task_type="team_report",
                    query={"team_name": team_name},
                    records=[],
                    sources=["opendota"],
                    data_source="not_found",
                )
            
            team_id = team["team_id"]
            
            # Fetch matches and heroes in parallel
            matches = await self._opendota.get_team_matches(team_id, limit=30)
            heroes = await self._opendota.get_team_heroes(team_id)
            
            records = [
                {"type": "team_info", "data": team},
                {"type": "recent_matches", "data": matches},
                {"type": "hero_stats", "data": heroes},
            ]
            
            logger.info(
                f"Retrieved team data for {team_name}: {len(matches)} matches, {len(heroes)} heroes"
            )
            
            return EvidenceBundle(
                task_type="team_report",
                query={"team_name": team_name},
                records=records,
                sources=["opendota"],
                data_source="opendota",
            )
        except Exception as exc:
            logger.warning(f"retrieve_team failed: {exc}, returning empty bundle")
            return EvidenceBundle(
                task_type="team_report",
                query={"team_name": team_name},
                records=[],
                sources=["error"],
                data_source="error",
            )

    async def retrieve_claim(self, claim: str, game: str = "dota2") -> EvidenceBundle:
        """
        Retrieve evidence for claim verification.
        
        Currently returns empty bundle - will be implemented in later milestone.
        """
        logger.info(f"retrieve_claim called with: {claim}")
        return EvidenceBundle(
            task_type="claim_verification",
            query={"claim": claim, "game": game},
            records=[],
            sources=["placeholder"],
            data_source="placeholder",
        )

    def _inject_patch_scores(
        self, heroes: list[dict[str, Any]], patch_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Inject patch_impact_score into hero records based on patch changes.
        
        Score calculation:
        - buff: +0.15 per buff
        - nerf: -0.15 per nerf
        """
        changes = patch_data.get("changes", [])
        
        # Build hero -> score map
        hero_scores: dict[str, float] = {}
        for change in changes:
            if change.get("entity_type") != "hero":
                continue
            hero_name = change.get("entity")
            polarity = change.get("polarity", "neutral")
            
            if hero_name not in hero_scores:
                hero_scores[hero_name] = 0.0
            
            if polarity == "buff":
                hero_scores[hero_name] += 0.15
            elif polarity == "nerf":
                hero_scores[hero_name] -= 0.15
        
        # Inject scores into hero records
        for hero in heroes:
            hero_name = hero.get("hero") or hero.get("hero_name") or hero.get("localized_name")
            hero["patch_impact_score"] = hero_scores.get(hero_name, 0.0)
        
        return heroes
