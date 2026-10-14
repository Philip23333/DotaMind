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
        self._source_tools: dict[str, str] = {}

    async def put(self, document: Any, source_tool: str | None = None) -> str:
        ref = f"{self.PREFIX}{uuid4().hex}"
        self._documents[ref] = document
        if source_tool is not None:
            self._source_tools[ref] = source_tool
        return ref

    async def get(self, ref: str) -> Any:
        self._validate_ref(ref)
        try:
            return self._documents[ref]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref}") from exc

    async def get_source_tool(self, ref: str) -> str | None:
        """Return the producing tool stored alongside an existing document."""

        self._validate_ref(ref)
        if ref not in self._documents:
            raise ArtifactNotFoundError(f"artifact not found: {ref}")
        return self._source_tools.get(ref)

    @classmethod
    def _validate_ref(cls, ref: str) -> None:
        if not ref.startswith(cls.PREFIX) or len(ref) != len(cls.PREFIX) + 32:
            raise InvalidArtifactRefError(f"invalid artifact reference: {ref!r}")
        token = ref[len(cls.PREFIX) :]
        if any(char not in "0123456789abcdef" for char in token):
            raise InvalidArtifactRefError(f"invalid artifact reference: {ref!r}")
