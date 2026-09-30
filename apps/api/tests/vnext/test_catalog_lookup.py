from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.vnext.capabilities.catalog.lookup import CatalogLookupInput
from app.vnext.composition import VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.valve.catalog_lookup import ValveCatalogLookupAdapter


def test_catalog_lookup_maps_exact_hero_and_item_ids_with_snapshot_version() -> None:
    repository = load_default_catalog_repository()
    adapter = ValveCatalogLookupAdapter(lambda: repository)

    hero = asyncio.run(adapter.lookup(CatalogLookupInput(kind="hero", ids=[1, 2**31 - 1])))
    item = asyncio.run(adapter.lookup(CatalogLookupInput(kind="item", ids=[1, 2**31 - 1])))

    assert hero.entries[0].model_dump() == {
        "id": 1,
        "status": "found",
        "name_en": repository.get_hero(1).name_en,
        "name_zh": repository.get_hero(1).name_zh,
    }
    assert hero.entries[1].model_dump() == {
        "id": 2**31 - 1,
        "status": "unknown",
        "name_en": None,
        "name_zh": None,
    }
    assert item.entries[0].name_en == repository.get_item(1).name_en
    assert item.entries[0].status == "found"
    assert item.entries[1].id == 2**31 - 1
    assert item.entries[1].status == "unknown"
    assert hero.catalog_version.patch == repository.manifest.patch
    assert hero.catalog_version.generated_at == repository.manifest.generated_at
    assert hero.catalog_version.source == "valve_dota2_datafeed"
    assert item.kind == "item"


def test_catalog_lookup_uses_one_repository_for_all_ids_and_version() -> None:
    repository = load_default_catalog_repository()
    provider_calls: list[int] = []

    def repository_provider():
        provider_calls.append(1)
        return repository

    adapter = ValveCatalogLookupAdapter(repository_provider)
    result = asyncio.run(
        adapter.lookup(CatalogLookupInput(kind="hero", ids=[1, 2, 2**31 - 1]))
    )

    assert provider_calls == [1]
    assert [entry.name_en for entry in result.entries[:2]] == [
        repository.get_hero(1).name_en,
        repository.get_hero(2).name_en,
    ]
    assert result.catalog_version.patch == repository.snapshot_metadata()["patch"]
    assert result.catalog_version.generated_at.isoformat() == repository.snapshot_metadata()[
        "generated_at"
    ]


def test_catalog_lookup_input_is_closed_bounded_and_uses_positive_integer_ids() -> None:
    with pytest.raises(ValidationError):
        CatalogLookupInput(kind="ability", ids=[1])
    with pytest.raises(ValidationError):
        CatalogLookupInput(kind="hero", ids=[0])
    with pytest.raises(ValidationError):
        CatalogLookupInput(kind="hero", ids=["1"])
    with pytest.raises(ValidationError):
        CatalogLookupInput(kind="item", ids=list(range(1, 22)))


def test_default_composition_exposes_local_lookup_without_provider_requests() -> None:
    registry = build_vnext_registry(settings=VNextSettings())
    assert "catalog.lookup" in {tool.name for tool in registry.schemas()}

    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="lookup-hero",
                name="catalog.lookup",
                arguments={"kind": "hero", "ids": [1]},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["entries"][0]["id"] == 1
    assert result.content["entries"][0]["status"] == "found"
    assert result.content["catalog_version"]["source"] == "valve_dota2_datafeed"
