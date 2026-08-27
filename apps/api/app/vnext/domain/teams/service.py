"""Team identity and source-fact capabilities."""

from __future__ import annotations

from app.vnext.domain.common.models import Freshness, Provenance, TeamRef
from app.vnext.domain.team_player_index import TeamPlayerRefIndex
from app.vnext.domain.teams.models import (
    Team,
    TeamCandidate,
    TeamGetResult,
    TeamPlayer,
    TeamSearchResult,
)
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.models import PandaScorePlayerBrief, PandaScoreTeam


class TeamService:
    """Normalize PandaScore team identity and source-backed team facts."""

    def __init__(self, provider: PandaScoreAdapter, index: TeamPlayerRefIndex) -> None:
        self.provider = provider
        self.index = index

    async def search(self, query: str, *, limit: int = 10) -> TeamSearchResult:
        normalized_query = " ".join(query.split())
        batch = await self.provider.search_teams(query=normalized_query, limit=limit)
        candidates = [
            self._candidate(row)
            for row in batch.items
        ]
        has_more = batch.has_more is True
        if not candidates:
            status = "not_found"
        elif len(candidates) == 1 and not has_more:
            status = "unique"
        else:
            status = "ambiguous"
        identity_status = (
            "not_found"
            if not candidates
            else "native"
            if len(candidates) == 1 and not has_more
            else "ambiguous"
        )
        warnings = (
            ["provider search was truncated; additional candidates may exist"]
            if has_more
            else []
        )
        return TeamSearchResult(
            status=status,
            query=normalized_query,
            candidate_count=len(candidates),
            candidates=candidates,
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=batch.fetched_at, status="fresh"),
                identity_status=identity_status,
                warnings=warnings,
            ),
        )

    async def get(self, ref: TeamRef) -> TeamGetResult:
        provider_id = self.index.team_provider_id(ref)
        if provider_id is None:
            return TeamGetResult(
                status="not_found",
                provenance=Provenance(
                    sources=["pandascore"],
                    freshness=Freshness(status="unknown"),
                    identity_status="not_found",
                    warnings=["team reference is not known to this in-memory runtime"],
                ),
            )

        result = await self.provider.get_team(provider_id)
        return TeamGetResult(
            status="available",
            team=self._team(result.item),
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=result.fetched_at, status="fresh"),
                identity_status="native",
            ),
        )

    def _candidate(self, row: PandaScoreTeam) -> TeamCandidate:
        ref = self.index.remember_team(row.provider_id)
        for player in row.players:
            self.index.remember_player(player.provider_id)
        return TeamCandidate(
            ref=ref,
            name=row.name,
            acronym=row.acronym,
            location=row.location,
            logo_url=row.image_url,
        )

    def _team(self, row: PandaScoreTeam) -> Team:
        ref = self.index.remember_team(row.provider_id)
        return Team(
            ref=ref,
            name=row.name,
            acronym=row.acronym,
            location=row.location,
            logo_url=row.image_url,
            players=[self._player(player) for player in row.players],
        )

    def _player(self, row: PandaScorePlayerBrief) -> TeamPlayer:
        return TeamPlayer(
            ref=self.index.remember_player(row.provider_id),
            name=row.name,
            first_name=row.first_name,
            last_name=row.last_name,
            nationality=row.nationality,
            role=row.role,
            active=row.active,
            birthday=row.birthday,
            birth_year=row.birth_year,
            hometown=row.hometown,
            image_url=row.image_url,
        )


__all__ = ["TeamService"]
