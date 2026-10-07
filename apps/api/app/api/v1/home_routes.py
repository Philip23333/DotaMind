"""Ordinary read-only data endpoints for the application home page."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.vnext.homepage.recent_series import (
    HomepageRecentSeriesService,
    RecentSeriesCacheDataError,
    RecentSeriesCacheUnavailableError,
    RecentSeriesResponse,
)

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/recent-series", response_model=RecentSeriesResponse)
async def read_recent_series(
    request: Request,
    wait_for_refresh: bool = Query(default=False),
) -> RecentSeriesResponse:
    service = getattr(request.app.state, "homepage_recent_series", None)
    if not isinstance(service, HomepageRecentSeriesService):
        raise HTTPException(
            status_code=503,
            detail={"code": "homepage_series_unavailable"},
        )
    try:
        return await service.get_recent_series(wait_for_refresh=wait_for_refresh)
    except (RecentSeriesCacheDataError, RecentSeriesCacheUnavailableError):
        raise HTTPException(
            status_code=503,
            detail={"code": "homepage_series_cache_unavailable"},
        ) from None


__all__ = ["router"]
