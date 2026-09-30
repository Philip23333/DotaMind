"""Persistent, atomic publication of complete Valve catalog snapshots."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

from pydantic import ValidationError

from app.integrations.valve.catalog import (
    AbilityCatalogRecord,
    CatalogBundle,
    CatalogManifest,
    CatalogSyncAudit,
    CatalogValidationError,
    HeroCatalogRecord,
    ItemCatalogRecord,
    RecipeEdge,
    validate_catalog,
    validate_sync_audit,
)
from app.integrations.valve.catalog_repository import (
    CatalogSnapshotError,
    DotaCatalogRepository,
)

_CATALOG_FILES = (
    "manifest.json",
    "dota2_heroes.json",
    "dota2_abilities.json",
    "dota2_items.json",
    "sync_audit.json",
)
_REVISION_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
CatalogStoreErrorReason = Literal["invalid_pointer", "invalid_snapshot", "storage_error"]


class CatalogStoreError(RuntimeError):
    """A safe, stable error raised while reading or publishing catalog files."""

    def __init__(self, reason: CatalogStoreErrorReason) -> None:
        messages = {
            "invalid_pointer": "catalog snapshot pointer is invalid",
            "invalid_snapshot": "catalog snapshot is invalid",
            "storage_error": "catalog snapshot storage operation failed",
        }
        if reason not in messages:
            raise ValueError("unsupported catalog store error reason")
        self.reason = reason
        super().__init__(messages[reason])


@dataclass(frozen=True)
class CatalogSnapshot:
    revision: str
    directory: Path
    repository: DotaCatalogRepository


class CatalogSnapshotStore:
    """Store immutable catalog revisions behind one atomically replaced pointer."""

    def __init__(self, data_root: Path) -> None:
        self._catalog_directory = Path(data_root) / "catalog"
        self._snapshots_directory = self._catalog_directory / "snapshots"
        self._current_pointer = self._catalog_directory / "current.json"

    def publish_from_directory(self, source_dir: Path) -> CatalogSnapshot:
        """Copy, validate, and publish the five catalog files as one revision."""

        source_directory = Path(source_dir)
        try:
            self._snapshots_directory.mkdir(parents=True, exist_ok=True)
            working_directory = Path(
                tempfile.mkdtemp(prefix=".catalog-", dir=self._snapshots_directory)
            )
        except OSError as exc:
            raise CatalogStoreError("storage_error") from exc

        temporary_directory: Path | None = working_directory
        pointer_temporary_path: Path | None = None
        try:
            for filename in _CATALOG_FILES:
                try:
                    shutil.copyfile(
                        source_directory / filename,
                        working_directory / filename,
                    )
                except FileNotFoundError:
                    raise CatalogStoreError("invalid_snapshot") from None
                except OSError as exc:
                    raise CatalogStoreError("storage_error") from exc

            self._validate_snapshot_directory(working_directory)
            try:
                repository = DotaCatalogRepository(working_directory)
            except CatalogSnapshotError as exc:
                self._raise_repository_error(exc)
            except OSError as exc:
                raise CatalogStoreError("storage_error") from exc

            revision, final_directory = self._new_revision_directory()
            try:
                os.rename(working_directory, final_directory)
            except OSError as exc:
                raise CatalogStoreError("storage_error") from exc
            temporary_directory = None

            # The repository has already loaded the validated files into memory.
            # Keep its provenance path aligned with the now-published directory.
            try:
                repository.snapshot_dir = final_directory.resolve(strict=True)
            except OSError as exc:
                raise CatalogStoreError("storage_error") from exc
            snapshot = CatalogSnapshot(
                revision=revision,
                directory=final_directory,
                repository=repository,
            )

            pointer_temporary_path = self._write_temporary_pointer(revision)
            try:
                os.replace(pointer_temporary_path, self._current_pointer)
            except OSError as exc:
                raise CatalogStoreError("storage_error") from exc
            pointer_temporary_path = None
            return snapshot
        finally:
            if temporary_directory is not None:
                with suppress(OSError):
                    shutil.rmtree(temporary_directory)
            if pointer_temporary_path is not None:
                with suppress(OSError):
                    pointer_temporary_path.unlink()

    def load_current(self) -> CatalogSnapshot | None:
        """Load and validate the single revision selected by ``current.json``."""

        try:
            pointer_bytes = self._current_pointer.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CatalogStoreError("storage_error") from exc

        revision = self._parse_pointer(pointer_bytes)
        directory = self._snapshots_directory / revision
        try:
            resolved_snapshots = self._snapshots_directory.resolve(strict=True)
            resolved_directory = directory.resolve(strict=True)
            directory_mode = resolved_directory.stat().st_mode
        except FileNotFoundError:
            raise CatalogStoreError("invalid_snapshot") from None
        except OSError as exc:
            raise CatalogStoreError("storage_error") from exc
        if (
            resolved_directory.parent != resolved_snapshots
            or not stat.S_ISDIR(directory_mode)
        ):
            raise CatalogStoreError("invalid_snapshot")

        self._validate_snapshot_directory(directory)
        try:
            repository = DotaCatalogRepository(directory)
        except CatalogSnapshotError as exc:
            self._raise_repository_error(exc)
        except OSError as exc:
            raise CatalogStoreError("storage_error") from exc
        return CatalogSnapshot(
            revision=revision,
            directory=directory,
            repository=repository,
        )

    def _new_revision_directory(self) -> tuple[str, Path]:
        while True:
            revision = uuid.uuid4().hex
            final_directory = self._snapshots_directory / revision
            if not final_directory.exists():
                return revision, final_directory

    @staticmethod
    def _raise_repository_error(error: CatalogSnapshotError) -> NoReturn:
        if isinstance(error.__cause__, OSError):
            raise CatalogStoreError("storage_error") from error.__cause__
        raise CatalogStoreError("invalid_snapshot") from None

    def _write_temporary_pointer(self, revision: str) -> Path:
        payload = json.dumps(
            {"schema_version": 1, "revision": revision}, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        descriptor: int | None = None
        path: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".current-", suffix=".tmp", dir=self._catalog_directory
            )
            path = Path(raw_path)
            pointer_file = os.fdopen(descriptor, "wb")
            descriptor = None
            with pointer_file:
                pointer_file.write(payload)
            return path
        except OSError as exc:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            if path is not None:
                with suppress(OSError):
                    path.unlink()
            raise CatalogStoreError("storage_error") from exc

    @staticmethod
    def _parse_pointer(pointer_bytes: bytes) -> str:
        try:
            pointer = json.loads(pointer_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CatalogStoreError("invalid_pointer") from None
        if (
            not isinstance(pointer, dict)
            or set(pointer) != {"schema_version", "revision"}
            or type(pointer.get("schema_version")) is not int
            or pointer["schema_version"] != 1
        ):
            raise CatalogStoreError("invalid_pointer")
        revision = pointer.get("revision")
        if not isinstance(revision, str) or _REVISION_PATTERN.fullmatch(revision) is None:
            raise CatalogStoreError("invalid_pointer")
        return revision

    @staticmethod
    def _validate_snapshot_directory(directory: Path) -> CatalogBundle:
        payloads: dict[str, object] = {}
        for filename in _CATALOG_FILES:
            path = directory / filename
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                raise CatalogStoreError("invalid_snapshot") from None
            except OSError as exc:
                raise CatalogStoreError("storage_error") from exc
            try:
                payloads[filename] = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise CatalogStoreError("invalid_snapshot") from None

        try:
            item_payload = payloads["dota2_items.json"]
            if isinstance(item_payload, list):
                item_records = item_payload
                recipe_payload = []
            elif isinstance(item_payload, dict):
                item_records = item_payload.get("items")
                recipe_payload = item_payload.get("recipes", [])
            else:
                raise ValueError("invalid item catalog payload")
            if not isinstance(item_records, list) or not isinstance(recipe_payload, list):
                raise ValueError("invalid item catalog collections")

            bundle = CatalogBundle(
                manifest=CatalogManifest.model_validate(payloads["manifest.json"]),
                heroes=[
                    HeroCatalogRecord.model_validate(record)
                    for record in payloads["dota2_heroes.json"]
                ],
                abilities=[
                    AbilityCatalogRecord.model_validate(record)
                    for record in payloads["dota2_abilities.json"]
                ],
                items=[ItemCatalogRecord.model_validate(record) for record in item_records],
                recipes=[RecipeEdge.model_validate(record) for record in recipe_payload],
                sync_audit=CatalogSyncAudit.model_validate(payloads["sync_audit.json"]),
            )
            if bundle.sync_audit is None:
                raise ValueError("catalog sync audit is required")
            validate_catalog(bundle.manifest, bundle.heroes, bundle.abilities, bundle.items)
            validate_sync_audit(
                bundle.manifest,
                bundle.sync_audit,
                bundle.heroes,
                bundle.abilities,
                bundle.items,
            )
        except (CatalogValidationError, ValidationError, TypeError, ValueError):
            raise CatalogStoreError("invalid_snapshot") from None
        return bundle
