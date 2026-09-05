from __future__ import annotations

import asyncio

import pytest

from app.vnext.capabilities.esports.tournament import (
    TournamentRosterItem,
    TournamentRosterPlayer,
    TournamentRostersInput,
    TournamentRostersResult,
    TournamentRosterTeam,
)
from app.vnext.composition import VNextServices, build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.esports import register_tournament_rosters_tool
from app.vnext.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"tournament_id": 0},
        {"tournament_id": -1},
        {"tournament_id": 14384, "team_id": 0},
        {"tournament_id": 14384, "team_id": -1},
        {"tournament_id": 14384, "name": "Group Stage"},
        {"tournament_id": 14384, "page": 1},
    ],
)
def test_tournament_rosters_input_is_required_and_closed(arguments) -> None:
    with pytest.raises(ValueError):
        TournamentRostersInput.model_validate(arguments)


def test_tournament_rosters_schema_and_description_are_bounded() -> None:
    registry = ToolRegistry()

    async def rosters(_query: TournamentRostersInput) -> TournamentRostersResult:
        return TournamentRostersResult(items=[])

    register_tournament_rosters_tool(registry, rosters)
    definition = registry.get("esports.tournament.rosters")
    schema = definition.schema()

    assert set(schema.input_schema["properties"]) == {"tournament_id", "team_id"}
    assert schema.input_schema["required"] == ["tournament_id"]
    assert definition.metadata == {"game": "dota2", "domain": "tournament"}
    assert definition.read_only is True
    assert definition.parallel_safe is True
    assert definition.externalize_result is True
    assert "tournament-time rosters" in definition.description
    assert "current contracted players" in " ".join(definition.description.split())
    assert "exact five players" in definition.description


def test_tournament_rosters_tool_returns_roster_contract() -> None:
    registry = ToolRegistry()

    async def rosters(query: TournamentRostersInput) -> TournamentRostersResult:
        assert query.tournament_id == 14384
        assert query.team_id == 128329
        return TournamentRostersResult(
            items=[
                TournamentRosterItem(
                    team=TournamentRosterTeam(
                        id=128329,
                        name="Xtreme Gaming",
                        acronym="XG",
                    ),
                    players=[TournamentRosterPlayer(id=123, name="Ame")],
                )
            ]
        )

    register_tournament_rosters_tool(registry, rosters)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="roster-call",
                name="esports.tournament.rosters",
                arguments={"tournament_id": 14384, "team_id": 128329},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {
        "items": [
            {
                "team": {"id": 128329, "name": "Xtreme Gaming", "acronym": "XG"},
                "players": [
                    {
                        "id": 123,
                        "name": "Ame",
                        "first_name": None,
                        "last_name": None,
                        "role": None,
                    }
                ],
            }
        ]
    }


def test_tournament_rosters_inherits_generic_externalization() -> None:
    players = [
        TournamentRosterPlayer(
            id=index,
            name=f"Player {index} {'x' * 200}",
        )
        for index in range(100)
    ]

    async def rosters(_query: TournamentRostersInput) -> TournamentRostersResult:
        return TournamentRostersResult(
            items=[
                TournamentRosterItem(
                    team=TournamentRosterTeam(
                        id=128329,
                        name="Xtreme Gaming",
                        acronym="XG",
                    ),
                    players=players,
                )
            ]
        )

    registry = build_vnext_registry(VNextServices(tournament_rosters=rosters))
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="large-roster",
                name="esports.tournament.rosters",
                arguments={"tournament_id": 14384},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    assert result.content["value"]["items"] == {
        "_artifact_path": "items",
        "kind": "collection",
        "count": 1,
    }
    ref = result.content["artifact_ref"]
    read = asyncio.run(
        registry.execute(
            ToolCall(
                id="read-roster",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "items.0.players",
                    "offset": 0,
                    "limit": 3,
                },
            )
        )
    )

    assert read.status == "ok"
    assert read.content["total"] == 100
    assert read.content["value"] == [player.model_dump(mode="json") for player in players[:3]]
