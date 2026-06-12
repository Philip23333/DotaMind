"""
PatchAgent: reads structured patch JSON and produces impact summaries.

Falls back to mock data if no patch file is available.
"""

from app.data.mock_data import MOCK_PATCH_IMPACT
from app.integrations.patch_notes import (
    compute_hero_patch_score,
    get_hero_changes,
    get_item_changes,
    load_patch,
)


class PatchAgent:
    """Interprets patch notes and produces structured impact data."""

    def summarize_patch(self, patch: str) -> dict[str, object]:
        """
        Summarize a patch. Returns a dict compatible with PatchImpactResponse fields.

        If no patch JSON is available, falls back to MOCK_PATCH_IMPACT.
        """
        data = load_patch(patch)
        if data is None:
            return {"patch": patch, **MOCK_PATCH_IMPACT}

        patch_id = data.get("patch", patch)
        hero_changes = get_hero_changes(patch)
        item_changes = get_item_changes(patch)
        scores = compute_hero_patch_score(patch)

        # Winners: heroes with highest patch score (most buffs)
        sorted_heroes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winners = [
            self._format_hero_name(h) for h, s in sorted_heroes[:6] if s > 0.5
        ]

        # Losers: heroes with lowest patch score (most nerfs)
        losers = [
            self._format_hero_name(h)
            for h, s in sorted(scores.items(), key=lambda x: x[1])[:6]
            if s < 0.5
        ]

        # Item impacts: summarize buffed/nerfed items
        item_buffs = [
            c["target"].replace("_", " ").title()
            for c in item_changes
            if c.get("polarity") == "buff"
        ]
        item_nerfs = [
            c["target"].replace("_", " ").title()
            for c in item_changes
            if c.get("polarity") == "nerf"
        ]

        item_impacts = []
        if item_buffs:
            unique_buffs = list(dict.fromkeys(item_buffs))[:5]
            item_impacts.append(f"Buffed items: {', '.join(unique_buffs)}")
        if item_nerfs:
            unique_nerfs = list(dict.fromkeys(item_nerfs))[:5]
            item_impacts.append(f"Nerfed items: {', '.join(unique_nerfs)}")

        # Count stats for summary
        total_changes = len(data.get("changes", []))
        buff_count = sum(
            1 for c in data["changes"] if c.get("polarity") == "buff"
        )
        nerf_count = sum(
            1 for c in data["changes"] if c.get("polarity") == "nerf"
        )

        summary = (
            f"Patch {patch_id} contains {total_changes} changes "
            f"({buff_count} buffs, {nerf_count} nerfs). "
            f"Heroes receiving the most buffs include {', '.join(winners[:3])}."
        )

        # Lineup trends (inferred from who got buffed)
        lineup_trends = []
        if any("offlane" in str(get_hero_changes(patch).get(h, "")) for h in [x[0] for x in sorted_heroes[:3]]):
            lineup_trends.append("Offlaners with teamfight presence received notable buffs.")
        if item_buffs:
            lineup_trends.append("Several mid-game items received cost reductions or damage increases.")
        lineup_trends.append(
            f"{len(winners)} heroes significantly buffed, {len(losers)} heroes nerfed."
        )

        # Practice advice
        practice_advice = []
        if winners:
            practice_advice.append(
                f"Consider practicing: {', '.join(winners[:3])}."
            )
        if losers:
            practice_advice.append(
                f"Be cautious with recently nerfed heroes: {', '.join(losers[:3])}."
            )
        practice_advice.append(
            "Review patch notes for heroes you play frequently to understand specific ability changes."
        )

        return {
            "patch": patch_id,
            "summary": summary,
            "winners": winners,
            "losers": losers,
            "item_impacts": item_impacts,
            "lineup_trends": lineup_trends,
            "practice_advice": practice_advice,
        }

    @staticmethod
    def _format_hero_name(name: str) -> str:
        """'anti_mage' -> 'Anti Mage'"""
        return name.replace("_", " ").title()
