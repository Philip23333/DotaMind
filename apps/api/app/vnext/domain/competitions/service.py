"""Competition capability orchestration over the PandaScore adapter."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone

from app.vnext.domain.common.models import (
    CompetitionRef,
    Freshness,
    Provenance,
    hash_ref,
    normalize_text,
)
from app.vnext.domain.competitions.models import (
    Competition,
    CompetitionCandidate,
    CompetitionSearchResult,
    CompetitionStatus,
)
from app.vnext.domain.matches.models import (
    CompetitionMatchesResult,
    CompetitionSummary,
    MatchStatus,
    TimeScope,
)
from app.vnext.domain.matches.normalization import normalize_panda_match
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.models import PandaScoreSeries


class CompetitionService:
    """Normalize competition search and schedules without provider leakage."""

    def __init__(
        self,
        provider: PandaScoreAdapter,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._competitions: dict[str, tuple[int, Competition]] = {}

    async def search(
        self,
        query: str,
        *,
        year: int | None = None,
        limit: int = 10,
    ) -> CompetitionSearchResult:
        normalized_query = " ".join(query.split())
        batch = await self.provider.search_series(query=normalized_query, year=year, limit=limit)
        candidates: list[CompetitionCandidate] = []
        seen: set[tuple[str, int | None, datetime | None, datetime | None]] = set()
        for series in batch.items:
            candidate = self._normalize_series(series, fetched_at=batch.fetched_at)
            if year is not None and candidate.year != year:
                continue
            if not _query_matches(candidate, normalized_query, series):
                continue
            key = (
                normalize_text(candidate.name),
                candidate.year,
                candidate.starts_at,
                candidate.ends_at,
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(CompetitionCandidate.model_validate(candidate.model_dump()))
            self._remember(series.provider_id, candidate)
        candidates.sort(key=lambda item: (item.year is None, -(item.year or 0), item.name))
        candidates = candidates[: max(1, limit)]
        status = (
            "not_found" if not candidates else "unique" if len(candidates) == 1 else "ambiguous"
        )
        warnings: list[str] = []
        if year is not None and not candidates:
            warnings.append("no competition edition matched the requested year")
        provenance = Provenance(
            sources=["pandascore"],
            freshness=Freshness(fetched_at=batch.fetched_at, status="fresh"),
            identity_status=(
                "not_found" if not candidates else "ambiguous" if len(candidates) > 1 else "native"
            ),
            warnings=warnings,
        )
        return CompetitionSearchResult(
            status=status,
            query=normalized_query,
            year=year,
            candidate_count=len(candidates),
            candidates=candidates,
            provenance=provenance,
        )

    async def list_matches(
        self,
        competition_ref: CompetitionRef,
        *,
        time_scope: TimeScope = "all",
        status: MatchStatus | None = None,
        limit: int = 10,
    ) -> CompetitionMatchesResult:
        remembered = self._competitions.get(competition_ref.value)
        if remembered is None:
            placeholder = CompetitionSummary(
                ref=competition_ref,
                name="Unknown competition",
                year=None,
            )
            return CompetitionMatchesResult(
                status="not_found",
                competition=placeholder,
                time_scope=time_scope,
                candidate_count=0,
                matches=[],
                provenance=Provenance(
                    sources=["pandascore"],
                    freshness=Freshness(status="unknown"),
                    identity_status="not_found",
                    warnings=["competition reference is not known to this in-memory runtime"],
                ),
            )

        provider_series_id, competition = remembered
        batch = await self.provider.list_matches(
            scope=time_scope,
            series_id=provider_series_id,
            limit=limit,
        )
        matches = []
        seen: set[str] = set()
        warnings: list[str] = []
        competition_summary = CompetitionSummary(
            ref=competition.ref,
            name=competition.name,
            year=competition.year,
        )
        for row in batch.items:
            normalized = normalize_panda_match(
                row,
                fetched_at=batch.fetched_at,
                competition_ref=competition.ref,
                competition_name=competition.name,
                competition_year=competition.year,
            )
            if normalized.summary.ref.value in seen:
                continue
            if status is not None and normalized.summary.status != status:
                continue
            seen.add(normalized.summary.ref.value)
            matches.append(normalized.summary)
            warnings.extend(normalized.summary.provenance.warnings)
        matches.sort(key=_schedule_sort_key, reverse=time_scope == "recent")
        matches = matches[: max(1, limit)]
        return CompetitionMatchesResult(
            status="ok" if matches else "not_found",
            competition=competition_summary,
            time_scope=time_scope,
            candidate_count=len(matches),
            matches=matches,
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=batch.fetched_at, status="fresh"),
                identity_status="native",
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    def get_known(self, reference: CompetitionRef) -> Competition | None:
        remembered = self._competitions.get(reference.value)
        return remembered[1] if remembered else None

    def provider_id_for(self, reference: CompetitionRef) -> int | None:
        remembered = self._competitions.get(reference.value)
        return remembered[0] if remembered else None

    def remember(
        self,
        provider_series_id: int,
        *,
        name: str,
        year: int | None,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        fetched_at: datetime | None = None,
    ) -> Competition:
        """Remember a provider-derived competition for a later tool call."""

        ref = CompetitionRef(value=hash_ref("competition", "pandascore-series", provider_series_id))
        competition = Competition(
            ref=ref,
            name=name,
            year=year,
            status=_status_from_dates(starts_at, ends_at, self._now()),
            starts_at=starts_at,
            ends_at=ends_at,
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(
                    fetched_at=fetched_at or self._now(),
                    status="fresh" if fetched_at is not None else "unknown",
                ),
                identity_status="native",
            ),
        )
        self._remember(provider_series_id, competition)
        return competition

    def _normalize_series(
        self,
        series: PandaScoreSeries,
        *,
        fetched_at: datetime,
    ) -> Competition:
        name = (
            series.name
            or series.full_name
            or (
                series.league.name
                if series.league and series.league.name
                else "Unknown competition"
            )
        )
        year = series.year or _extract_year(series.full_name or "") or _extract_year(name)
        if year is None and series.league and series.league.name:
            year = _extract_year(series.league.name)
        warnings: list[str] = []
        if series.begin_at is None and series.end_at is None:
            warnings.append("PandaScore did not provide competition dates")
        return Competition(
            ref=CompetitionRef(
                value=hash_ref("competition", "pandascore-series", series.provider_id)
            ),
            name=name,
            year=year,
            status=_competition_status(series.status, series.begin_at, series.end_at, self._now()),
            starts_at=series.begin_at,
            ends_at=series.end_at,
            tier=series.tier,
            region=series.region,
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=fetched_at, status="fresh"),
                identity_status="native",
                warnings=warnings,
            ),
        )

    def _remember(self, provider_series_id: int, competition: Competition) -> None:
        self._competitions[competition.ref.value] = (provider_series_id, competition)


def _query_matches(
    candidate: Competition,
    query: str,
    series: PandaScoreSeries,
) -> bool:
    needle = normalize_text(query)
    values = [candidate.name, series.full_name or ""]
    if series.league and series.league.name:
        values.append(series.league.name)
    return any(needle in normalize_text(value) for value in values if value)


def _competition_status(
    raw_status: str | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
    now: datetime,
) -> CompetitionStatus:
    normalized = normalize_text(raw_status or "")
    if normalized in {"running", "live", "ongoing"}:
        return "running"
    if normalized in {"finished", "completed", "past"}:
        return "completed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    return _status_from_dates(starts_at, ends_at, now)


def _status_from_dates(
    starts_at: datetime | None,
    ends_at: datetime | None,
    now: datetime,
) -> CompetitionStatus:
    if starts_at is not None and starts_at > now:
        return "upcoming"
    if ends_at is not None and ends_at < now:
        return "completed"
    if starts_at is not None:
        return "running"
    return "unknown"


def _schedule_sort_key(match: object) -> datetime:
    scheduled = getattr(match, "scheduled_at", None)
    started = getattr(match, "started_at", None)
    return scheduled or started or datetime.max.replace(tzinfo=timezone.utc)


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


__all__ = ["CompetitionService"]
