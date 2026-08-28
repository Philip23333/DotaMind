from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    ArtifactSearcher,
    GameSummaryArtifactProducer,
    MemoryArtifactStore,
)
from app.vnext.artifacts.game_summary_builder_v4 import GameSummaryBuilderV4
from app.vnext.composition import VNextServices
from app.vnext.domain.competitions.service import CompetitionService
from app.vnext.domain.matches.service import MatchService
from app.vnext.domain.players.service import PlayerService
from app.vnext.domain.team_player_index import TeamPlayerRefIndex
from app.vnext.domain.teams.service import TeamService
from app.vnext.identity.ability_v4 import AbilityResolverV4
from app.vnext.identity.hero_v4 import HeroResolverV4
from app.vnext.identity.item_v4 import ItemResolverV4
from app.vnext.providers.common import ProviderBatch, ProviderObject
from app.vnext.providers.opendota.adapter import (
    OpenDotaGameConstructionAdapter,
    OpenDotaHTTPError,
)
from app.vnext.providers.opendota.models import (
    OpenDotaGameConstructionMatch,
    OpenDotaLeague,
    OpenDotaLeagueMatch,
    OpenDotaMatchDetail,
    OpenDotaTeam,
)
from app.vnext.providers.pandascore.adapter import PandaScoreHTTPError
from app.vnext.providers.pandascore.models import (
    PandaScoreLeague,
    PandaScoreMatch,
    PandaScorePlayer,
    PandaScoreSeries,
    PandaScoreTeam,
)

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 8, 24, tzinfo=timezone.utc)


def load_fixture(provider: str, name: str) -> Any:
    return json.loads((FIXTURES / provider / name).read_text(encoding="utf-8"))


def panda_series() -> list[PandaScoreSeries]:
    return [
        PandaScoreSeries.model_validate(row)
        for row in load_fixture("pandascore", "series_search.json")
    ]


def panda_matches() -> list[PandaScoreMatch]:
    rows = load_fixture("pandascore", "matches_past.json")
    rows.extend(load_fixture("pandascore", "matches_upcoming.json"))
    rows.append(load_fixture("pandascore", "match_bo3.json"))
    return [PandaScoreMatch.model_validate(row) for row in rows]


def panda_team_search() -> list[PandaScoreTeam]:
    return [
        PandaScoreTeam.model_validate(row)
        for row in load_fixture("pandascore", "teams_search.json")
    ]


def panda_team_detail() -> PandaScoreTeam:
    return PandaScoreTeam.model_validate(load_fixture("pandascore", "team_detail.json"))


def panda_player_search() -> list[PandaScorePlayer]:
    return [
        PandaScorePlayer.model_validate(row)
        for row in load_fixture("pandascore", "players_search.json")
    ]


def panda_player_detail() -> PandaScorePlayer:
    return PandaScorePlayer.model_validate(load_fixture("pandascore", "player_detail.json"))


def open_leagues() -> list[OpenDotaLeague]:
    return [OpenDotaLeague.model_validate(row) for row in load_fixture("opendota", "leagues.json")]


def open_teams() -> list[OpenDotaTeam]:
    return [OpenDotaTeam.model_validate(row) for row in load_fixture("opendota", "teams.json")]


def open_league_matches() -> list[OpenDotaLeagueMatch]:
    rows = [
        OpenDotaLeagueMatch.model_validate(row)
        for row in load_fixture("opendota", "league_matches_9001.json")
    ]
    rows.extend(
        OpenDotaLeagueMatch.model_validate(row)
        for row in load_fixture("opendota", "league_matches_9001_bo3.json")
    )
    return rows


def open_detail(provider_match_id: int = 40001) -> OpenDotaMatchDetail:
    return OpenDotaMatchDetail.model_validate(
        load_fixture("opendota", f"match_detail_{provider_match_id}.json")
    )


class FakePandaScore:
    def __init__(self, *, detail_available: bool = True) -> None:
        self.series = panda_series()
        self.direct_series = self.series
        self.league_series = self.series
        self.matches = panda_matches()
        self.teams = _panda_teams(self.matches)
        self.team_search_results: dict[str, list[PandaScoreTeam]] = {
            "Team Spirit": panda_team_search(),
        }
        self.team_details: dict[int, PandaScoreTeam] = {
            team.provider_id: team for team in self.teams
        }
        self.team_details[1669] = panda_team_detail()
        self.player_search_results: dict[str, list[PandaScorePlayer]] = {
            "Yatoro": panda_player_search(),
        }
        self.player_details: dict[int, PandaScorePlayer] = {30258: panda_player_detail()}
        self.team_match_pages: dict[int, list[list[PandaScoreMatch]]] = {}
        self.detail_available = detail_available
        self.list_matches_has_more = False
        self.get_calls: list[int] = []
        self.list_calls: list[dict[str, object]] = []
        self.league_search_calls: list[dict[str, object]] = []
        self.league_series_calls: list[dict[str, object]] = []
        self.team_search_calls: list[dict[str, object]] = []
        self.team_match_calls: list[dict[str, object]] = []
        self.team_get_calls: list[int] = []
        self.player_search_calls: list[dict[str, object]] = []
        self.player_get_calls: list[int] = []

    async def search_series(
        self,
        *,
        query: str | None = None,
        year: int | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreSeries]:
        return ProviderBatch(self.direct_series[:limit], FETCHED_AT, has_more=False)

    async def search_leagues(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreLeague]:
        self.league_search_calls.append({"query": query, "limit": limit})
        leagues = {
            item.league.provider_id: PandaScoreLeague(
                id=item.league.provider_id,
                name=item.league.name,
            )
            for item in self.league_series
            if item.league is not None
            and (not query or query.casefold() in (item.league.name or "").casefold())
        }
        return ProviderBatch(list(leagues.values())[:limit], FETCHED_AT, has_more=False)

    async def list_league_series(
        self,
        league_id: int,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreSeries]:
        self.league_series_calls.append({"league_id": league_id, "year": year, "limit": limit})
        rows = [
            item
            for item in self.league_series
            if item.league and item.league.provider_id == league_id
        ]
        if year is not None:
            rows = [item for item in rows if item.year == year]
        return ProviderBatch(rows[:limit], FETCHED_AT, has_more=False)

    async def search_teams(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreTeam]:
        self.team_search_calls.append({"query": query, "limit": limit})
        rows = self.team_search_results.get(query or "", self.teams)
        if query:
            needle = query.casefold()
            rows = [
                item
                for item in rows
                if any(
                    needle in (value or "").casefold()
                    for value in (item.name, item.acronym, item.slug)
                )
            ]
        return ProviderBatch(rows[:limit], FETCHED_AT, has_more=False)

    async def get_team(self, provider_team_id: int) -> ProviderObject[PandaScoreTeam]:
        self.team_get_calls.append(provider_team_id)
        try:
            return ProviderObject(self.team_details[provider_team_id], FETCHED_AT)
        except KeyError as exc:
            raise PandaScoreHTTPError(404, f"/teams/{provider_team_id}") from exc

    async def search_players(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScorePlayer]:
        self.player_search_calls.append({"query": query, "limit": limit})
        rows = self.player_search_results.get(query or "", [])
        return ProviderBatch(rows[:limit], FETCHED_AT, has_more=False)

    async def get_player(self, provider_player_id: int) -> ProviderObject[PandaScorePlayer]:
        self.player_get_calls.append(provider_player_id)
        try:
            return ProviderObject(self.player_details[provider_player_id], FETCHED_AT)
        except KeyError as exc:
            raise PandaScoreHTTPError(404, f"/players/{provider_player_id}") from exc

    async def list_matches(
        self,
        *,
        scope: str = "all",
        series_id: int | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreMatch]:
        self.list_calls.append(
            {"scope": scope, "series_id": series_id, "query": query, "limit": limit}
        )
        rows = self.matches
        if scope == "recent":
            rows = [item for item in rows if item.status == "finished"]
        elif scope == "upcoming":
            rows = [item for item in rows if item.status == "not_started"]
        elif scope == "running":
            rows = [item for item in rows if item.status == "running"]
        if series_id is not None:
            rows = [item for item in rows if item.series_id == series_id]
        if query:
            needle = query.casefold()
            rows = [item for item in rows if needle in item.name.casefold()]
        return ProviderBatch(rows[:limit], FETCHED_AT, has_more=self.list_matches_has_more)

    async def list_team_matches(
        self,
        team_id: int,
        *,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        query: str | None = None,
        series_id: int | None = None,
    ) -> ProviderBatch[PandaScoreMatch]:
        self.team_match_calls.append(
            {
                "team_id": team_id,
                "page_number": page_number,
                "page_size": page_size,
                "sort": sort,
                "query": query,
                "series_id": series_id,
            }
        )
        configured_pages = self.team_match_pages.get(team_id)
        if configured_pages is not None:
            if page_number > len(configured_pages):
                return ProviderBatch([], FETCHED_AT, has_more=False)
            return ProviderBatch(
                configured_pages[page_number - 1],
                FETCHED_AT,
                has_more=page_number < len(configured_pages),
            )
        rows = [
            item
            for item in self.matches
            if team_id in {opponent.opponent.provider_id for opponent in item.opponents}
        ]
        start = (page_number - 1) * page_size
        page = rows[start : start + page_size]
        return ProviderBatch(
            page,
            FETCHED_AT,
            has_more=start + page_size < len(rows),
        )

    async def get_match(self, provider_match_id: int) -> ProviderObject[PandaScoreMatch]:
        self.get_calls.append(provider_match_id)
        if not self.detail_available:
            raise PandaScoreHTTPError(404, "/dota2/matches")
        for item in self.matches:
            if item.provider_id == provider_match_id:
                return ProviderObject(item, FETCHED_AT)
        raise AssertionError(f"unknown fixture match {provider_match_id}")


def _panda_teams(matches: list[PandaScoreMatch]) -> list[PandaScoreTeam]:
    teams: dict[int, PandaScoreTeam] = {}
    for match in matches:
        for opponent in match.opponents:
            team = opponent.opponent
            teams.setdefault(
                team.provider_id,
                PandaScoreTeam(
                    id=team.provider_id,
                    name=team.name,
                    acronym=team.acronym,
                    slug=team.name.casefold().replace(" ", "-"),
                    image_url=team.image_url,
                ),
            )
    return list(teams.values())


class FakeOpenDota:
    def __init__(
        self,
        *,
        detail_available: bool = True,
        resolution_available: bool = True,
        unavailable_detail_ids: set[int] | None = None,
    ) -> None:
        self.leagues = open_leagues()
        self.teams = open_teams()
        self.matches = open_league_matches()
        self.detail_available = detail_available
        self.resolution_available = resolution_available
        self.unavailable_detail_ids = unavailable_detail_ids or set()
        self.detail_calls: list[int] = []
        self.construction_calls: list[int] = []

    async def list_leagues(self) -> ProviderBatch[OpenDotaLeague]:
        if not self.resolution_available:
            raise OpenDotaHTTPError(503, "/leagues")
        return ProviderBatch(self.leagues, FETCHED_AT)

    async def list_teams(self) -> ProviderBatch[OpenDotaTeam]:
        if not self.resolution_available:
            raise OpenDotaHTTPError(503, "/teams")
        return ProviderBatch(self.teams, FETCHED_AT)

    async def list_league_matches(
        self,
        league_id: int,
    ) -> ProviderBatch[OpenDotaLeagueMatch]:
        if not self.resolution_available:
            raise OpenDotaHTTPError(503, "/leagues/matches")
        return ProviderBatch(
            [item for item in self.matches if item.league_id == league_id],
            FETCHED_AT,
        )

    async def get_match_detail(self, match_id: int) -> ProviderObject[OpenDotaMatchDetail]:
        self.detail_calls.append(match_id)
        if not self.detail_available or match_id in self.unavailable_detail_ids:
            raise OpenDotaHTTPError(503, "/matches")
        return ProviderObject(open_detail(match_id), FETCHED_AT)

    async def get_game_construction_match(
        self,
        match_id: int,
    ) -> ProviderObject[OpenDotaGameConstructionMatch]:
        self.construction_calls.append(match_id)
        if not self.detail_available or match_id in self.unavailable_detail_ids:
            raise OpenDotaHTTPError(503, "/matches")
        detail = open_detail(match_id)
        players = []
        for index, player in enumerate(detail.players):
            row = dict(player)
            row.setdefault("player_slot", 0 if row.get("isRadiant") is True else 128 + index)
            players.append(row)
        return ProviderObject(
            OpenDotaGameConstructionMatch.model_validate(
                {
                    "match_id": detail.provider_match_id,
                    "start_time": detail.start_time,
                    "duration": detail.duration,
                    "radiant_win": detail.radiant_win,
                    "game_mode": detail.game_mode,
                    "lobby_type": detail.lobby_type,
                    "radiant_team": detail.radiant_team,
                    "dire_team": detail.dire_team,
                    "radiant_score": detail.radiant_score,
                    "dire_score": detail.dire_score,
                    "players": players,
                    "picks_bans": detail.picks_bans,
                }
            ),
            FETCHED_AT,
        )


def fixture_services(
    *,
    pandascore_detail_available: bool = True,
    detail_available: bool = True,
    resolution_available: bool = True,
    unavailable_detail_ids: set[int] | None = None,
) -> tuple[CompetitionService, MatchService, FakePandaScore, FakeOpenDota]:
    panda = FakePandaScore(detail_available=pandascore_detail_available)
    opendota = FakeOpenDota(
        detail_available=detail_available,
        resolution_available=resolution_available,
        unavailable_detail_ids=unavailable_detail_ids,
    )
    competition_service = CompetitionService(
        panda, now=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc)
    )
    team_player_index = TeamPlayerRefIndex()
    match_service = MatchService(
        panda,
        opendota,
        competition_service=competition_service,
        team_player_index=team_player_index,
        now=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    competition_service.set_match_cache(match_service.remember_fixture)
    return competition_service, match_service, panda, opendota


def fixture_vnext_services(
    competition_service: CompetitionService,
    match_service: MatchService,
    panda: FakePandaScore,
    opendota: FakeOpenDota,
    *,
    builder: GameSummaryBuilderV4 | None = None,
) -> VNextServices:
    store = MemoryArtifactStore()
    producer = GameSummaryArtifactProducer(
        opendota=opendota,
        construction_adapter=OpenDotaGameConstructionAdapter(),
        builder=builder
        or GameSummaryBuilderV4(
            hero_resolver=HeroResolverV4({}),
            item_resolver=ItemResolverV4({}),
            ability_resolver=AbilityResolverV4({}),
        ),
        store=store,
    )
    searcher = ArtifactSearcher(store)
    reader = ArtifactReader(store)
    grepper = ArtifactGrepper(store)
    team_service = TeamService(panda, match_service.team_player_index)
    player_service = PlayerService(panda, match_service.team_player_index)
    return VNextServices(
        panda,
        opendota,
        competition_service,
        match_service,
        team_service,
        player_service,
        store,
        producer,
        searcher,
        reader,
        grepper,
    )
