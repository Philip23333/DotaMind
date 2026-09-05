"""Process validated tool results into model-visible bounded observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .externalize import ToolResponseExternalizer
from .observation import build_bounded_observation


@dataclass(frozen=True)
class ProcessedToolResult:
    content: Any
    artifact_ref: str | None = None


class ToolResultProcessor(Protocol):
    async def process(self, output: Any) -> ProcessedToolResult:
        """Return model-visible content for one validated tool output."""


ObservationBuilder = Callable[..., dict[str, Any]]


class ArtifactBackedToolResultProcessor:
    """Externalize oversized outputs and return a bounded structural view."""

    def __init__(
        self,
        externalizer: ToolResponseExternalizer,
        observation_builder: ObservationBuilder = build_bounded_observation,
    ) -> None:
        self._externalizer = externalizer
        self._observation_builder = observation_builder

    async def process(self, output: Any) -> ProcessedToolResult:
        decision = await self._externalizer.externalize(output)
        if decision.artifact_ref is None:
            return ProcessedToolResult(content=output)
        return ProcessedToolResult(
            content=self._observation_builder(
                output,
                artifact_ref=decision.artifact_ref,
            ),
            artifact_ref=decision.artifact_ref,
        )


__all__ = [
    "ArtifactBackedToolResultProcessor",
    "ObservationBuilder",
    "ProcessedToolResult",
    "ToolResultProcessor",
]
