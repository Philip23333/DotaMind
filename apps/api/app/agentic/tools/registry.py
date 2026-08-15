from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.agentic.models import QueryContext, ToolResult, ToolSource

ToolHandler = Callable[[BaseModel, QueryContext], Any | Awaitable[Any]]
EvidenceExtractor = Callable[[ToolResult], list[Any]]


@dataclass(frozen=True)
class AcceptedRef:
    from_tool: str
    path: str
    type: str


@dataclass(frozen=True)
class ArgContract:
    description: str = ""
    accepts_refs: tuple[AcceptedRef, ...] = ()
    requires_reference: bool = False


@dataclass(frozen=True)
class OutputPathContract:
    path: str
    type: str
    description: str = ""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    source: ToolSource | None = None
    evidence_extractor: EvidenceExtractor | None = None
    evidence_kinds: tuple[str, ...] = ()
    # Runtime-owned minimum proof obligation. The controller may add evidence
    # requirements, but cannot remove these primary result kinds.
    mandatory_evidence: tuple[str, ...] = ()
    arg_contracts: dict[str, ArgContract] = field(default_factory=dict)
    output_paths: dict[str, OutputPathContract] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._frozen = False

    def register(self, definition: ToolDefinition) -> None:
        if self._frozen:
            raise RuntimeError("tool registry is frozen")
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def freeze(self) -> None:
        """Close registration before the Controller renders its catalog."""

        self._frozen = True

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())

