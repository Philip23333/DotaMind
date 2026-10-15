"""Pure OpenDota-to-game-data mappings; never perform transport or mutate source facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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

from .detail_timeline import project_economy, project_minutes
from .detail_values import _missing, _rows, _value
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


def _draft(source: Mapping[str, Any], coverage: CoverageData) -> DraftData:
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
            hero_id=_value(row, "hero_id", int, f"{path}.hero_id", coverage), side=side,
        ))
    return DraftData(picks_bans=result)


def _player(source: Mapping[str, Any], i: int, coverage: CoverageData) -> PlayerData:
    path = f"players[{i}]"
    side = _side(source.get("isRadiant"))
    if side is None:
        _missing(coverage, f"{path}.identity.side", "Source isRadiant is unavailable or invalid")
    identity = PlayerIdentity(
        **{key: _value(source, key, int, f"{path}.identity.{key}", coverage)
           for key in ("account_id", "player_slot", "hero_id")},
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


def _build(source: Mapping[str, Any], i: int, coverage: CoverageData) -> PlayerBuild:
    path = f"builds.players[{i}]"
    loadout = {}
    for target, prefix, count in (("inventory", "item", 6), ("backpack", "backpack", 3)):
        loadout[target] = [
            _value(source, f"{prefix}_{slot}", int, f"{path}.final_loadout.{target}[{slot}]",
                   coverage, required=False) for slot in range(count)
        ]
        if any(value is None for value in loadout[target]):
            _missing(coverage, f"{path}.final_loadout.{target}",
                     "Some source item slots are unavailable or invalid")
    for key in ("item_neutral", "item_neutral2", "aghanims_scepter", "aghanims_shard", "moonshard"):
        kind = int if key.startswith("item_") else float
        loadout[key] = _value(source, key, kind, f"{path}.final_loadout.{key}", coverage)
    purchases = _rows(source.get("purchase_log"), f"{path}.purchase_events", coverage)
    purchase_events = None if purchases is None else [PurchaseEvent(
        time_seconds=_value(row, "time", float, "", coverage, required=False),
        item_key=_value(row, "key", str, "", coverage, required=False),
        charges=_value(row, "charges", float, "", coverage, required=False),
    ) for row in purchases]
    upgrades = source.get("ability_upgrades_arr")
    if not (isinstance(upgrades, list) and all(type(item) is int for item in upgrades)):
        upgrades = None
        _missing(coverage, f"{path}.ability_upgrade_sequence",
                 "Source ability_upgrades_arr is unavailable or invalid")
    history = _rows(source.get("neutral_item_history"), f"{path}.neutral_item_history", coverage)
    neutral_events = None if history is None else [NeutralItemEvent(
        time_seconds=_value(row, "time", float, "", coverage, required=False),
        item_key=_value(row, "item_neutral", str, "", coverage, required=False),
        enhancement_key=_value(row, "item_neutral_enhancement", str, "", coverage, required=False),
    ) for row in history]
    return PlayerBuild(
        player_slot=_value(source, "player_slot", int, f"{path}.player_slot", coverage),
        final_loadout=FinalLoadout(**loadout), purchase_events=purchase_events,
        ability_upgrade_sequence=upgrades, neutral_item_history=neutral_events,
    )


def project_game_detail(record: OpenDotaGameRecord) -> GameDetailData:
    """Project a validated source record; the public Service is not switched yet."""
    source = record.data
    if type(source.get("match_id")) is not int or source["match_id"] != record.match_id:
        raise ValueError("Source match_id must equal the internal record identity")
    coverage = CoverageData()
    players = _rows(source.get("players"), "players", coverage)
    return GameDetailData(
        match=_match(source, coverage), draft=_draft(source, coverage),
        players=None if players is None else [
            _player(player, i, coverage) for i, player in enumerate(players)
        ],
        builds=BuildsData(players=None if players is None else [
            _build(player, i, coverage) for i, player in enumerate(players)
        ]),
        economy=project_economy(source, players, coverage),
        coverage=coverage,
    )
