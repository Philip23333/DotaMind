"""Generic tool metadata; domain-specific capabilities live above this layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.vnext.llm.protocol import ModelTool

ToolHandler = Callable[[BaseModel], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    timeout: float | None = None
    read_only: bool = True
    parallel_safe: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name must not be empty")
        if not self.description:
            raise ValueError(f"tool description must not be empty: {self.name}")
        if not isinstance(self.input_model, type) or not issubclass(self.input_model, BaseModel):
            raise TypeError("input_model must be a Pydantic BaseModel subclass")
        if not isinstance(self.output_model, type) or not issubclass(self.output_model, BaseModel):
            raise TypeError("output_model must be a Pydantic BaseModel subclass")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("tool timeout must be greater than zero")

    def schema(self) -> ModelTool:
        """Return the provider-neutral tool description consumed by the runtime."""

        return ModelTool(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )


__all__ = ["ToolDefinition", "ToolHandler"]
