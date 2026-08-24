from __future__ import annotations

import asyncio
import os

import pytest

from app.vnext.composition import VNextSettings, build_vnext_services
from app.vnext.providers.pandascore.adapter import PandaScoreProviderError


def _enabled() -> bool:
    return os.getenv("DOTAMIND_RUN_LIVE_SMOKE", "").casefold() in {"1", "true", "yes"}


if not _enabled():
    pytest.skip(
        "live smoke disabled; set DOTAMIND_RUN_LIVE_SMOKE=1 with provider configuration",
        allow_module_level=True,
    )


_live_settings = VNextSettings.from_env()


if not _live_settings.pandascore_token:
    pytest.skip(
        "live smoke skipped; DOTAMIND_PANDASCORE_TOKEN is not configured",
        allow_module_level=True,
    )


def test_live_pandascore_competition_and_small_match_window() -> None:
    query = os.getenv("DOTAMIND_LIVE_COMPETITION_QUERY", "The International")
    year_raw = os.getenv("DOTAMIND_LIVE_COMPETITION_YEAR")
    year = int(year_raw) if year_raw else None

    async def exercise() -> None:
        services = build_vnext_services(_live_settings)
        try:
            result = await services.competitions.search(query, year=year, limit=5)
            assert result.candidates, "PandaScore returned no live competition candidates"
            schedule = await services.competitions.list_matches(
                result.candidates[0].ref,
                time_scope="all",
                limit=5,
            )
            assert schedule.status == "ok", "PandaScore returned no live match window"
            assert schedule.provenance.sources == ["pandascore"]
            assert schedule.provenance.freshness.fetched_at is not None
        finally:
            await services.aclose()

    asyncio.run(exercise())


def test_live_opendota_resolution_and_detail() -> None:
    if not _live_settings.opendota_api_key:
        pytest.skip("OpenDota live smoke skipped; DOTAMIND_OPENDOTA_API_KEY is not configured")

    async def exercise() -> None:
        services = build_vnext_services(_live_settings)
        try:
            matches = await services.matches.search(
                time_scope="recent",
                limit=5,
            )
            assert matches.candidates, "no live match candidate for OpenDota smoke"
            detail = None
            outcomes: list[str] = []
            for candidate in matches.candidates:
                try:
                    candidate_detail = await services.matches.get_detail(match_ref=candidate.ref)
                except PandaScoreProviderError:
                    outcomes.append("pandascore_detail_unavailable")
                    continue
                outcomes.append(candidate_detail.status)
                if candidate_detail.status == "available":
                    detail = candidate_detail
                    break
            assert detail is not None, (
                "live cross-source mapping/detail was not available; "
                f"candidate outcomes: {outcomes}"
            )
            assert "opendota" in detail.provenance.sources
            assert detail.provenance.freshness.fetched_at is not None
        finally:
            await services.aclose()

    asyncio.run(exercise())
