"""Complete source-backed artifacts for one PandaScore search response."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactRef

_ARTIFACT_TYPE = "esports_search_result"
_SCHEMA_VERSION = "1"


class EsportsSearchResultArtifact(BaseModel):
    """One complete provider-shaped esports-search response and its query provenance."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["esports_search_result"] = _ARTIFACT_TYPE
    schema_version: Literal["1"] = _SCHEMA_VERSION
    source: Literal["pandascore"] = "pandascore"
    fetched_at: datetime
    kind: Literal["esports_search_result"] = _ARTIFACT_TYPE
    query: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


def esports_search_result_artifact_ref(query: dict[str, Any]) -> ArtifactRef:
    """Build the stable reference for a normalized PandaScore search query."""

    payload = json.dumps(
        query,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = sha256(payload).hexdigest()[:24]
    return ArtifactRef(
        id=f"{_ARTIFACT_TYPE}:{_SCHEMA_VERSION}:{digest}",
        artifact_type=_ARTIFACT_TYPE,
        schema_version=_SCHEMA_VERSION,
    )


__all__ = ["EsportsSearchResultArtifact", "esports_search_result_artifact_ref"]
