"""Count normalized death facts without treating missing events as zero deaths."""

from bisect import bisect_right
from collections import Counter

from .data import DeathCounts, GameDetailData, MissingData, Provider


def apply_death_coverage(
    data: GameDetailData, available_slots: set[int], *, provider: Provider,
) -> None:
    players = data.players or []
    slots = Counter(p.identity.player_slot for p in players)
    deaths = data.events.hero_deaths if data.events else None
    for i, player in enumerate(players):
        slot = player.identity.player_slot
        final = player.final_stats.deaths
        available = slot is not None and slots[slot] == 1 and slot in available_slots
        rows = [d for d in deaths or [] if d.victim_player_slot == slot] if available else []
        times = sorted(d.time_seconds for d in rows if d.time_seconds is not None)
        known = len(times) if available else None
        unknown = sum(d.time_seconds is None for d in rows) if available else None
        remaining = None
        if available and final is not None:
            observed = len(rows)
            if final >= observed:
                remaining = final - observed
            else:
                data.coverage.missing.append(MissingData(
                    path=f"coverage.death_counts[{i}].unaccounted_deaths", source=provider,
                    reason="Normalized death count exceeds final deaths; counts are not reconciled",
                ))
        data.coverage.death_counts.append(DeathCounts(
            player_slot=slot, final_deaths=final, known_time_deaths=known,
            unknown_time_deaths=unknown, unaccounted_deaths=remaining,
        ))
        for node in player.minute_timeline or []:
            node.known_deaths = bisect_right(times, node.time_seconds) if available else None
        if not available or unknown or remaining or (available and remaining is None):
            data.coverage.missing.append(MissingData(
                path=f"players[{i}].minute_timeline.known_deaths",
                reason="Death coverage is unavailable or partial; final deaths stay independent",
                source=provider,
            ))
