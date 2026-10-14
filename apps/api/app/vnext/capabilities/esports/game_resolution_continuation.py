"""Continue single-game resolution from a validated Match-search Artifact."""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.vnext.artifacts.retrieval import ArtifactPathNotFoundError
from app.vnext.artifacts.store import SessionArtifactStore
from app.vnext.capabilities.esports.game_resolution import (
    EsportsGameResolutionResult,
    EsportsGameResolveInput,
    GameResolutionService,
)
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.tools.errors import StructuredToolError

_MATCH_SEARCH_TOOL = "esports.match.search"
_MATCH_PATH_RE = re.compile(r"^items\.([0-9]+)$")


class GameResolutionContinuation:
    """Validate an Artifact continuation, then call the existing capability Service."""

    def __init__(
        self,
        store: SessionArtifactStore,
        service: GameResolutionService,
    ) -> None:
        self._store = store
        self._service = service

    async def resolve(
        self, request: EsportsGameResolveInput
    ) -> EsportsGameResolutionResult:
        """Select one Match from its source Artifact and resolve the requested game."""

        document = await self._store.get(request.match_artifact_ref)
        source_tool = await self._store.get_source_tool(request.match_artifact_ref)
        if source_tool != _MATCH_SEARCH_TOOL:
            raise _artifact_type_mismatch("Artifact was not produced by Match search")

        if not isinstance(document, Mapping):
            raise _artifact_type_mismatch("Artifact does not contain a Match-search result")
        try:
            result = MatchSearchResult.model_validate(document)
        except (TypeError, ValueError):
            raise _artifact_type_mismatch(
                "Artifact does not match the Match-search result contract"
            ) from None

        match_index = _match_index(request.match_path)
        if match_index >= len(result.items):
            raise ArtifactPathNotFoundError("selected Match path is not present")

        raw_items = document.get("items")
        if not isinstance(raw_items, list) or match_index >= len(raw_items):
            raise _artifact_type_mismatch("Artifact Match collection is invalid")
        raw_match = raw_items[match_index]
        if not isinstance(raw_match, Mapping):
            raise _artifact_type_mismatch("selected Artifact value is not a Match")
        match_id = raw_match.get("id")
        if type(match_id) is not int or match_id <= 0:
            raise _artifact_type_mismatch("selected Match has no valid identity")
        if result.items[match_index].id != match_id:
            raise _artifact_type_mismatch("selected Match identity is inconsistent")

        return await self._service.resolve(
            match_id,
            request.game_position,
            confirmed_mappings={},
        )


def _match_index(path: str) -> int:
    match = _MATCH_PATH_RE.fullmatch(path)
    if match is None:
        # The public input model normally rejects this before handler dispatch.
        raise StructuredToolError(
            "invalid_arguments",
            "match_path must select an item in the Match-search result",
        )
    try:
        return int(match.group(1))
    except ValueError:
        raise ArtifactPathNotFoundError("selected Match path is not present") from None


def _artifact_type_mismatch(message: str) -> StructuredToolError:
    return StructuredToolError("artifact_type_mismatch", message)


__all__ = ["GameResolutionContinuation"]
