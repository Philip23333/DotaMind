from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.vnext.capabilities.hero.guide import ProMatchExample, PubGuide
from app.vnext.providers.d2pt import D2PTParseError
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"


def _pub_fixture() -> list[dict[str, Any]]:
    return json.loads((_FIXTURE_DIR / "pub_sven_pos1.json").read_bytes())


def _pro_fixture() -> list[dict[str, Any]]:
    return json.loads((_FIXTURE_DIR / "pro_sven.json").read_bytes())


def _pub_row(**overrides: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "hero_id": 18,
        "position": "pos 1",
        "build_id": 0,
        "facet_id": 0,
        "updated_at": None,
        "data_scope": {},
        "build_data": {},
    }
    row.update(overrides)
    return row


def _pro_match(**overrides: object) -> dict[str, Any]:
    match: dict[str, Any] = {
        "match_id": 90,
        "hero_id": 18,
        "items": [],
        "abilities": [],
        "talent_data": [],
    }
    match.update(overrides)
    return match


def _pro_row(**overrides: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "hero_id": 18,
        "position": "pos 1",
        "recent_matches": [],
    }
    row.update(overrides)
    return row


def _parse_error(call: Any) -> D2PTParseError:
    with pytest.raises(D2PTParseError) as exc_info:
        call()
    return exc_info.value


def test_sven_pub_fixture_maps_all_records_and_candidate_groups() -> None:
    rows = _pub_fixture()

    guides = parse_pub_builds(rows, hero_id=18, position=1)

    assert len(guides) == 1
    guide = guides[0]
    assert isinstance(guide, PubGuide)
    assert guide.build_id == rows[0]["build_id"]
    assert guide.facet_id == rows[0]["facet_id"]
    assert guide.source_updated_at == rows[0]["updated_at"]
    assert guide.scope == rows[0]["data_scope"]
    assert len(guide.starting_options) == 3
    first_start = guide.starting_options[0]
    assert [item.item_id for item in first_start.items] == [11, 16, 34, 44, 237]
    assert [item.quantity for item in first_start.items] == [1, 2, 1, 1, 1]
    assert all(item.name is None for item in first_start.items)
    assert first_start.statistics == rows[0]["build_data"]["starting_items_new"][0][1]
    assert first_start.source_path == "$[0].build_data.starting_items_new[0]"
    assert len(guide.item_progression) == 9
    assert guide.item_progression[0].item_id == 63
    assert guide.item_progression[0].timing is not None
    assert guide.item_progression[0].timing.kind == "average"
    assert guide.item_progression[0].timing.minute == pytest.approx(5.459013209013209)
    assert guide.item_progression[0].phase == "mid"
    assert guide.item_progression[0].timing.source_path == (
        "$[0].build_data.anchor_items[0].avg_minute"
    )
    assert guide.item_progression[0].statistics == rows[0]["build_data"]["anchor_items"][0]
    assert len(guide.situational_items) == 17
    assert len(guide.skill_sequences) == 5
    assert guide.skill_sequences[0].ability_ids == [
        5094,
        5096,
        5095,
        5095,
        5095,
        5097,
        5095,
        5094,
        5094,
        5094,
    ]
    assert guide.skill_sequences[0].statistics == rows[0]["build_data"]["abilities_new"][0][1]
    assert len(guide.talents) == 4
    assert guide.talents[0].data == rows[0]["build_data"]["talents"][0]


def test_sven_pub_statistics_keep_root_and_build_data_namespaces() -> None:
    guide = parse_pub_builds(_pub_fixture(), hero_id=18, position=1)[0]

    assert guide.statistics["root"]["pick_rate"] == 100.0
    assert guide.statistics["build_data"]["pick_rate"] == 1.0
    assert "num_matches" in guide.statistics["root"]
    assert "num_wins" in guide.statistics["build_data"]


def test_sven_pro_fixture_maps_recent_matches_only() -> None:
    rows = _pro_fixture()

    examples = parse_pro_examples(rows, hero_id=18)

    assert len(examples) == 5
    first = examples[0]
    assert isinstance(first, ProMatchExample)
    assert first.source_match_id == 9015520660
    assert first.player_name == "Wits"
    assert len(first.item_timeline) == 23
    assert len(first.ability_timeline) == 27
    assert len(first.talent_choices) == 4
    assert first.item_timeline[0].item_id == 11
    assert first.item_timeline[0].minute == -2
    assert first.position == 1
    assert first.position_basis == "draft"
    assert first.source_path == "$[0].recent_matches[0]"


def test_multiple_pub_roots_preserve_order_and_do_not_pair_candidates() -> None:
    rows = [
        _pub_row(
            build_id=10,
            build_data={
                "starting_items_new": [[[11, 11], {"pick_rate": 0.2}]],
                "abilities_new": [[[100, 101], {"win_rate": 0.5}]],
            },
        ),
        _pub_row(
            build_id=20,
            build_data={
                "starting_items_new": [[[12], {"pick_rate": 0.3}]],
                "abilities_new": [[[102, 103, 104], {"win_rate": 0.6}]],
            },
        ),
    ]

    guides = parse_pub_builds(rows, hero_id=18, position=1)

    assert [guide.build_id for guide in guides] == [10, 20]
    assert [guide.starting_options[0].items[0].item_id for guide in guides] == [11, 12]
    assert [guide.skill_sequences[0].ability_ids for guide in guides] == [
        [100, 101],
        [102, 103, 104],
    ]


def test_multiple_pro_roots_preserve_root_and_match_order_and_positions() -> None:
    rows = [
        _pro_row(
            position="pos 1",
            recent_matches=[_pro_match(match_id=90), _pro_match(match_id=91)],
        ),
        _pro_row(position="pos 2", recent_matches=[_pro_match(match_id=92)]),
    ]

    examples = parse_pro_examples(rows, hero_id=18)

    assert [example.source_match_id for example in examples] == [90, 91, 92]
    assert [example.position for example in examples] == [1, 1, 2]
    assert [example.position_basis for example in examples] == ["build"] * 3


def test_empty_roots_and_missing_or_null_optional_fields_are_empty() -> None:
    assert parse_pub_builds([], hero_id=18, position=1) == []
    assert parse_pro_examples([], hero_id=18) == []

    pub = parse_pub_builds(
        [_pub_row(build_id=None, facet_id=None, updated_at=None, data_scope=None)],
        hero_id=18,
        position=1,
    )[0]
    assert pub.build_id is None
    assert pub.facet_id is None
    assert pub.source_updated_at is None
    assert pub.scope == {}
    assert pub.statistics == {"root": {}, "build_data": {}}
    assert pub.starting_options == []
    assert pub.item_progression == []
    assert pub.situational_items == []
    assert pub.skill_sequences == []
    assert pub.talents == []

    examples = parse_pro_examples(
        [_pro_row(), _pro_row(recent_matches=None), _pro_row(recent_matches=[])],
        hero_id=18,
    )
    assert examples == []


def test_pub_timing_uses_average_boundary_and_missing_semantics() -> None:
    row = _pub_row(
        build_data={
            "anchor_items": [
                {"raw_item_id": 1, "avg_minute": 30},
                {"raw_item_id": 2, "avg_minute": 30.01},
                {"raw_item_id": 3, "avg_minute": 0},
                {"raw_item_id": 4},
                {"raw_item_id": 5, "avg_minute": None},
            ]
        }
    )

    items = parse_pub_builds([row], hero_id=18, position=1)[0].item_progression

    assert [item.phase for item in items] == ["mid", "late", "mid", "unknown", "unknown"]
    assert [item.timing.minute if item.timing else None for item in items] == [
        30.0,
        30.01,
        0.0,
        None,
        None,
    ]


def test_pub_unknown_statistics_and_json_values_are_preserved_without_aliasing() -> None:
    rows = [
        _pub_row(
            pick_rate=100.0,
            win_rate=None,
            ignored_root_stat={"future": [None, 0, False]},
            build_data={
                "pick_rate": 1.0,
                "num_matches": None,
                "future_stat": {"nested": [None, 0, False]},
                "anchor_items": [
                    {
                        "raw_item_id": 5,
                        "avg_minute": 0,
                        "future_field": {"x": [None, 0, False]},
                    }
                ],
            },
        )
    ]
    before = deepcopy(rows)

    guide = parse_pub_builds(rows, hero_id=18, position=1)[0]
    guide.item_progression[0].statistics["future_field"]["x"].append("output-only")

    assert rows == before
    assert guide.statistics["root"] == {"pick_rate": 100.0, "win_rate": None}
    assert guide.statistics["build_data"] == {"num_matches": None, "pick_rate": 1.0}
    assert guide.item_progression[0].statistics["future_field"] == {
        "x": [None, 0, False, "output-only"]
    }
    assert before[0]["build_data"]["future_stat"] == {"nested": [None, 0, False]}


def test_pub_does_not_mutate_source_when_later_root_fails() -> None:
    rows = [_pub_row(build_id=1), _pub_row(build_id=2, position="pos 2")]
    before = deepcopy(rows)

    error = _parse_error(lambda: parse_pub_builds(rows, hero_id=18, position=1))

    assert error.reason == "position_mismatch"
    assert error.source_path == "$[1].position"
    assert rows == before


@pytest.mark.parametrize(
    ("hero_id", "position"),
    [
        (True, 1),
        (0, 1),
        (-1, 1),
        (18.0, 1),
        ("18", 1),
        (18, True),
        (18, 0),
        (18, 6),
        (18, 1.0),
        (18, "1"),
    ],
)
def test_pub_rejects_invalid_query_values_before_parsing(
    hero_id: object,
    position: object,
) -> None:
    with pytest.raises(ValueError):
        parse_pub_builds([], hero_id=hero_id, position=position)  # type: ignore[arg-type]


@pytest.mark.parametrize("hero_id", [True, 0, -1, 18.0, "18"])
def test_pro_rejects_invalid_query_hero_id(hero_id: object) -> None:
    with pytest.raises(ValueError):
        parse_pro_examples([], hero_id=hero_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("rows", "reason", "path"),
    [
        (None, "invalid_structure", "$"),
        ([None], "invalid_structure", "$[0]"),
        ([{"position": "pos 1", "build_data": {}}], "invalid_value", "$[0].hero_id"),
        ([_pub_row(hero_id=True)], "invalid_value", "$[0].hero_id"),
        ([_pub_row(hero_id=19)], "hero_mismatch", "$[0].hero_id"),
        ([_pub_row(position="pos 2")], "position_mismatch", "$[0].position"),
        ([_pub_row(build_data=[])], "invalid_structure", "$[0].build_data"),
        ([_pub_row(build_id=True)], "invalid_value", "$[0].build_id"),
        ([_pub_row(facet_id=-1)], "invalid_value", "$[0].facet_id"),
        ([_pub_row(updated_at=7)], "invalid_value", "$[0].updated_at"),
        ([_pub_row(data_scope=[])], "invalid_structure", "$[0].data_scope"),
    ],
)
def test_pub_root_validation_uses_safe_errors(
    rows: object,
    reason: str,
    path: str,
) -> None:
    error = _parse_error(lambda: parse_pub_builds(rows, hero_id=18, position=1))

    assert error.code == "invalid_guide_data"
    assert error.reason == reason
    assert error.source_path == path


@pytest.mark.parametrize(
    ("field", "value", "reason", "path"),
    [
        ("starting_items_new", "bad", "invalid_structure", "$[0].build_data.starting_items_new"),
        (
            "starting_items_new",
            [[11]],
            "invalid_structure",
            "$[0].build_data.starting_items_new[0]",
        ),
        (
            "starting_items_new",
            [[[11, True], {}]],
            "invalid_value",
            "$[0].build_data.starting_items_new[0][0][1]",
        ),
        (
            "starting_items_new",
            [[[11], []]],
            "invalid_structure",
            "$[0].build_data.starting_items_new[0][1]",
        ),
        (
            "anchor_items",
            [{"raw_item_id": 0}],
            "invalid_value",
            "$[0].build_data.anchor_items[0].raw_item_id",
        ),
        (
            "anchor_items",
            [{"raw_item_id": 1, "avg_minute": True}],
            "invalid_value",
            "$[0].build_data.anchor_items[0].avg_minute",
        ),
        (
            "abilities_new",
            [[[11, False], {}]],
            "invalid_value",
            "$[0].build_data.abilities_new[0][0][1]",
        ),
        (
            "talents",
            [{"lvl": False}],
            "invalid_value",
            "$[0].build_data.talents[0].lvl",
        ),
    ],
)
def test_pub_malformed_candidates_fail_the_whole_parse(
    field: str,
    value: object,
    reason: str,
    path: str,
) -> None:
    error = _parse_error(
        lambda: parse_pub_builds(
            [_pub_row(build_data={field: value})],
            hero_id=18,
            position=1,
        )
    )

    assert error.reason == reason
    assert error.source_path == path


def test_pub_later_candidate_error_does_not_return_partial_guides() -> None:
    rows = [
        _pub_row(build_id=1),
        _pub_row(build_id=2, build_data={"anchor_items": [{"raw_item_id": False}]}),
    ]
    before = deepcopy(rows)

    error = _parse_error(lambda: parse_pub_builds(rows, hero_id=18, position=1))

    assert error.reason == "invalid_value"
    assert error.source_path == "$[1].build_data.anchor_items[0].raw_item_id"
    assert rows == before


@pytest.mark.parametrize(
    ("rows", "reason", "path"),
    [
        (None, "invalid_structure", "$"),
        ([None], "invalid_structure", "$[0]"),
        ([{"position": "pos 1", "recent_matches": []}], "invalid_value", "$[0].hero_id"),
        ([_pro_row(hero_id=19)], "hero_mismatch", "$[0].hero_id"),
        ([_pro_row(position=[])], "position_mismatch", "$[0].position"),
        ([_pro_row(position="pos 6")], "position_mismatch", "$[0].position"),
        ([_pro_row(recent_matches={})], "invalid_structure", "$[0].recent_matches"),
        ([_pro_row(recent_matches=[None])], "invalid_structure", "$[0].recent_matches[0]"),
    ],
)
def test_pro_root_validation_uses_safe_errors(
    rows: object,
    reason: str,
    path: str,
) -> None:
    error = _parse_error(lambda: parse_pro_examples(rows, hero_id=18))

    assert error.reason == reason
    assert error.source_path == path


@pytest.mark.parametrize(
    ("match", "reason", "path"),
    [
        ({"hero_id": 18}, "invalid_value", "$[0].recent_matches[0].match_id"),
        (_pro_match(match_id=True), "invalid_value", "$[0].recent_matches[0].match_id"),
        (_pro_match(hero_id=19), "hero_mismatch", "$[0].recent_matches[0].hero_id"),
        (_pro_match(account_id=-1), "invalid_value", "$[0].recent_matches[0].account_id"),
        (_pro_match(activate_time=-1), "invalid_value", "$[0].recent_matches[0].activate_time"),
        (_pro_match(date=123), "invalid_value", "$[0].recent_matches[0].date"),
        (_pro_match(won=1), "invalid_value", "$[0].recent_matches[0].won"),
        (_pro_match(duration=True), "invalid_value", "$[0].recent_matches[0].duration"),
        (
            _pro_match(items=[{"item_id": 0}]),
            "invalid_value",
            "$[0].recent_matches[0].items[0].item_id",
        ),
        (
            _pro_match(items=[{"item_id": 1, "minute": float("inf")}]),
            "invalid_value",
            "$[0].recent_matches[0].items[0].minute",
        ),
        (
            _pro_match(abilities=[{"ability_id": 1, "time": float("nan")}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].time",
        ),
        (
            _pro_match(abilities=[{"ability_id": -1}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{"ability_id": True}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{"ability_id": False}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{"ability_id": "0"}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{"ability_id": 0.0}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{"ability_id": None}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].ability_id",
        ),
        (
            _pro_match(abilities=[{"ability_id": 1, "level": False}]),
            "invalid_value",
            "$[0].recent_matches[0].abilities[0].level",
        ),
        (
            _pro_match(talent_data=[None]),
            "invalid_structure",
            "$[0].recent_matches[0].talent_data[0]",
        ),
        (
            _pro_match(draft=[]),
            "invalid_structure",
            "$[0].recent_matches[0].draft",
        ),
        (
            _pro_match(draft={"radiant": [None]}),
            "invalid_structure",
            "$[0].recent_matches[0].draft.radiant[0]",
        ),
    ],
)
def test_pro_match_validation_uses_safe_errors(
    match: dict[str, Any],
    reason: str,
    path: str,
) -> None:
    error = _parse_error(lambda: parse_pro_examples([_pro_row(recent_matches=[match])], hero_id=18))

    assert error.reason == reason
    assert error.source_path == path


def test_pro_draft_position_requires_unique_identity_match() -> None:
    no_account_match = _pro_match(
        account_id=None,
        draft={"radiant": [{"hero_id": 18, "position": "pos 2"}]},
    )
    multiple_matches = _pro_match(
        account_id=None,
        draft={
            "radiant": [{"hero_id": 18, "position": "pos 2"}],
            "dire": [{"hero_id": 18, "position": "pos 3"}],
        },
    )
    exact_account = _pro_match(
        account_id=700,
        draft={
            "radiant": [
                {"hero_id": 18, "account_id": 701, "position": "pos 4"},
                {"hero_id": 18, "account_id": 700, "position": "pos 3"},
            ]
        },
    )
    invalid_position = _pro_match(
        account_id=None,
        draft={"radiant": [{"hero_id": 18, "position": "unknown"}]},
    )

    examples = parse_pro_examples(
        [
            _pro_row(
                recent_matches=[
                    no_account_match,
                    multiple_matches,
                    exact_account,
                    invalid_position,
                ]
            )
        ],
        hero_id=18,
    )

    assert [(example.position, example.position_basis) for example in examples] == [
        (2, "draft"),
        (1, "build"),
        (3, "draft"),
        (1, "build"),
    ]


def test_pro_draft_position_does_not_rewrite_root_position() -> None:
    match = _pro_match(
        draft={"dire": [{"hero_id": 18, "position": "pos 4"}]},
    )

    examples = parse_pro_examples(
        [_pro_row(position="pos 1", recent_matches=[match])],
        hero_id=18,
    )
    example = examples[0]

    assert example.position == 4
    assert example.position_basis == "draft"


def test_pro_aggregate_recommendation_fields_are_not_parsed() -> None:
    match = _pro_match()
    baseline = parse_pro_examples(
        [
            _pro_row(
                recent_matches=[match],
                core_items=[1],
                abilities=[[100]],
                starting_items=[2],
            )
        ],
        hero_id=18,
    )
    changed_aggregates = parse_pro_examples(
        [
            _pro_row(
                recent_matches=[match],
                core_items={"bad": True},
                abilities=None,
                starting_items="ignored",
            )
        ],
        hero_id=18,
    )

    assert baseline == changed_aggregates


def test_pro_optional_fields_and_event_arrays_preserve_source_values() -> None:
    match = _pro_match(
        account_id=0,
        date=None,
        activate_time=0,
        player_name=None,
        won=False,
        duration=0,
        items=[{"item_id": 1, "minute": None, "custom": {"zero": 0, "flag": False}}],
        abilities=[{"ability_id": 2, "time": 0, "level": 1, "future": None}],
        talent_data=[{"lvl": 10, "selected": "left"}],
    )

    example = parse_pro_examples([_pro_row(recent_matches=[match])], hero_id=18)[0]

    assert example.account_id == 0
    assert example.date is None
    assert example.started_at_unix == 0
    assert example.won is False
    assert example.duration_seconds == 0
    assert example.item_timeline[0].minute is None
    assert example.item_timeline[0].source_fields["custom"] == {"zero": 0, "flag": False}
    assert example.ability_timeline[0].time_seconds == 0
    assert example.ability_timeline[0].source_fields["future"] is None
    assert example.talent_choices == [{"lvl": 10, "selected": "left"}]


def test_pro_ability_events_preserve_zero_order_duplicates_and_source_fields() -> None:
    abilities = [
        {"ability_id": 2, "time": 100, "level": 1},
        {
            "ability_id": 0,
            "time": 1105,
            "level": 14,
            "unknown": {"values": [0, False, None]},
        },
        {"ability_id": 2, "time": 1106, "level": 15},
    ]
    rows = [_pro_row(recent_matches=[_pro_match(abilities=abilities)])]
    before = deepcopy(rows)

    example = parse_pro_examples(rows, hero_id=18)[0]

    assert rows == before
    assert len(example.ability_timeline) == len(abilities)
    assert [event.ability_id for event in example.ability_timeline] == [2, 0, 2]
    zero_event = example.ability_timeline[1]
    assert zero_event.time_seconds == 1105
    assert zero_event.hero_level == 14
    assert zero_event.source_fields == abilities[1]
    zero_event.source_fields["unknown"]["values"].append("output-only")
    assert rows == before


def test_pro_missing_and_null_optional_event_fields_map_to_empty_or_none() -> None:
    example = parse_pro_examples(
        [
            _pro_row(
                recent_matches=[
                    _pro_match(
                        account_id=None,
                        date=None,
                        activate_time=None,
                        player_name=None,
                        team_name=None,
                        opponent_name=None,
                        won=None,
                        duration=None,
                        items=None,
                        abilities=None,
                        talent_data=None,
                    )
                ]
            )
        ],
        hero_id=18,
    )[0]

    assert example.account_id is None
    assert example.date is None
    assert example.started_at_unix is None
    assert example.player_name is None
    assert example.team_name is None
    assert example.opponent_name is None
    assert example.won is None
    assert example.duration_seconds is None
    assert example.item_timeline == []
    assert example.ability_timeline == []
    assert example.talent_choices == []


def test_pro_output_open_objects_are_deep_copies_and_source_is_unchanged() -> None:
    rows = [
        _pro_row(
            recent_matches=[
                _pro_match(
                    items=[{"item_id": 1, "custom": {"values": [None, 0, False]}}],
                    abilities=[{"ability_id": 2, "extra": {"levels": [1, 2]}}],
                    talent_data=[{"choice": {"ids": [3, 4]}}],
                )
            ]
        )
    ]
    before = deepcopy(rows)

    example = parse_pro_examples(rows, hero_id=18)[0]
    example.item_timeline[0].source_fields["custom"]["values"].append("output-only")
    example.ability_timeline[0].source_fields["extra"]["levels"].append(9)
    example.talent_choices[0]["choice"]["ids"].append(5)

    assert rows == before
    assert before[0]["recent_matches"][0]["items"][0]["custom"] == {"values": [None, 0, False]}


def test_pro_error_on_later_event_is_all_or_nothing_and_does_not_mutate_input() -> None:
    rows = [
        _pro_row(
            recent_matches=[
                _pro_match(match_id=90),
                _pro_match(match_id=91, items=[{"item_id": False, "marker": "SECRET_PLAYER_DATA"}]),
            ]
        )
    ]
    before = deepcopy(rows)

    error = _parse_error(lambda: parse_pro_examples(rows, hero_id=18))

    assert error.reason == "invalid_value"
    assert error.source_path == "$[0].recent_matches[1].items[0].item_id"
    assert "SECRET_PLAYER_DATA" not in str(error)
    assert rows == before


def test_pro_nested_mismatch_and_later_root_failure_do_not_return_partial_examples() -> None:
    rows = [
        _pro_row(recent_matches=[_pro_match(match_id=90)]),
        _pro_row(position="invalid", recent_matches=[_pro_match(match_id=91)]),
    ]

    error = _parse_error(lambda: parse_pro_examples(rows, hero_id=18))

    assert error.reason == "position_mismatch"
    assert error.source_path == "$[1].position"


def test_parser_errors_expose_only_fixed_reason_and_generated_source_path() -> None:
    row = _pub_row(build_data={"anchor_items": [{"raw_item_id": "PRIVATE_ITEM_VALUE"}]})

    error = _parse_error(lambda: parse_pub_builds([row], hero_id=18, position=1))

    assert error.code == "invalid_guide_data"
    assert error.reason == "invalid_value"
    assert error.source_path == "$[0].build_data.anchor_items[0].raw_item_id"
    assert "PRIVATE_ITEM_VALUE" not in str(error)
    assert "invalid_value" in str(error)
    assert error.source_path in str(error)
