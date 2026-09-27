"""Generic tool metadata; domain-specific capabilities live above this layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.vnext.llm.protocol import ModelTool
from app.vnext.tools.json_schema import compile_object_json_schema

ToolArguments = BaseModel | dict[str, Any]
ToolHandler = Callable[[ToolArguments], Any | Awaitable[Any]]


class ToolContextEffect(str, Enum):
    """How a successful tool result affects model context lifetime."""

    BOUNDED = "bounded"
    MATERIALIZING = "materializing"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel] | None
    output_model: type[BaseModel]
    handler: ToolHandler
    input_schema: Mapping[str, Any] | None = None
    timeout: float | None = None
    read_only: bool = True
    parallel_safe: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    externalize_result: bool = True
    context_effect: ToolContextEffect = ToolContextEffect.BOUNDED
    _json_schema_validator: Any = field(init=False, default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name must not be empty")
        if not self.description:
            raise ValueError(f"tool description must not be empty: {self.name}")
        if self.input_model is None:
            if self.input_schema is None:
                raise TypeError("a Pydantic input_model or JSON input_schema is required")
            schema = deepcopy(dict(self.input_schema))
            validator = compile_object_json_schema(schema)
            object.__setattr__(self, "input_schema", schema)
            object.__setattr__(self, "_json_schema_validator", validator)
        elif self.input_schema is not None:
            raise TypeError("input_model and input_schema are mutually exclusive")
        elif not isinstance(self.input_model, type) or not issubclass(self.input_model, BaseModel):
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
            input_schema=(
                deepcopy(dict(self.input_schema))
                if self.input_schema is not None
                else self.input_model.model_json_schema()  # type: ignore[union-attr]
            ),
        )

    def json_schema_errors(self, arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Return bounded, value-free errors for a remote JSON Schema input."""

        validator = self._json_schema_validator
        if validator is None:
            return []
        errors = sorted(
            validator.iter_errors(arguments),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        return [
            {
                "loc": list(error.absolute_path),
                "type": error.validator or "json_schema",
            }
            for error in errors[:10]
        ]


__all__ = ["ToolContextEffect", "ToolDefinition", "ToolHandler"]
