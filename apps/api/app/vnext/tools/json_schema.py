"""Safe validation helpers for provider-discovered object schemas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator, validators


def compile_object_json_schema(schema: Mapping[str, Any]) -> Any:
    """Validate a tool schema and compile it without enabling remote references."""

    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        raise ValueError("tool JSON Schema root must describe an object")
    _reject_remote_references(schema)
    schema_dict = dict(schema)
    validator_type = validators.validator_for(
        schema_dict,
        default=Draft202012Validator,
    )
    validator_type.check_schema(schema_dict)
    return validator_type(schema_dict)


def _reject_remote_references(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                not isinstance(nested, str) or not nested.startswith("#")
            ):
                raise ValueError("tool JSON Schema must not contain remote references")
            _reject_remote_references(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_remote_references(nested)


__all__ = ["compile_object_json_schema"]
