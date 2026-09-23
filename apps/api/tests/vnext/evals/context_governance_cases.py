"""Fixed synthetic tournament data for Context Governance evaluations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SCENE_ID = "synthetic-three-edition-context-governance-v1"
_TEAM_TAGS = {
    "Northwind Lanterns": "NWL",
    "Ember Foxes": "EFX",
    "Copper Comets": "CCM",
    "Quartz Owls": "QOW",
    "Moss Giants": "MGI",
    "River Glass": "RGL",
    "Amber Kites": "AKI",
    "Silver Kite Collective": "SKC",
    "Redwood Current": "RWC",
    "Indigo Harbor": "IHB",
    "Golden Vale": "GVA",
}
_ROLES = ("carry", "mid", "offlane", "support", "hard_support")
_ROLE_TAGS = ("c", "m", "o", "s", "h")
_HEROES = (
    "Axe",
    "Crystal Maiden",
    "Puck",
    "Mars",
    "Lich",
    "Lina",
    "Tidehunter",
    "Witch Doctor",
    "Juggernaut",
    "Earthshaker",
    "Shadow Shaman",
    "Dazzle",
    "Centaur Warrunner",
    "Rubick",
    "Sven",
    "Disruptor",
    "Slardar",
    "Oracle",
    "Phantom Assassin",
    "Treant Protector",
)

FIRST_QUESTION = (
    "Compare the championship paths of the three editions, explain the key "
    "differences, and distinguish conclusions directly supported by the records "
    "from points the records cannot establish."
)
SECOND_QUESTION = (
    "Verify the opponent and score from one round of the first edition, and "
    "explain whether that changes the earlier comparison."
)

_EDITION_ROWS: tuple[dict[str, Any], ...] = (
    {
        "edition_id": "synthetic-edition-one",
        "event_name": "Synthetic International Practice Edition One",
        "format": (
            "Four-team single-elimination playoff; semifinals are best-of-three and "
            "the final is best-of-seven."
        ),
        "champion": "Northwind Lanterns",
        "placement": ["Northwind Lanterns", "Copper Comets", "Ember Foxes", "Quartz Owls"],
        "match_records": (
            (
                "SYN-01-SF1",
                "semifinal",
                "Northwind Lanterns",
                "Ember Foxes",
                "Northwind Lanterns",
                ("Northwind Lanterns", "Northwind Lanterns"),
                (
                    "Northwind opened with a patient two-lane setup and converted the "
                    "first series without dropping a map."
                ),
                (
                    (
                        "The opening map stayed even through the first objective cycle; "
                        "Northwind's support rotation created the first clean tower "
                        "exchange."
                    ),
                    (
                        "Ember contested the river entrance, but Northwind grouped "
                        "earlier and closed the map after a second objective trade."
                    ),
                ),
            ),
            (
                "SYN-01-SF2",
                "semifinal",
                "Copper Comets",
                "Quartz Owls",
                "Copper Comets",
                ("Copper Comets", "Quartz Owls", "Copper Comets"),
                (
                    "Copper advanced after a three-map series in which Quartz "
                    "answered once before Copper adjusted its lane assignments."
                ),
                (
                    (
                        "Copper controlled the first map's outer objectives and finished "
                        "with a coordinated high-ground approach."
                    ),
                    (
                        "Quartz slowed the second map with defensive vision and evened "
                        "the series after winning a late base defense."
                    ),
                    (
                        "Copper changed its opening rotation on map three and secured the "
                        "deciding objective before Quartz could regroup."
                    ),
                ),
            ),
            (
                "SYN-01-GF",
                "grand-final",
                "Northwind Lanterns",
                "Copper Comets",
                "Northwind Lanterns",
                (
                    "Northwind Lanterns",
                    "Copper Comets",
                    "Northwind Lanterns",
                    "Copper Comets",
                    "Northwind Lanterns",
                    "Northwind Lanterns",
                ),
                (
                    "The best-of-seven final ended 4-2; Northwind completed the edition "
                    "without a series loss."
                ),
                (
                    (
                        "Northwind's first-map draft gave it two reliable ways to start "
                        "fights, and both appeared in the first major engagement."
                    ),
                    (
                        "Copper held map two close with split pressure and tied the final "
                        "after forcing Northwind to defend both side lanes."
                    ),
                    (
                        "Northwind reclaimed the lead on map three by trading outer "
                        "objectives instead of chasing Copper's defenders."
                    ),
                    (
                        "Copper evened the series again on map four after a late "
                        "counter-engagement near the central objective."
                    ),
                    (
                        "Northwind protected its map-five lead around the central "
                        "objective and forced Copper to defend its base."
                    ),
                    (
                        "Northwind closed map six after an objective contest; the final "
                        "score was four maps to two."
                    ),
                ),
            ),
        ),
    },
    {
        "edition_id": "synthetic-edition-two",
        "event_name": "Synthetic International Practice Edition Two",
        "format": (
            "Four-team double-elimination bracket with a single best-of-five grand final "
            "and no bracket reset."
        ),
        "champion": "Copper Comets",
        "placement": ["Copper Comets", "Moss Giants", "River Glass", "Amber Kites"],
        "match_records": (
            (
                "SYN-02-USF1",
                "upper-semifinal",
                "Copper Comets",
                "Amber Kites",
                "Copper Comets",
                ("Copper Comets", "Copper Comets"),
                "Copper won its upper semifinal in two maps and advanced to the upper final.",
                (
                    (
                        "Copper established lane control early and converted it into the "
                        "first map's outer objective sequence."
                    ),
                    (
                        "Amber changed its draft emphasis, but Copper kept the second map "
                        "grouped and finished before the late-game split push."
                    ),
                ),
            ),
            (
                "SYN-02-USF2",
                "upper-semifinal",
                "Moss Giants",
                "River Glass",
                "Moss Giants",
                ("Moss Giants", "River Glass", "Moss Giants"),
                ("Moss reached the upper final after River took one map and Moss won the decider."),
                (
                    (
                        "Moss used a compact opening formation to protect its first map "
                        "lead around the side-lane objectives."
                    ),
                    (
                        "River equalized by delaying engagements and taking the second "
                        "map's late neutral objective."
                    ),
                    (
                        "Moss returned to faster rotations on the decider and forced "
                        "River to defend two lanes at once."
                    ),
                ),
            ),
            (
                "SYN-02-UF",
                "upper-final",
                "Moss Giants",
                "Copper Comets",
                "Moss Giants",
                ("Moss Giants", "Copper Comets", "Moss Giants"),
                (
                    "Moss won the upper final 2-1; this is Copper's only recorded "
                    "series loss before the grand final."
                ),
                (
                    (
                        "Moss took the opener after controlling the first major objective "
                        "and preserving its lead through the second cycle."
                    ),
                    (
                        "Copper tied the series with a slower map built around repeated "
                        "defensive trades rather than an early push."
                    ),
                    (
                        "Moss won the decider after contesting Copper's vision line and "
                        "converting the resulting pick into a base approach."
                    ),
                ),
            ),
            (
                "SYN-02-LR",
                "lower-round",
                "River Glass",
                "Amber Kites",
                "River Glass",
                ("River Glass", "River Glass"),
                "River eliminated Amber in two maps and qualified for the lower final.",
                (
                    (
                        "River's first-map supports maintained a defensive route between "
                        "lanes, allowing its cores to finish key items."
                    ),
                    (
                        "Amber attempted earlier pressure on map two; River absorbed the "
                        "opening move and won the next objective exchange."
                    ),
                ),
            ),
            (
                "SYN-02-LF",
                "lower-final",
                "Copper Comets",
                "River Glass",
                "Copper Comets",
                ("Copper Comets", "Copper Comets"),
                (
                    "Copper recovered from its upper-final loss by defeating River "
                    "2-0 in the lower final."
                ),
                (
                    (
                        "Copper favored short engagements on map one and avoided giving "
                        "River the extended defense it had used earlier."
                    ),
                    (
                        "On map two Copper moved its support pair toward the exposed lane "
                        "and closed after securing the adjacent objective."
                    ),
                ),
            ),
            (
                "SYN-02-GF",
                "grand-final",
                "Moss Giants",
                "Copper Comets",
                "Copper Comets",
                ("Copper Comets", "Moss Giants", "Copper Comets", "Moss Giants", "Copper Comets"),
                ("The best-of-five final went the distance at 3-2, with Copper winning map five."),
                (
                    (
                        "Copper took the opener after a measured start and a coordinated "
                        "push through the safer lane."
                    ),
                    (
                        "Moss tied the final by winning a long defensive map in which it "
                        "traded the outer objectives efficiently."
                    ),
                    (
                        "Copper regained the lead after changing its map-three initiation "
                        "target and protecting the follow-up retreat."
                    ),
                    (
                        "Moss forced a deciding map with a late contest near the central "
                        "objective after falling behind early."
                    ),
                    (
                        "Copper won map five by controlling the final objective approach; "
                        "the record does not include player-level statistics."
                    ),
                ),
            ),
        ),
    },
    {
        "edition_id": "synthetic-edition-three",
        "event_name": "Synthetic International Practice Edition Three",
        "format": (
            "Four-team single round-robin group; the top two advance directly to a "
            "best-of-five final."
        ),
        "champion": "Silver Kite Collective",
        "placement": ["Silver Kite Collective", "Redwood Current", "Indigo Harbor", "Golden Vale"],
        "match_records": (
            (
                "SYN-03-G1",
                "group-round-1",
                "Silver Kite Collective",
                "Indigo Harbor",
                "Silver Kite Collective",
                ("Silver Kite Collective", "Silver Kite Collective"),
                "Silver began group play with a 2-0 result over Indigo.",
                (
                    (
                        "Silver's first map used early side-lane pressure to open a route "
                        "toward the outer objective."
                    ),
                    (
                        "Indigo defended the second map for longer, but Silver's repeated "
                        "vision resets kept the next objective contested on its terms."
                    ),
                ),
            ),
            (
                "SYN-03-G2",
                "group-round-1",
                "Redwood Current",
                "Golden Vale",
                "Redwood Current",
                ("Redwood Current", "Golden Vale", "Redwood Current"),
                "Redwood took the opening group series 2-1.",
                (
                    (
                        "Redwood claimed map one after its off-lane rotation arrived "
                        "before Golden's first defensive regroup."
                    ),
                    (
                        "Golden equalized by holding its high-ground entrance and winning "
                        "a later neutral-objective fight."
                    ),
                    (
                        "Redwood secured map three after shifting its ward coverage "
                        "toward the route Golden had used to recover."
                    ),
                ),
            ),
            (
                "SYN-03-G3",
                "group-round-2",
                "Silver Kite Collective",
                "Redwood Current",
                "Silver Kite Collective",
                ("Silver Kite Collective", "Redwood Current", "Silver Kite Collective"),
                "Silver beat Redwood 2-1; the result later placed both teams in the final.",
                (
                    (
                        "Silver opened with stronger lane trades and kept Redwood away "
                        "from the first grouped objective."
                    ),
                    (
                        "Redwood answered on map two by delaying a direct fight and using "
                        "the extra time to complete its defensive items."
                    ),
                    (
                        "Silver took the decider after protecting its support line during "
                        "the final objective contest."
                    ),
                ),
            ),
            (
                "SYN-03-G4",
                "group-round-2",
                "Indigo Harbor",
                "Golden Vale",
                "Indigo Harbor",
                ("Indigo Harbor", "Indigo Harbor"),
                "Indigo defeated Golden 2-0 in the second group round.",
                (
                    (
                        "Indigo's opening map featured a quick rotation from mid toward "
                        "the exposed side lane."
                    ),
                    (
                        "Golden changed its early defense on map two, while Indigo won "
                        "through patient objective trades rather than a quick finish."
                    ),
                ),
            ),
            (
                "SYN-03-G5",
                "group-round-3",
                "Silver Kite Collective",
                "Golden Vale",
                "Silver Kite Collective",
                ("Silver Kite Collective", "Silver Kite Collective"),
                "Silver completed an undefeated group stage with a 2-0 win over Golden.",
                (
                    (
                        "Silver's first map included an early tower exchange followed by "
                        "a controlled retreat from Golden's counter-engagement."
                    ),
                    (
                        "On the second map Silver contested the central objective with "
                        "more teammates present and closed the series afterward."
                    ),
                ),
            ),
            (
                "SYN-03-G6",
                "group-round-3",
                "Redwood Current",
                "Indigo Harbor",
                "Redwood Current",
                ("Redwood Current", "Indigo Harbor", "Redwood Current"),
                "Redwood beat Indigo 2-1 and finished the group stage as the second finalist.",
                (
                    (
                        "Redwood won the opener by keeping its frontline near the first "
                        "objective after Indigo's attempted flank."
                    ),
                    (
                        "Indigo leveled the series when it isolated a carry during a "
                        "split defense on map two."
                    ),
                    (
                        "Redwood won the decider through a series of short engagements "
                        "and a final coordinated lane push."
                    ),
                ),
            ),
            (
                "SYN-03-GF",
                "grand-final",
                "Silver Kite Collective",
                "Redwood Current",
                "Silver Kite Collective",
                (
                    "Silver Kite Collective",
                    "Redwood Current",
                    "Redwood Current",
                    "Silver Kite Collective",
                    "Silver Kite Collective",
                ),
                (
                    "The best-of-five final went to map five; Silver won 3-2 after "
                    "Redwood took maps two and three."
                ),
                (
                    (
                        "Silver took map one with an early lead, then used that advantage "
                        "to secure the first grouped objective."
                    ),
                    (
                        "Redwood equalized by contesting Silver's vision and winning the "
                        "next team engagement near the river."
                    ),
                    (
                        "Redwood moved ahead after map three, using a defensive formation "
                        "to survive Silver's first base approach."
                    ),
                    (
                        "Silver restored parity on map four by taking safer objective "
                        "trades and refusing Redwood's preferred long fight."
                    ),
                    (
                        "Silver won the deciding map after a final objective contest; the "
                        "records provide no player-level damage totals or ban sequence."
                    ),
                ),
            ),
        ),
    },
)


def _player_box_score(team: str, game_number: int) -> list[dict[str, Any]]:
    team_index = sum(ord(character) for character in team) % len(_HEROES)
    tag = _TEAM_TAGS[team]
    return [
        {
            "player_tag": f"{tag}-{_ROLE_TAGS[index]}",
            "role": role,
            "hero": _HEROES[(team_index + game_number * 3 + index * 2) % len(_HEROES)],
            "kills": (team_index + game_number + index * 2) % 9,
            "deaths": (game_number + index + team_index // 3) % 7,
            "assists": (team_index + game_number * 2 + index * 3) % 16,
            "last_hits": 38 + (team_index * 3 + game_number * 7 + index * 11) % 290,
        }
        for index, role in enumerate(_ROLES)
    ]


def _match_record(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        match_id,
        stage,
        team_a,
        team_b,
        winner,
        game_winners,
        series_note,
        game_notes,
    ) = row
    score = {
        team_a: game_winners.count(team_a),
        team_b: game_winners.count(team_b),
    }
    return {
        "match_id": match_id,
        "round": stage,
        "teams": [team_a, team_b],
        "series_score": score,
        "winner": winner,
        "series_record": series_note,
        "games": [
            {
                "game_number": index,
                "winner": game_winner,
                "record_note": note,
                "synthetic_player_box_score": [
                    *_player_box_score(team_a, index),
                    *_player_box_score(team_b, index),
                ],
            }
            for index, (game_winner, note) in enumerate(
                zip(game_winners, game_notes, strict=True), start=1
            )
        ],
    }


def _build_editions() -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for edition in _EDITION_ROWS:
        records = [_match_record(row) for row in edition["match_records"]]
        documents[edition["edition_id"]] = {
            "synthetic_fixture": True,
            "historical_fact_warning": (
                "Synthetic test tournament; not a real TI edition or historical fact."
            ),
            "edition_id": edition["edition_id"],
            "event_name": edition["event_name"],
            "champion": edition["champion"],
            "format": edition["format"],
            "placement": list(edition["placement"]),
            "match_records": records,
        }
    return documents


EDITION_DOCUMENTS = _build_editions()
EDITION_IDS = tuple(EDITION_DOCUMENTS)

# This checklist is for the human report only and is never included in prompts.
HUMAN_REVIEW_CHECKLIST = (
    "Did the answer name each champion correctly?",
    "Did it identify each edition's win/loss path correctly?",
    "Did it preserve the key format and path differences?",
    "Did it invent opponent strength or other unsupported facts?",
    "Was the follow-up opponent and score correct?",
    "Are answer claims supported by observations from the fixture?",
)

FOLLOW_UP_EXPECTED = {
    "edition_id": "synthetic-edition-one",
    "match_id": "SYN-01-SF1",
    "round": "semifinal",
    "opponent": "Ember Foxes",
    "score": "2-0",
}


def get_edition_document(edition_id: str) -> dict[str, Any]:
    """Return a defensive copy of one fixed synthetic tournament document."""

    try:
        return deepcopy(EDITION_DOCUMENTS[edition_id])
    except KeyError as exc:
        raise ValueError("unknown synthetic fixture edition") from exc


def fixture_manifest_hash_payload() -> dict[str, dict[str, Any]]:
    """Return the exact model-visible fixture content for manifest hashing."""

    return deepcopy(EDITION_DOCUMENTS)


def validate_fixture() -> None:
    """Check fixed data structure and match score consistency before evaluation."""

    if len(EDITION_DOCUMENTS) != 3:
        raise ValueError("fixture must contain exactly three editions")
    for edition_id, document in EDITION_DOCUMENTS.items():
        if document["synthetic_fixture"] is not True:
            raise ValueError("fixture data must be explicitly marked synthetic")
        if "not a real TI edition" not in document["historical_fact_warning"]:
            raise ValueError("fixture warning must distinguish synthetic data from TI history")
        if edition_id not in EDITION_IDS or not document["match_records"]:
            raise ValueError("fixture edition is incomplete")
        for match in document["match_records"]:
            score = match["series_score"]
            if set(score) != set(match["teams"]):
                raise ValueError("match score must cover both recorded teams")
            if (
                score[match["winner"]]
                <= score[next(team for team in match["teams"] if team != match["winner"])]
            ):
                raise ValueError("recorded match winner must have the higher series score")
            game_score = {
                team: sum(game["winner"] == team for game in match["games"])
                for team in match["teams"]
            }
            if game_score != score:
                raise ValueError("game records must agree with the series score")


__all__ = [
    "EDITION_DOCUMENTS",
    "EDITION_IDS",
    "FIRST_QUESTION",
    "FOLLOW_UP_EXPECTED",
    "HUMAN_REVIEW_CHECKLIST",
    "SCENE_ID",
    "SECOND_QUESTION",
    "fixture_manifest_hash_payload",
    "get_edition_document",
    "validate_fixture",
]
