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


class LeagueRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized esports league."""

    model_config = ConfigDict(
        json_schema_extra={
            "description": (
                "League reference object. Pass the complete object returned by another "
                "tool. Do not pass its value as a bare string or JSON-encode this object "
                "into a string."
            ),
            "examples": [{"value": "league:0123456789abcdef01234567"}],
        }
    )

    value: str = Field(
        pattern=r"^league:[0-9a-f]{24}$",
        description="Opaque league reference value inside this reference object.",
    )


class SeriesRef(_OpaqueRef):
    value: str = Field(pattern=r"^series:[0-9a-f]{24}$")


class TournamentRef(_OpaqueRef):
    value: str = Field(pattern=r"^tournament:[0-9a-f]{24}$")


class CompetitionRef(_OpaqueRef):
    """Legacy ref retained until the Series capability replacement lands."""

    value: str = Field(pattern=r"^competition:[0-9a-f]{24}$")


class MatchRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized series match."""

    model_config = ConfigDict(
        json_schema_extra={
            "description": (
                "Match reference object. Pass the complete object returned by another tool. "
                "Do not pass its value as a bare string or JSON-encode this object into a string."
            ),
            "examples": [{"value": "match:0123456789abcdef01234567"}],
        }
    )

    value: str = Field(
        pattern=r"^match:[0-9a-f]{24}$",
        description="Opaque match reference value inside this reference object.",
    )


class GameRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized game."""

    model_config = ConfigDict(
        json_schema_extra={
            "description": (
                "Game reference object. Pass the complete object returned by another tool. "
                "Do not pass its value as a bare string or JSON-encode this object into a string."
            ),
            "examples": [{"value": "game:0123456789abcdef01234567"}],
        }
    )

    value: str = Field(
        pattern=r"^game:[0-9a-f]{24}$",
        description="Opaque game reference value inside this reference object.",
    )


class TeamRef(_OpaqueRef):
    """Opaque team reference used inside match facts, not a team capability."""

    model_config = ConfigDict(
        json_schema_extra={
            "description": (
                "Team reference object. Pass the complete object returned by another tool. "
                "Do not pass its value as a bare string or JSON-encode this object into a string."
            ),
            "examples": [{"value": "team:0123456789abcdef01234567"}],
        }
    )

    value: str = Field(
        pattern=r"^team:[0-9a-f]{24}$",
        description="Opaque team reference value inside this reference object.",
    )


class PlayerRef(_OpaqueRef):
    """Opaque, runtime-scoped reference to a normalized professional player."""

    model_config = ConfigDict(
        json_schema_extra={
            "description": (
                "Player reference object. Pass the complete object returned by another tool. "
                "Do not pass its value as a bare string or JSON-encode this object into a string."
            ),
            "examples": [{"value": "player:0123456789abcdef01234567"}],
        }
    )

    value: str = Field(
        pattern=r"^player:[0-9a-f]{24}$",
        description="Opaque player reference value inside this reference object.",
    )


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


def hash_ref(
    kind: Literal["league", "series", "tournament", "match", "game", "team", "player"],
    *parts: object,
) -> str:
    """Create a deterministic opaque reference without embedding provider IDs."""

    payload = "\x1f".join(
        normalize_text(str(part)) if part is not None else "" for part in (kind, *parts)
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{kind}:{digest}"


__all__ = [
    "DomainModel",
    "Freshness",
    "GameRef",
    "IdentityStatus",
    "MatchRef",
    "PlayerRef",
    "Provenance",
    "Team",
    "TeamRef",
    "LeagueRef",
    "CompetitionRef",
    "SeriesRef",
    "TournamentRef",
    "hash_ref",
    "normalize_text",
]
