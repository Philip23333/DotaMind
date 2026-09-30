"""File-backed whole-snapshot storage for Pub and Pro hero guide partitions."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic_core import PydanticSerializationError

from .cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
    _revalidate_snapshot,
    _validate_aware_datetime,
    _validate_error_code,
    _validate_guide_cache_entry,
    _validate_partition_identity,
)

SampleType = Literal["pub", "pro"]
_FILE_SCHEMA_VERSION = 1


class GuideMigrationConflictError(RuntimeError):
    """An existing guide partition differs from the entry being imported."""

    def __init__(self) -> None:
        super().__init__("hero guide migration target conflicts with source entry")


class FileHeroGuideCache:
    """Persist each complete guide partition as one atomically replaced file."""

    def __init__(self, data_root: Path) -> None:
        self._guides_directory = Path(data_root) / "guides"

    async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
        _validate_partition_identity("pub", hero_id, position)
        entry = await asyncio.to_thread(self._read_entry_sync, "pub", hero_id, position)
        return GuideCacheEntry() if entry is None else entry

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
        _validate_partition_identity("pro", hero_id, None)
        entry = await asyncio.to_thread(self._read_entry_sync, "pro", hero_id, None)
        return GuideCacheEntry() if entry is None else entry

    async def publish(
        self,
        snapshot: GuideCacheSnapshot,
        *,
        attempted_at: datetime,
    ) -> None:
        checked_snapshot = _revalidate_snapshot(snapshot)
        _validate_aware_datetime(attempted_at, "attempted_at")
        entry = _validate_guide_cache_entry(
            GuideCacheEntry(
                snapshot=checked_snapshot,
                last_attempt_at=attempted_at,
                last_error=None,
            ),
            sample_type=checked_snapshot.sample_type,
            hero_id=checked_snapshot.hero_id,
            position=checked_snapshot.position,
        )
        await asyncio.to_thread(
            self._write_entry_sync,
            checked_snapshot.sample_type,
            checked_snapshot.hero_id,
            checked_snapshot.position,
            entry,
        )

    async def record_failure(
        self,
        *,
        sample_type: SampleType,
        hero_id: int,
        position: int | None = None,
        attempted_at: datetime,
        error_code: str,
    ) -> None:
        _validate_partition_identity(sample_type, hero_id, position)
        _validate_aware_datetime(attempted_at, "attempted_at")
        _validate_error_code(error_code)
        await asyncio.to_thread(
            self._record_failure_sync,
            sample_type,
            hero_id,
            position,
            attempted_at,
            error_code,
        )

    async def import_entry(
        self,
        *,
        sample_type: SampleType,
        hero_id: int,
        position: int | None = None,
        entry: GuideCacheEntry,
    ) -> bool:
        _validate_partition_identity(sample_type, hero_id, position)
        checked_entry = _validate_guide_cache_entry(
            entry,
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
        )
        return await asyncio.to_thread(
            self._import_entry_sync,
            sample_type,
            hero_id,
            position,
            checked_entry,
        )

    def _record_failure_sync(
        self,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
        attempted_at: datetime,
        error_code: str,
    ) -> None:
        existing = self._read_entry_sync(sample_type, hero_id, position)
        old_entry = GuideCacheEntry() if existing is None else existing
        updated = _validate_guide_cache_entry(
            GuideCacheEntry(
                snapshot=old_entry.snapshot,
                last_attempt_at=attempted_at,
                last_error=error_code,
            ),
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
        )
        self._write_entry_sync(sample_type, hero_id, position, updated)

    def _import_entry_sync(
        self,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
        entry: GuideCacheEntry,
    ) -> bool:
        existing = self._read_entry_sync(sample_type, hero_id, position)
        if entry == GuideCacheEntry():
            if existing is None or existing == entry:
                return False
            raise GuideMigrationConflictError()
        if existing is not None:
            if existing == entry:
                return False
            raise GuideMigrationConflictError()
        self._write_entry_sync(sample_type, hero_id, position, entry)
        return True

    def _read_entry_sync(
        self,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
    ) -> GuideCacheEntry | None:
        path = self._partition_path(sample_type, hero_id, position)
        try:
            serialized = path.read_bytes()
        except FileNotFoundError:
            return None
        except (IsADirectoryError, NotADirectoryError):
            raise HeroGuideCacheDataError() from None
        except OSError:
            raise HeroGuideCacheUnavailableError() from None
        return self._decode_entry(
            serialized,
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
        )

    def _write_entry_sync(
        self,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
        entry: GuideCacheEntry,
    ) -> None:
        checked_entry = _validate_guide_cache_entry(
            entry,
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
        )
        serialized = self._serialize_entry(
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
            entry=checked_entry,
        )
        path = self._partition_path(sample_type, hero_id, position)
        temporary_path: Path | None = None
        descriptor: int | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(raw_path)
            temporary_file = os.fdopen(descriptor, "wb")
            descriptor = None
            with temporary_file:
                temporary_file.write(serialized)
            os.replace(temporary_path, path)
            temporary_path = None
        except OSError:
            raise HeroGuideCacheUnavailableError() from None
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()

    def _partition_path(
        self,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
    ) -> Path:
        if sample_type == "pub":
            assert position is not None
            return self._guides_directory / "pub" / str(hero_id) / f"{position}.json"
        return self._guides_directory / "pro" / f"{hero_id}.json"

    @staticmethod
    def _serialize_entry(
        *,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
        entry: GuideCacheEntry,
    ) -> bytes:
        try:
            payload = {
                "schema_version": _FILE_SCHEMA_VERSION,
                "sample_type": sample_type,
                "hero_id": hero_id,
                "position": position,
                "entry": entry.model_dump(mode="json"),
            }
            return json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
        except (PydanticSerializationError, TypeError, ValueError):
            raise HeroGuideCacheDataError() from None

    @staticmethod
    def _decode_entry(
        serialized: bytes,
        *,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
    ) -> GuideCacheEntry:
        try:
            payload = json.loads(serialized.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HeroGuideCacheDataError() from None
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {"schema_version", "sample_type", "hero_id", "position", "entry"}
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != _FILE_SCHEMA_VERSION
            or type(payload.get("sample_type")) is not str
            or payload["sample_type"] != sample_type
            or type(payload.get("hero_id")) is not int
            or payload["hero_id"] != hero_id
        ):
            raise HeroGuideCacheDataError()

        stored_position = payload.get("position")
        if position is None:
            if stored_position is not None:
                raise HeroGuideCacheDataError()
        elif type(stored_position) is not int or stored_position != position:
            raise HeroGuideCacheDataError()

        try:
            encoded_entry = json.dumps(
                payload["entry"],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            entry = GuideCacheEntry.model_validate_json(encoded_entry)
        except (PydanticSerializationError, TypeError, ValueError):
            raise HeroGuideCacheDataError() from None
        return _validate_guide_cache_entry(
            entry,
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
        )


__all__ = ["FileHeroGuideCache", "GuideMigrationConflictError"]
