"""Source-backed Artifact documents and generic bounded observations."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactRef

_SOURCE_DOCUMENT_TYPE = "source_document"
_SOURCE_DOCUMENT_SCHEMA_VERSION = "1"
_MAX_TOP_LEVEL_FIELDS = 32
_MAX_STRING_LENGTH = 256
_PRIVATE_ID_KEYS = {"id", "provider_id"}


class SourceDocumentArtifact(BaseModel):
    """A validated provider-shaped document retained outside model context."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["source_document"] = _SOURCE_DOCUMENT_TYPE
    schema_version: Literal["1"] = _SOURCE_DOCUMENT_SCHEMA_VERSION
    source: str
    kind: str
    fetched_at: datetime
    facts: dict[str, Any] = Field(default_factory=dict)


def source_document_artifact_ref(source: str, kind: str, provider_identity: int | str) -> ArtifactRef:
    """Build an opaque deterministic reference without exposing provider identity."""

    payload = f"{source}\x1f{kind}\x1f{provider_identity}".encode("utf-8")
    digest = sha256(payload).hexdigest()[:24]
    return ArtifactRef(
        id=f"{_SOURCE_DOCUMENT_TYPE}:{_SOURCE_DOCUMENT_SCHEMA_VERSION}:{digest}",
        artifact_type=_SOURCE_DOCUMENT_TYPE,
        schema_version=_SOURCE_DOCUMENT_SCHEMA_VERSION,
    )


def bounded_source_observation(document: dict[str, Any]) -> dict[str, Any]:
    """Return a provider-blind, depth-one observation of a source document.

    The observation is intentionally structural rather than a hand-written
    League/Series/Match preview. Provider-private identity keys are omitted from
    model-facing facts while the full stored document remains unchanged.
    """

    observation: dict[str, Any] = {}
    sections: dict[str, dict[str, Any]] = {}
    visible_items = [
        (key, value)
        for key, value in document.items()
        if not _is_private_identity_key(key)
    ]
    for key, value in visible_items[:_MAX_TOP_LEVEL_FIELDS]:
        if isinstance(value, dict):
            sections[key] = {"kind": "object", "fields": len(value)}
        elif isinstance(value, list):
            sections[key] = {"kind": "collection", "count": len(value)}
        elif isinstance(value, str):
            observation[key] = (
                value
                if len(value) <= _MAX_STRING_LENGTH
                else value[:_MAX_STRING_LENGTH] + "…"
            )
        else:
            observation[key] = value
    if sections:
        observation["sections"] = sections
    if len(visible_items) > _MAX_TOP_LEVEL_FIELDS:
        observation["observation_truncated"] = True
    return observation


def _is_private_identity_key(key: str) -> bool:
    normalized = key.casefold()
    return (
        normalized in _PRIVATE_ID_KEYS
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
    )


__all__ = [
    "SourceDocumentArtifact",
    "bounded_source_observation",
    "source_document_artifact_ref",
]
