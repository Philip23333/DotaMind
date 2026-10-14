from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.vnext.providers.match_resolution import compare_game_identity_evidence


def _context(
    radiant_id: int | None = 10,
    radiant_name: str = "Alpha",
    dire_id: int | None = 20,
    dire_name: str = "Beta",
    **extra: Any,
) -> dict[str, Any]:
    radiant = {"name": radiant_name}
    dire = {"name": dire_name}
    if radiant_id is not None:
        radiant["id"] = radiant_id
    if dire_id is not None:
        dire["id"] = dire_id
    return {
        "id": 1000,
        "opponents": [{"opponent": radiant}, {"opponent": dire}],
        **extra,
    }


def _game(
    *,
    winner_id: int | None = 10,
    winner_type: str | None = "Team",
    nested_type: str | None = None,
    source_winner_id: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    game: dict[str, Any] = {"id": 2000, "position": 1, **extra}
    if winner_id is not None:
        winner: dict[str, Any] = {"id": winner_id, "name": "Alpha"}
        if nested_type is not None:
            winner["type"] = nested_type
        game["winner"] = winner
    if winner_type is not None:
        game["winner_type"] = winner_type
    if source_winner_id is not None:
        game["winner_id"] = source_winner_id
    return game


def _record(match_id: int = 9040000001) -> dict[str, Any]:
    return {"match_id": match_id, "leagueid": 19102}


def _detail(
    match_id: int = 9040000001,
    *,
    radiant_id: int | None = 800,
    radiant_name: str = "Alpha",
    dire_id: int | None = 900,
    dire_name: str = "Beta",
    radiant_win: bool | None = True,
    **extra: Any,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"match_id": match_id}
    if radiant_name is not None:
        radiant: dict[str, Any] = {"name": radiant_name}
        if radiant_id is not None:
            radiant["team_id"] = radiant_id
        detail["radiant_team"] = radiant
    if dire_name is not None:
        dire: dict[str, Any] = {"name": dire_name}
        if dire_id is not None:
            dire["team_id"] = dire_id
        detail["dire_team"] = dire
    if radiant_win is not None:
        detail["radiant_win"] = radiant_win
    detail.update(extra)
    return detail


def _compare(
    context: dict[str, Any] | None = None,
    game: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
):
    selected_record = record if record is not None else _record()
    return compare_game_identity_evidence(
        context if context is not None else _context(),
        game if game is not None else _game(),
        selected_record,
        detail if detail is not None else _detail(selected_record["match_id"]),
    )


def test_names_are_normalized_and_side_swaps_map_by_name_not_id() -> None:
    context = _context(
        10,
        "Ｙａｋｕｌｔ　Brothers!",
        20,
        "Zenith",
    )
    detail = _detail(
        radiant_id=777,
        radiant_name="ZENITH",
        dire_id=888,
        dire_name="Yakult-Brothers",
        radiant_win=False,
    )
    game = _game(winner_id=10, winner_type="Team")

    result = _compare(context, game, detail=detail)

    assert result.participants_status == "supported"
    assert result.winner_status == "consistent"
    yakult = result.participant_associations[0]
    assert yakult.pandascore_team_id == 10
    assert yakult.opendota_side == "dire"
    assert yakult.opendota_team_id == 888
    assert yakult.opendota_team_id == result.facts.opendota_participants[1].team_id
    assert result.facts.opendota_participants[1].team_id_path == "dire_team.team_id"
    assert yakult.pandascore_name == "Ｙａｋｕｌｔ　Brothers!"
    assert yakult.opendota_name == "Yakult-Brothers"
    assert not hasattr(result, "resolved")
    assert not hasattr(result, "confidence")


@pytest.mark.parametrize(
    ("context", "detail", "reason"),
    [
        (
            _context(10, "Alpha", 20, "Alpha!"),
            _detail(radiant_name="Alpha", dire_name="Alpha"),
            "participant_name_collision",
        ),
        (
            _context(10, "Team Yandex", 20, "Team Spirit"),
            _detail(radiant_name="TY", dire_name="Team Spirit"),
            "participant_names_unaligned",
        ),
        (
            _context(10, "!!!", 20, "Beta"),
            _detail(radiant_name="", dire_name="Beta"),
            "participant_name_not_comparable",
        ),
        (
            _context(),
            _detail(dire_name=None),
            "participant_name_missing",
        ),
    ],
)
def test_name_collision_alias_or_missing_team_stays_unknown(
    context: dict[str, Any], detail: dict[str, Any], reason: str
) -> None:
    result = _compare(context, detail=detail)

    assert result.participants_status == "unknown"
    assert result.participant_associations == ()
    assert reason in result.reasons


def test_different_provider_team_ids_are_preserved_but_not_compared() -> None:
    result = _compare(
        _context(10, "Alpha", 20, "Beta"),
        _game(winner_id=10),
        detail=_detail(radiant_id=800, dire_id=900),
    )

    assert result.participants_status == "supported"
    assert result.winner_status == "consistent"
    assert [item.opendota_team_id for item in result.participant_associations] == [
        800,
        900,
    ]
    assert [item.pandascore_team_id for item in result.participant_associations] == [
        10,
        20,
    ]


@pytest.mark.parametrize(
    ("game", "detail", "expected", "reason"),
    [
        (_game(winner_id=10), _detail(radiant_win=True), "consistent", None),
        (_game(winner_id=10), _detail(radiant_win=False), "conflict", None),
        (_game(winner_id=None), _detail(), "unknown", "game_winner_missing"),
        (
            _game(winner_id=10, source_winner_id=20),
            _detail(),
            "unknown",
            "game_winner_source_conflict",
        ),
        (
            _game(winner_id=10, winner_type="Team", nested_type="Player"),
            _detail(),
            "unknown",
            "game_winner_source_conflict",
        ),
        (
            _game(winner_id=999),
            _detail(),
            "unknown",
            "game_winner_not_in_participants",
        ),
        (
            _game(winner_id=10, winner_type="Player"),
            _detail(),
            "unknown",
            "game_winner_not_team",
        ),
        (
            _game(winner_id=10, winner_type=None, nested_type=None),
            _detail(),
            "unknown",
            "game_winner_type_missing",
        ),
        (
            _game(winner_id=10),
            _detail(radiant_win=None),
            "unknown",
            "opendota_winner_missing",
        ),
    ],
)
def test_game_winner_comparison_requires_consistent_team_evidence(
    game: dict[str, Any],
    detail: dict[str, Any],
    expected: str,
    reason: str | None,
) -> None:
    result = _compare(game=game, detail=detail)

    assert result.winner_status == expected
    if reason is not None:
        assert reason in result.reasons


def test_match_level_winner_is_not_used_for_selected_game() -> None:
    context = _context(winner={"id": 10, "type": "Team"})
    game = _game(winner_id=None, winner_type=None)

    result = _compare(context=context, game=game)

    assert result.winner_status == "unknown"
    assert "game_winner_missing" in result.reasons


@pytest.mark.parametrize(
    ("record_id", "detail_id"),
    [
        (9040000001, 9040000002),
        (0, 0),
        (-1, -1),
        (True, True),
    ],
)
def test_candidate_and_detail_must_share_a_strict_positive_match_id(
    record_id: Any, detail_id: Any
) -> None:
    with pytest.raises(ValueError, match="candidate detail match_id"):
        _compare(
            record={"match_id": record_id},
            detail={"match_id": detail_id},
        )


def test_inputs_remain_unchanged_and_candidate_game_id_is_source_match_id() -> None:
    inputs = [
        _context(unmodified=[1, 2]),
        _game(unmodified={"game": True}),
        _record(),
        _detail(unmodified=[3, 4]),
    ]
    original = deepcopy(inputs)

    result = _compare(*inputs)

    assert inputs == original
    assert result.candidate_valve_game_id == 9040000001


def test_blast_game_four_real_source_facts_support_participants_and_winner() -> None:
    context = _context(137073, "Team Yandex", 1669, "Team Spirit")
    context.update({"id": 1709131, "serie": {"id": 11012}})
    target_game = {
        "id": 739826,
        "position": 4,
        "winner": {"id": 137073, "name": "Team Yandex", "type": "Team"},
        "winner_id": 137073,
        "winner_type": "Team",
    }
    record = {"match_id": 9040578015, "series_id": 1153562, "leagueid": 19102}
    detail = _detail(
        match_id=9040578015,
        radiant_id=9823272,
        radiant_name="Team Yandex",
        dire_id=7119388,
        dire_name="Team Spirit",
        radiant_win=True,
    )

    result = _compare(context, target_game, record, detail)

    assert result.candidate_valve_game_id == 9040578015
    assert result.participants_status == "supported"
    assert result.winner_status == "consistent"
    assert result.facts.pandascore_opponent_count == 2
    assert result.participant_associations[0].opendota_side == "radiant"


def test_yakult_games_keep_per_game_team_ids_and_compare_both_winners() -> None:
    context = _context(135697, "Yakult Brothers", 139363, "Zenith")
    context.update({"id": 1745472, "serie": {"id": 11107}})

    game_one = {
        "id": 740347,
        "position": 1,
        "winner": {"id": 139363, "name": "Zenith", "type": "Team"},
        "winner_id": 139363,
        "winner_type": "Team",
    }
    record_one = {
        "match_id": 9042629988,
        "leagueid": 20359,
        "series_id": 1154058,
    }
    detail_one = _detail(
        match_id=9042629988,
        radiant_id=10252232,
        radiant_name="Zenith",
        dire_id=10208034,
        dire_name="Yakult Brothers",
        radiant_win=True,
    )
    first = _compare(context, game_one, record_one, detail_one)

    assert first.participants_status == "supported"
    yakult_first = first.participant_associations[0]
    assert yakult_first.pandascore_team_id == 135697
    assert yakult_first.opendota_side == "dire"
    assert yakult_first.opendota_team_id == 10208034
    assert first.winner_status == "consistent"

    game_two = {
        "id": 740348,
        "position": 2,
        "winner": {"id": 135697, "name": "Yakult Brothers", "type": "Team"},
        "winner_id": 135697,
        "winner_type": "Team",
    }
    record_two = {
        "match_id": 9042668580,
        "leagueid": 20359,
        "series_id": 1154073,
    }
    detail_two = _detail(
        match_id=9042668580,
        radiant_id=10252232,
        radiant_name="Zenith",
        dire_id=9351740,
        dire_name="Yakult Brothers",
        radiant_win=False,
    )
    second = _compare(context, game_two, record_two, detail_two)

    assert second.participants_status == "supported"
    yakult_second = second.participant_associations[0]
    assert yakult_second.opendota_side == "dire"
    assert yakult_second.opendota_team_id == 9351740
    assert second.winner_status == "consistent"


def test_old_blood_game_two_does_not_fill_missing_dire_from_neighboring_game() -> None:
    # Relevant fields from the source responses captured on 2026-10-13.
    context = _context(139389, "old blood", 139406, "White Sails")
    context.update({"id": 1743558, "serie_id": 11103})
    game = {
        "id": 740236,
        "position": 2,
        "winner": {"id": 139406, "type": "Team"},
        "winner_type": "Team",
    }
    record = {
        "match_id": 9041812996,
        "leagueid": 20359,
        "series_id": 0,
        "radiant_team_id": 10232798,
        "dire_team_id": None,
        "radiant_win": True,
    }
    detail = {
        "match_id": 9041812996,
        "radiant_team_id": 10232798,
        "radiant_team": {"team_id": 10232798, "name": "WhiteSails", "tag": "WTS"},
        "radiant_win": True,
        "series_id": 0,
    }

    result = _compare(context, game, record, detail)

    assert result.participants_status == "unknown"
    assert result.winner_status == "unknown"
    assert result.reasons == (
        "participant_name_missing",
        "winner_participants_unavailable",
    )
    assert result.facts.pandascore_winner == {"id": 139406, "type": "Team"}
    assert result.facts.pandascore_winner_type_field == "Team"
    assert result.facts.opendota_radiant_win is True
    assert result.facts.opendota_radiant_win_present is True
    assert result.facts.opendota_participants[1].name_present is False
    assert result.facts.opendota_participants[1].team_id_present is False

    # Synthetic contrast: only add the missing name, without using a neighbor
    # or claiming that OpenDota supplied this object in the real response.
    detail_with_dire_name = deepcopy(detail)
    detail_with_dire_name["dire_team"] = {"name": "old blood"}
    contrast = _compare(context, game, record, detail_with_dire_name)
    assert contrast.participants_status == "supported"
    assert contrast.winner_status == "consistent"
    assert contrast.reasons == ()
    assert "dire_team" not in detail
