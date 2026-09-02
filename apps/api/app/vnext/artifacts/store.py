"""Temporary, session-owned storage for externalized tool responses."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


class ArtifactNotFoundError(LookupError):
    """Raised when a requested session artifact has no stored value."""


class InvalidArtifactRefError(ValueError):
    """Raised when a model-facing artifact reference has an unsupported shape."""


class SessionArtifactStore:
    """In-memory artifacts that exist only for one chat-session runtime."""

    PREFIX = "artifact:tool:"

    def __init__(self) -> None:
        self._documents: dict[str, Any] = {}

    async def put(self, document: Any) -> str:
        ref = f"{self.PREFIX}{uuid4().hex}"
        self._documents[ref] = document
        return ref

    async def get(self, ref: str) -> Any:
        self._validate_ref(ref)
        try:
            return self._documents[ref]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref}") from exc

    @classmethod
    def _validate_ref(cls, ref: str) -> None:
        if not ref.startswith(cls.PREFIX) or len(ref) != len(cls.PREFIX) + 32:
            raise InvalidArtifactRefError(f"invalid artifact reference: {ref!r}")
        token = ref[len(cls.PREFIX) :]
        if any(char not in "0123456789abcdef" for char in token):
            raise InvalidArtifactRefError(f"invalid artifact reference: {ref!r}")
