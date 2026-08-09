"""Agent tool registration for the committed Valve static catalog."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolResult, ToolSource
from app.agentic.tools import ArgContract, OutputPathContract, ToolDefinition, ToolRegistry
from app.integrations.valve.catalog_repository import (
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.integrations.valve.datafeed import DATAFEED_ROOT


class ResolveHeroInput(BaseModel):
    query: str = Field(min_length=1)


def register_dota_catalog_tools(
    registry: ToolRegistry,
    repository: DotaCatalogRepository | None = None,
) -> None:
    catalog = repository or load_default_catalog_repository()
    registry.register(
        ToolDefinition(
            name="resolve_hero",
            description=(
                "Resolve a Dota 2 hero name, localized name, internal name, or "
                "alias to a canonical hero id from the committed Valve catalog. "
                "Returns resolved, ambiguous, or not_found without querying a network."
            ),
            input_model=ResolveHeroInput,
            handler=_resolve_hero_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=resolve_hero_evidence,
            evidence_kinds=("hero_identity",),
            mandatory_evidence=("hero_identity",),
            arg_contracts={
                "query": ArgContract(description="Hero name, internal name, or alias."),
            },
            output_paths={
                "hero_id": OutputPathContract(
                    path="data.hero.hero_id",
                    type="int",
                    description="Canonical Dota 2 hero id.",
                ),
            },
            metadata={"game": "dota2", "domain": "hero_identity", "snapshot": True},
        )
    )


def _resolve_hero_handler(repository: DotaCatalogRepository):
    def handle(args: ResolveHeroInput, _context: QueryContext) -> dict[str, Any]:
        result = repository.resolve_hero(args.query)
        result["snapshot"] = repository.snapshot_metadata()
        return result

    return handle


def resolve_hero_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved" or not isinstance(data.get("hero"), dict):
        return []

    hero = data["hero"]
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:hero_identity:{hero.get('hero_id')}",
            kind="hero_identity",
            subject=str(hero.get("localized_name") or hero.get("hero_id")),
            value={
                "hero_id": hero.get("hero_id"),
                "name": hero.get("name"),
                "name_en": hero.get("name_en"),
                "name_zh": hero.get("name_zh"),
                "localized_name": hero.get("localized_name"),
                "aliases": hero.get("aliases", []),
                "method": data.get("method"),
                "query": data.get("query"),
                "snapshot": data.get("snapshot"),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]
