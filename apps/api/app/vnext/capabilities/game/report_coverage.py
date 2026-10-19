"""Translate governed field locations to the sole public report namespace.

Provider source paths are evidence, not document locations, and stay untouched.
"""

from .data import CoverageGroup


def report_coverage(data, report):
    mappings = {
        "match": "report.overview.match",
        "draft": "report.overview.draft",
        "economy.minute_timeline": "report.player_statistics.team_economy_timeline",
        "economy": "report.player_statistics.team_economy_timeline",
        "coverage": "report.coverage",
        "events.first_blood": "report.events.first_blood",
    }
    excluded = set()
    for i, player in enumerate(data.players or []):
        root = f"players[{i}]"
        final = f"report.player_statistics.final_players[{i}]"
        history = f"report.player_statistics.player_histories[{i}]"
        minute = f"report.player_statistics.minute_snapshots[*].players[{i}]"
        mappings.update(
            {
                f"{root}.identity": f"{final}.identity",
                f"{root}.final_stats": f"{final}.final_stats",
                f"{root}.level_events": f"{history}.level_events",
                f"{root}.minute_timeline.cumulative_experience": f"{history}.experience_timeline",
                f"{root}.minute_timeline": minute,
                f"{root}.support": f"report.support_contributions.player_histories[{i}]",
            }
        )
        # The report counts kills from normalized death facts, not the DTO's
        # supplemental kills_log curve. Do not misattribute that unused curve.
        excluded.add(f"{root}.minute_timeline.kills")
        by_time = {
            s.time_seconds: j for j, s in enumerate(report.player_statistics.minute_snapshots)
        }
        for j, node in enumerate(player.minute_timeline or []):
            old = f"{root}.minute_timeline[{j}]"
            new = (
                f"report.player_statistics.minute_snapshots[{by_time[node.time_seconds]}].players[{i}]"
                if node.time_seconds in by_time
                else minute
            )
            mappings[old] = new
            mappings[f"{old}.cumulative_experience"] = (
                f"{history}.experience_timeline[{j}].cumulative_experience"
            )
            excluded.add(f"{old}.kills")
    for j, build in enumerate(data.builds.players or []):
        owners = [
            i
            for i, p in enumerate(data.players or [])
            if p.identity.player_slot == build.player_slot
        ]
        root = f"builds.players[{j}]"
        if build.player_slot is not None and len(owners) == 1:
            i = owners[0]
            mappings[root] = f"report.equipment_and_skills.player_histories[{i}]"
            mappings[f"{root}.final_loadout"] = (
                f"report.equipment_and_skills.final_players[{i}].final_loadout"
            )
        else:
            mappings[root] = "report.equipment_and_skills"
    for j, interaction in enumerate(data.interactions.players or [] if data.interactions else []):
        owners = [
            i
            for i, p in enumerate(data.players or [])
            if p.identity.player_slot == interaction.player_slot
        ]
        root = f"interactions.players[{j}]"
        if interaction.player_slot is not None and len(owners) == 1:
            mappings[root] = f"report.hero_damage.player_relations[{owners[0]}]"
        else:
            mappings[root] = "report.hero_damage"
        for field in ("damage_by_target", "damage_received_by_source"):
            mappings[f"{root}.{field}"] = "report.hero_damage.matrix"
    for source_name, public_name in (
        ("hero_deaths", "hero_kills_and_deaths"),
        *(
            (key, key)
            for key in (
                "buybacks",
                "building_destructions",
                "roshan_kills",
                "aegis_pickups",
                "other_objectives",
            )
        ),
    ):
        root = f"events.{source_name}"
        public = f"report.events.{public_name}"
        mappings[root] = public
        rows = getattr(report.events, public_name)
        for i, fact in enumerate(getattr(data.events, source_name, None) or []):
            matches = [j for j, row in enumerate(rows) if row.fact is fact]
            if len(matches) == 1:
                mappings[f"{root}[{i}]"] = f"{public}[{matches[0]}].fact"
    mappings.update(
        {
            "players": "report.player_statistics",
            "builds": "report.equipment_and_skills",
            "interactions": "report.hero_damage",
            "events": "report.events",
        }
    )

    def translate(path):
        # Exact location first, then its ancestors; never scan thousands of
        # unrelated mapping entries for each missing inventory slot.
        parents = [path] + [path[:i] for i in range(len(path) - 1, -1, -1) if path[i] in ".["]
        for old in parents:
            if old in excluded:
                return None
            if old in mappings:
                return mappings[old] + path[len(old) :]
        raise ValueError(f"Unmapped governed coverage location: {path}")

    coverage = data.coverage.model_copy(deep=True)
    for name in ("groups", "missing"):
        rows = []
        for row in getattr(coverage, name):
            path = translate(row.path)
            if path is not None:
                row.path = path
                rows.append(row)
        setattr(coverage, name, rows)
    paths = {
        (path.source, path.path): path
        for event in report.events.hero_kills_and_deaths
        for path in event.fact.source_paths
    }
    available = data.events is not None and data.events.hero_deaths is not None
    coverage.groups.append(
        CoverageGroup(
            path="report.player_statistics.minute_snapshots[*].players[*].known_kills",
            status="partial" if available else "unavailable",
            source_paths=list(paths.values()),
            reason=(
                "Known credited kills from normalized death facts; "
                "not a complete source kills curve"
            ),
        )
    )
    return coverage
