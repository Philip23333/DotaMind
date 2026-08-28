from __future__ import annotations

import asyncio

from app.vnext.artifacts import (
    ArtifactScopeRef,
    MemoryArtifactScopeStore,
    game_summary_artifact_ref,
)


def test_memory_scope_store_deduplicates_refs_and_keeps_scopes_isolated() -> None:
    store = MemoryArtifactScopeStore()
    series = ArtifactScopeRef(value="series:abc")
    other = ArtifactScopeRef(value="series:def")
    first = game_summary_artifact_ref(1)
    second = game_summary_artifact_ref(2)

    async def exercise() -> tuple[list[object], list[object]]:
        await store.add(series, second)
        await store.add(series, first)
        await store.add(series, first)
        await store.add(other, second)
        refs = [ref async for ref in store.iter_refs(series)]
        other_refs = [ref async for ref in store.iter_refs(other)]
        return refs, other_refs

    refs, other_refs = asyncio.run(exercise())

    assert refs == [first, second]
    assert other_refs == [second]
