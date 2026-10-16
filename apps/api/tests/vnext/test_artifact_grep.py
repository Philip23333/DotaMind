from __future__ import annotations

import asyncio

import pytest

from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    serialized_size,
)
from app.vnext.artifacts.grep import ArtifactGrepMatch
from app.vnext.artifacts.query import ArtifactQuerier, ArtifactQueryInput
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.registry import ToolRegistry


def test_purchase_member_discovery_then_exact_query() -> None:
    """Regression for a real replay's purchase/item zero-match false absence."""

    async def exercise():
        document = {
            "data": {
                "builds": {
                    "players": [
                        {
                            "player_slot": 1,
                            "purchase_events": [
                                {"time_seconds": 1004, "item": {"id": 145, "name_zh": "狂战斧"}},
                                {"time_seconds": 1478, "item": {"id": 147, "name_zh": "幻影斧"}},
                            ],
                        }
                    ],
                },
            },
        }
        store = SessionArtifactStore()
        ref = await store.put(document)
        grepper = ArtifactGrepper(store)
        discovery = await grepper.grep(ref, "PURCHASE")
        assert discovery.returned == 1
        match = discovery.matches[0]
        assert match.path == "data.builds.players.0.purchase_events"
        assert "matched_on" not in match.model_dump()
        assert match.value_type == "array"
        assert match.preview == "array (2 items)"
        read = await ArtifactReader(store).read(ref, match.path)
        assert [x["time_seconds"] for x in read.value] == [1004, 1478]
        exact = await ArtifactQuerier(store).query(
            ArtifactQueryInput(
                ref=ref,
                expression=(
                    "$.data.builds.players[?@.player_slot == 1]"
                    ".purchase_events[?@.item.id == 145 || @.item.id == 147]"
                ),
                fields=["time_seconds", "item"],
            )
        )
        assert [x.value["time_seconds"] for x in exact.matches] == [1004, 1478]
        assert (await grepper.grep(ref, "item")).returned == 2
        assert (await grepper.grep(ref, "狂战")).matches[0].preview == "狂战斧"
        assert await store.get(ref) == document

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "value,kind",
    [
        (None, "null"),
        ([], "array"),
        ({}, "object"),
        (False, "boolean"),
        (0, "number"),
        ("", "string"),
    ],
)
def test_member_discovery_retains_null_empty_and_zero(value, kind) -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"purchase_events": value})
        result = await ArtifactGrepper(store).grep(ref, "purchase")
        assert result.returned == 1
        assert result.matches[0].value_type == kind
        read = await ArtifactReader(store).read(ref, result.matches[0].path)
        assert read.value == value

    asyncio.run(exercise())


def test_key_and_value_match_is_not_duplicated() -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"name": "NAME", "other": "name", "name_list": ["x"]})
        grepper = ArtifactGrepper(store)
        result = await grepper.grep(ref, "name")
        assert [m.path for m in result.matches] == ["name", "other", "name_list"]
        assert "matched_on" not in ArtifactGrepMatch.model_json_schema()["properties"]

    asyncio.run(exercise())


def test_no_ancestor_fanout_but_descendant_values_still_match() -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"purchase": [{"x": "purchase"}, {"x": "no"}]})
        result = await ArtifactGrepper(store).grep(ref, "purchase")
        assert [m.path for m in result.matches] == ["purchase", "purchase.0.x"]

    asyncio.run(exercise())


def test_literal_scalar_search_preview_and_truncation() -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put(
            {
                "items": ["a.b", "aXb", 1004, False, None, "x" * 300 + "needle" + "y" * 300],
            }
        )
        grepper = ArtifactGrepper(store)
        assert (await grepper.grep(ref, "a.b")).returned == 1
        assert (await grepper.grep(ref, "1004")).matches[0].value_type == "number"
        assert (await grepper.grep(ref, "false")).matches[0].value_type == "boolean"
        assert (await grepper.grep(ref, "null")).matches[0].value_type == "null"
        preview = (await grepper.grep(ref, "needle")).matches[0].preview
        assert "needle" in preview and len(preview) <= 200
        limited = await grepper.grep(ref, "b", limit=1)
        assert limited.returned == 1 and limited.truncated
        exact = await grepper.grep(ref, "a.b", limit=1)
        assert exact.returned == 1 and not exact.truncated

    asyncio.run(exercise())


@pytest.mark.parametrize("key", ["", "a.b"])
def test_unrepresentable_member_is_explicit_error_instead_of_silent_omission(key) -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({key: "needle"})
        with pytest.raises(ValueError, match="read-compatible paths"):
            await ArtifactGrepper(store).grep(ref, "needle")

    asyncio.run(exercise())


def test_manual_content_uses_the_same_member_and_value_search() -> None:
    class Manuals:
        def read(self, ref):
            assert ref == "manual:sample"
            return "Battle Fury"

    async def exercise():
        grepper = ArtifactGrepper(SessionArtifactStore(), Manuals())
        value = await grepper.grep("manual:sample", "battle")
        assert value.matches[0].path == "content"
        assert (await grepper.grep("manual:sample", "content")).returned == 1
        assert (await grepper.grep("manual:sample", "battle", offset=1)).returned == 0

    asyncio.run(exercise())


def test_byte_limited_pages_have_no_missing_or_repeated_matches() -> None:
    async def exercise():
        store = SessionArtifactStore()
        document = {"rows": [{"name": 'needle中文\\"' * 50, "skip": "ignore"} for _ in range(75)]}
        ref = await store.put(document)
        grepper = ArtifactGrepper(store, observation_max_bytes=1000)
        offset = 0
        paths = []
        while True:
            page = await grepper.grep(ref, "needle", limit=20, offset=offset)
            assert serialized_size(page.model_dump(mode="json")) <= 1000
            assert page.offset == offset and page.limit == 20
            assert 0 < page.returned < 20
            paths.extend(m.path for m in page.matches)
            if page.next_offset is None:
                assert not page.truncated
                break
            assert page.truncated and page.next_offset == offset + page.returned
            offset = page.next_offset
        assert paths == [f"rows.{i}.name" for i in range(75)]
        for offset in [75, 100]:
            page = await grepper.grep(ref, "needle", offset=offset)
            assert page.returned == 0 and page.matches == []
            assert page.next_offset is None and not page.truncated
        assert await store.get(ref) == document

    asyncio.run(exercise())


def test_count_pagination_offsets_matching_nodes_not_visited_nodes() -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"rows": ["skip", "hit", "ignore", "hit", "hit", "skip"]})
        grepper = ArtifactGrepper(store)
        first = await grepper.grep(ref, "hit", limit=2)
        assert [m.path for m in first.matches] == ["rows.1", "rows.3"]
        assert first.next_offset == 2 and first.truncated
        last = await grepper.grep(ref, "hit", limit=2, offset=first.next_offset)
        assert [m.path for m in last.matches] == ["rows.4"]
        assert not last.truncated and last.next_offset is None
        exact = await grepper.grep(ref, "hit", limit=3)
        assert exact.returned == 3 and not exact.truncated

    asyncio.run(exercise())


def test_exact_envelope_budget_and_explicit_first_match_overflow() -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"name": "hit"})
        result = await ArtifactGrepper(store).grep(ref, "hit")
        budget = serialized_size(result.model_dump(mode="json"))
        exact = await ArtifactGrepper(store, observation_max_bytes=budget).grep(ref, "hit")
        assert exact == result
        with pytest.raises(ValueError, match="byte limit"):
            await ArtifactGrepper(store, observation_max_bytes=budget - 1).grep(ref, "hit")
        with pytest.raises(ValueError, match="byte limit"):
            await ArtifactGrepper(store, observation_max_bytes=1).grep(ref, "absent")

    asyncio.run(exercise())


def test_registry_no_scope_and_strict_paging_inputs() -> None:
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"purchase_events": []})
        registry = ToolRegistry()
        register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
        result = await registry.execute(
            ToolCall(
                id="default",
                name="artifact.grep",
                arguments={"ref": ref, "pattern": "purchase"},
            )
        )
        assert result.status == "ok"
        assert "matched_on" not in result.content["matches"][0]
        assert result.content["matches"][0]["value_type"] == "array"
        invalid = await registry.execute(
            ToolCall(
                id="invalid",
                name="artifact.grep",
                arguments={"ref": ref, "pattern": "purchase", "scope": "keys"},
            )
        )
        assert invalid.status == "error"
        assert invalid.error.code == "invalid_arguments"
        assert "scope" not in registry.get("artifact.grep").schema().input_schema["properties"]
        for args in [
            {"offset": -1},
            {"offset": True},
            {"offset": "1"},
            {"limit": False},
            {"limit": 101},
            {"limit": 0},
        ]:
            bad = await registry.execute(
                ToolCall(
                    id="invalid-paging",
                    name="artifact.grep",
                    arguments={"ref": ref, "pattern": "purchase", **args},
                )
            )
            assert bad.status == "error" and bad.error.code == "invalid_arguments"

    asyncio.run(exercise())


def test_worker_timeout_is_reported_without_claiming_worker_termination(monkeypatch) -> None:
    from threading import Event

    import app.vnext.artifacts.grep as module

    started, release, finished = Event(), Event(), Event()
    original = module._grep_document

    def blocked(*args):
        started.set()
        release.wait(2)
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(module, "_grep_document", blocked)

    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"name": "needle"})
        registry = ToolRegistry()
        register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
        task = asyncio.create_task(
            registry.execute(
                ToolCall(
                    id="timeout", name="artifact.grep", arguments={"ref": ref, "pattern": "needle"}
                ),
                timeout=0.05,
            )
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            result = await task
            assert result.status == "error" and result.error.code == "tool_timeout"
            assert not finished.is_set()
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 1)

    asyncio.run(exercise())


def test_unknown_or_cross_session_ref_is_not_an_empty_page() -> None:
    async def exercise():
        first, second = SessionArtifactStore(), SessionArtifactStore()
        foreign = await first.put({"name": "needle"})
        registry = ToolRegistry()
        register_artifact_tools(registry, ArtifactReader(second), ArtifactGrepper(second))
        result = await registry.execute(
            ToolCall(
                id="foreign",
                name="artifact.grep",
                arguments={"ref": foreign, "pattern": "needle"},
            )
        )
        assert result.status == "error" and result.error.code == "artifact_not_found"
        assert result.content is None
        assert not second._documents

    asyncio.run(exercise())
