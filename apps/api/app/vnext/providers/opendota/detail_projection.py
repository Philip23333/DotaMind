"""Pure OpenDota-to-game-data mappings; never perform transport or mutate source facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.data import (
    BuildsData,
    CoverageData,
    DraftAction,
    DraftData,
    FinalLoadout,
    FinalStats,
    GameDetailData,
    MatchData,
    NeutralItemEvent,
    PlayerBuild,
    PlayerData,
    PlayerIdentity,
    PurchaseEvent,
    ScoreData,
    TeamData,
    TeamsData,
)

from .detail_entities import DetailEntities
from .detail_events import project_events
from .detail_interactions import project_interactions
from .detail_timeline import project_economy, project_minutes
from .detail_values import ABSENT, _missing, _rows, _value
from .game_detail import OpenDotaGameRecord

_FINAL_INTEGERS = ("kills", "deaths", "assists", "level", "last_hits", "denies")
_FINAL_NUMBERS = ("net_worth", "hero_damage", "tower_damage", "hero_healing")


def _side(value: Any) -> str | None:
    return "radiant" if value is True else "dire" if value is False else None


def _match(source: Mapping[str, Any], coverage: CoverageData) -> MatchData:
    date = None
    stamp = source.get("start_time")
    if type(stamp) is int and stamp > 0:
        try:
            date = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            pass
    if date is None:
        _missing(coverage, "match.match_date", "Source start_time is unavailable or invalid")
    winner = _side(source.get("radiant_win"))
    if winner is None:
        _missing(coverage, "match.game_winner", "Source radiant_win is unavailable or invalid")
    teams = {}
    for side in ("radiant", "dire"):
        team = source.get(f"{side}_team")
        path = f"match.teams.{side}"
        if not isinstance(team, dict):
            teams[side] = None
            _missing(coverage, path, "Source team record is unavailable or invalid")
        else:
            teams[side] = TeamData(
                source_team_id=_value(team, "team_id", int, f"{path}.source_team_id", coverage),
                name=_value(team, "name", str, f"{path}.name", coverage),
            )
    return MatchData(
        match_date=date,
        duration_seconds=_value(source, "duration", int, "match.duration_seconds", coverage),
        game_winner=winner,
        score=ScoreData(**{
            side: _value(source, f"{side}_score", int, f"match.score.{side}", coverage)
            for side in ("radiant", "dire")
        }),
        teams=TeamsData(**teams),
    )


def _draft(
    source: Mapping[str, Any], entities: DetailEntities, coverage: CoverageData,
) -> DraftData:
    rows = _rows(source.get("picks_bans"), "draft.picks_bans", coverage)
    if rows is None:
        return DraftData()
    result = []
    for i, row in enumerate(rows):
        path = f"draft.picks_bans[{i}]"
        code = row.get("team")
        side = {0: "radiant", 1: "dire"}.get(code) if type(code) is int else None
        pick = row.get("is_pick")
        action = "pick" if pick is True else "ban" if pick is False else None
        if side is None:
            _missing(coverage, f"{path}.side", "Unrecognized source pick/ban team code")
        if action is None:
            _missing(coverage, f"{path}.action", "Source is_pick is unavailable or invalid")
        result.append(DraftAction(
            order=_value(row, "order", int, f"{path}.order", coverage), action=action,
            hero=entities.by_id(row.get("hero_id", ABSENT), "hero", f"{path}.hero",
                                f"picks_bans[{i}].hero_id", coverage), side=side,
        ))
    return DraftData(picks_bans=result)


def _player(
    source: Mapping[str, Any], i: int, entities: DetailEntities, coverage: CoverageData,
) -> PlayerData:
    path = f"players[{i}]"
    side = _side(source.get("isRadiant"))
    if side is None:
        _missing(coverage, f"{path}.identity.side", "Source isRadiant is unavailable or invalid")
    identity = PlayerIdentity(
        **{key: _value(source, key, int, f"{path}.identity.{key}", coverage)
           for key in ("account_id", "player_slot")},
        hero=entities.by_id(source.get("hero_id", ABSENT), "hero", f"{path}.identity.hero",
                            f"players[{i}].hero_id", coverage),
        **{key: _value(source, key, str, f"{path}.identity.{key}", coverage, required=False)
           for key in ("name", "personaname")},
        side=side,
    )
    stats = FinalStats(
        **{key: _value(source, key, int, f"{path}.final_stats.{key}", coverage)
           for key in _FINAL_INTEGERS},
        **{key: _value(source, key, float, f"{path}.final_stats.{key}", coverage)
           for key in _FINAL_NUMBERS},
    )
    return PlayerData(identity=identity, final_stats=stats,
                      minute_timeline=project_minutes(source, i, coverage))


def _build(
    source: Mapping[str, Any], i: int, entities: DetailEntities, coverage: CoverageData,
) -> PlayerBuild:
    path = f"builds.players[{i}]"
    source_path = f"players[{i}]"
    loadout = {}
    for target, prefix, count in (("inventory", "item", 6), ("backpack", "backpack", 3)):
        loadout[target] = [entities.by_id(
            source.get(f"{prefix}_{slot}", ABSENT), "item",
            f"{path}.final_loadout.{target}[{slot}]", f"{source_path}.{prefix}_{slot}",
            coverage, empty_zero=True,
        ) for slot in range(count)]
    for key in ("item_neutral", "item_neutral2"):
        loadout[key] = entities.by_id(source.get(key, ABSENT), "item",
                                     f"{path}.final_loadout.{key}", f"{source_path}.{key}",
                                     coverage, empty_zero=True)
    for key in ("aghanims_scepter", "aghanims_shard", "moonshard"):
        loadout[key] = _value(source, key, float, f"{path}.final_loadout.{key}", coverage)
    purchases = _rows(source.get("purchase_log"), f"{path}.purchase_events", coverage)
    purchase_events = None if purchases is None else [PurchaseEvent(
        time_seconds=_value(row, "time", float, "", coverage, required=False),
        item=entities.by_key(row.get("key", ABSENT), "item", f"{path}.purchase_events[{j}].item",
                             f"{source_path}.purchase_log[{j}].key", coverage),
        charges=_value(row, "charges", float, "", coverage, required=False),
    ) for j, row in enumerate(purchases)]
    upgrades = source.get("ability_upgrades_arr")
    if not (isinstance(upgrades, list) and all(
        type(item) is int and item >= 0 for item in upgrades
    )):
        upgrades = None
        _missing(coverage, f"{path}.ability_upgrade_sequence",
                 "Source ability_upgrades_arr is unavailable or invalid")
    else:
        upgrades = [entities.by_id(
            identifier, "ability", f"{path}.ability_upgrade_sequence[{j}]",
            f"{source_path}.ability_upgrades_arr[{j}]", coverage,
        ) for j, identifier in enumerate(upgrades)]
    history = _rows(source.get("neutral_item_history"), f"{path}.neutral_item_history", coverage)
    neutral_events = None if history is None else [NeutralItemEvent(
        time_seconds=_value(row, "time", float, "", coverage, required=False),
        item=entities.by_key(row.get("item_neutral", ABSENT), "item",
                             f"{path}.neutral_item_history[{j}].item",
                             f"{source_path}.neutral_item_history[{j}].item_neutral",
                             coverage, required=False),
        enhancement=entities.by_key(row.get("item_neutral_enhancement", ABSENT), "item",
                                    f"{path}.neutral_item_history[{j}].enhancement",
                                    f"{source_path}.neutral_item_history[{j}].item_neutral_enhancement",
                                    coverage, required=False),
    ) for j, row in enumerate(history)]
    return PlayerBuild(
        player_slot=_value(source, "player_slot", int, f"{path}.player_slot", coverage),
        final_loadout=FinalLoadout(**loadout), purchase_events=purchase_events,
        ability_upgrade_sequence=upgrades, neutral_item_history=neutral_events,
    )


def project_game_detail(
    record: OpenDotaGameRecord, *, catalog: DotaCatalogRepository,
) -> GameDetailData:
    """Project a validated source record; the public Service is not switched yet."""
    source = record.data
    if type(source.get("match_id")) is not int or source["match_id"] != record.match_id:
        raise ValueError("Source match_id must equal the internal record identity")
    coverage = CoverageData()
    players = _rows(source.get("players"), "players", coverage)
    entities = DetailEntities(catalog)
    return GameDetailData(
        match=_match(source, coverage), draft=_draft(source, entities, coverage),
        players=None if players is None else [
            _player(player, i, entities, coverage) for i, player in enumerate(players)
        ],
        builds=BuildsData(players=None if players is None else [
            _build(player, i, entities, coverage) for i, player in enumerate(players)
        ]),
        economy=project_economy(source, players, coverage),
        events=project_events(source, players, entities.hero_ids, coverage),
        interactions=project_interactions(players, entities, coverage),
        coverage=coverage,
    )
