"""Pure projection of verified STRATZ facts; no transport or provider selection."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from app.vnext.capabilities.game.data import (
    BuildsData,
    BuybackEvent,
    CoverageData,
    CoverageGroup,
    DraftAction,
    DraftData,
    EconomyData,
    EventsData,
    FinalLoadout,
    FinalStats,
    FirstBloodData,
    GameDetailData,
    HeroDamageFrom,
    HeroDeath,
    InteractionsData,
    InventoryEvent,
    InventorySlot,
    MatchData,
    ObjectiveEvent,
    PlayerBuild,
    PlayerData,
    PlayerIdentity,
    PlayerInteractions,
    PurchaseEvent,
    ScoreData,
    SourceConflict,
    SourcePath,
    TargetValue,
    TeamData,
    TeamsData,
)
from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.providers.opendota.detail_values import ABSENT, _missing, _rows

from .detail_states import ability_events, level_events, permanent_events
from .game_detail import StratzGameRecord


def source_path(path: str) -> list[SourcePath]:
    return [SourcePath(source="stratz", path=path)]


def _group(coverage, path, raw_path, value, *, partial=False, reason=None):
    coverage.groups.append(
        CoverageGroup(
            path=path,
            status="unavailable" if value is None else "partial" if partial else "available",
            source_paths=source_path(raw_path),
            reason=reason,
        )
    )


def _side(value):
    return "radiant" if value is True else "dire" if value is False else None


def _object(value):
    return value if isinstance(value, dict) else {}


def _draft(source, entities, coverage):
    rows = _rows(source.get("pickBans"), "draft.picks_bans", coverage)
    actions = None if rows is None else []
    for i, row in enumerate(rows or []):
        pick = row.get("isPick")
        key = "heroId" if pick is True else "bannedHeroId" if pick is False else None
        hero = entities.by_id(
            row.get(key, ABSENT) if key else ABSENT,
            "hero",
            f"draft.picks_bans[{i}].hero",
            f"pickBans[{i}].{key}",
            coverage,
        )
        if pick is False and row.get("heroId") not in (None, 0, row.get("bannedHeroId")):
            coverage.conflicts.append(
                SourceConflict(
                    sources=["stratz", "stratz"],
                    paths=[f"pickBans[{i}].heroId", f"pickBans[{i}].bannedHeroId"],
                    values=[row["heroId"], row.get("bannedHeroId")],
                )
            )
            hero = None
        actions.append(
            DraftAction(
                order=row.get("order"),
                hero=hero,
                side=_side(row.get("isRadiant")),
                action="pick" if pick is True else "ban" if pick is False else None,
            )
        )
    _group(coverage, "draft.picks_bans", "pickBans", actions)
    return DraftData(picks_bans=actions)


def _loadout(player, i, entities, coverage):
    path = f"builds.players[{i}].final_loadout"
    values = {}
    for field, prefix, count in (("inventory", "item", 6), ("backpack", "backpack", 3)):
        values[field] = [
            entities.by_id(
                player.get(f"{prefix}{n}Id", ABSENT),
                "item",
                f"{path}.{field}[{n}]",
                f"players[{i}].{prefix}{n}Id",
                coverage,
                empty_zero=True,
            )
            for n in range(count)
        ]
    values["item_neutral"] = entities.by_id(
        player.get("neutral0Id", ABSENT),
        "item",
        f"{path}.item_neutral",
        f"players[{i}].neutral0Id",
        coverage,
        empty_zero=True,
    )
    return FinalLoadout(**values)


def _build(player, i, entities, coverage):
    path = f"builds.players[{i}]"
    stats = _object(player.get("stats"))
    playback = _object(player.get("playbackData"))
    inventory = _rows(playback.get("inventoryEvents"), f"{path}.inventory_events", coverage)
    snapshots = None if inventory is None else []
    for j, row in enumerate(inventory or []):

        def slot(key, row=row, j=j):
            original = row.get(key)
            field = (
                f"backpack[{key[-1]}]"
                if key.startswith("backPack")
                else "item_neutral"
                if key == "neutral0"
                else f"inventory[{key[-1]}]"
            )
            target = f"{path}.inventory_events[{j}].{field}"
            raw = f"players[{i}].playbackData.inventoryEvents[{j}].{key}"
            if not isinstance(original, dict):
                _missing(coverage, target, "Inventory slot observation unavailable")
                return None
            return InventorySlot(
                item=entities.by_id(
                    original.get("itemId", ABSENT),
                    "item",
                    f"{target}.item",
                    f"{raw}.itemId",
                    coverage,
                    empty_zero=True,
                ),
                charges=original.get("charges"),
            )

        snapshots.append(
            InventoryEvent(
                time_seconds=row.get("time"),
                inventory=[slot(f"item{k}") for k in range(6)],
                backpack=[slot(f"backPack{k}") for k in range(3)],
                item_neutral=slot("neutral0"),
            )
        )
    purchases = _rows(stats.get("itemPurchases"), f"{path}.purchase_events", coverage)
    purchase_events = (
        None
        if purchases is None
        else [
            PurchaseEvent(
                time_seconds=row.get("time"),
                item=entities.by_id(
                    row.get("itemId", ABSENT),
                    "item",
                    f"{path}.purchase_events[{j}].item",
                    f"players[{i}].stats.itemPurchases[{j}].itemId",
                    coverage,
                ),
            )
            for j, row in enumerate(purchases)
        ]
    )
    upgrade_events = ability_events(player, i, entities, coverage)
    buffs = permanent_events(player, i, entities, coverage)
    loadout = _loadout(player, i, entities, coverage)
    for buff, field in (
        ("consumed_scepter", "has_consumed_scepter"),
        ("shard", "has_shard"),
        ("consumed_moon_shard", "has_consumed_moon_shard"),
    ):
        if any(e.upgrade == buff for e in buffs or []):
            setattr(loadout, field, True)
    for field, raw, value in (
        ("inventory_events", "playbackData.inventoryEvents", snapshots),
        ("purchase_events", "stats.itemPurchases", purchase_events),
        ("ability_upgrade_events", "playbackData.abilityLearnEvents", upgrade_events),
    ):
        _group(
            coverage,
            f"{path}.{field}",
            f"players[{i}].{raw}",
            value,
            partial=any(e.time_seconds is None for e in value or []),
            reason="Source observations only; no inventory or purchase-completeness inference",
        )
    for field in ("inventory", "backpack", "item_neutral"):
        _group(coverage, f"{path}.final_loadout.{field}", f"players[{i}]", player)
    return PlayerBuild(
        player_slot=player.get("playerSlot"),
        final_loadout=loadout,
        inventory_events=snapshots,
        purchase_events=purchase_events,
        ability_upgrade_events=upgrade_events,
        permanent_upgrade_events=buffs,
    )


def _deaths(players, coverage):
    result = []
    available = set()
    slots = Counter(p.get("playerSlot") for p in players or [])
    heroes = Counter(p.get("heroId") for p in players or [])
    for i, player in enumerate(players or []):
        slot, hero = player.get("playerSlot"), player.get("heroId")
        playback = _object(player.get("playbackData"))
        gold = playback.get("goldEvents")
        path = f"players[{i}].playbackData"
        if not isinstance(gold, list) or type(slot) is not int or slots[slot] != 1:
            _group(coverage, f"players[{i}].minute_timeline.known_deaths", path, None)
            continue
        available.add(slot)
        facts = [(j, g) for j, g in enumerate(gold) if g.get("reason") == "DEATH"]
        times = Counter(g.get("time") for _, g in facts)
        raw_deaths = playback.get("deathEvents") or []
        for j, fact in facts:
            time = fact.get("time")
            candidates = [
                d
                for d in raw_deaths
                if time is not None and d.get("time") == time and d.get("target") == hero
            ]
            linked = candidates[0] if len(candidates) == 1 and times[time] == 1 else None
            paths = source_path(f"{path}.goldEvents[{j}]")
            if linked is not None:
                k = next(k for k, d in enumerate(raw_deaths) if d is linked)
                paths += source_path(f"{path}.deathEvents[{k}]")
            elif candidates or time is None:
                _missing(
                    coverage, "events.hero_deaths", "Death attributes cannot be uniquely linked"
                )
            attacker = linked.get("attacker") if linked is not None else None
            killer = next(
                (
                    p.get("playerSlot")
                    for p in players or []
                    if type(attacker) is int
                    and p.get("heroId") == attacker
                    and heroes[attacker] == 1
                    and slots[p.get("playerSlot")] == 1
                ),
                None,
            )
            if attacker is not None and killer is None:
                _missing(
                    coverage,
                    f"events.hero_deaths[{len(result)}].killer_player_slot",
                    "Attacker cannot be associated with one same-game hero; unit remains unknown",
                    source_path=f"{path}.deathEvents[{k}].attacker",
                    source_value=attacker,
                )
            result.append(
                HeroDeath(
                    time_seconds=time,
                    victim_player_slot=slot,
                    killer_player_slot=killer,
                    source_paths=paths,
                    gold_lost=linked.get("goldLost") if linked else None,
                    gold_fed=linked.get("goldFed") if linked else None,
                    time_dead_seconds=linked.get("timeDead") if linked else None,
                )
            )
        final = player.get("deaths")
        _group(
            coverage,
            f"players[{i}].minute_timeline.known_deaths",
            f"{path}.goldEvents",
            facts,
            partial=final is None
            or len(facts) != final
            or any(g.get("time") is None for _, g in facts),
            reason="DEATH facts anchor times; gold-event amount is not deathEvents.goldLost",
        )
    return result if available or players == [] else None, available


def project_stratz_detail(
    record: StratzGameRecord, *, entities: DetailEntities
) -> tuple[
    GameDetailData,
    set[int],
]:
    """Project selected source facts; return slots whose death source was observed."""
    source = record.data
    if type(source.get("id")) is not int or source["id"] != record.match_id:
        raise ValueError("STRATZ source identity differs from the internal record")
    coverage = CoverageData()
    for issue in record.field_issues:
        _missing(coverage, "builds", f"STRATZ reported an optional playback field error at {issue}")
    players = _rows(source.get("players"), "players", coverage)
    rows = None if players is None else []
    builds = None if players is None else []
    interactions = None if players is None else []
    by_hero = {p.get("heroId") for p in players or [] if type(p.get("heroId")) is int}
    for i, p in enumerate(players or []):
        path = f"players[{i}]"
        rows.append(
            PlayerData(
                identity=PlayerIdentity(
                    account_id=p.get("steamAccountId"),
                    player_slot=p.get("playerSlot"),
                    side=_side(p.get("isRadiant")),
                    hero=entities.by_id(
                        p.get("heroId", ABSENT),
                        "hero",
                        f"{path}.identity.hero",
                        f"{path}.heroId",
                        coverage,
                    ),
                ),
                final_stats=FinalStats(
                    **{
                        field: p.get(key)
                        for field, key in {
                            "kills": "kills",
                            "deaths": "deaths",
                            "assists": "assists",
                            "level": "level",
                            "last_hits": "numLastHits",
                            "denies": "numDenies",
                            "gold_per_minute": "goldPerMinute",
                            "experience_per_minute": "experiencePerMinute",
                            "hero_damage": "heroDamage",
                            "tower_damage": "towerDamage",
                            "hero_healing": "heroHealing",
                        }.items()
                    }
                ),
                level_events=level_events(p, i, coverage),
            )
        )
        _missing(
            coverage,
            f"{path}.final_stats.earned_gold_net_worth_gap",
            "Reliable same-instant terminal cumulative income is unavailable",
        )
        _group(coverage, f"{path}.identity", path, p)
        _group(
            coverage,
            f"{path}.final_stats",
            path,
            p,
            partial=True,
            reason="Terminal earned-income/net-worth gap unavailable",
        )
        builds.append(_build(p, i, entities, coverage))
        report = _object(_object(p.get("stats")).get("heroDamageReport"))
        targets = report.get("dealtTargets")
        amounts = None if not isinstance(targets, list) else []
        for j, target in enumerate(targets or []):
            key = target.get("target")
            raw = f"{path}.stats.heroDamageReport.dealtTargets[{j}]"
            dest = f"interactions.players[{i}].damage_by_target[{j}].target_hero"
            entity = (
                entities.by_id(key, "hero", dest, f"{raw}.target", coverage)
                if key in by_hero
                else None
            )
            if entity is None:
                _missing(
                    coverage,
                    dest,
                    "Damage target namespace is not verified for this game",
                    source_path=f"{raw}.target",
                    source_value=key,
                )
            if target.get("amount") is not None:
                amounts.append(TargetValue(target_hero=entity, value=target["amount"]))
        interactions.append(
            PlayerInteractions(
                player_slot=p.get("playerSlot"),
                damage_by_target=amounts,
                damage_received_by_source=[
                    HeroDamageFrom(
                        source_hero=entities.by_id(
                            t["target"],
                            "hero",
                            f"interactions.players[{i}].damage_received_by_source[{j}].source_hero",
                            f"{path}.stats.heroDamageReport.receivedTargets[{j}].target",
                            coverage,
                        )
                        if t.get("target") in by_hero
                        else None,
                        value=t["amount"],
                    )
                    for j, t in enumerate(report.get("receivedTargets") or [])
                    if t.get("amount") is not None
                ]
                if isinstance(report.get("receivedTargets"), list)
                else None,
            )
        )
        _group(
            coverage,
            f"interactions.players[{i}].damage_received_by_source",
            f"{path}.stats.heroDamageReport.receivedTargets",
            interactions[-1].damage_received_by_source,
            partial=any(
                t.source_hero is None for t in interactions[-1].damage_received_by_source or []
            ),
        )
        _group(
            coverage,
            f"interactions.players[{i}].damage_by_target",
            f"{path}.stats.heroDamageReport.dealtTargets",
            amounts,
            partial=any(a.target_hero is None for a in amounts or []),
        )
    deaths, available = _deaths(players, coverage)
    buybacks = []
    buyback_available = False
    for i, p in enumerate(players or []):
        log = _object(p.get("playbackData")).get("buyBackEvents")
        if isinstance(log, list):
            buyback_available = True
            buybacks.extend(
                BuybackEvent(
                    time_seconds=e.get("time"),
                    player_slot=p.get("playerSlot"),
                    source_paths=source_path(f"players[{i}].playbackData.buyBackEvents[{j}]"),
                )
                for j, e in enumerate(log)
            )
        _group(
            coverage,
            "events.buybacks",
            f"players[{i}].playbackData.buyBackEvents",
            log,
        )
    chats = source.get("chatEvents")
    first = [] if isinstance(chats, list) else None
    objectives = [] if isinstance(chats, list) else None
    reported = source.get("firstBloodTime")
    for i, row in enumerate(chats or []):
        kind = {5: "first_blood", 117: "tormentor_kill"}.get(row.get("type"))
        if kind is None:
            continue
        event = ObjectiveEvent(
            time_seconds=row.get("time"), type=kind, source_paths=source_path(f"chatEvents[{i}]")
        )
        if kind == "tormentor_kill" and row.get("time") is not None:
            candidates = [p for p in players or [] if p.get("heroId") == row.get("fromHeroId")]
            if len(candidates) == 1:
                owner = candidates[0]
                owner_index = next(k for k, p in enumerate(players) if p is owner)
                buffs = (owner.get("stats") or {}).get("matchPlayerBuffEvent") or []
                linked = [
                    (j, b)
                    for j, b in enumerate(buffs)
                    if b.get("time") == row["time"] and b.get("itemId") == 609
                ]
                if len(linked) == 1:
                    event.reward_player_slot = owner.get("playerSlot")
                    raw = f"players[{owner_index}].stats.matchPlayerBuffEvent[{linked[0][0]}]"
                    event.reward_item = entities.by_id(
                        609,
                        "item",
                        "events.other_objectives.reward_item",
                        f"{raw}.itemId",
                        coverage,
                    )
                    event.source_paths += source_path(raw)
        (first if kind == "first_blood" else objectives).append(event)
        for key in ("fromHeroId", "toHeroId", "value", "isRadiant"):
            if key == "fromHeroId" and event.reward_player_slot is not None:
                continue
            if row.get(key) is not None:
                _missing(
                    coverage,
                    "events.first_blood" if kind == "first_blood" else "events.other_objectives",
                    "Unverified chat participant/reward encoding",
                    source_path=f"chatEvents[{i}].{key}",
                    source_value=row[key],
                )
        if kind == "first_blood" and reported is not None and event.time_seconds is not None:
            if reported != event.time_seconds:
                coverage.conflicts.append(
                    SourceConflict(
                        sources=["stratz", "stratz"],
                        paths=["firstBloodTime", f"chatEvents[{i}].time"],
                        values=[reported, event.time_seconds],
                    )
                )
    stamp = source.get("startDateTime")
    date = (
        datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        if stamp
        else None
    )
    teams = {}
    for side in ("radiant", "dire"):
        identifier = source.get(f"{side}TeamId")
        team = _object(source.get(f"{side}Team"))
        teams[side] = (
            TeamData(source_team_id=identifier, name=team.get("name"))
            if (identifier is not None or team)
            else None
        )
    for field, key in (
        ("match_date", "startDateTime"),
        ("duration_seconds", "durationSeconds"),
        ("game_winner", "didRadiantWin"),
        ("teams", "radiantTeamId"),
    ):
        _group(coverage, f"match.{field}", key, source.get(key))
    _group(
        coverage,
        "events.first_blood",
        "firstBloodTime",
        reported,
        partial=first is None,
        reason="Reported source time and explicit messages are separate",
    )
    _group(
        coverage,
        "events.other_objectives",
        "chatEvents",
        objectives,
        partial=True,
        reason="Returned explicit messages only; complete game-category coverage is unverified",
    )
    result = GameDetailData(
        match=MatchData(
            match_date=date,
            duration_seconds=source.get("durationSeconds"),
            game_winner=_side(source.get("didRadiantWin")),
            teams=TeamsData(**teams),
            score=ScoreData(
                **{
                    side: sum(values)
                    if isinstance(values := source.get(f"{side}Kills"), list)
                    and all(type(v) is int and v >= 0 for v in values)
                    else None
                    for side in ("radiant", "dire")
                }
            ),
        ),
        draft=_draft(source, entities, coverage),
        players=rows,
        economy=EconomyData(),
        builds=BuildsData(players=builds),
        events=EventsData(
            hero_deaths=deaths,
            buybacks=buybacks if buyback_available or players == [] else None,
            first_blood=FirstBloodData(reported_time_seconds=reported, objective_events=first),
            other_objectives=objectives,
        ),
        interactions=InteractionsData(players=interactions),
        coverage=coverage,
    )
    for gap in coverage.missing:
        gap.source = "stratz"
    return result, available
