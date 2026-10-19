"""Deterministic final statistics with explicit derivation and completeness."""

from .data import CoverageGroup, SourcePath


def apply_final_statistics(data, primary, available_slots):
    duration = primary.data.get("durationSeconds")
    for i, player in enumerate(data.players or []):
        stats = player.final_stats
        path = f"players[{i}].final_stats"
        gpm = stats.gold_per_minute
        if type(duration) is int and duration >= 0 and gpm is not None:
            stats.cumulative_gold_earned = gpm * duration // 60
        data.coverage.groups.append(
            CoverageGroup(
                path=f"{path}.cumulative_gold_earned",
                status="available" if stats.cumulative_gold_earned is not None else "unavailable",
                source_paths=[
                    SourcePath(source="stratz", path=f"players[{i}].goldPerMinute"),
                    SourcePath(source="stratz", path="durationSeconds"),
                ],
                reason=(
                    "floor(goldPerMinute * durationSeconds / 60); "
                    "derived, not an exact final counter"
                ),
            )
        )
        slot = player.identity.player_slot
        unique_slot = (
            slot is not None
            and sum(p.identity.player_slot == slot for p in data.players or []) == 1
        )
        deaths = [e for e in data.events.hero_deaths or [] if e.victim_player_slot == slot]
        amounts = [e.gold_lost for e in deaths if e.gold_lost is not None and e.gold_lost >= 0]
        observed = unique_slot and slot in available_slots
        stats.known_death_gold_lost = sum(amounts) if observed else None
        stats.death_gold_lost_count = len(amounts) if observed else None
        complete = (
            observed and stats.deaths is not None and len(deaths) == len(amounts) == stats.deaths
        )
        stats.death_gold_lost = sum(amounts) if complete else None
        paths = {(p.source, p.path): p for e in deaths for p in e.source_paths}
        data.coverage.groups.append(
            CoverageGroup(
                path=f"{path}.death_gold_lost",
                status="available" if complete else "partial" if observed else "unavailable",
                source_paths=list(paths.values()),
                reason="Sum of explicit linked death gold loss; known subtotal/count are separate",
            )
        )
