"""Explicit bounded lookup for static hero and item names."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.catalog.lookup import CatalogLookupInput, CatalogLookupResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

CatalogLookupHandler = Callable[[CatalogLookupInput], Awaitable[CatalogLookupResult]]

CATALOG_LOOKUP_DESCRIPTION = """\
Look up exact Valve hero_id or item_id values in the local committed Dota 2
static catalog. Accepts only kind='hero' or kind='item' and up to 20 IDs. The
result preserves every requested ID, marks absent IDs as unknown, and reports
the catalog patch/version. Returned names are static display labels, not facts
reported by a particular match or game provider. This lookup does not change or
enrich the original game-detail data.
"""


def register_catalog_lookup_tool(registry: ToolRegistry, lookup: CatalogLookupHandler) -> None:
    async def handler(args: CatalogLookupInput) -> CatalogLookupResult:
        return await lookup(args)

    registry.register(
        ToolDefinition(
            name="catalog.lookup",
            description=CATALOG_LOOKUP_DESCRIPTION,
            input_model=CatalogLookupInput,
            output_model=CatalogLookupResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "catalog", "provider": "valve_snapshot"},
        )
    )


__all__ = ["CATALOG_LOOKUP_DESCRIPTION", "CatalogLookupHandler", "register_catalog_lookup_tool"]
