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
from app.vnext.data_updates.team_directory_store import TeamDirectoryStoreError
from app.vnext.data_updates.team_refresh import (
    TeamImageFetcher,
    TeamMetadataReader,
    TeamRefreshReport,
    refresh_team_directory,
)
from app.vnext.hero_guides.cache import HeroGuideCacheDataError, HeroGuideCacheUnavailableError
from app.vnext.hero_guides.file_cache import FileHeroGuideCache
from app.vnext.hero_guides.refresh import HeroGuideRefresher, HeroGuideRefreshReport
from app.vnext.providers.d2pt import D2PTClient
from app.vnext.providers.pandascore.client import (
    PandaScoreConfigurationError,
    PandaScoreProtocolError,
)
from app.vnext.providers.pandascore.team_directory import PandaScoreTeamDirectoryError

ModuleStatus = Literal["success", "skipped", "partial", "failed", "blocked"]
OverallStatus = Literal["success", "partial", "failed"]
_Report = (
    CatalogRefreshReport
    | PatchRefreshReport
    | ImageRefreshReport
    | HeroGuideRefreshReport
    | TeamRefreshReport
)


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
    team_metadata_reader: TeamMetadataReader,
    team_image_client: TeamImageFetcher,
    guide_clock: Callable[[], datetime] | None = None,
    guide_sleep: Callable[[float], Awaitable[None]] | None = None,
    team_clock: Callable[[], datetime] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RefreshAllReport:
    """Refresh shared data under one owner with serial image-source phases.

    Catalog and patch-note fetches share the supplied session and run alongside
    the serial guide refresher. Valve images wait for Catalog success or a normal
    skip; Team images start only after the Valve image phase has finished.
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

        teams_task = asyncio.create_task(
            _run_team_refresh(
                data_root=data_root,
                metadata_reader=team_metadata_reader,
                image_client=team_image_client,
                image_workers=image_workers,
                clock=team_clock,
            ),
            name="refresh-all-teams",
        )
        tasks.append(teams_task)
        teams_outcome = await teams_task

        patches_outcome, guides_outcome = await asyncio.gather(patches_task, guides_task)
        modules = {
            "catalog": catalog_result,
            "patches": _module_result(patches_outcome, "patches"),
            "images": images_result,
            "guides": _module_result(guides_outcome, "guides"),
            "teams": _module_result(teams_outcome, "teams"),
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


async def _run_team_refresh(
    *,
    data_root: Path,
    metadata_reader: TeamMetadataReader,
    image_client: TeamImageFetcher,
    image_workers: int,
    clock: Callable[[], datetime] | None,
) -> _Outcome:
    try:
        report = await refresh_team_directory(
            data_root=data_root,
            metadata_reader=metadata_reader,
            image_client=image_client,
            image_workers=image_workers,
            clock=clock,
        )
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
    if isinstance(error, TeamDirectoryStoreError):
        return error.reason
    if isinstance(error, PandaScoreConfigurationError):
        return "pandascore_configuration_error"
    if isinstance(error, PandaScoreProtocolError):
        return "pandascore_protocol_error"
    if isinstance(error, PandaScoreTeamDirectoryError):
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
