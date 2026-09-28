"""Operator CLI for the cache-only hero-guide data refresh."""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import json
import os
import signal
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from redis.asyncio import from_url
from redis.exceptions import RedisError

from app.vnext.hero_guides.cache import (
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
    RedisHeroGuideCache,
)
from app.vnext.hero_guides.refresh import HeroGuideRefresher, HeroGuideRefreshReport
from app.vnext.providers.d2pt import D2PTClient

_LOCK_PATH = Path("/tmp/dotamind-hero-guide-refresh.lock")
_BUSY_ERRNOS = {errno.EACCES, errno.EAGAIN}


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    lock_path: str | os.PathLike[str] = _LOCK_PATH,
    stdout: TextIO | None = None,
) -> int:
    """Parse and execute the sole refresh command, returning its exit status."""

    output = sys.stdout if stdout is None else stdout
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(file=output)
        return 2

    environment = os.environ if environ is None else environ
    redis_url = environment.get("DOTAMIND_REDIS_URL")
    if not isinstance(redis_url, str) or not redis_url.strip():
        _emit(output, {"status": "failed", "reason": "missing_redis_url"})
        return 2

    try:
        lock_fd = _try_acquire_lock(lock_path)
    except OSError:
        _emit(output, {"status": "failed", "reason": "lock_unavailable"})
        return 1
    if lock_fd is None:
        _emit(output, {"status": "skipped", "reason": "already_running"})
        return 3

    result: tuple[dict[str, Any], int]
    try:
        try:
            report = asyncio.run(_run_refresh(redis_url))
            result = _report_result(report)
        except (asyncio.CancelledError, KeyboardInterrupt):
            result = ({"status": "cancelled"}, 130)
        except HeroGuideCacheUnavailableError:
            result = ({"status": "failed", "reason": "cache_unavailable"}, 1)
        except HeroGuideCacheDataError:
            result = ({"status": "failed", "reason": "cache_invalid_data"}, 1)
        except RedisError:
            result = ({"status": "failed", "reason": "redis_unavailable"}, 1)
        except Exception:
            result = ({"status": "failed", "reason": "refresh_failed"}, 1)
    finally:
        try:
            _release_lock(lock_fd)
        except OSError:
            result = ({"status": "failed", "reason": "lock_unavailable"}, 1)

    _emit(output, result[0])
    return result[1]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.vnext.hero_guides",
        description="Refresh the shared D2PT hero-guide cache.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("refresh", help="refresh all cached hero guides")
    return parser


def _try_acquire_lock(path: str | os.PathLike[str]) -> int | None:
    """Return a locked descriptor, or None only when another process holds it."""

    fd = os.open(os.fspath(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in _BUSY_ERRNOS:
            return None
        raise
    return fd


def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


async def _run_refresh(redis_url: str) -> HeroGuideRefreshReport:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("refresh CLI requires an asyncio task")

    stop_requested = False
    cleaning_up = False
    installed_signals: list[signal.Signals] = []
    redis_client: Any | None = None

    def request_stop() -> None:
        nonlocal stop_requested
        if stop_requested or cleaning_up:
            return
        stop_requested = True
        task.cancel()

    try:
        for stop_signal in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(stop_signal, request_stop)
            installed_signals.append(stop_signal)

        redis_client = from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        cache = RedisHeroGuideCache(redis_client)
        client = D2PTClient()
        refresher = HeroGuideRefresher(client, cache)
        return await refresher.refresh_all()
    finally:
        cleaning_up = True
        try:
            await loop.shutdown_default_executor()
        finally:
            try:
                if redis_client is not None:
                    await redis_client.aclose()
            finally:
                for stop_signal in installed_signals:
                    loop.remove_signal_handler(stop_signal)


def _report_result(report: HeroGuideRefreshReport) -> tuple[dict[str, Any], int]:
    serialized = asdict(report)
    serialized["started_at"] = _isoformat(report.started_at)
    serialized["finished_at"] = _isoformat(report.finished_at)
    status_codes = {"success": 0, "partial": 4, "failed": 1}
    status = report.status
    if status not in status_codes:
        raise ValueError("refresh report has an unknown status")
    return {"status": status, "report": serialized}, status_codes[status]


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("refresh report timestamps must include a timezone")
    return value.isoformat()


def _emit(stream: TextIO, payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=stream)


__all__ = ["main"]
