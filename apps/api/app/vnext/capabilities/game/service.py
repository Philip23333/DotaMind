"""Construct governed detail while the identity resolver retains complete source facts."""

from __future__ import annotations

from collections.abc import Callable

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.providers.opendota.game_detail import OpenDotaGameDetailAdapter
from app.vnext.providers.stratz.game_detail import StratzGameDetailAdapter
from app.vnext.tools.errors import StructuredToolError

from .detail import GameDetailInput, GameDetailResult, SourceRead
from .projection import project_detail


class GameDetailService:
    """Pin labels, read STRATZ, and supplement fixed groups without model fallback."""

    def __init__(
        self,
        provider: StratzGameDetailAdapter,
        catalog_provider: Callable[[], DotaCatalogRepository],
        units: UnitCatalog,
        *,
        supplement: OpenDotaGameDetailAdapter | None = None,
    ) -> None:
        self._provider = provider
        self._catalog_provider = catalog_provider
        self._units = units
        self._supplement = supplement

    async def get_game_detail(self, query: GameDetailInput) -> GameDetailResult:
        entities = DetailEntities(self._catalog_provider())
        record = await self._provider.get_game_record(query.valve_game_id)
        if (
            record.match_id != query.valve_game_id
            or type(record.data.get("id")) is not int
            or record.data["id"] != query.valve_game_id
        ):
            raise StructuredToolError(
                "provider_schema_error",
                "STRATZ record does not match the requested Valve game",
                {"provider": "stratz", "field": "id"},
            )
        supplement = None
        error_code = None
        if self._supplement is not None:
            try:
                supplement = await self._supplement.get_game_record(query.valve_game_id)
            except StructuredToolError as exc:
                if exc.code not in {"provider_timeout", "provider_http_error", "provider_error"}:
                    raise
                error_code = exc.code
            if supplement is not None and (
                supplement.match_id != query.valve_game_id
                or type(supplement.data.get("match_id")) is not int
                or supplement.data["match_id"] != query.valve_game_id
            ):
                raise StructuredToolError(
                    "provider_schema_error",
                    "OpenDota supplement identifies a different Valve game",
                    {"provider": "opendota", "field": "match_id"},
                )
        sources = {"stratz": SourceRead(retrieved_at=record.retrieved_at)}
        if supplement is not None:
            sources["opendota"] = SourceRead(retrieved_at=supplement.retrieved_at)
        return GameDetailResult(
            valve_game_id=record.match_id,
            provider=record.provider,
            retrieved_at=record.retrieved_at,
            sources=sources,
            catalog_version=entities.catalog_version,
            unit_mapping_version=self._units.version,
            data=project_detail(
                record,
                supplement,
                entities=entities,
                units=self._units,
                supplement_error=error_code,
            ),
        )
