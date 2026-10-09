from __future__ import annotations

import asyncio
from pathlib import Path

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.vnext.artifacts import ArtifactLimits
from app.vnext.capabilities.esports.display_enrichment import (
    enrich_match_search_result,
    enrich_player_search_result,
    enrich_series_teams_result,
    enrich_team_search_result,
    enrich_tournament_search_result,
)
from app.vnext.capabilities.esports.dtos import (
    MatchDTO,
    MatchParticipantDTO,
    PlayerDTO,
    TeamDTO,
    TeamRefDTO,
    TournamentDTO,
    TournamentParticipantDTO,
)
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.capabilities.esports.player import PlayerSearchResult
from app.vnext.capabilities.esports.series import SeriesTeamsResult
from app.vnext.capabilities.esports.team import TeamSearchInput, TeamSearchResult
from app.vnext.capabilities.esports.tournament import TournamentSearchResult
from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.data_updates.team_directory_store import TeamDirectoryStore, TeamDisplayRecord
from app.vnext.entity_display import EntityDisplayDirectory
from app.vnext.llm.protocol import ToolCall


def _directory(data_root: Path) -> EntityDisplayDirectory:
    TeamDirectoryStore(data_root).publish(
        {
            101: TeamDisplayRecord(source_id=101, label="BetBoom Team"),
            202: TeamDisplayRecord(source_id=202, label="Black Box"),
        }
    )
    repository = load_default_catalog_repository()
    return EntityDisplayDirectory(lambda: repository, data_root=data_root)


class _CountingDirectory:
    def __init__(self, directory: EntityDisplayDirectory) -> None:
        self.directory = directory
        self.calls: list[list[str]] = []

    def resolve_many(self, refs):
        batch = list(refs)
        self.calls.append(batch)
        return self.directory.resolve_many(batch)


def test_team_search_uses_local_team_identity_and_preserves_provider_facts(
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path)
    counter = _CountingDirectory(directory)
    result = TeamSearchResult(
        items=[
            TeamDTO(
                id=101,
                name="Provider BetBoom",
                acronym="BB",
                image_url="https://provider.invalid/bb.png",
            ),
            TeamDTO(id=202, name="Provider Black Box", acronym="BB"),
            TeamDTO(id=303, name="Unknown BB", acronym="BB"),
        ],
        page=1,
        limit=20,
    )

    enriched = enrich_team_search_result(result, counter)  # type: ignore[arg-type]

    assert [team.display_ref for team in enriched.items] == [
        "display:pandascore:team:101",
        "display:pandascore:team:202",
        None,
    ]
    assert enriched.items[0].name == "Provider BetBoom"
    assert enriched.items[0].image_url == "https://provider.invalid/bb.png"
    assert enriched.items[1].name == "Provider Black Box"
    assert result.items[0].display_ref is None
    assert result.items[1].display_ref is None
    assert result.items[2].display_ref is None
    assert counter.calls == [[
        "display:pandascore:team:101",
        "display:pandascore:team:202",
        "display:pandascore:team:303",
    ]]


def test_team_search_without_configured_display_directory_keeps_reference_null() -> None:
    async def team_search(query: TeamSearchInput) -> TeamSearchResult:
        return TeamSearchResult(
            items=[TeamDTO(id=101, name="Provider Team")],
            page=query.page,
            limit=query.limit,
        )

    registry = build_vnext_registry(
        VNextServices(team_search=team_search),
        settings=VNextSettings(),
    )
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="team-no-directory",
                name="esports.team.search",
                arguments={"id": 101},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["items"][0]["display_ref"] is None


def test_five_result_paths_resolve_explicit_team_fields_in_one_deduplicated_batch(
    tmp_path: Path,
) -> None:
    counter = _CountingDirectory(_directory(tmp_path))
    first = TeamRefDTO(id=101, name="Provider A", acronym="BB")
    second = TeamRefDTO(id=202, name="Provider B", acronym="BB")

    top_level = TeamSearchResult(
        items=[TeamDTO(id=101, name="Provider A"), TeamDTO(id=101, name="Repeated")],
        page=1,
        limit=20,
    )
    top_level_out = enrich_team_search_result(top_level, counter)  # type: ignore[arg-type]
    assert [team.display_ref for team in top_level_out.items] == [
        "display:pandascore:team:101",
        "display:pandascore:team:101",
    ]
    assert counter.calls[-1] == ["display:pandascore:team:101"]

    series = SeriesTeamsResult(items=[first, second, first], page=1, limit=20)
    series_out = enrich_series_teams_result(series, counter)  # type: ignore[arg-type]
    assert [team.display_ref for team in series_out.items] == [
        "display:pandascore:team:101",
        "display:pandascore:team:202",
        "display:pandascore:team:101",
    ]
    assert counter.calls[-1] == [
        "display:pandascore:team:101",
        "display:pandascore:team:202",
    ]

    tournament = TournamentSearchResult(
        items=[
            TournamentDTO(
                id=1,
                series_id=2,
                league_id=3,
                name="Stage",
                participants=[
                    TournamentParticipantDTO(team=first),
                    TournamentParticipantDTO(team=first),
                ],
            )
        ],
        page=1,
        limit=20,
    )
    tournament_out = enrich_tournament_search_result(tournament, counter)  # type: ignore[arg-type]
    assert [
        participant.team.display_ref
        for participant in tournament_out.items[0].participants
    ] == ["display:pandascore:team:101"] * 2
    assert counter.calls[-1] == ["display:pandascore:team:101"]

    match = MatchSearchResult(
        items=[
            MatchDTO(
                id=4,
                name="Final",
                status="finished",
                participants=[
                    MatchParticipantDTO(team=first, score=2),
                    MatchParticipantDTO(team=second, score=1),
                ],
                winner=second,
                draw=False,
                forfeit=False,
                rescheduled=False,
            )
        ],
        page=1,
        limit=20,
    )
    match_out = enrich_match_search_result(match, counter)  # type: ignore[arg-type]
    assert [
        participant.team.display_ref
        for participant in match_out.items[0].participants
    ] == ["display:pandascore:team:101", "display:pandascore:team:202"]
    assert match_out.items[0].winner is not None
    assert match_out.items[0].winner.display_ref is None
    assert counter.calls[-1] == [
        "display:pandascore:team:101",
        "display:pandascore:team:202",
    ]

    players = PlayerSearchResult(
        items=[
            PlayerDTO(id=10, name="Player", active=True, current_team=first),
            PlayerDTO(id=11, name="Free Agent", active=True),
        ],
        page=1,
        limit=20,
    )
    players_out = enrich_player_search_result(players, counter)  # type: ignore[arg-type]
    assert players_out.items[0].current_team is not None
    assert players_out.items[0].current_team.display_ref == "display:pandascore:team:101"
    assert players_out.items[1].current_team is None
    assert not hasattr(players_out.items[0], "display_ref")
    assert counter.calls[-1] == ["display:pandascore:team:101"]

    assert first.display_ref is None
    assert second.display_ref is None
    assert tournament.items[0].participants[0].team.display_ref is None
    assert match.items[0].participants[0].team.display_ref is None
    assert players.items[0].current_team is not None
    assert players.items[0].current_team.display_ref is None


def test_composed_team_result_keeps_reference_through_artifact_read(
    tmp_path: Path,
) -> None:
    _directory(tmp_path)
    repository = load_default_catalog_repository()
    settings = VNextSettings(
        data_dir=tmp_path,
        artifact_limits=ArtifactLimits(
            inline_max_bytes=100,
            observation_max_bytes=2_048,
        ),
    )
    services = build_vnext_services(
        settings,
        catalog_repository_provider=lambda: repository,
    )
    assert services.entity_display_directory is not None

    async def fake_team_search(query: TeamSearchInput) -> TeamSearchResult:
        return TeamSearchResult(
            items=[TeamDTO(id=101, name="Provider Team " + "x" * 500)],
            page=query.page,
            limit=query.limit,
        )

    services.team_search = fake_team_search
    registry = build_vnext_registry(services, settings=settings)

    async def execute():
        searched = await registry.execute(
            ToolCall(
                id="team-search",
                name="esports.team.search",
                arguments={"id": 101},
            )
        )
        assert searched.status == "ok"
        assert searched.content["externalized"] is True
        return await registry.execute(
            ToolCall(
                id="read-team-artifact",
                name="artifact.read",
                arguments={
                    "ref": searched.content["artifact_ref"],
                    "mode": "read",
                    "path": "items",
                    "limit": 1,
                },
            )
        )

    read = asyncio.run(execute())

    assert read.status == "ok"
    assert read.content["value"][0]["display_ref"] == "display:pandascore:team:101"
    assert read.content["value"][0]["name"] == "Provider Team " + "x" * 500
