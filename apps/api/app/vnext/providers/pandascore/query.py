"""Mechanical compilation and execution of validated PandaScore-native queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.vnext.providers.pandascore.capabilities import (
    EndpointCapability,
    EsportsSearchQuery,
    PandaScoreCapabilities,
)

if TYPE_CHECKING:
    from app.vnext.providers.pandascore.adapter import PandaScoreAdapter


@dataclass(frozen=True, slots=True)
class CompiledPandaScoreQuery:
    path: str
    params: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PandaScoreNativeResult:
    resource: str
    scope: str
    rows: list[dict[str, Any]]
    fetched_at: datetime
    has_more: bool | None


def compile_query(
    query: EsportsSearchQuery, endpoint: EndpointCapability
) -> CompiledPandaScoreQuery:
    if query.resource != endpoint.resource or query.scope != endpoint.scope:
        raise ValueError("Query and endpoint capability must have the same resource and scope")
    params: dict[str, Any] = {
        "page[number]": query.page,
        "page[size]": query.page_size,
    }
    _compile_operator(params, "filter", query.filter)
    _compile_operator(params, "search", query.search)
    _compile_operator(params, "range", query.range)
    if query.sort:
        params["sort"] = _comma_separated(query.sort)
    return CompiledPandaScoreQuery(path=endpoint.path, params=params)


class PandaScoreNativeQueryExecutor:
    """Thin capability-selected execution seam over the existing PandaScore adapter."""

    def __init__(self, capabilities: PandaScoreCapabilities, adapter: PandaScoreAdapter) -> None:
        self._capabilities = capabilities
        self._adapter = adapter

    async def execute(
        self, query: EsportsSearchQuery | Mapping[str, Any]
    ) -> PandaScoreNativeResult:
        normalized_query = self._capabilities.validate_query(query)
        endpoint = self._capabilities.endpoint(normalized_query.resource, normalized_query.scope)
        compiled = compile_query(normalized_query, endpoint)
        return await self._adapter.execute_native_query(
            compiled,
            resource=normalized_query.resource,
            scope=normalized_query.scope,
        )


def _compile_operator(
    params: dict[str, Any], operator: str, values: Mapping[str, Any] | None
) -> None:
    if values is None:
        return
    for field, value in values.items():
        wire_value = _comma_separated(value) if operator == "range" else _wire_value(value)
        params[f"{operator}[{field}]"] = wire_value


def _wire_value(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return _comma_separated(value)
    return value


def _comma_separated(values: Any) -> str:
    if isinstance(values, str):
        return values
    return ",".join(str(value) for value in values)
