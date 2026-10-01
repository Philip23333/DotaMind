"""Coordinate one bounded refresh of the persistent Dota data sources."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.integrations.valve.fetch_session import ValveFetchSession
from app.integrations.valve.image_client import ValveImageClient
from app.vnext.data_updates.catalog_refresh import CatalogRefreshReport, refresh_catalog
from app.vnext.data_updates.catalog_store import CatalogStoreError
from app.vnext.data_updates.image_refresh import (
    ImageRefreshError,
    ImageRefreshReport,
    refresh_images,
)
from app.vnext.data_updates.patch_refresh import (
    PatchRefreshError,
    PatchRefreshReport,
    refresh_patches,
)
from app.vnext.hero_guides.cache import HeroGuideCacheDataError, HeroGuideCacheUnavailableError
from app.vnext.hero_guides.file_cache import FileHeroGuideCache
from app.vnext.hero_guides.refresh import HeroGuideRefresher, HeroGuideRefreshReport
from app.vnext.providers.d2pt import D2PTClient

ModuleStatus = Literal["success", "skipped", "partial", "failed", "blocked"]
OverallStatus = Literal["success", "partial", "failed"]
_Report = CatalogRefreshReport | PatchRefreshReport | ImageRefreshReport | HeroGuideRefreshReport


@dataclass(frozen=True, slots=True)
class RefreshAllModuleResult:
    status: ModuleStatus
    report: dict[str, Any] | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshAllReport:
    status: OverallStatus
    started_at: datetime
    finished_at: datetime
    modules: dict[str, RefreshAllModuleResult]
    exit_code: int


@dataclass(frozen=True, slots=True)
class _Outcome:
    report: _Report | None = None
    reason: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _validated_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("refresh-all clock must return timezone-aware datetimes")
    return value


async def refresh_all(
    *,
    data_root: Path,
    session: ValveFetchSession,
    workers: int = 8,
    image_workers: int = 8,
    force: bool = False,
    guide_client: D2PTClient | None = None,
    image_client: ValveImageClient | None = None,
    guide_clock: Callable[[], datetime] | None = None,
    guide_sleep: Callable[[float], Awaitable[None]] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RefreshAllReport:
    """Refresh Catalog, patch notes, images, and guide files under one owner.

    Catalog and patch-note fetches share the supplied session and run alongside
    the serial guide refresher. Image work starts only after Catalog succeeds or
    reports a normal same-patch skip.
    """

    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("workers must be an integer between 1 and 16")
    if type(image_workers) is not int or not 1 <= image_workers <= 16:
        raise ValueError("image_workers must be an integer between 1 and 16")
    if type(force) is not bool:
        raise ValueError("force must be a boolean")

    report_clock = _now if clock is None else clock
    started_at = _validated_now(report_clock)
    guides_client = D2PTClient() if guide_client is None else guide_client
    images_client = ValveImageClient() if image_client is None else image_client

    catalog_task = asyncio.create_task(
        _run_sync(
            refresh_catalog,
            data_root=data_root,
            session=session,
            workers=workers,
            force=force,
        ),
        name="refresh-all-catalog",
    )
    patches_task = asyncio.create_task(
        _run_sync(
            refresh_patches,
            data_root=data_root,
            session=session,
            force=force,
        ),
        name="refresh-all-patches",
    )
    guides_task = asyncio.create_task(
        _run_guides(
            data_root=data_root,
            client=guides_client,
            clock=guide_clock,
            sleep=guide_sleep,
        ),
        name="refresh-all-guides",
    )
    tasks: list[asyncio.Task[_Outcome]] = [catalog_task, patches_task, guides_task]

    try:
        catalog_outcome = await catalog_task
        catalog_result = _module_result(catalog_outcome, "catalog")

        if catalog_result.status in {"success", "skipped"}:
            images_task = asyncio.create_task(
                _run_sync(
                    refresh_images,
                    data_root=data_root,
                    workers=image_workers,
                    force=force,
                    client=images_client,
                ),
                name="refresh-all-images",
            )
            tasks.append(images_task)
            images_outcome = await images_task
            images_result = _module_result(images_outcome, "images")
        else:
            images_result = RefreshAllModuleResult(
                status="blocked",
                reason="catalog_failed",
            )

        patches_outcome, guides_outcome = await asyncio.gather(patches_task, guides_task)
        modules = {
            "catalog": catalog_result,
            "patches": _module_result(patches_outcome, "patches"),
            "images": images_result,
            "guides": _module_result(guides_outcome, "guides"),
        }
        status, exit_code = _overall_result(modules)
        return RefreshAllReport(
            status=status,
            started_at=started_at,
            finished_at=_validated_now(report_clock),
            modules=modules,
            exit_code=exit_code,
        )
    except BaseException:
        await _cancel_and_wait(tasks)
        raise


async def _run_sync(function: Callable[..., _Report], **kwargs: Any) -> _Outcome:
    try:
        report = await asyncio.to_thread(function, **kwargs)
    except Exception as exc:
        return _Outcome(reason=_failure_reason(exc))
    return _Outcome(report=report)


async def _run_guides(
    *,
    data_root: Path,
    client: D2PTClient,
    clock: Callable[[], datetime] | None,
    sleep: Callable[[float], Awaitable[None]] | None,
) -> _Outcome:
    try:
        refresher = HeroGuideRefresher(
            client,
            FileHeroGuideCache(data_root),
            clock=clock,
            sleep=sleep,
        )
        report = await refresher.refresh_all()
    except Exception as exc:
        return _Outcome(reason=_failure_reason(exc))
    return _Outcome(report=report)


def _module_result(outcome: _Outcome, module: str) -> RefreshAllModuleResult:
    if outcome.reason is not None:
        return RefreshAllModuleResult(status="failed", reason=outcome.reason)
    report = outcome.report
    if report is None:
        return RefreshAllModuleResult(status="failed", reason="operation_failed")

    if module in {"catalog", "patches"}:
        status: ModuleStatus = "skipped" if report.action == "skipped" else "success"  # type: ignore[union-attr]
    elif module == "images":
        status = "partial" if report.failures else "success"  # type: ignore[union-attr]
    else:
        status = report.status  # type: ignore[union-attr,assignment]

    serialized = asdict(report)
    if isinstance(report, HeroGuideRefreshReport):
        serialized["started_at"] = report.started_at.isoformat()
        serialized["finished_at"] = report.finished_at.isoformat()
    return RefreshAllModuleResult(status=status, report=serialized)


def _overall_result(
    modules: dict[str, RefreshAllModuleResult],
) -> tuple[OverallStatus, int]:
    statuses = [module.status for module in modules.values()]
    successful = {"success", "skipped", "partial"}
    if all(status in {"success", "skipped"} for status in statuses):
        return "success", 0
    if any(status in successful for status in statuses):
        return "partial", 4
    return "failed", 1


def _failure_reason(error: Exception) -> str:
    if isinstance(error, CatalogStoreError):
        return error.reason
    if isinstance(error, PatchRefreshError):
        return error.reason
    if isinstance(error, ImageRefreshError):
        return error.reason
    if isinstance(error, HeroGuideCacheDataError):
        return "cache_invalid_data"
    if isinstance(error, HeroGuideCacheUnavailableError):
        return "cache_unavailable"
    if isinstance(error, OSError):
        return "storage_error"
    return "operation_failed"


async def _cancel_and_wait(tasks: list[asyncio.Task[_Outcome]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()

    pending = asyncio.gather(*tasks, return_exceptions=True)
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            # Repeated cancellation cannot release the CLI locks before task cleanup.
            continue
    pending.result()


__all__ = ["RefreshAllModuleResult", "RefreshAllReport", "refresh_all"]
