"""Process validated tool results into model-visible bounded observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .externalize import ToolResponseExternalizer, serialized_size
from .observation import MAX_MODEL_TOOL_OBSERVATION_BYTES, build_bounded_observation


@dataclass(frozen=True)
class ProcessedToolResult:
    content: Any
    artifact_ref: str | None = None


class ToolResultProcessor(Protocol):
    async def process(
        self,
        output: Any,
        *,
        source_tool: str | None = None,
        force_artifact: bool = False,
    ) -> ProcessedToolResult:
        """Return model-visible content for one validated tool output."""


ObservationBuilder = Callable[..., dict[str, Any]]


class ArtifactBackedToolResultProcessor:
    """Externalize oversized outputs and return a bounded structural view."""

    def __init__(
        self,
        externalizer: ToolResponseExternalizer,
        observation_builder: ObservationBuilder = build_bounded_observation,
        *,
        observation_max_bytes: int = MAX_MODEL_TOOL_OBSERVATION_BYTES,
    ) -> None:
        self._externalizer = externalizer
        self._observation_builder = observation_builder
        self._observation_max_bytes = observation_max_bytes

    async def process(
        self,
        output: Any,
        *,
        source_tool: str | None = None,
        force_artifact: bool = False,
    ) -> ProcessedToolResult:
        decision = await self._externalizer.externalize(
            output,
            source_tool=source_tool,
            force_artifact=force_artifact,
        )
        if decision.artifact_ref is None:
            return ProcessedToolResult(content=output)
        if decision.inline_eligible:
            full_envelope = {
                "artifact_ref": decision.artifact_ref,
                "externalized": True,
                "value": output,
            }
            if serialized_size(full_envelope) <= self._observation_max_bytes:
                return ProcessedToolResult(
                    content=full_envelope,
                    artifact_ref=decision.artifact_ref,
                )
        return ProcessedToolResult(
            content=self._observation_builder(
                output,
                artifact_ref=decision.artifact_ref,
                max_bytes=self._observation_max_bytes,
            ),
            artifact_ref=decision.artifact_ref,
        )


__all__ = [
    "ArtifactBackedToolResultProcessor",
    "ObservationBuilder",
    "ProcessedToolResult",
    "ToolResultProcessor",
]
