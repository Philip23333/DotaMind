"""Operator commands for initializing and migrating shared application data."""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import json
import os
import signal
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, TypeVar

from redis.asyncio import from_url
from redis.exceptions import RedisError

from app.integrations.valve.catalog_repository import CATALOG_DIR
from app.integrations.valve.datafeed import ValveDatafeedClient
from app.integrations.valve.fetch_session import ValveFetchSession
from app.integrations.valve.image_client import ValveImageClient
from app.vnext.data_updates.catalog_refresh import CatalogRefreshReport, refresh_catalog
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore, CatalogStoreError
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
from app.vnext.data_updates.refresh_all import RefreshAllReport
from app.vnext.data_updates.refresh_all import refresh_all as run_refresh_all
from app.vnext.hero_guides.cache import (
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
    RedisHeroGuideCache,
)
from app.vnext.hero_guides.file_cache import (
    FileHeroGuideCache,
    GuideMigrationConflictError,
)
from app.vnext.hero_guides.migration import (
    GuideMigrationReport,
    GuideMigrationVerificationError,
    migrate_redis_guides,
)
from app.vnext.hero_guides.refresh import HeroGuideRefresher, HeroGuideRefreshReport
from app.vnext.providers.d2pt import D2PTClient

_DATA_LOCK_NAME = ".update.lock"
_BUSY_ERRNOS = {errno.EACCES, errno.EAGAIN}
_OperationResult = TypeVar("_OperationResult")


class _OutputArgumentParser(argparse.ArgumentParser):
    def __init__(
        self,
        *args: Any,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        **kwargs: Any,
    ) -> None:
        self._output_stdout = stdout
        self._output_stderr = stderr
        super().__init__(*args, **kwargs)

    def _print_message(self, message: str, file: TextIO | None = None) -> None:
        if not message or file is None:
            return
        if file is sys.stdout and self._output_stdout is not None:
            file = self._output_stdout
        elif file is sys.stderr and self._output_stderr is not None:
            file = self._output_stderr
        file.write(message)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    refresh_clock: Callable[[], datetime] | None = None,
    refresh_sleep: Callable[[float], Awaitable[None]] | None = None,
    refresh_all_clock: Callable[[], datetime] | None = None,
) -> int:
    """Run one data-update command and return its stable process exit code."""

    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    parser = _build_parser(output, error_output)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    environment = os.environ if environ is None else environ
    operation = args.command
    data_root, config_error = _resolve_data_root(args.data_dir, environment)
    if config_error is not None:
        _emit(output, _failed(operation, config_error))
        return 2
    workers: int | None = None
    if operation in {"refresh-catalog", "refresh-images", "refresh-all"}:
        try:
            workers = int(args.workers)
        except (TypeError, ValueError):
            _emit(output, _failed(operation, "invalid_workers"))
            return 2
        if not 1 <= workers <= 16:
            _emit(output, _failed(operation, "invalid_workers"))
            return 2
    image_workers: int | None = None
    if operation == "refresh-all":
        try:
            image_workers = int(args.image_workers)
        except (TypeError, ValueError):
            _emit(output, _failed(operation, "invalid_image_workers"))
            return 2
        if not 1 <= image_workers <= 16:
            _emit(output, _failed(operation, "invalid_image_workers"))
            return 2

    redis_url: str | None = None
    if operation == "migrate-guides":
        redis_url = environment.get("DOTAMIND_REDIS_URL")
        if not isinstance(redis_url, str) or not redis_url.strip():
            _emit(output, _failed(operation, "missing_redis_url"))
            return 2

    assert data_root is not None
    try:
        data_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        _emit(output, _failed(operation, "storage_error"))
        return 1

    data_lock_fd: int | None = None
    result: tuple[dict[str, Any], int] | None = None
    lock_error = False
    try:
        try:
            data_lock_fd = _try_acquire_lock(data_root / _DATA_LOCK_NAME)
        except OSError:
            result = (_failed(operation, "storage_error"), 1)
        else:
            if data_lock_fd is None:
                result = (
                    _refresh_skipped_already_running()
                    if operation == "refresh-guides"
                    else _catalog_refresh_skipped_already_running()
                    if operation == "refresh-catalog"
                    else _patch_refresh_skipped_already_running()
                    if operation == "refresh-patches"
                    else _image_refresh_skipped_already_running()
                    if operation == "refresh-images"
                    else _refresh_all_skipped_already_running()
                    if operation == "refresh-all"
                    else _skipped_already_running(),
                    3,
                )
            elif operation == "migrate-guides":
                result = _run_migration_command(
                    data_root=data_root,
                    redis_url=redis_url,
                    operation=operation,
                )
            elif operation == "refresh-guides":
                result = _run_refresh_guides_command(
                    data_root=data_root,
                    clock=refresh_clock,
                    sleep=refresh_sleep,
                )
            elif operation == "refresh-all":
                assert workers is not None and image_workers is not None
                result = _run_refresh_all_command(
                    data_root=data_root,
                    workers=workers,
                    image_workers=image_workers,
                    force=args.force,
                    guide_clock=refresh_clock,
                    guide_sleep=refresh_sleep,
                    report_clock=refresh_all_clock,
                )
            elif operation == "refresh-catalog":
                assert workers is not None
                result = _run_refresh_catalog_command(
                    data_root=data_root,
                    workers=workers,
                    force=args.force,
                )
            elif operation == "refresh-patches":
                result = _run_refresh_patches_command(
                    data_root=data_root,
                    force=args.force,
                )
            elif operation == "refresh-images":
                assert workers is not None
                result = _run_refresh_images_command(
                    data_root=data_root,
                    workers=workers,
                    force=args.force,
                )
            else:
                result = _run_init_command(
                    data_root=data_root,
                    source_dir=args.source_dir,
                )
    except (asyncio.CancelledError, KeyboardInterrupt):
        result = (
            {"status": "cancelled", "operation": operation}
            if operation in {
                "refresh-guides",
                "refresh-catalog",
                "refresh-patches",
                "refresh-images",
                "refresh-all",
            }
            else {"status": "cancelled"},
            130,
        )
    except Exception as exc:
        result = (_failed(operation, _safe_reason(exc)), 1)
    finally:
        if data_lock_fd is not None:
            try:
                _release_lock(data_lock_fd)
            except OSError:
                lock_error = True

    if result is None:
        result = (_failed(operation, "operation_failed"), 1)
    if lock_error:
        result = (_failed(operation, "storage_error"), 1)
    _emit(output, result[0])
    return result[1]


def _build_parser(stdout: TextIO, stderr: TextIO) -> argparse.ArgumentParser:
    parser = _OutputArgumentParser(
        prog="python -m app.vnext.data_updates",
        description="Initialize, migrate, and refresh persistent shared Dota data.",
        stdout=stdout,
        stderr=stderr,
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=lambda **kwargs: _OutputArgumentParser(
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        ),
    )

    init_parser = subparsers.add_parser(
        "init-catalog", help="initialize the current five-file Valve catalog"
    )
    init_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    init_parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="local catalog source directory (defaults to the bundled catalog)",
    )

    migrate_parser = subparsers.add_parser(
        "migrate-guides", help="import Redis guide partitions into file storage"
    )
    migrate_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )

    refresh_parser = subparsers.add_parser(
        "refresh-guides", help="refresh D2PT guide partitions into file storage"
    )
    refresh_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    catalog_refresh_parser = subparsers.add_parser(
        "refresh-catalog", help="refresh the persistent Valve catalog snapshot"
    )
    catalog_refresh_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    catalog_refresh_parser.add_argument(
        "--workers",
        default="8",
        help="maximum concurrent Valve Datafeed calls (1-16, default: 8)",
    )
    catalog_refresh_parser.add_argument(
        "--force",
        action="store_true",
        help="refresh even when the current snapshot has the latest patch",
    )
    patch_refresh_parser = subparsers.add_parser(
        "refresh-patches", help="refresh the latest Valve patch notes file"
    )
    patch_refresh_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    patch_refresh_parser.add_argument(
        "--force",
        action="store_true",
        help="fetch and replace the local patch notes file",
    )
    image_refresh_parser = subparsers.add_parser(
        "refresh-images", help="refresh persistent images for the current catalog"
    )
    image_refresh_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    image_refresh_parser.add_argument(
        "--workers",
        default="8",
        help="maximum concurrent image downloads (1-16, default: 8)",
    )
    image_refresh_parser.add_argument(
        "--force",
        action="store_true",
        help="download all current catalog images again",
    )
    refresh_all_parser = subparsers.add_parser(
        "refresh-all", help="refresh Catalog, patch notes, images, and guide files"
    )
    refresh_all_parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="absolute persistent data directory (or DOTAMIND_DATA_DIR)",
    )
    refresh_all_parser.add_argument(
        "--workers",
        default="8",
        help="maximum concurrent Valve Datafeed calls (1-16, default: 8)",
    )
    refresh_all_parser.add_argument(
        "--image-workers",
        default="8",
        help="maximum concurrent image downloads (1-16, default: 8)",
    )
    refresh_all_parser.add_argument(
        "--force",
        action="store_true",
        help="refresh Catalog, patch notes, and current images even when already current",
    )
    return parser


def _resolve_data_root(
    explicit_value: str | None,
    environment: Mapping[str, str],
) -> tuple[Path | None, str | None]:
    value = explicit_value
    if value is None:
        value = environment.get("DOTAMIND_DATA_DIR")
    if value is None:
        return None, "missing_data_dir"
    if not isinstance(value, str) or not value.strip():
        return None, "invalid_data_dir"
    path = Path(value)
    if not path.is_absolute():
        return None, "invalid_data_dir"
    return path, None


def _run_init_command(
    *,
    data_root: Path,
    source_dir: Path | None,
) -> tuple[dict[str, Any], int]:
    store = CatalogSnapshotStore(data_root)
    try:
        current = store.load_current()
        if current is not None:
            return (
                {
                    "status": "skipped",
                    "operation": "init-catalog",
                    "reason": "already_initialized",
                    "revision": current.revision,
                    "patch": current.repository.manifest.patch,
                },
                0,
            )
        snapshot = store.publish_from_directory(CATALOG_DIR if source_dir is None else source_dir)
    except Exception as exc:
        return _failed("init-catalog", _safe_reason(exc)), 1
    return (
        {
            "status": "success",
            "operation": "init-catalog",
            "revision": snapshot.revision,
            "patch": snapshot.repository.manifest.patch,
        },
        0,
    )


def _run_migration_command(
    *,
    data_root: Path,
    redis_url: str | None,
    operation: str,
) -> tuple[dict[str, Any], int]:
    store = CatalogSnapshotStore(data_root)
    try:
        catalog = store.load_current()
        if catalog is None:
            return _failed(operation, "catalog_missing"), 1
    except Exception as exc:
        return _failed(operation, _safe_reason(exc)), 1

    hero_ids = [hero.hero_id for hero in catalog.repository.list_heroes()]
    assert redis_url is not None
    try:
        report = asyncio.run(_run_migration(redis_url, data_root, hero_ids))
    except (asyncio.CancelledError, KeyboardInterrupt):
        return {"status": "cancelled"}, 130
    except Exception as exc:
        return _failed(operation, _safe_reason(exc)), 1
    return (
        {
            "status": "success",
            "operation": operation,
            "partitions_checked": report.partitions_checked,
            "missing": report.missing,
            "imported": report.imported,
            "already_present": report.already_present,
        },
        0,
    )


def _run_refresh_guides_command(
    *,
    data_root: Path,
    clock: Callable[[], datetime] | None,
    sleep: Callable[[float], Awaitable[None]] | None,
) -> tuple[dict[str, Any], int]:
    try:
        report = asyncio.run(_run_file_refresh(data_root, clock=clock, sleep=sleep))
    except (asyncio.CancelledError, KeyboardInterrupt):
        return {"status": "cancelled", "operation": "refresh-guides"}, 130
    except Exception as exc:
        return _failed("refresh-guides", _safe_reason(exc)), 1
    return _refresh_report_result(report)


def _run_refresh_catalog_command(
    *,
    data_root: Path,
    workers: int,
    force: bool,
) -> tuple[dict[str, Any], int]:
    try:
        report = asyncio.run(
            _run_catalog_refresh(data_root=data_root, workers=workers, force=force)
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        return {"status": "cancelled", "operation": "refresh-catalog"}, 130
    except Exception as exc:
        return _failed("refresh-catalog", _safe_reason(exc)), 1
    return _catalog_refresh_report_result(report)


def _run_refresh_patches_command(
    *,
    data_root: Path,
    force: bool,
) -> tuple[dict[str, Any], int]:
    try:
        report = asyncio.run(_run_patch_refresh(data_root=data_root, force=force))
    except (asyncio.CancelledError, KeyboardInterrupt):
        return {"status": "cancelled", "operation": "refresh-patches"}, 130
    except PatchRefreshError as exc:
        return _failed("refresh-patches", exc.reason), 1
    except Exception:
        # Remote/client failures are classified with one safe operation code.
        return _failed("refresh-patches", "operation_failed"), 1
    return _patch_refresh_report_result(report)


def _run_refresh_images_command(
    *,
    data_root: Path,
    workers: int,
    force: bool,
) -> tuple[dict[str, Any], int]:
    try:
        report = asyncio.run(
            _run_image_refresh(data_root=data_root, workers=workers, force=force)
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        return {"status": "cancelled", "operation": "refresh-images"}, 130
    except ImageRefreshError as exc:
        return _failed("refresh-images", exc.reason), 1
    except Exception as exc:
        return _failed("refresh-images", _safe_reason(exc)), 1
    return _image_refresh_report_result(report)


def _run_refresh_all_command(
    *,
    data_root: Path,
    workers: int,
    image_workers: int,
    force: bool,
    guide_clock: Callable[[], datetime] | None,
    guide_sleep: Callable[[float], Awaitable[None]] | None,
    report_clock: Callable[[], datetime] | None,
) -> tuple[dict[str, Any], int]:
    async def run() -> RefreshAllReport:
        session = ValveFetchSession(ValveDatafeedClient(), max_concurrency=workers)
        return await run_refresh_all(
            data_root=data_root,
            session=session,
            workers=workers,
            image_workers=image_workers,
            force=force,
            guide_client=D2PTClient(),
            image_client=ValveImageClient(),
            guide_clock=guide_clock,
            guide_sleep=guide_sleep,
            clock=report_clock,
        )

    try:
        report = asyncio.run(
            _run_with_cli_cleanup(run, operation_name="unified data refresh")
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        return {"status": "cancelled", "operation": "refresh-all"}, 130
    except Exception as exc:
        return _failed("refresh-all", _safe_reason(exc)), 1
    return _refresh_all_report_result(report)


async def _run_catalog_refresh(
    *,
    data_root: Path,
    workers: int,
    force: bool,
) -> CatalogRefreshReport:
    def refresh() -> CatalogRefreshReport:
        session = ValveFetchSession(ValveDatafeedClient(), max_concurrency=workers)
        return refresh_catalog(
            data_root=data_root,
            session=session,
            workers=workers,
            force=force,
        )

    async def run() -> CatalogRefreshReport:
        return await asyncio.to_thread(refresh)

    return await _run_with_cli_cleanup(run, operation_name="catalog refresh")


async def _run_patch_refresh(*, data_root: Path, force: bool) -> PatchRefreshReport:
    def refresh() -> PatchRefreshReport:
        session = ValveFetchSession(ValveDatafeedClient())
        return refresh_patches(data_root=data_root, session=session, force=force)

    async def run() -> PatchRefreshReport:
        return await asyncio.to_thread(refresh)

    return await _run_with_cli_cleanup(run, operation_name="patch refresh")


async def _run_image_refresh(
    *,
    data_root: Path,
    workers: int,
    force: bool,
) -> ImageRefreshReport:
    def refresh() -> ImageRefreshReport:
        return refresh_images(
            data_root=data_root,
            workers=workers,
            force=force,
            client=ValveImageClient(),
        )

    async def run() -> ImageRefreshReport:
        return await asyncio.to_thread(refresh)

    return await _run_with_cli_cleanup(run, operation_name="image refresh")


def _catalog_refresh_report_result(
    report: CatalogRefreshReport,
) -> tuple[dict[str, Any], int]:
    return (
        {
            "status": "success",
            "operation": "refresh-catalog",
            "report": asdict(report),
        },
        0,
    )


def _patch_refresh_report_result(
    report: PatchRefreshReport,
) -> tuple[dict[str, Any], int]:
    return (
        {
            "status": "success",
            "operation": "refresh-patches",
            "report": asdict(report),
        },
        0,
    )


def _image_refresh_report_result(
    report: ImageRefreshReport,
) -> tuple[dict[str, Any], int]:
    status = "partial" if report.failures else "success"
    return (
        {
            "status": status,
            "operation": "refresh-images",
            "report": asdict(report),
        },
        4 if report.failures else 0,
    )


def _refresh_all_report_result(
    report: RefreshAllReport,
) -> tuple[dict[str, Any], int]:
    modules: dict[str, dict[str, Any]] = {}
    for name, result in report.modules.items():
        module: dict[str, Any] = {"status": result.status}
        if result.report is not None:
            module["report"] = result.report
        if result.reason is not None:
            module["reason"] = result.reason
        modules[name] = module
    return (
        {
            "status": report.status,
            "operation": "refresh-all",
            "started_at": report.started_at.isoformat(),
            "finished_at": report.finished_at.isoformat(),
            "modules": modules,
        },
        report.exit_code,
    )


async def _run_file_refresh(
    data_root: Path,
    *,
    clock: Callable[[], datetime] | None,
    sleep: Callable[[float], Awaitable[None]] | None,
) -> HeroGuideRefreshReport:
    async def refresh() -> HeroGuideRefreshReport:
        refresher = HeroGuideRefresher(
            D2PTClient(),
            FileHeroGuideCache(data_root),
            clock=clock,
            sleep=sleep,
        )
        return await refresher.refresh_all()

    return await _run_with_cli_cleanup(refresh, operation_name="guide refresh")


def _refresh_report_result(
    report: HeroGuideRefreshReport,
) -> tuple[dict[str, Any], int]:
    code = {"success": 0, "partial": 4, "failed": 1}.get(report.status)
    if code is None:
        return _failed("refresh-guides", "operation_failed"), 1

    serialized = asdict(report)
    serialized["started_at"] = report.started_at.isoformat()
    serialized["finished_at"] = report.finished_at.isoformat()
    return (
        {
            "status": report.status,
            "operation": "refresh-guides",
            "report": serialized,
        },
        code,
    )


async def _run_migration(
    redis_url: str,
    data_root: Path,
    hero_ids: Sequence[int],
) -> GuideMigrationReport:
    redis_client: Any | None = None

    async def migrate() -> GuideMigrationReport:
        nonlocal redis_client
        redis_client = from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        source = RedisHeroGuideCache(redis_client)
        target = FileHeroGuideCache(data_root)
        return await migrate_redis_guides(
            source=source,
            target=target,
            hero_ids=hero_ids,
        )

    async def close_redis() -> None:
        if redis_client is not None:
            await redis_client.aclose()

    return await _run_with_cli_cleanup(
        migrate,
        operation_name="migration",
        after_executor_shutdown=close_redis,
    )


async def _run_with_cli_cleanup(
    operation: Callable[[], Awaitable[_OperationResult]],
    *,
    operation_name: str,
    after_executor_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> _OperationResult:
    """Run one CLI operation with signal cancellation and worker cleanup."""

    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError(f"{operation_name} CLI requires an asyncio task")

    stop_requested = False
    cleaning_up = False
    installed_signals: list[signal.Signals] = []

    def request_stop() -> None:
        nonlocal stop_requested
        if stop_requested or cleaning_up:
            return
        stop_requested = True
        task.cancel()

    try:
        for stop_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(stop_signal, request_stop)
            except (NotImplementedError, RuntimeError):
                continue
            installed_signals.append(stop_signal)
        return await operation()
    finally:
        cleaning_up = True
        try:
            await loop.shutdown_default_executor()
        finally:
            try:
                if after_executor_shutdown is not None:
                    await after_executor_shutdown()
            finally:
                for stop_signal in installed_signals:
                    loop.remove_signal_handler(stop_signal)


def _try_acquire_lock(path: str | os.PathLike[str]) -> int | None:
    """Return a non-blocking exclusive lock descriptor or ``None`` if busy."""

    descriptor = os.open(os.fspath(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in _BUSY_ERRNOS:
            return None
        raise
    return descriptor


def _release_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _safe_reason(error: Exception) -> str:
    if isinstance(error, CatalogStoreError):
        return error.reason
    if isinstance(error, PatchRefreshError):
        return error.reason
    if isinstance(error, ImageRefreshError):
        return error.reason
    if isinstance(error, GuideMigrationConflictError):
        return "migration_conflict"
    if isinstance(error, GuideMigrationVerificationError):
        return "migration_verification_failed"
    if isinstance(error, HeroGuideCacheUnavailableError):
        return "cache_unavailable"
    if isinstance(error, HeroGuideCacheDataError):
        return "cache_invalid_data"
    if isinstance(error, RedisError):
        return "redis_unavailable"
    if isinstance(error, OSError):
        return "storage_error"
    return "operation_failed"


def _failed(operation: str, reason: str) -> dict[str, str]:
    return {"status": "failed", "operation": operation, "reason": reason}


def _skipped_already_running() -> dict[str, str]:
    return {"status": "skipped", "reason": "already_running"}


def _refresh_skipped_already_running() -> dict[str, str]:
    return {
        "status": "skipped",
        "operation": "refresh-guides",
        "reason": "already_running",
    }


def _catalog_refresh_skipped_already_running() -> dict[str, str]:
    return {
        "status": "skipped",
        "operation": "refresh-catalog",
        "reason": "already_running",
    }


def _patch_refresh_skipped_already_running() -> dict[str, str]:
    return {
        "status": "skipped",
        "operation": "refresh-patches",
        "reason": "already_running",
    }


def _image_refresh_skipped_already_running() -> dict[str, str]:
    return {
        "status": "skipped",
        "operation": "refresh-images",
        "reason": "already_running",
    }


def _refresh_all_skipped_already_running() -> dict[str, str]:
    return {
        "status": "skipped",
        "operation": "refresh-all",
        "reason": "already_running",
    }


def _emit(stream: TextIO, payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=stream)


__all__ = ["main"]
