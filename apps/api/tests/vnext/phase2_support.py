from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.vnext.domain.competitions.service import CompetitionService
from app.vnext.domain.matches.service import MatchService
from app.vnext.providers.common import ProviderBatch, ProviderObject
from app.vnext.providers.opendota.adapter import OpenDotaHTTPError
from app.vnext.providers.opendota.models import (
    OpenDotaLeague,
    OpenDotaLeagueMatch,
    OpenDotaMatchDetail,
    OpenDotaTeam,
)
from app.vnext.providers.pandascore.adapter import PandaScoreHTTPError
from app.vnext.providers.pandascore.models import (
    PandaScoreMatch,
    PandaScoreSeries,
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
        self.matches = panda_matches()
        self.detail_available = detail_available
        self.get_calls: list[int] = []
        self.list_calls: list[dict[str, object]] = []

    async def search_series(
        self,
        *,
        query: str | None = None,
        year: int | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreSeries]:
        return ProviderBatch(self.series, FETCHED_AT)

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
        return ProviderBatch(rows[:limit], FETCHED_AT)

    async def get_match(self, provider_match_id: int) -> ProviderObject[PandaScoreMatch]:
        self.get_calls.append(provider_match_id)
        if not self.detail_available:
            raise PandaScoreHTTPError(404, "/dota2/matches")
        for item in self.matches:
            if item.provider_id == provider_match_id:
                return ProviderObject(item, FETCHED_AT)
        raise AssertionError(f"unknown fixture match {provider_match_id}")


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
    match_service = MatchService(
        panda,
        opendota,
        competition_service=competition_service,
        now=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    competition_service.set_match_cache(match_service.remember_fixture)
    return competition_service, match_service, panda, opendota
