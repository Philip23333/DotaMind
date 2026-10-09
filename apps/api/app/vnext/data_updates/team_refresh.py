"""Refresh the persistent Team display directory and best-effort local images."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from app.vnext.data_updates.image_assets import (
    ImageAssetError,
    content_asset_is_valid,
    store_content_addressed_png,
)
from app.vnext.data_updates.team_directory_store import (
    TeamDirectoryStore,
    TeamDirectoryStoreError,
    TeamDisplayRecord,
)
from app.vnext.providers.pandascore.team_directory import (
    PandaScoreTeamMetadata,
    validate_team_metadata,
)
from app.vnext.providers.pandascore.team_image_client import TeamImageError

_MIGRATION_COMMIT = "180058efcb897b9aaceb1433bde6754bfeb9680f"
_MIGRATION_NAME = "team_display_migration.json"
_LEGACY_IMAGE_PATH = re.compile(
    r"/api/v1/assets/esports/teams/([1-9][0-9]*)[.]png\Z",
    re.ASCII,
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class TeamMetadataReader(Protocol):
    async def read_all(self) -> list[PandaScoreTeamMetadata]: ...


class TeamImageFetcher(Protocol):
    def fetch_png(self, url: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class TeamRefreshFailure:
    source_id: int
    error_code: str


@dataclass(frozen=True, slots=True)
class TeamRefreshReport:
    observed_team_count: int
    retained_old_records: int
    migrated_records: int
    downloaded: int
    skipped: int
    no_url: int
    failures: tuple[TeamRefreshFailure, ...]

    @property
    def status(self) -> str:
        return "partial" if self.failures else "success"


async def refresh_team_directory(
    *,
    data_root: Path,
    metadata_reader: TeamMetadataReader,
    image_client: TeamImageFetcher,
    image_workers: int = 8,
    clock: Callable[[], datetime] | None = None,
    migration_manifest_path: Path | None = None,
    legacy_images_directory: Path | None = None,
) -> TeamRefreshReport:
    """Read all source metadata, refresh eligible images, then atomically publish."""

    if type(image_workers) is not int or not 1 <= image_workers <= 16:
        raise ValueError("image_workers must be a strict integer from 1 through 16")
    read_clock = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    now = _read_now(read_clock)
    month = now.astimezone(_SHANGHAI).strftime("%Y-%m")

    store = TeamDirectoryStore(Path(data_root))
    previous = store.read_for_update()
    migrated_records = 0
    if previous is None:
        migration_path = (
            Path(migration_manifest_path)
            if migration_manifest_path is not None
            else (
                Path(__file__).resolve().parents[2]
                / "data"
                / "esports"
                / "teams"
                / _MIGRATION_NAME
            )
        )
        legacy_directory = (
            Path(legacy_images_directory)
            if legacy_images_directory is not None
            else migration_path.parent
        )
        imported = _import_historical_teams(
            migration_path=migration_path,
            legacy_images_directory=legacy_directory,
            assets_directory=store.assets_directory,
        )
        previous = store.publish(imported)
        migrated_records = len(imported)

    source_result = await metadata_reader.read_all()
    teams = validate_team_metadata(source_result)

    old_records = previous.teams
    retained_ids = set(old_records) - {team.source_id for team in teams}
    merged: dict[int, TeamDisplayRecord] = dict(old_records)
    observed: list[PandaScoreTeamMetadata] = []
    candidates: list[PandaScoreTeamMetadata] = []
    skipped = 0
    no_url = 0

    for team in teams:
        previous_record = old_records.get(team.source_id)
        current_record = (
            TeamDisplayRecord(source_id=team.source_id, label=team.label)
            if previous_record is None
            else replace(previous_record, label=team.label)
        )
        current_record = replace(
            current_record,
            observed_image_url=team.image_url,
        )
        merged[team.source_id] = current_record
        observed.append(team)

        if team.image_url is None:
            no_url += 1
            continue
        should_download = (
            current_record.downloaded_image_url is None
            or current_record.downloaded_image_url != team.image_url
            or current_record.image_asset is None
            or not _asset_valid(store.assets_directory, current_record.image_asset)
            or current_record.monthly_refresh_completed != month
        )
        if should_download:
            candidates.append(team)
        else:
            skipped += 1

    outcomes = await _download_images(
        candidates,
        image_client=image_client,
        workers=image_workers,
    )
    downloaded = 0
    failures: list[TeamRefreshFailure] = []
    for team, outcome in outcomes:
        current_record = merged[team.source_id]
        if isinstance(outcome, BaseException):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            error_code = (
                outcome.reason
                if isinstance(outcome, TeamImageError)
                else "download_failed"
            )
            failures.append(TeamRefreshFailure(team.source_id, error_code))
            continue
        if not isinstance(outcome, bytes):
            failures.append(TeamRefreshFailure(team.source_id, "invalid_image"))
            continue
        try:
            content_hash = store_content_addressed_png(
                store.assets_directory,
                outcome,
            )
        except ImageAssetError as exc:
            if exc.reason == "invalid_image":
                failures.append(TeamRefreshFailure(team.source_id, "invalid_image"))
                continue
            raise TeamDirectoryStoreError("storage_error") from None
        completed_at = _read_now(read_clock)
        merged[team.source_id] = replace(
            current_record,
            downloaded_image_url=team.image_url,
            image_asset=content_hash,
            image_downloaded_at=_utc_timestamp(completed_at),
            monthly_refresh_completed=month,
        )
        downloaded += 1

    store.publish(merged)
    return TeamRefreshReport(
        observed_team_count=len(observed),
        retained_old_records=len(retained_ids),
        migrated_records=migrated_records,
        downloaded=downloaded,
        skipped=skipped,
        no_url=no_url,
        failures=tuple(failures),
    )


async def _download_images(
    teams: tuple[PandaScoreTeamMetadata, ...],
    *,
    image_client: TeamImageFetcher,
    workers: int,
) -> list[tuple[PandaScoreTeamMetadata, object]]:
    if not teams:
        return []
    semaphore = asyncio.Semaphore(workers)

    async def download(team: PandaScoreTeamMetadata) -> tuple[PandaScoreTeamMetadata, object]:
        assert team.image_url is not None
        async with semaphore:
            try:
                payload = await asyncio.to_thread(image_client.fetch_png, team.image_url)
            except Exception as exc:
                return team, exc
            return team, payload

    return list(await asyncio.gather(*(download(team) for team in teams)))


def _import_historical_teams(
    *,
    migration_path: Path,
    legacy_images_directory: Path,
    assets_directory: Path,
) -> dict[int, TeamDisplayRecord]:
    try:
        raw = migration_path.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object_pairs,
        )
    except FileNotFoundError:
        return {}
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        raise TeamDirectoryStoreError("invalid_snapshot") from None
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or payload.get("source_commit") != _MIGRATION_COMMIT
        or not isinstance(payload.get("teams"), list)
    ):
        raise TeamDirectoryStoreError("invalid_snapshot")

    result: dict[int, TeamDisplayRecord] = {}
    for row in payload["teams"]:
        if not isinstance(row, dict):
            raise TeamDirectoryStoreError("invalid_snapshot")
        source_id = row.get("source_id")
        label = row.get("label")
        source_url = row.get("source_url")
        image_path = row.get("legacy_image_path")
        match = _LEGACY_IMAGE_PATH.fullmatch(image_path) if isinstance(image_path, str) else None
        if (
            type(source_id) is not int
            or source_id <= 0
            or source_id in result
            or not isinstance(label, str)
            or not label.strip()
            or not isinstance(source_url, str)
            or not source_url.strip()
            or match is None
            or int(match.group(1)) != source_id
        ):
            raise TeamDirectoryStoreError("invalid_snapshot")

        image_file = legacy_images_directory / f"{source_id}.png"
        image_asset: str | None = None
        downloaded_url: str | None = None
        try:
            image_bytes = image_file.read_bytes()
        except FileNotFoundError:
            image_bytes = b""
        except OSError:
            raise TeamDirectoryStoreError("storage_error") from None
        if image_bytes:
            try:
                image_asset = store_content_addressed_png(
                    assets_directory,
                    image_bytes,
                )
            except ImageAssetError as exc:
                if exc.reason != "invalid_image":
                    raise TeamDirectoryStoreError("storage_error") from None
            else:
                downloaded_url = source_url

        result[source_id] = TeamDisplayRecord(
            source_id=source_id,
            label=label.strip(),
            observed_image_url=source_url,
            downloaded_image_url=downloaded_url,
            image_asset=image_asset,
            image_downloaded_at=None,
            monthly_refresh_completed=None,
        )
    return result


def _asset_valid(assets_directory: Path, content_hash: str) -> bool:
    try:
        return content_asset_is_valid(assets_directory, content_hash)
    except ImageAssetError:
        raise TeamDirectoryStoreError("storage_error") from None


def _read_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("team migration contains a duplicate key")
        result[key] = value
    return result


def _reject_json_constant(_constant: str) -> None:
    raise ValueError("team migration contains a non-finite number")


__all__ = [
    "TeamRefreshFailure",
    "TeamRefreshReport",
    "refresh_team_directory",
]
