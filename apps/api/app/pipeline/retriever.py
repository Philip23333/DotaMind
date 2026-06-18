import logging
import re
from typing import Any

from app.core.config import get_settings
from app.data.mock_data import MOCK_HERO_STATS, MOCK_TEAM_REPORT
from app.domain.evidence import EvidenceBundle
from app.integrations.opendota import OpenDotaClient
from app.integrations.patch_notes import compute_hero_patch_score, get_item_changes, load_patch

logger = logging.getLogger(__name__)


def _parse_days(time_range: str) -> int:
    """Extract number of days from a string like 'last_30_days'. Defaults to 30."""
    match = re.search(r"(\d+)", time_range)
    return int(match.group(1)) if match else 30


class RetrieverTool:
    """Deterministic evidence assembly. No LLM decisions live here."""

    def __init__(self) -> None:
        settings = get_settings()
        self._live_data_enabled = settings.live_data_enabled
        self._opendota = OpenDotaClient(settings.opendota_base_url, settings.opendota_api_key)

    async def retrieve_meta(self, role: str, patch: str = "latest") -> EvidenceBundle:
        if self._live_data_enabled:
            try:
                records = await self._opendota.get_hero_stats_for_role(role)
                if records:
                    records = self._inject_patch_scores(records, patch)
                    return EvidenceBundle(
                        task_type="meta_report",
                        query={"role": role, "patch": patch},
                        records=records,
                        sources=["opendota", "patch_json"],
                        data_source="mixed",
                    )
            except Exception as exc:
                logger.warning("OpenDota meta retrieval failed: %s", exc)

        return EvidenceBundle(
            task_type="meta_report",
            query={"role": role, "patch": patch},
            records=self._mock_heroes(role),
            sources=["mock"],
            data_source="mock",
            missing=["live OpenDota hero stats"],
        )

    async def retrieve_patch(self, patch: str = "latest") -> EvidenceBundle:
        data = load_patch(patch)
        if data is None:
            return EvidenceBundle(
                task_type="patch_impact",
                query={"patch": patch},
                sources=["mock"],
                data_source="mock",
                missing=["structured patch JSON"],
            )
        return EvidenceBundle(
            task_type="patch_impact",
            query={"patch": data.get("patch", patch)},
            records=list(data.get("changes", [])),
            sources=["patch_json"],
            data_source="patch_json",
        )

    async def retrieve_team(self, team_name: str, time_range: str) -> EvidenceBundle:
        if self._live_data_enabled:
            days = _parse_days(time_range)
            try:
                data = await self._opendota.get_team_report_data(
                    team_name, match_limit=30, days=days
                )
                if data:
                    return EvidenceBundle(
                        task_type="team_report",
                        query={"team_name": team_name, "time_range": time_range},
                        records=[data],
                        sources=["opendota"],
                        data_source="opendota",
                    )
            except Exception as exc:
                logger.warning("OpenDota team retrieval failed: %s", exc)

        return EvidenceBundle(
            task_type="team_report",
            query={"team_name": team_name, "time_range": time_range},
            records=[dict(MOCK_TEAM_REPORT)],
            sources=["mock"],
            data_source="mock",
            missing=["live team match data"],
        )

    async def retrieve_claim(self, claim: str, game: str = "dota2") -> EvidenceBundle:
        normalized = claim.lower()
        records = [
            {
                "signal": "claim_entity_match",
                "value": "beastmaster" in normalized,
                "source": "rules",
            },
            {
                "signal": "role_match",
                "value": "offlane" in normalized or "position 3" in normalized,
                "source": "rules",
            },
        ]
        return EvidenceBundle(
            task_type="claim_verification",
            query={"claim": claim, "game": game},
            records=records,
            sources=["rules"],
            data_source="placeholder",
            missing=["live STRATZ pro draft sample", "fresh patch evidence"],
        )

    def _inject_patch_scores(
        self, records: list[dict[str, Any]], patch: str
    ) -> list[dict[str, Any]]:
        scores = compute_hero_patch_score(patch)
        if not scores:
            return records
        lookup = {self._key(name): score for name, score in scores.items()}
        for record in records:
            hero_name = str(record.get("hero") or record.get("localized_name") or "")
            record["patch_impact_score"] = lookup.get(self._key(hero_name), 0.5)
        return records

    @staticmethod
    def _mock_heroes(role: str) -> list[dict[str, Any]]:
        return [dict(hero) for hero in MOCK_HERO_STATS if hero["role"] == role]

    @staticmethod
    def _key(name: str) -> str:
        return name.lower().replace("-", "_").replace(" ", "_").replace("'", "")


def summarize_patch_records(records: list[dict[str, Any]], patch: str) -> dict[str, Any]:
    scores: dict[str, float] = {}
    for change in records:
        if change.get("target_type") != "hero":
            continue
        target = str(change.get("target", ""))
        scores.setdefault(target, 0.5)
        if change.get("polarity") == "buff":
            scores[target] = min(1.0, scores[target] + 0.15)
        elif change.get("polarity") == "nerf":
            scores[target] = max(0.0, scores[target] - 0.15)

    winners = [
        _title(name)
        for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if score > 0.5
    ][:6]
    losers = [
        _title(name)
        for name, score in sorted(scores.items(), key=lambda item: item[1])
        if score < 0.5
    ][:6]
    item_changes = get_item_changes(patch)
    item_buffs = [
        _title(str(c.get("target", ""))) for c in item_changes if c.get("polarity") == "buff"
    ]
    item_nerfs = [
        _title(str(c.get("target", ""))) for c in item_changes if c.get("polarity") == "nerf"
    ]
    total = len(records)
    buffs = sum(1 for c in records if c.get("polarity") == "buff")
    nerfs = sum(1 for c in records if c.get("polarity") == "nerf")
    summary = f"Patch {patch} contains {total} tracked changes ({buffs} buffs, {nerfs} nerfs)."
    return {
        "patch": patch,
        "summary": summary,
        "winners": winners or ["No clear hero winners detected"],
        "losers": losers or ["No clear hero losers detected"],
        "item_impacts": _impact_lines("Buffed items", item_buffs)
        + _impact_lines("Nerfed items", item_nerfs),
        "lineup_trends": [
            f"{len(winners)} heroes received net-positive changes.",
            "Draft priority should be reviewed against changed hero and item timings.",
        ],
        "practice_advice": [
            f"Review top changed heroes: {', '.join((winners + losers)[:4])}.",
            "Re-test item timings affected by the patch before ranked or scrim use.",
        ],
    }


def _impact_lines(label: str, values: list[str]) -> list[str]:
    unique = list(dict.fromkeys([value for value in values if value]))[:5]
    return [f"{label}: {', '.join(unique)}"] if unique else []


def _title(value: str) -> str:
    return value.replace("_", " ").title()
