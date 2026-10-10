"""Attach local display references to explicitly resolved Catalog entries."""

from __future__ import annotations

from app.vnext.capabilities.catalog.lookup import CatalogLookupResult
from app.vnext.entity_display import (
    EntityDisplayDirectory,
    EntityIdentity,
    make_display_ref,
)


def enrich_catalog_lookup_result(
    result: CatalogLookupResult,
    directory: EntityDisplayDirectory,
) -> CatalogLookupResult:
    refs_by_id = {
        entry.id: make_display_ref(
            EntityIdentity(source="valve", kind=result.kind, entity_id=entry.id)
        )
        for entry in result.entries
        if entry.status == "found"
    }
    resolved = directory.resolve_many(refs_by_id.values()) if refs_by_id else {}
    entries = [
        entry.model_copy(
            update={
                "display_ref": (
                    refs_by_id[entry.id]
                    if entry.status == "found"
                    and refs_by_id.get(entry.id) in resolved
                    else None
                )
            }
        )
        for entry in result.entries
    ]
    return result.model_copy(update={"entries": entries})


__all__ = ["enrich_catalog_lookup_result"]
