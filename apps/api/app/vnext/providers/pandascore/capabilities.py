"""Generated PandaScore query capability loading and deterministic validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
_DEFAULT_CAPABILITIES_PATH = (
    _REPOSITORY_ROOT / "docs" / "reference" / "pandascore-generated" / "capabilities.json"
)
NORMAL_SCOPES = frozenset({"all", "past", "running", "upcoming"})


class CapabilitySchemaError(ValueError):
    """The generated capability document does not meet the runtime contract."""


class PandaScoreQueryValidationError(ValueError):
    """A PandaScore-native query cannot be represented by the loaded capability."""

    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(code)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, **self.details}


@dataclass(frozen=True, slots=True)
class EsportsSearchQuery:
    """Minimal native query shape consumed by the capability validator."""

    resource: str
    scope: str = "all"
    filter: Mapping[str, Any] | None = None
    search: Mapping[str, Any] | None = None
    range: Mapping[str, Any] | None = None
    sort: Sequence[str] | None = None
    page: int = 1
    page_size: int = 10


@dataclass(frozen=True, slots=True)
class EndpointCapability:
    resource: str
    scope: str
    path: str
    path_params: Mapping[str, Any]
    filter: Mapping[str, Mapping[str, Any]]
    search: Mapping[str, Mapping[str, Any]]
    range: Mapping[str, Mapping[str, Any]]
    sort: tuple[str | Mapping[str, str], ...]
    pagination: Mapping[str, Any]


class PandaScoreCapabilities:
    """Runtime view of the generated PandaScore Dota 2 query capabilities."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = document

    @classmethod
    def load(cls, path: Path | None = None) -> PandaScoreCapabilities:
        document_path = path or _DEFAULT_CAPABILITIES_PATH
        try:
            document = json.loads(document_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            message = f"Unable to load PandaScore capabilities: {document_path}"
            raise CapabilitySchemaError(message) from exc
        if not isinstance(document, dict):
            raise CapabilitySchemaError("PandaScore capabilities must be a JSON object")
        if document.get("schema_version") != 1:
            raise CapabilitySchemaError("Unsupported PandaScore capability schema_version")
        if document.get("source") != "pandascore":
            raise CapabilitySchemaError("PandaScore capability source must be 'pandascore'")
        if document.get("game") != "dota2":
            raise CapabilitySchemaError("PandaScore capability game must be 'dota2'")
        if not isinstance(document.get("resources"), dict):
            raise CapabilitySchemaError("PandaScore capability resources must be an object")
        return cls(document)

    @property
    def supported_resources(self) -> tuple[str, ...]:
        return tuple(sorted(self._document["resources"]))

    def endpoint(self, resource: str, scope: str = "all") -> EndpointCapability:
        resources = self._document["resources"]
        resource_document = resources.get(resource)
        if not isinstance(resource_document, Mapping):
            raise PandaScoreQueryValidationError(
                "unsupported_resource",
                resource=resource,
                supported_resources=list(self.supported_resources),
            )
        scopes = resource_document.get("scopes")
        if not isinstance(scopes, Mapping):
            raise CapabilitySchemaError(f"PandaScore resource {resource!r} has invalid scopes")
        normal_scopes = tuple(
            sorted(scope_name for scope_name in scopes if scope_name in NORMAL_SCOPES)
        )
        scope_document = scopes.get(scope)
        if scope not in NORMAL_SCOPES or not isinstance(scope_document, Mapping):
            raise PandaScoreQueryValidationError(
                "unsupported_scope",
                resource=resource,
                scope=scope,
                supported_scopes=list(normal_scopes),
            )
        return self._endpoint_capability(resource, scope, scope_document)

    def validate_query(
        self, query: EsportsSearchQuery | Mapping[str, Any]
    ) -> EsportsSearchQuery:
        normalized_query = normalize_query(query)
        endpoint = self.endpoint(normalized_query.resource, normalized_query.scope)
        self._validate_operator(endpoint, "filter", normalized_query.filter)
        self._validate_operator(endpoint, "search", normalized_query.search)
        self._validate_operator(endpoint, "range", normalized_query.range)
        self._validate_sort(endpoint, normalized_query.sort)
        return normalized_query

    @staticmethod
    def _endpoint_capability(
        resource: str, scope: str, document: Mapping[str, Any]
    ) -> EndpointCapability:
        try:
            path = document["path"]
            path_params = document["path_params"]
            filter_fields = document["filter"]
            search_fields = document["search"]
            range_fields = document["range"]
            sort = document["sort"]
            pagination = document["pagination"]
        except KeyError as exc:
            raise CapabilitySchemaError(
                f"PandaScore capability {resource}/{scope} is missing {exc.args[0]!r}"
            ) from exc
        if not isinstance(path, str):
            raise CapabilitySchemaError(
                f"PandaScore capability {resource}/{scope} has an invalid path"
            )
        if not all(
            isinstance(value, Mapping)
            for value in (path_params, filter_fields, search_fields, range_fields, pagination)
        ) or not isinstance(sort, list):
            raise CapabilitySchemaError(
                f"PandaScore capability {resource}/{scope} has invalid fields"
            )
        return EndpointCapability(
            resource=resource,
            scope=scope,
            path=path,
            path_params=path_params,
            filter=filter_fields,
            search=search_fields,
            range=range_fields,
            sort=tuple(sort),
            pagination=pagination,
        )

    def _validate_operator(
        self,
        endpoint: EndpointCapability,
        operator: str,
        values: Mapping[str, Any] | None,
    ) -> None:
        if values is None:
            return
        if not isinstance(values, Mapping):
            raise PandaScoreQueryValidationError(
                "invalid_value",
                resource=endpoint.resource,
                scope=endpoint.scope,
                operator=operator,
                reason="operator_requires_object",
            )
        capability_fields = getattr(endpoint, operator)
        unsupported_fields = sorted(set(values) - set(capability_fields))
        if unsupported_fields:
            details: dict[str, Any] = {
                "resource": endpoint.resource,
                "scope": endpoint.scope,
                "operator": operator,
                "supported_fields": sorted(capability_fields),
            }
            if len(unsupported_fields) == 1:
                details["field"] = unsupported_fields[0]
            else:
                details["fields"] = unsupported_fields
            raise PandaScoreQueryValidationError("unsupported_field", **details)
        for field, value in values.items():
            self._validate_value(endpoint, operator, field, value, capability_fields[field])

    def _validate_value(
        self,
        endpoint: EndpointCapability,
        operator: str,
        field: str,
        value: Any,
        specification: Mapping[str, Any],
    ) -> None:
        if operator == "range":
            if not _is_value_sequence(value) or len(value) != 2:
                raise _invalid_value_error(
                    endpoint, operator, field, "range_requires_two_values"
                )
            for item in value:
                self._validate_atomic_value(endpoint, operator, field, item, specification)
            return
        if _is_value_sequence(value):
            if not specification.get("multiple", False):
                raise _invalid_value_error(endpoint, operator, field, "multiple_values_not_allowed")
            for item in value:
                self._validate_atomic_value(endpoint, operator, field, item, specification)
            return
        self._validate_atomic_value(endpoint, operator, field, value, specification)

    @staticmethod
    def _validate_atomic_value(
        endpoint: EndpointCapability,
        operator: str,
        field: str,
        value: Any,
        specification: Mapping[str, Any],
    ) -> None:
        value_type = specification.get("type")
        if value_type != "unknown" and not _value_matches_type(value, value_type):
            raise _invalid_value_error(endpoint, operator, field, "type_mismatch")
        allowed_values = specification.get("enum")
        if allowed_values is not None and value not in allowed_values:
            raise _invalid_value_error(
                endpoint,
                operator,
                field,
                "value_not_in_enum",
                allowed_values=list(allowed_values),
            )

    @staticmethod
    def _validate_sort(endpoint: EndpointCapability, sort: Sequence[str] | None) -> None:
        if sort is None:
            return
        if isinstance(sort, str) or not isinstance(sort, Sequence):
            raise PandaScoreQueryValidationError(
                "invalid_value",
                resource=endpoint.resource,
                scope=endpoint.scope,
                operator="sort",
                reason="sort_requires_array",
            )
        supported_fields = sorted(_sort_fields(endpoint.sort))
        for requested_field in sort:
            if not isinstance(requested_field, str):
                raise PandaScoreQueryValidationError(
                    "invalid_value",
                    resource=endpoint.resource,
                    scope=endpoint.scope,
                    operator="sort",
                    reason="sort_field_must_be_string",
                )
            field = requested_field.removeprefix("-")
            if field not in supported_fields:
                raise PandaScoreQueryValidationError(
                    "unsupported_field",
                    resource=endpoint.resource,
                    scope=endpoint.scope,
                    operator="sort",
                    field=field,
                    supported_fields=supported_fields,
                )


def normalize_query(query: EsportsSearchQuery | Mapping[str, Any]) -> EsportsSearchQuery:
    if isinstance(query, EsportsSearchQuery):
        normalized_query = query
    elif not isinstance(query, Mapping):
        raise PandaScoreQueryValidationError("invalid_value", reason="query_requires_object")
    else:
        resource = query.get("resource")
        if not isinstance(resource, str):
            raise PandaScoreQueryValidationError(
                "invalid_value", field="resource", reason="resource_requires_string"
            )
        scope = query.get("scope", "all")
        if not isinstance(scope, str):
            raise PandaScoreQueryValidationError(
                "invalid_value", field="scope", reason="scope_requires_string"
            )
        normalized_query = EsportsSearchQuery(
            resource=resource,
            scope=scope,
            filter=query.get("filter"),
            search=query.get("search"),
            range=query.get("range"),
            sort=query.get("sort"),
            page=query.get("page", 1),
            page_size=query.get("page_size", 10),
        )
    _validate_pagination(normalized_query)
    return normalized_query


def _validate_pagination(query: EsportsSearchQuery) -> None:
    if not _is_plain_integer(query.page) or query.page < 1:
        raise PandaScoreQueryValidationError(
            "invalid_value", field="page", reason="page_must_be_positive_integer"
        )
    if not _is_plain_integer(query.page_size) or not 1 <= query.page_size <= 100:
        raise PandaScoreQueryValidationError(
            "invalid_value", field="page_size", reason="page_size_out_of_range"
        )


def _invalid_value_error(
    endpoint: EndpointCapability,
    operator: str,
    field: str,
    reason: str,
    **details: Any,
) -> PandaScoreQueryValidationError:
    return PandaScoreQueryValidationError(
        "invalid_value",
        resource=endpoint.resource,
        scope=endpoint.scope,
        operator=operator,
        field=field,
        reason=reason,
        **details,
    )


def _is_value_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _value_matches_type(value: Any, value_type: Any) -> bool:
    if value_type == "integer":
        return _is_plain_integer(value)
    if value_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "boolean":
        return isinstance(value, bool)
    return True


def _is_plain_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sort_fields(sort: Sequence[str | Mapping[str, str]]) -> set[str]:
    fields: set[str] = set()
    for entry in sort:
        if isinstance(entry, str):
            fields.add(entry)
        elif isinstance(entry, Mapping) and isinstance(entry.get("field"), str):
            fields.add(entry["field"])
        else:
            raise CapabilitySchemaError("PandaScore capability sort entry is invalid")
    return fields
