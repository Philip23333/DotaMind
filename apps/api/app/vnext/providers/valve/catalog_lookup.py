"""Map local Valve catalog records to the small vNext lookup contract."""

from __future__ import annotations

from collections.abc import Callable

from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
)
from app.vnext.capabilities.catalog.lookup import (
    CatalogLookupEntry,
    CatalogLookupInput,
    CatalogLookupResult,
    CatalogVersion,
)


class ValveCatalogLookupAdapter:
    def __init__(
        self,
        repository_provider: Callable[[], DotaCatalogRepository],
    ) -> None:
        self._repository_provider = repository_provider

    async def lookup(self, query: CatalogLookupInput) -> CatalogLookupResult:
        repository = self._repository_provider()
        entries = []
        for identifier in query.ids:
            try:
                record = (
                    repository.get_hero(identifier)
                    if query.kind == "hero"
                    else repository.get_item(identifier)
                )
            except CatalogLookupError:
                entries.append(
                    CatalogLookupEntry(
                        id=identifier,
                        status="unknown",
                        name_en=None,
                        name_zh=None,
                    )
                )
                continue

            entries.append(
                CatalogLookupEntry(
                    id=identifier,
                    status="found",
                    name_en=record.name_en or None,
                    name_zh=record.name_zh or None,
                )
            )

        metadata = repository.snapshot_metadata()
        return CatalogLookupResult(
            kind=query.kind,
            catalog_version=CatalogVersion(
                patch=metadata["patch"],
                generated_at=metadata["generated_at"],
                schema_version=metadata["schema_version"],
            ),
            entries=entries,
        )


__all__ = ["ValveCatalogLookupAdapter"]
