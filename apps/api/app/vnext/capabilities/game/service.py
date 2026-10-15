"""Construct governed detail while the identity resolver retains complete source facts."""

from __future__ import annotations

from collections.abc import Callable

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.providers.opendota.detail_projection import project_game_detail
from app.vnext.providers.opendota.game_detail import OpenDotaGameDetailAdapter
from app.vnext.tools.errors import StructuredToolError

from .detail import GameDetailInput, GameDetailResult


class GameDetailService:
    """Pin local label resources per query and project one native-ID source read."""

    def __init__(
        self, provider: OpenDotaGameDetailAdapter,
        catalog_provider: Callable[[], DotaCatalogRepository], units: UnitCatalog,
    ) -> None:
        self._provider = provider
        self._catalog_provider = catalog_provider
        self._units = units

    async def get_game_detail(self, query: GameDetailInput) -> GameDetailResult:
        entities = DetailEntities(self._catalog_provider())
        record = await self._provider.get_game_record(query.valve_game_id)
        if (record.match_id != query.valve_game_id
                or type(record.data.get("match_id")) is not int
                or record.data["match_id"] != query.valve_game_id):
            raise StructuredToolError(
                "provider_schema_error", "OpenDota record does not match the requested Valve game",
                {"provider": "opendota", "field": "match_id"},
            )
        return GameDetailResult(
            valve_game_id=record.match_id, provider=record.provider,
            retrieved_at=record.retrieved_at,
            catalog_version=entities.catalog_version, unit_mapping_version=self._units.version,
            data=project_game_detail(record, entities=entities, units=self._units),
        )
