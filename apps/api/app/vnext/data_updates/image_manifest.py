"""Shared validation for the persistent Valve image manifest."""

from __future__ import annotations

import json
import re
from typing import Any

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_EXPECTED_FIELDS = {
    "kind",
    "entity_id",
    "internal_name",
    "content_sha256",
    "source_patch",
}


def parse_image_manifest(raw: bytes) -> dict[str, dict[str, Any]]:
    """Decode and validate one complete manifest without exposing its contents in errors."""

    payload = json.loads(
        raw.decode("utf-8"),
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_object_pairs,
    )
    return validate_image_manifest(payload)


def validate_image_manifest(payload: object) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "entries"}:
        raise ValueError("manifest root is invalid")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("manifest version is invalid")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        raise ValueError("manifest entries are invalid")

    entries: dict[str, dict[str, Any]] = {}
    for key, entry in raw_entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ValueError("manifest entry is invalid")
        if set(entry) != _EXPECTED_FIELDS:
            raise ValueError("manifest entry shape is invalid")
        kind = entry.get("kind")
        entity_id = entry.get("entity_id")
        internal_name = entry.get("internal_name")
        content_hash = entry.get("content_sha256")
        source_patch = entry.get("source_patch")
        if not isinstance(kind, str) or kind not in {"heroes", "items", "abilities"}:
            raise ValueError("manifest kind is invalid")
        if type(entity_id) is not int or entity_id <= 0:
            raise ValueError("manifest ID is invalid")
        if key != f"{kind}:{entity_id}":
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
