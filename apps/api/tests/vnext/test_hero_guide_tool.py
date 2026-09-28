from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.capabilities.hero.guide import (
    GuideSourceMetadata,
    HeroGuideInput,
    HeroGuideResult,
    ProMatchExample,
    PubGuide,
)
from app.vnext.capabilities.hero.service import HeroGuideQueryError, HeroGuideService
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.hero.guide import (
    HERO_GUIDE_DESCRIPTION,
    register_hero_guide_tool,
)
from app.vnext.tools.registry import ToolRegistry

_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)


def _result() -> HeroGuideResult:
    return HeroGuideResult(
        hero_id=18,
        position=1,
        section="all",
        pub_metadata=GuideSourceMetadata(
            provider="d2pt",
            sample_type="pub",
            availability="missing",
            stale=False,
        ),
        pro_metadata=GuideSourceMetadata(
            provider="d2pt",
            sample_type="pro",
            availability="missing",
            stale=False,
        ),
    )


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def test_tool_contract_and_small_result_are_inline() -> None:
    calls: list[HeroGuideInput] = []

    async def lookup(query: HeroGuideInput) -> HeroGuideResult:
        calls.append(query)
        return _result()

    registry = ToolRegistry()
    register_hero_guide_tool(registry, lookup)
    definition = registry.get("hero.guide")

    assert definition.input_model is HeroGuideInput
    assert definition.output_model is HeroGuideResult
    assert definition.read_only is True
    assert definition.parallel_safe is True
    assert definition.externalize_result is True
    assert definition.metadata == {"game": "dota2", "domain": "hero", "provider": "d2pt"}
    assert "Valve hero ID" in HERO_GUIDE_DESCRIPTION
    assert "does not trigger a refresh" in HERO_GUIDE_DESCRIPTION
    assert "independent candidates" in HERO_GUIDE_DESCRIPTION
    assert "Artifact" in HERO_GUIDE_DESCRIPTION

    result = _run(
        registry.execute(
            ToolCall(
                id="guide-call",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["pub_metadata"]["availability"] == "missing"
    assert calls == [HeroGuideInput(hero_id=18, position=1)]
    assert "hero.guide" in {tool.name for tool in registry.schemas()}


def test_invalid_input_is_rejected_before_service_call() -> None:
    calls: list[HeroGuideInput] = []

    async def lookup(query: HeroGuideInput) -> HeroGuideResult:
        calls.append(query)
        return _result()

    registry = ToolRegistry()
    register_hero_guide_tool(registry, lookup)

    result = _run(
        registry.execute(
            ToolCall(
                id="bad-guide-call",
                name="hero.guide",
                arguments={"hero_id": True, "position": 6},
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None and result.error.code == "invalid_arguments"
    assert calls == []


def test_query_error_maps_to_fixed_structured_tool_error() -> None:
    async def lookup(_query: HeroGuideInput) -> HeroGuideResult:
        raise HeroGuideQueryError(
            pub_error="cache_unavailable",
            pro_error="cache_invalid_data",
        )

    registry = ToolRegistry()
    register_hero_guide_tool(registry, lookup)
    result = _run(
        registry.execute(
            ToolCall(
                id="guide-error-call",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1},
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "tool_execution_error"
    assert result.error.message == "Hero guide cache could not be read."
    assert result.error.details == {
        "pub_error": "cache_unavailable",
        "pro_error": "cache_invalid_data",
    }
    assert "HeroGuideQueryError" not in result.model_dump_json()


def test_cache_exception_text_is_not_disclosed_by_tool() -> None:
    class SecretUnavailableError(HeroGuideCacheUnavailableError):
        def __str__(self) -> str:
            return "CACHE_PRIVATE_SECRET"

    class SecretDataError(HeroGuideCacheDataError):
        def __str__(self) -> str:
            return "CACHE_PRIVATE_SECRET"

    class FailingCache:
        async def get_pub(self, **_kwargs: Any) -> GuideCacheEntry:
            raise SecretUnavailableError()

        async def get_pro(self, **_kwargs: Any) -> GuideCacheEntry:
            raise SecretDataError()

    registry = ToolRegistry()
    register_hero_guide_tool(
        registry,
        HeroGuideService(FailingCache(), clock=lambda: _NOW).get_guide,
    )
    result = _run(
        registry.execute(
            ToolCall(
                id="private-cache-error",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1},
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None and result.error.code == "tool_execution_error"
    assert result.error.details == {
        "pub_error": "cache_unavailable",
        "pro_error": "cache_invalid_data",
    }
    assert "CACHE_PRIVATE_SECRET" not in result.model_dump_json()


def test_hero_guide_auto_externalizes_and_artifact_read_returns_both_sources() -> None:
    pub_guides = [
        PubGuide(build_id=index, statistics={"sample": f"pub-{index}-" + "p" * 1200})
        for index in range(20)
    ]
    pro_examples = [
        ProMatchExample(
            source_match_id=index + 1,
            hero_id=18,
            position=1,
            position_basis="build",
            player_name=f"pro-{index}-" + "x" * 700,
            source_path=f"$[0].recent_matches[{index}]",
        )
        for index in range(8)
    ]
    pub_snapshot = GuideCacheSnapshot(
        sample_type="pub",
        hero_id=18,
        position=1,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=b"RAW_SOURCE_BYTES_PRIVATE",
        source_rows=[
            {
                "position": "pos 1",
                "updated_at": "7.41f",
                "private_source_marker": "SOURCE_ROWS_PRIVATE",
            }
        ],
        pub_guides=pub_guides,
    )
    pro_snapshot = GuideCacheSnapshot(
        sample_type="pro",
        hero_id=18,
        position=None,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=b"RAW_PRO_BYTES_PRIVATE",
        source_rows=[{"position": "pos 1", "updated_at": "7.41f"}],
        pro_examples=pro_examples,
    )

    class FakeCache:
        async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
            assert (hero_id, position) == (18, 1)
            return GuideCacheEntry(snapshot=pub_snapshot, last_attempt_at=_NOW)

        async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
            assert hero_id == 18
            return GuideCacheEntry(snapshot=pro_snapshot, last_attempt_at=_NOW)

    store = SessionArtifactStore()
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
    register_hero_guide_tool(
        registry,
        HeroGuideService(FakeCache(), clock=lambda: _NOW).get_guide,
    )

    result = _run(
        registry.execute(
            ToolCall(
                id="large-guide-call",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    ref = result.content["artifact_ref"]
    stored = _run(store.get(ref))
    assert len(stored["pub_guides"]) == 20
    assert len(stored["pro_examples"]) == 8
    assert "raw_body" not in stored
    assert "source_rows" not in stored
    assert "SOURCE_ROWS_PRIVATE" not in str(stored)
    assert "RAW_SOURCE_BYTES_PRIVATE" not in str(stored)

    pub_read = _run(
        registry.execute(
            ToolCall(
                id="read-pub-guide",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "pub_guides",
                    "offset": 0,
                    "limit": 3,
                },
            )
        )
    )
    pro_read = _run(
        registry.execute(
            ToolCall(
                id="read-pro-examples",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "pro_examples",
                    "offset": 0,
                    "limit": 3,
                },
            )
        )
    )

    assert pub_read.status == "ok"
    assert pub_read.content["value"][0]["build_id"] == 0
    assert pro_read.status == "ok"
    assert pro_read.content["value"][0]["source_match_id"] == 1
