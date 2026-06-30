from app.integrations.opendota.team_resolution import resolve_team


def _team(
    team_id: int,
    name: str,
    tag: str,
    *,
    rating: float = 1000,
    last_match_time: int = 0,
) -> dict:
    return {
        "team_id": team_id,
        "name": name,
        "tag": tag,
        "rating": rating,
        "last_match_time": last_match_time,
    }


def test_resolve_team_normalizes_generic_team_prefix() -> None:
    teams = [_team(8255888, "BB", "BB")]

    resolution = resolve_team("Team BB", teams)

    assert resolution.status == "resolved"
    assert resolution.team == teams[0]


def test_resolve_team_uses_camel_case_acronym_as_fallback() -> None:
    teams = [_team(8255888, "BB", "BB")]

    resolution = resolve_team("BetBoom", teams)

    assert resolution.status == "resolved"
    assert resolution.team == teams[0]
    assert resolution.candidates[0]["match_reason"] == "acronym matched team name"


def test_resolve_team_returns_ambiguous_candidates() -> None:
    teams = [
        _team(1, "Big Bears", "BB", last_match_time=100),
        _team(2, "Bright Blades", "BB", last_match_time=200),
    ]

    resolution = resolve_team("BB", teams)

    assert resolution.status == "ambiguous"
    assert {candidate["team_id"] for candidate in resolution.candidates} == {1, 2}


def test_resolve_team_does_not_let_generic_name_match_hide_tag_ambiguity() -> None:
    teams = [
        _team(8255888, "BoomBoys", "BB", rating=1440, last_match_time=1780832552),
        _team(9131584, "BB Team", "BB", rating=1396, last_match_time=1754141860),
    ]

    resolution = resolve_team("Team BB", teams)

    assert resolution.status == "ambiguous"
    assert [candidate["team_id"] for candidate in resolution.candidates] == [
        8255888,
        9131584,
    ]


def test_resolve_team_returns_not_found() -> None:
    resolution = resolve_team(
        "No Such Team",
        [_team(1, "Team Liquid", "Liquid")],
    )

    assert resolution.status == "not_found"
    assert resolution.candidates == []


def test_resolve_team_uses_fuzzy_name_match_after_exact_stages_fail() -> None:
    teams = [_team(2163, "Team Liquid", "Liquid")]

    resolution = resolve_team("Liqud", teams)

    assert resolution.status == "resolved"
    assert resolution.team == teams[0]
    assert resolution.candidates[0]["match_reason"] == "fuzzy team name match"


