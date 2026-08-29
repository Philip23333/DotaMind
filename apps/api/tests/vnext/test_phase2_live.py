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


def test_live_pandascore_esports_navigation_and_small_match_window() -> None:
    query = os.getenv("DOTAMIND_LIVE_COMPETITION_QUERY", "The International")
    year_raw = os.getenv("DOTAMIND_LIVE_COMPETITION_YEAR")
    year = int(year_raw) if year_raw else None

    async def exercise() -> None:
        services = build_vnext_services(_live_settings)
        try:
            result = await services.esports.search(query=query, limit=5)
            series = next(
                record
                for record in result.records
                if record.kind == "series" and (year is None or record.facts.get("year") == year)
            )
            assert series.locator is not None, "PandaScore series result did not include a locator"
            schedule = await services.esports.search(
                within=series.locator,
                time_scope="all",
                limit=5,
            )
            assert all(record.kind == "match" for record in schedule.records)
        finally:
            await services.aclose()

    asyncio.run(exercise())


def test_live_opendota_resolution_and_detail() -> None:
    if not _live_settings.opendota_api_key:
        pytest.skip("OpenDota live smoke skipped; DOTAMIND_OPENDOTA_API_KEY is not configured")

    async def exercise() -> None:
        services = build_vnext_services(_live_settings)
        try:
            discovery = await services.esports.search(
                time_scope="recent",
                limit=5,
            )
            matches = [record for record in discovery.records if record.kind == "match"]
            assert matches, "no live match candidate for OpenDota smoke"
            detail = None
            outcomes: list[str] = []
            for candidate in matches:
                assert candidate.locator is not None
                try:
                    candidate_detail = await services.matches.get_detail(locator=candidate.locator)
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
