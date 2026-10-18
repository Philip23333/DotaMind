"""Fixed capability-owned STRATZ/OpenDota data groups, independent of Runtime."""

from collections import Counter
from copy import deepcopy

from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.providers.opendota.detail_projection import project_game_detail
from app.vnext.providers.opendota.game_detail import OpenDotaGameRecord
from app.vnext.providers.stratz.detail_projection import project_stratz_detail
from app.vnext.providers.stratz.game_detail import StratzGameRecord

from .data import CoverageGroup, SourcePath, TargetValue
from .death_coverage import apply_death_coverage


def _association(player, candidates):
    identity = player.identity
    if identity.player_slot is None or identity.hero is None or identity.side is None:
        return None
    matches = []
    for i, other in enumerate(candidates or []):
        candidate = other.identity
        if (
            candidate.player_slot == identity.player_slot
            and candidate.hero is not None
            and candidate.hero.id == identity.hero.id
            and candidate.side == identity.side
            and (
                identity.account_id is None
                or candidate.account_id is None
                or identity.account_id == candidate.account_id
            )
        ):
            matches.append(i)
    return matches[0] if len(matches) == 1 else None


def project_detail(
    primary: StratzGameRecord,
    supplement: OpenDotaGameRecord | None,
    *,
    entities: DetailEntities,
    units: UnitCatalog,
    supplement_error: str | None = None,
):
    """Use only the explicitly selected supplement groups, not the public raw source."""
    if supplement is not None and supplement.match_id != primary.match_id:
        raise ValueError("Supplement must identify the same Valve game")
    data, available_slots = project_stratz_detail(primary, entities=entities)
    extra = project_game_detail(supplement, entities=entities, units=units) if supplement else None
    coverage = data.coverage
    used_prefixes = {"match.score", "economy"}

    def group(path, raw, value, *, partial=False, reason=None):
        coverage.groups.append(
            CoverageGroup(
                path=path,
                status="unavailable" if value is None else "partial" if partial else "available",
                source_paths=[SourcePath(source="opendota", path=raw)] if supplement else [],
                reason=reason
                or (
                    f"OpenDota supplement unavailable ({supplement_error or 'not configured'})"
                    if supplement is None
                    else None
                ),
            )
        )

    if extra:
        data.match.score = deepcopy(extra.match.score)
        data.economy = deepcopy(extra.economy)
    group("match.score", "radiant_score", data.match.score if extra else None)
    group(
        "economy",
        "radiant_gold_adv",
        data.economy if extra else None,
        partial=extra is not None and extra.economy.time_seconds is None,
    )
    for category in ("building_destructions", "roshan_kills", "aegis_pickups"):
        value = deepcopy(getattr(extra.events, category)) if extra and extra.events else None
        setattr(data.events, category, value)
        group(
            f"events.{category}",
            "objectives",
            value,
            partial=value is not None,
            reason="Explicit returned objective records; source completeness is not asserted"
            if value is not None
            else None,
        )
        used_prefixes.add(f"events.{category}")
    # Select subcategories once: primary Tormentor, supplement courier/unknown.
    if extra and extra.events and extra.events.other_objectives is not None:
        remaining = [
            deepcopy(e) for e in extra.events.other_objectives if e.type != "tormentor_kill"
        ]
        data.events.other_objectives = (data.events.other_objectives or []) + remaining
        group(
            "events.other_objectives",
            "objectives",
            remaining,
            partial=True,
            reason="OpenDota courier/other records; Tormentor is selected from STRATZ",
        )
        used_prefixes.add("events.other_objectives")

    remapping = {}
    for i, player in enumerate(data.players or []):
        j = _association(player, extra.players if extra else None)
        same_primary = [
            p for p in data.players or [] if p.identity.player_slot == player.identity.player_slot
        ]
        if len(same_primary) != 1:
            j = None
        raw = f"players[{j}]" if j is not None else "players"
        if j is not None:
            remapping[j] = i
            player.minute_timeline = deepcopy(extra.players[j].minute_timeline)
            build = data.builds.players[i]
            old_build = extra.builds.players[j]
            for key in ("item_neutral2", "aghanims_scepter", "aghanims_shard", "moonshard"):
                setattr(build.final_loadout, key, deepcopy(getattr(old_build.final_loadout, key)))
                used_prefixes.add(f"builds.players[{j}].final_loadout.{key}")
                group(
                    f"builds.players[{i}].final_loadout.{key}",
                    f"{raw}.{key}",
                    getattr(build.final_loadout, key),
                )
            build.neutral_item_history = deepcopy(old_build.neutral_item_history)
            used_prefixes.add(f"builds.players[{j}].neutral_item_history")
            group(
                f"builds.players[{i}].neutral_item_history",
                f"{raw}.neutral_item_history",
                build.neutral_item_history,
            )
            current = data.interactions.players[i]
            previous = extra.interactions.players[j]
            current.healing_by_target = deepcopy(previous.healing_by_target)
            used_prefixes.add(f"interactions.players[{j}].healing_by_target")
            group(
                f"interactions.players[{i}].healing_by_target",
                f"{raw}.healing",
                current.healing_by_target,
            )
            if current.damage_by_target is None or any(
                row.target_hero is None for row in current.damage_by_target
            ):
                current.damage_by_target = deepcopy(previous.damage_by_target)
                prefix = f"interactions.players[{i}].damage_by_target"
                coverage.groups[:] = [g for g in coverage.groups if g.path != prefix]
                coverage.missing[:] = [m for m in coverage.missing if not m.path.startswith(prefix)]
                used_prefixes.add(f"interactions.players[{j}].damage_by_target")
                group(prefix, f"{raw}.damage", current.damage_by_target)
            slot = player.identity.player_slot
            primary_rows = [
                e for e in data.events.hero_deaths or [] if e.victim_player_slot == slot
            ]
            death_log = supplement.data["players"][j].get("deaths_log")
            if (
                slot not in available_slots or (not primary_rows and player.final_stats.deaths)
            ) and (isinstance(death_log, list) and all(isinstance(e, dict) for e in death_log)):
                replacements = [
                    deepcopy(e)
                    for e in extra.events.hero_deaths or []
                    if e.victim_player_slot == slot
                ]
                data.events.hero_deaths = (data.events.hero_deaths or []) + replacements
                available_slots.add(slot)
                prefix = f"players[{i}].minute_timeline.known_deaths"
                coverage.groups[:] = [g for g in coverage.groups if g.path != prefix]
                group(
                    prefix,
                    f"{raw}.deaths_log",
                    replacements,
                    partial=True,
                    reason="Explicit OpenDota player death log supplement",
                )
            used_prefixes.add(f"players[{j}].minute_timeline")
        for field, key in (
            ("cumulative_gold_earned", "gold_t"),
            ("cumulative_experience", "xp_t"),
            ("last_hits", "lh_t"),
            ("denies", "dn_t"),
            ("kills", "kills_log"),
        ):
            values = [getattr(node, field) for node in player.minute_timeline or []]
            available = player.minute_timeline is not None and all(v is not None for v in values)
            group(
                f"players[{i}].minute_timeline.{field}",
                f"{raw}.{key}",
                values if available else None,
                reason="Same-game player association or source series unavailable"
                if not available
                else None,
            )
        if j is None:
            group(
                f"builds.players[{i}].neutral_item_history",
                "players",
                None,
                reason="No uniquely associated supplemental player",
            )

    # Copy only gaps for selected groups; source indices in evidence remain untouched.
    if extra:
        for missing in extra.coverage.missing:
            if missing.path.endswith(".known_deaths"):
                continue
            if any(
                missing.path == p
                or missing.path.startswith(p + ".")
                or missing.path.startswith(p + "[")
                for p in used_prefixes
            ):
                copy = missing.model_copy(deep=True)
                for old, new in remapping.items():
                    if f"players[{old}]" in copy.path:
                        copy.path = copy.path.replace(f"players[{old}]", f"players[{new}]", 1)
                        break
                copy.source = "opendota"
                coverage.missing.append(copy)

    coverage.death_counts.clear()
    apply_death_coverage(data, available_slots, provider="stratz")
    # One normalized death list also supplies the kill-relation view.
    slots = Counter(p.identity.player_slot for p in data.players or [])
    by_slot = {
        p.identity.player_slot: p
        for p in data.players or []
        if p.identity.player_slot is not None and slots[p.identity.player_slot] == 1
    }
    for i, player in enumerate(data.players or []):
        if player.minute_timeline is None:
            for entry in coverage.groups:
                if entry.path == f"players[{i}].minute_timeline.known_deaths":
                    entry.status = "unavailable"
                    entry.reason = "Death facts have independent coverage; minute axis unavailable"
    for i, interaction in enumerate(data.interactions.players or []):
        counts = {}
        identified = interaction.player_slot in by_slot
        for event in data.events.hero_deaths or []:
            if identified and event.killer_player_slot == interaction.player_slot:
                victim = by_slot.get(event.victim_player_slot)
                if victim is not None and victim.identity.hero is not None:
                    key = victim.identity.hero.id
                    counts[key] = (victim.identity.hero, counts.get(key, (None, 0))[1] + 1)
        interaction.kills_by_target = (
            [TargetValue(target_hero=hero, value=count) for hero, count in counts.values()]
            if available_slots and identified
            else None
        )
        paths = [
            p
            for e in data.events.hero_deaths or []
            for p in e.source_paths
            if identified and e.killer_player_slot == interaction.player_slot
        ]
        unique = {(p.source, p.path): p for p in paths}
        coverage.groups.append(
            CoverageGroup(
                path=f"interactions.players[{i}].kills_by_target",
                status="partial" if available_slots else "unavailable",
                source_paths=list(unique.values()),
                reason="Counts of confirmed normalized death facts only",
            )
        )
    return data
