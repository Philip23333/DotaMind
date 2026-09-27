"""Pure source-to-DTO projections for D2PT Pub and Pro guide data."""

from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy
from typing import TypeVar, cast

from pydantic import BaseModel, JsonValue, ValidationError

from app.vnext.capabilities.hero.guide import (
    GuideItem,
    GuideItemObservation,
    ItemTiming,
    ProAbilityEvent,
    ProItemEvent,
    ProMatchExample,
    PubGuide,
    SkillSequenceOption,
    StartingItemOption,
    TalentObservation,
)

from .errors import D2PTParseError

_STATISTIC_FIELDS = ("num_matches", "num_wins", "pick_rate", "win_rate")
_POSITION_TO_NUMBER = {f"pos {position}": position for position in range(1, 6)}
_MISSING = object()

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def parse_pub_builds(
    rows: list[dict[str, JsonValue]],
    *,
    hero_id: int,
    position: int,
) -> list[PubGuide]:
    """Project every Pub source row into an independent guide DTO."""

    _validate_query(hero_id, position)
    result: list[PubGuide] = []

    for index, raw_row in enumerate(_root_rows(rows)):
        path = f"$[{index}]"
        row = _object(raw_row, path)
        source_hero_id = _required_int(row.get("hero_id", _MISSING), f"{path}.hero_id")
        if source_hero_id != hero_id:
            _fail("hero_mismatch", f"{path}.hero_id")
        source_position = row.get("position", _MISSING)
        if source_position != f"pos {position}" or not isinstance(source_position, str):
            _fail("position_mismatch", f"{path}.position")

        build_data = _object(row.get("build_data", _MISSING), f"{path}.build_data")
        build_id = _optional_int(row, "build_id", f"{path}.build_id", minimum=0)
        facet_id = _optional_int(row, "facet_id", f"{path}.facet_id", minimum=0)
        updated_at = _optional_string(row, "updated_at", f"{path}.updated_at")
        scope = _optional_object(row, "data_scope", f"{path}.data_scope")

        result.append(
            _validated(
                PubGuide,
                {
                    "build_id": build_id,
                    "facet_id": facet_id,
                    "source_updated_at": updated_at,
                    "scope": scope,
                    "statistics": {
                        "root": _statistics(row),
                        "build_data": _statistics(build_data),
                    },
                    "starting_options": _parse_starting_options(
                        build_data.get("starting_items_new", _MISSING),
                        f"{path}.build_data.starting_items_new",
                    ),
                    "item_progression": _parse_pub_items(
                        build_data.get("anchor_items", _MISSING),
                        f"{path}.build_data.anchor_items",
                    ),
                    "situational_items": _parse_pub_items(
                        build_data.get("items_mid_late", _MISSING),
                        f"{path}.build_data.items_mid_late",
                    ),
                    "skill_sequences": _parse_skill_sequences(
                        build_data.get("abilities_new", _MISSING),
                        f"{path}.build_data.abilities_new",
                    ),
                    "talents": _parse_pub_talents(
                        build_data.get("talents", _MISSING),
                        f"{path}.build_data.talents",
                    ),
                },
                path,
            )
        )

    return result


def parse_pro_examples(
    rows: list[dict[str, JsonValue]],
    *,
    hero_id: int,
) -> list[ProMatchExample]:
    """Project only recent Pro matches, preserving source order and duplicates."""

    _validate_hero_id(hero_id)
    result: list[ProMatchExample] = []

    for index, raw_row in enumerate(_root_rows(rows)):
        path = f"$[{index}]"
        row = _object(raw_row, path)
        source_hero_id = _required_int(row.get("hero_id", _MISSING), f"{path}.hero_id")
        if source_hero_id != hero_id:
            _fail("hero_mismatch", f"{path}.hero_id")
        source_position = row.get("position", _MISSING)
        if not isinstance(source_position, str) or source_position not in _POSITION_TO_NUMBER:
            _fail("position_mismatch", f"{path}.position")
        build_position = _POSITION_TO_NUMBER[source_position]

        matches = _optional_array(
            row,
            "recent_matches",
            f"{path}.recent_matches",
        )
        for match_index, raw_match in enumerate(matches):
            match_path = f"{path}.recent_matches[{match_index}]"
            match = _object(raw_match, match_path)
            result.append(
                _parse_pro_match(
                    match,
                    source_path=match_path,
                    hero_id=hero_id,
                    build_position=build_position,
                )
            )

    return result


def _parse_pro_match(
    match: dict[str, object],
    *,
    source_path: str,
    hero_id: int,
    build_position: int,
) -> ProMatchExample:
    match_id = _required_int(match.get("match_id", _MISSING), f"{source_path}.match_id")
    match_hero_id = _required_int(match.get("hero_id", _MISSING), f"{source_path}.hero_id")
    if match_hero_id != hero_id:
        _fail("hero_mismatch", f"{source_path}.hero_id")

    account_id = _optional_int(
        match,
        "account_id",
        f"{source_path}.account_id",
        minimum=0,
        maximum=4_294_967_295,
    )
    position, position_basis = _infer_match_position(
        match.get("draft", _MISSING),
        path=f"{source_path}.draft",
        hero_id=hero_id,
        account_id=account_id,
        build_position=build_position,
    )

    item_events = _optional_array(match, "items", f"{source_path}.items")
    ability_events = _optional_array(match, "abilities", f"{source_path}.abilities")
    talent_rows = _optional_array(match, "talent_data", f"{source_path}.talent_data")

    item_timeline = [
        _parse_pro_item(item, f"{source_path}.items[{index}]")
        for index, item in enumerate(item_events)
    ]
    ability_timeline = [
        _parse_pro_ability(ability, f"{source_path}.abilities[{index}]")
        for index, ability in enumerate(ability_events)
    ]
    talent_choices = [
        deepcopy(_object(talent, f"{source_path}.talent_data[{index}]"))
        for index, talent in enumerate(talent_rows)
    ]

    return _validated(
        ProMatchExample,
        {
            "source_match_id": match_id,
            "account_id": account_id,
            "hero_id": match_hero_id,
            "position": position,
            "position_basis": position_basis,
            "date": _optional_string(match, "date", f"{source_path}.date"),
            "started_at_unix": _optional_int(
                match,
                "activate_time",
                f"{source_path}.activate_time",
                minimum=0,
            ),
            "player_name": _optional_string(
                match,
                "player_name",
                f"{source_path}.player_name",
            ),
            "team_name": _optional_string(match, "team_name", f"{source_path}.team_name"),
            "opponent_name": _optional_string(
                match,
                "opponent_name",
                f"{source_path}.opponent_name",
            ),
            "won": _optional_bool(match, "won", f"{source_path}.won"),
            "duration_seconds": _optional_int(
                match,
                "duration",
                f"{source_path}.duration",
                minimum=0,
            ),
            "item_timeline": item_timeline,
            "ability_timeline": ability_timeline,
            "talent_choices": talent_choices,
            "source_path": source_path,
        },
        source_path,
    )


def _parse_starting_options(value: object, path: str) -> list[StartingItemOption]:
    if value is _MISSING or value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_structure", path)

    options: list[StartingItemOption] = []
    for index, raw_option in enumerate(value):
        option_path = f"{path}[{index}]"
        if not isinstance(raw_option, list) or len(raw_option) != 2:
            _fail("invalid_structure", option_path)
        raw_item_ids, raw_statistics = raw_option
        if not isinstance(raw_item_ids, list):
            _fail("invalid_structure", f"{option_path}[0]")
        statistics = _object(raw_statistics, f"{option_path}[1]")

        counts: Counter[int] = Counter()
        for item_index, raw_item_id in enumerate(raw_item_ids):
            item_id = _required_int(
                raw_item_id,
                f"{option_path}[0][{item_index}]",
            )
            counts[item_id] += 1

        items = [
            _validated(
                GuideItem,
                {"item_id": item_id, "quantity": quantity, "name": None},
                option_path,
            )
            for item_id, quantity in counts.items()
        ]
        options.append(
            _validated(
                StartingItemOption,
                {
                    "items": items,
                    "statistics": deepcopy(statistics),
                    "source_path": option_path,
                },
                option_path,
            )
        )
    return options


def _parse_pub_items(value: object, path: str) -> list[GuideItemObservation]:
    if value is _MISSING or value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_structure", path)

    observations: list[GuideItemObservation] = []
    for index, raw_item in enumerate(value):
        item_path = f"{path}[{index}]"
        item = _object(raw_item, item_path)
        item_id = _required_int(item.get("raw_item_id", _MISSING), f"{item_path}.raw_item_id")
        raw_minute = item.get("avg_minute", _MISSING)
        if raw_minute is _MISSING or raw_minute is None:
            phase = "unknown"
            timing = None
        else:
            minute = _finite_number(raw_minute, f"{item_path}.avg_minute")
            phase = "mid" if minute <= 30 else "late"
            timing = _validated(
                ItemTiming,
                {
                    "kind": "average",
                    "minute": minute,
                    "source_path": f"{item_path}.avg_minute",
                },
                f"{item_path}.avg_minute",
            )

        observations.append(
            _validated(
                GuideItemObservation,
                {
                    "item_id": item_id,
                    "name": None,
                    "phase": phase,
                    "timing": timing,
                    "statistics": deepcopy(item),
                    "source_path": item_path,
                },
                item_path,
            )
        )
    return observations


def _parse_skill_sequences(value: object, path: str) -> list[SkillSequenceOption]:
    if value is _MISSING or value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_structure", path)

    sequences: list[SkillSequenceOption] = []
    for index, raw_sequence in enumerate(value):
        sequence_path = f"{path}[{index}]"
        if not isinstance(raw_sequence, list) or len(raw_sequence) != 2:
            _fail("invalid_structure", sequence_path)
        raw_ids, raw_statistics = raw_sequence
        if not isinstance(raw_ids, list):
            _fail("invalid_structure", f"{sequence_path}[0]")
        statistics = _object(raw_statistics, f"{sequence_path}[1]")
        ability_ids = [
            _required_int(ability_id, f"{sequence_path}[0][{ability_index}]")
            for ability_index, ability_id in enumerate(raw_ids)
        ]
        sequences.append(
            _validated(
                SkillSequenceOption,
                {
                    "ability_ids": ability_ids,
                    "statistics": deepcopy(statistics),
                    "source_path": sequence_path,
                },
                sequence_path,
            )
        )
    return sequences


def _parse_pub_talents(value: object, path: str) -> list[TalentObservation]:
    if value is _MISSING or value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_structure", path)

    talents: list[TalentObservation] = []
    for index, raw_talent in enumerate(value):
        talent_path = f"{path}[{index}]"
        talent = _object(raw_talent, talent_path)
        level = _optional_int(talent, "lvl", f"{talent_path}.lvl", minimum=1)
        talents.append(
            _validated(
                TalentObservation,
                {
                    "level": level,
                    "data": deepcopy(talent),
                    "source_path": talent_path,
                },
                talent_path,
            )
        )
    return talents


def _parse_pro_item(value: object, path: str) -> ProItemEvent:
    item = _object(value, path)
    item_id = _required_int(item.get("item_id", _MISSING), f"{path}.item_id")
    raw_minute = item.get("minute", _MISSING)
    minute = None if raw_minute is _MISSING or raw_minute is None else _finite_number(
        raw_minute,
        f"{path}.minute",
    )
    return _validated(
        ProItemEvent,
        {
            "item_id": item_id,
            "minute": minute,
            "source_fields": deepcopy(item),
        },
        path,
    )


def _parse_pro_ability(value: object, path: str) -> ProAbilityEvent:
    ability = _object(value, path)
    ability_id = _required_int(
        ability.get("ability_id", _MISSING),
        f"{path}.ability_id",
    )
    raw_time = ability.get("time", _MISSING)
    time_seconds = None if raw_time is _MISSING or raw_time is None else _finite_number(
        raw_time,
        f"{path}.time",
    )
    hero_level = _optional_int(ability, "level", f"{path}.level", minimum=1)
    return _validated(
        ProAbilityEvent,
        {
            "ability_id": ability_id,
            "time_seconds": time_seconds,
            "hero_level": hero_level,
            "source_fields": deepcopy(ability),
        },
        path,
    )


def _infer_match_position(
    draft_value: object,
    *,
    path: str,
    hero_id: int,
    account_id: int | None,
    build_position: int,
) -> tuple[int, str]:
    if draft_value is _MISSING or draft_value is None:
        return build_position, "build"
    draft = _object(draft_value, path)

    matching_rows: list[dict[str, object]] = []
    for side in ("radiant", "dire"):
        side_path = f"{path}.{side}"
        raw_side = draft.get(side, _MISSING)
        if raw_side is _MISSING or raw_side is None:
            continue
        if not isinstance(raw_side, list):
            _fail("invalid_structure", side_path)
        for index, raw_player in enumerate(raw_side):
            player_path = f"{side_path}[{index}]"
            player = _object(raw_player, player_path)
            player_hero_id = player.get("hero_id", _MISSING)
            if type(player_hero_id) is not int or player_hero_id != hero_id:
                continue
            if account_id is not None:
                player_account_id = player.get("account_id", _MISSING)
                if type(player_account_id) is not int or player_account_id != account_id:
                    continue
            matching_rows.append(player)

    if len(matching_rows) != 1:
        return build_position, "build"
    raw_position = matching_rows[0].get("position")
    if not isinstance(raw_position, str):
        return build_position, "build"
    position = _POSITION_TO_NUMBER.get(raw_position)
    if position is None:
        return build_position, "build"
    return position, "draft"


def _root_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        _fail("invalid_structure", "$")
    return [_object(row, f"$[{index}]") for index, row in enumerate(value)]


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail("invalid_structure", path)
    return cast(dict[str, object], value)


def _optional_object(source: dict[str, object], key: str, path: str) -> dict[str, JsonValue]:
    value = source.get(key, _MISSING)
    if value is _MISSING or value is None:
        return {}
    return cast(dict[str, JsonValue], deepcopy(_object(value, path)))


def _optional_array(source: dict[str, object], key: str, path: str) -> list[object]:
    value = source.get(key, _MISSING)
    if value is _MISSING or value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_structure", path)
    return cast(list[object], value)


def _required_int(value: object, path: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        _fail("invalid_value", path)
    return value


def _optional_int(
    source: dict[str, object],
    key: str,
    path: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int | None:
    value = source.get(key, _MISSING)
    if value is _MISSING or value is None:
        return None
    parsed = _required_int(value, path, minimum=minimum)
    if maximum is not None and parsed > maximum:
        _fail("invalid_value", path)
    return parsed


def _optional_string(source: dict[str, object], key: str, path: str) -> str | None:
    value = source.get(key, _MISSING)
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, str):
        _fail("invalid_value", path)
    return value


def _optional_bool(source: dict[str, object], key: str, path: str) -> bool | None:
    value = source.get(key, _MISSING)
    if value is _MISSING or value is None:
        return None
    if type(value) is not bool:
        _fail("invalid_value", path)
    return value


def _finite_number(value: object, path: str) -> float:
    if type(value) not in (int, float):
        _fail("invalid_value", path)
    try:
        number = float(value)
    except (OverflowError, ValueError):
        _fail("invalid_value", path)
    if not math.isfinite(number):
        _fail("invalid_value", path)
    return number


def _statistics(source: dict[str, object]) -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        {key: deepcopy(source[key]) for key in _STATISTIC_FIELDS if key in source},
    )


def _validate_query(hero_id: object, position: object) -> None:
    _validate_hero_id(hero_id)
    if type(position) is not int or not 1 <= position <= 5:
        raise ValueError("position must be an integer from 1 through 5")


def _validate_hero_id(hero_id: object) -> None:
    if type(hero_id) is not int or hero_id <= 0:
        raise ValueError("hero_id must be a positive integer")


def _validated(model_type: type[_ModelT], value: object, source_path: str) -> _ModelT:
    try:
        return model_type.model_validate(value)
    except ValidationError:
        _fail("invalid_value", source_path)


def _fail(reason: str, source_path: str) -> None:
    raise D2PTParseError(reason, source_path)
