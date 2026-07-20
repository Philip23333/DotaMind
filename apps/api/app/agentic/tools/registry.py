from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from types import MappingProxyType
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
        """Seal the catalog shared by prompt rendering, validation and execution."""

        if self._frozen:
            return
        self._tools = {
            name: replace(
                definition,
                arg_contracts=_freeze_mapping(definition.arg_contracts),
                output_paths=_freeze_mapping(definition.output_paths),
                metadata=_freeze_mapping(definition.metadata),
            )
            for name, definition in self._tools.items()
        }
        self._frozen = True

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())


def _freeze_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {key: _freeze_value(value) for key, value in deepcopy(dict(values)).items()}
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    return value

