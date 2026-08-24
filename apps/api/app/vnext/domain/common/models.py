"""Small, stable contracts shared by competition and match capabilities."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IdentityStatus = Literal[
    "native",
    "resolved",
    "inferred_cross_source",
    "not_found",
    "ambiguous",
    "unresolved",
    "unknown",
]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Freshness(DomainModel):
    """Freshness metadata for facts that can change upstream."""

    fetched_at: datetime | None = None
    status: Literal["fresh", "stale", "unknown"] = "unknown"


class Provenance(DomainModel):
    """Source and identity metadata safe to expose in agent-visible results."""

    sources: list[str] = Field(min_length=1)
    freshness: Freshness = Field(default_factory=Freshness)
    identity_status: IdentityStatus = "unknown"
    warnings: list[str] = Field(default_factory=list)


class _OpaqueRef(DomainModel):
    value: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


class CompetitionRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized competition."""

    value: str = Field(pattern=r"^competition:[0-9a-f]{24}$")


class MatchRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized series match."""

    value: str = Field(pattern=r"^match:[0-9a-f]{24}$")


class GameRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized game."""

    value: str = Field(pattern=r"^game:[0-9a-f]{24}$")


class TeamRef(_OpaqueRef):
    """Opaque team reference used inside match facts, not a team capability."""

    value: str = Field(pattern=r"^team:[0-9a-f]{24}$")


class Team(DomainModel):
    ref: TeamRef
    name: str = Field(min_length=1)
    acronym: str | None = None
    logo_url: str | None = None


def normalize_text(value: str) -> str:
    """Normalize names for deterministic exact comparisons and de-duplication."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def hash_ref(kind: Literal["competition", "match", "game", "team"], *parts: object) -> str:
    """Create a deterministic opaque reference without embedding provider IDs."""

    payload = "\x1f".join(
        normalize_text(str(part)) if part is not None else "" for part in (kind, *parts)
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{kind}:{digest}"


__all__ = [
    "CompetitionRef",
    "DomainModel",
    "Freshness",
    "GameRef",
    "IdentityStatus",
    "MatchRef",
    "Provenance",
    "Team",
    "TeamRef",
    "hash_ref",
    "normalize_text",
]
