"""Player identity and source-fact capabilities."""

from __future__ import annotations

from app.vnext.domain.common.models import Freshness, PlayerRef, Provenance
from app.vnext.domain.players.models import (
    Player,
    PlayerCandidate,
    PlayerGetResult,
    PlayerSearchResult,
)
from app.vnext.domain.team_player_index import TeamPlayerRefIndex
from app.vnext.domain.teams.models import TeamIdentity
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.models import PandaScorePlayer, PandaScoreTeamBrief


class PlayerService:
    """Normalize PandaScore player identity and source-backed player facts."""

    def __init__(self, provider: PandaScoreAdapter, index: TeamPlayerRefIndex) -> None:
        self.provider = provider
        self.index = index

    async def search(self, query: str, *, limit: int = 10) -> PlayerSearchResult:
        normalized_query = " ".join(query.split())
        batch = await self.provider.search_players(query=normalized_query, limit=limit)
        candidates = [self._candidate(row) for row in batch.items]
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
        return PlayerSearchResult(
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

    async def get(self, ref: PlayerRef) -> PlayerGetResult:
        provider_id = self.index.player_provider_id(ref)
        if provider_id is None:
            return PlayerGetResult(
                status="not_found",
                provenance=Provenance(
                    sources=["pandascore"],
                    freshness=Freshness(status="unknown"),
                    identity_status="not_found",
                    warnings=["player reference is not known to this in-memory runtime"],
                ),
            )

        result = await self.provider.get_player(provider_id)
        return PlayerGetResult(
            status="available",
            player=self._player(result.item),
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=result.fetched_at, status="fresh"),
                identity_status="native",
            ),
        )

    def _candidate(self, row: PandaScorePlayer) -> PlayerCandidate:
        return PlayerCandidate(
            ref=self.index.remember_player(row.provider_id),
            name=row.name,
            first_name=row.first_name,
            last_name=row.last_name,
            nationality=row.nationality,
            role=row.role,
            active=row.active,
            image_url=row.image_url,
            current_team=self._team_identity(row.current_team),
        )

    def _player(self, row: PandaScorePlayer) -> Player:
        return Player(
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
            current_team=self._team_identity(row.current_team),
        )

    def _team_identity(self, row: PandaScoreTeamBrief | None) -> TeamIdentity | None:
        if row is None:
            return None
        return TeamIdentity(
            ref=self.index.remember_team(row.provider_id),
            name=row.name,
            acronym=row.acronym,
            logo_url=row.image_url,
        )


__all__ = ["PlayerService"]
