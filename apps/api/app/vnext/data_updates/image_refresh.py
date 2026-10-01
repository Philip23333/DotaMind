"""Refresh catalog-selected Valve images into content-addressed storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.integrations.valve import game_data_sync
from app.integrations.valve.catalog_repository import CatalogSnapshotError
from app.integrations.valve.image_client import (
    MAX_IMAGE_BYTES,
    PNG_SIGNATURE,
    ImageKind,
    ValveImageClient,
    ValveImageError,
)
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore, CatalogStoreError

ImageRefreshErrorReason = Literal["catalog_missing", "invalid_manifest", "storage_error"]
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MANIFEST_NAME = "manifest.json"


class ImageRefreshError(RuntimeError):
    """A safe, stable error raised by the persistent image store."""

    def __init__(self, reason: ImageRefreshErrorReason) -> None:
        messages = {
            "catalog_missing": "no published catalog snapshot is available",
            "invalid_manifest": "image resource manifest is invalid",
            "storage_error": "image resource storage operation failed",
        }
        self.reason = reason
        super().__init__(messages[reason])


@dataclass(frozen=True)
class ImageRefreshFailure:
    kind: ImageKind
    entity_id: int
    error_code: str


@dataclass(frozen=True)
class ImageRefreshReport:
    catalog_revision: str
    catalog_patch: str
    target_count: int
    downloaded: int
    skipped: int
    failures: tuple[ImageRefreshFailure, ...]


def refresh_images(
    *,
    data_root: Path,
    workers: int = 8,
    force: bool = False,
    client: ValveImageClient | None = None,
) -> ImageRefreshReport:
    """Refresh images for one immutable, currently published catalog snapshot."""

    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("workers must be a strict integer from 1 through 16")
    if type(force) is not bool:
        raise ValueError("force must be a boolean")

    store = CatalogSnapshotStore(Path(data_root))
    try:
        snapshot = store.load_current()
    except CatalogStoreError:
        raise
    except CatalogSnapshotError:
        raise
    if snapshot is None:
        raise ImageRefreshError("catalog_missing")

    repository = snapshot.repository
    try:
        targets = game_data_sync._catalog_image_targets(
            heroes=repository.list_heroes(),
            items=repository.list_items(),
            abilities=repository.list_abilities(),
        )
    except Exception:
        raise CatalogStoreError("invalid_snapshot") from None

    images_directory = Path(data_root) / "images"
    assets_directory = images_directory / "assets"
    manifest_path = images_directory / _MANIFEST_NAME
    existing_manifest, existing_bytes = _read_manifest(manifest_path)
    entries: dict[str, dict[str, Any]] = {
        key: dict(value) for key, value in existing_manifest.items()
    }

    to_download: list[game_data_sync.CatalogImageTarget] = []
    skipped = 0
    for target in targets:
        key = _entry_key(target.kind, target.entity_id)
        entry = entries.get(key)
        if (
            not force
            and entry is not None
            and entry["internal_name"] == target.internal_name
            and entry["source_patch"] == repository.manifest.patch
            and _asset_is_valid(assets_directory, entry["content_sha256"])
        ):
            skipped += 1
            continue
        to_download.append(target)

    active_client = ValveImageClient() if client is None else client
    failures_by_key: dict[str, str] = {}
    downloaded = 0
    if to_download:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    active_client.fetch_png,
                    target.kind,
                    target.internal_name,
                ): target
                for target in to_download
            }
            for future in as_completed(futures):
                target = futures[future]
                key = _entry_key(target.kind, target.entity_id)
                try:
                    payload = future.result()
                except ValveImageError as exc:
                    failures_by_key[key] = exc.reason
                    continue
                except Exception:
                    failures_by_key[key] = "download_failed"
                    continue

                if not _is_png_payload(payload):
                    failures_by_key[key] = "invalid_image"
                    continue
                content_hash = hashlib.sha256(payload).hexdigest()
                _store_asset(assets_directory, content_hash, payload)
                entries[key] = {
                    "kind": target.kind,
                    "entity_id": target.entity_id,
                    "internal_name": target.internal_name,
                    "content_sha256": content_hash,
                    "source_patch": repository.manifest.patch,
                }
                downloaded += 1

    failures = tuple(
        ImageRefreshFailure(target.kind, target.entity_id, failures_by_key[key])
        for target in targets
        if (key := _entry_key(target.kind, target.entity_id)) in failures_by_key
    )
    new_manifest = {
        "schema_version": 1,
        "entries": {key: entries[key] for key in sorted(entries)},
    }
    manifest_changed = (
        existing_bytes is None or new_manifest["entries"] != existing_manifest
    )
    if manifest_changed:
        serialized = (
            json.dumps(new_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_manifest(manifest_path, serialized)

    return ImageRefreshReport(
        catalog_revision=snapshot.revision,
        catalog_patch=repository.manifest.patch,
        target_count=len(targets),
        downloaded=downloaded,
        skipped=skipped,
        failures=failures,
    )


def _read_manifest(path: Path) -> tuple[dict[str, dict[str, Any]], bytes | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, None
    except OSError:
        raise ImageRefreshError("storage_error") from None

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object_pairs,
        )
        entries = _validate_manifest(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        raise ImageRefreshError("invalid_manifest") from None
    return entries, raw


def _validate_manifest(payload: object) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "entries"}:
        raise ValueError("manifest root is invalid")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("manifest version is invalid")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        raise ValueError("manifest entries are invalid")

    entries: dict[str, dict[str, Any]] = {}
    expected_fields = {
        "kind",
        "entity_id",
        "internal_name",
        "content_sha256",
        "source_patch",
    }
    for key, entry in raw_entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ValueError("manifest entry is invalid")
        if set(entry) != expected_fields:
            raise ValueError("manifest entry shape is invalid")
        kind = entry.get("kind")
        entity_id = entry.get("entity_id")
        internal_name = entry.get("internal_name")
        content_hash = entry.get("content_sha256")
        source_patch = entry.get("source_patch")
        if kind not in {"heroes", "items", "abilities"}:
            raise ValueError("manifest kind is invalid")
        if type(entity_id) is not int or entity_id <= 0:
            raise ValueError("manifest ID is invalid")
        if key != _entry_key(kind, entity_id):
            raise ValueError("manifest key does not match its identity")
        if not isinstance(internal_name, str) or not internal_name:
            raise ValueError("manifest internal name is invalid")
        if not isinstance(content_hash, str) or _HASH_PATTERN.fullmatch(content_hash) is None:
            raise ValueError("manifest content hash is invalid")
        if not isinstance(source_patch, str) or not source_patch:
            raise ValueError("manifest source patch is invalid")
        entries[key] = {
            "kind": kind,
            "entity_id": entity_id,
            "internal_name": internal_name,
            "content_sha256": content_hash,
            "source_patch": source_patch,
        }
    return entries


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("manifest contains a duplicate key")
        result[key] = value
    return result


def _reject_json_constant(_constant: str) -> None:
    raise ValueError("manifest contains a non-finite number")


def _entry_key(kind: str, entity_id: int) -> str:
    return f"{kind}:{entity_id}"


def _is_png_payload(payload: object) -> bool:
    return (
        isinstance(payload, bytes)
        and 0 < len(payload) <= MAX_IMAGE_BYTES
        and payload.startswith(PNG_SIGNATURE)
    )


def _asset_is_valid(assets_directory: Path, content_hash: str) -> bool:
    path = assets_directory / f"{content_hash}.png"
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return False
    except OSError:
        raise ImageRefreshError("storage_error") from None
    return _is_png_payload(payload) and hashlib.sha256(payload).hexdigest() == content_hash


def _store_asset(assets_directory: Path, content_hash: str, payload: bytes) -> None:
    path = assets_directory / f"{content_hash}.png"
    try:
        assets_directory.mkdir(parents=True, exist_ok=True)
        if _asset_is_valid(assets_directory, content_hash):
            return
        _atomic_write(path, payload)
    except ImageRefreshError:
        raise
    except OSError:
        raise ImageRefreshError("storage_error") from None


def _write_manifest(path: Path, content: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, content)
    except OSError:
        raise ImageRefreshError("storage_error") from None


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as temporary_file:
            descriptor = None
            temporary_file.write(content)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()


__all__ = [
    "ImageRefreshError",
    "ImageRefreshFailure",
    "ImageRefreshReport",
    "refresh_images",
]
