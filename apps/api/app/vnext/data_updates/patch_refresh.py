"""Refresh the latest Valve patch notes into independent patch files."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.integrations.valve import game_data_sync
from app.integrations.valve.fetch_session import ValveFetchSession

PatchRefreshAction = Literal["updated", "skipped"]
PatchRefreshReason = Literal["missing", "invalid_local", "forced", "already_present"]
PatchRefreshErrorReason = Literal["invalid_patch", "invalid_patch_data", "storage_error"]

_PATCH_PATTERN = re.compile(r"[0-9]+\.[0-9]+[a-z]?\Z", re.ASCII)


class PatchRefreshError(RuntimeError):
    """A safe, stable error raised by the persistent patch-record store."""

    def __init__(self, reason: PatchRefreshErrorReason) -> None:
        messages = {
            "invalid_patch": "Valve patch identifier is invalid",
            "invalid_patch_data": "Valve patch data is invalid",
            "storage_error": "patch record storage operation failed",
        }
        if reason not in messages:
            raise ValueError("unsupported patch refresh error reason")
        self.reason = reason
        super().__init__(messages[reason])


@dataclass(frozen=True)
class PatchRefreshReport:
    action: PatchRefreshAction
    reason: PatchRefreshReason
    patch: str
    content_sha256: str
    change_count: int


def refresh_patches(
    *,
    data_root: Path,
    session: ValveFetchSession,
    force: bool = False,
) -> PatchRefreshReport:
    """Fetch and atomically save latest patch notes when the local file needs it."""

    if type(force) is not bool:
        raise ValueError("force must be a boolean")

    patch = game_data_sync._latest_patch(session)
    _validate_patch_id(patch)
    patch_path = Path(data_root) / "patches" / f"{patch.replace('.', '_')}.json"

    local_bytes: bytes | None
    local_reason: Literal["missing", "invalid_local"] | None
    try:
        local_bytes = patch_path.read_bytes()
    except FileNotFoundError:
        local_bytes = None
        local_reason = "missing"
    except OSError:
        raise PatchRefreshError("storage_error") from None
    else:
        try:
            local_document = _decode_and_validate_patch(local_bytes, patch)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ):
            local_document = None
            local_reason = "invalid_local"
        else:
            local_reason = None

    if local_reason is None and not force:
        assert local_bytes is not None and local_document is not None
        return PatchRefreshReport(
            action="skipped",
            reason="already_present",
            patch=patch,
            content_sha256=hashlib.sha256(local_bytes).hexdigest(),
            change_count=len(local_document["changes"]),
        )

    reason: PatchRefreshReason = "forced" if force and local_reason is None else (
        local_reason or "invalid_local"
    )
    records = game_data_sync._build_patch_records(session, patch)
    try:
        _validate_patch_document(records, patch)
        serialized = (
            json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise PatchRefreshError("invalid_patch_data") from None

    try:
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(patch_path, serialized)
    except OSError:
        raise PatchRefreshError("storage_error") from None

    return PatchRefreshReport(
        action="updated",
        reason=reason,
        patch=patch,
        content_sha256=hashlib.sha256(serialized).hexdigest(),
        change_count=len(records["changes"]),
    )


def _validate_patch_id(patch: object) -> None:
    if not isinstance(patch, str) or _PATCH_PATTERN.fullmatch(patch) is None:
        raise PatchRefreshError("invalid_patch")


def _decode_and_validate_patch(raw: bytes, expected_patch: str) -> dict[str, Any]:
    document = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    _validate_patch_document(document, expected_patch)
    return document


def _validate_patch_document(document: object, expected_patch: str) -> None:
    if not isinstance(document, dict):
        raise ValueError("patch document must be an object")
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported patch schema")
    if document.get("patch") != expected_patch:
        raise ValueError("patch identifier mismatch")
    for field in ("source_url", "source_data_url", "normalization"):
        if not isinstance(document.get(field), str):
            raise ValueError("patch metadata is invalid")
    released_at = document.get("released_at")
    if not isinstance(released_at, str):
        raise ValueError("patch release time is invalid")
    try:
        parsed_time = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("patch release time is invalid") from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ValueError("patch release time must include a timezone")
    changes = document.get("changes")
    if not isinstance(changes, list) or any(
        not isinstance(change, dict) for change in changes
    ):
        raise ValueError("patch changes are invalid")
    _ensure_finite_numbers(document)


def _ensure_finite_numbers(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("patch data contains a non-finite number")
    if isinstance(value, dict):
        for nested in value.values():
            _ensure_finite_numbers(nested)
    elif isinstance(value, list):
        for nested in value:
            _ensure_finite_numbers(nested)


def _reject_json_constant(_constant: str) -> None:
    raise ValueError("patch data contains a non-finite number")


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
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


__all__ = ["PatchRefreshError", "PatchRefreshReport", "refresh_patches"]
