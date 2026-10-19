"""Fixed support facts: uses, purchases, placements and destruction stay distinct."""

from collections import Counter

from .data import CoverageGroup, PlayerSupport, SourcePath, SupportCount, SupportEvent

SUPPORT_ITEMS = {30, 40, 42, 43, 188, 218}
WARD_KEYS = {
    42: ("obs_log", "obs_placed", "observer_kills"),
    43: ("sen_log", "sen_placed", "sentry_kills"),
}


def apply_support(data, primary, supplement, associations, entities):
    raw_players = primary.data.get("players") or []
    # Select a source per whole ward category; an empty STRATZ group does not
    # override explicit positive OpenDota evidence in the historical sample.
    has_stratz_wards = {
        name: any((p.get("stats") or {}).get(name) for p in raw_players)
        for name in ("wards", "wardDestruction")
    }
    for i, player in enumerate(data.players or []):
        raw = raw_players[i]
        stats, playback = raw.get("stats") or {}, raw.get("playbackData") or {}
        old = next((old for old, new in associations.items() if new == i), None)
        od = supplement.data["players"][old] if supplement and old is not None else {}
        result = PlayerSupport()

        def entity(item, i=i):
            return entities.by_id(
                item, "item", f"players[{i}].support", "support item identity", data.coverage
            )

        def event(item, action, row, source, path, result=result, entity=entity):
            if item not in SUPPORT_ITEMS:
                return
            time = row.get("time")
            if time is not None and type(time) not in (int, float):
                time = None
            result.events.append(
                SupportEvent(
                    item=entity(item),
                    action=action,
                    time_seconds=time,
                    source_paths=[SourcePath(source=source, path=path)],
                )
            )

        for key, action, container in (
            ("itemUsedEvents", "used", playback),
            ("itemPurchases", "purchase_record", stats),
        ):
            for j, row in enumerate(container.get(key) or []):
                event(
                    row.get("itemId"),
                    action,
                    row,
                    "stratz",
                    f"players[{i}].{'playbackData' if action == 'used' else 'stats'}.{key}[{j}]",
                )

        for j, row in enumerate(stats.get("itemUsed") or []):
            if (
                row.get("itemId") in SUPPORT_ITEMS
                and type(row.get("count")) is int
                and row["count"] >= 0
            ):
                result.totals.append(
                    SupportCount(
                        item=entity(row["itemId"]),
                        action="used",
                        count=row["count"],
                        scope="source_total",
                        source_paths=[
                            SourcePath(source="stratz", path=f"players[{i}].stats.itemUsed[{j}]")
                        ],
                    )
                )

        if has_stratz_wards["wards"]:
            for j, row in enumerate(stats.get("wards") or []):
                item = {0: 42, 1: 43}.get(row.get("type"))
                event(item, "placed", row, "stratz", f"players[{i}].stats.wards[{j}]")
        else:
            for item, (key, _, _) in WARD_KEYS.items():
                for j, row in enumerate(od.get(key) or []):
                    if isinstance(row, dict):
                        event(item, "placed", row, "opendota", f"players[{old}].{key}[{j}]")

        if has_stratz_wards["wardDestruction"]:
            for j, row in enumerate(stats.get("wardDestruction") or []):
                item = (
                    42 if row.get("isWard") is True else 43 if row.get("isWard") is False else None
                )
                event(item, "destroyed", row, "stratz", f"players[{i}].stats.wardDestruction[{j}]")
        for item, (_, placed_key, destroyed_key) in WARD_KEYS.items():
            for action, key, category in (
                ("placed", placed_key, "wards"),
                ("destroyed", destroyed_key, "wardDestruction"),
            ):
                value = od.get(key)
                if not has_stratz_wards[category] and type(value) is int and value >= 0:
                    result.totals.append(
                        SupportCount(
                            item=entity(item),
                            action=action,
                            count=value,
                            scope="source_total",
                            source_paths=[
                                SourcePath(source="opendota", path=f"players[{old}].{key}")
                            ],
                        )
                    )
        totals = {(t.item.id, t.action) for t in result.totals}
        counts = Counter((e.item.id, e.action) for e in result.events)
        for (item, action), count in counts.items():
            if (item, action) not in totals:
                paths = [
                    p
                    for e in result.events
                    if e.item.id == item and e.action == action
                    for p in e.source_paths
                ]
                result.totals.append(
                    SupportCount(
                        item=entity(item),
                        action=action,
                        count=count,
                        scope="known_events",
                        source_paths=paths,
                    )
                )
        player.support = result
        paths = {
            (p.source, p.path): p for e in result.events + result.totals for p in e.source_paths
        }
        data.coverage.groups.append(
            CoverageGroup(
                path=f"players[{i}].support",
                status="partial" if paths else "unavailable",
                source_paths=list(paths.values()),
                reason=(
                    "Separate support actions; missing counters are unknown; "
                    "gem holding time is not derived"
                ),
            )
        )
