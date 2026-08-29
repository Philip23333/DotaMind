from __future__ import annotations

import asyncio
import json

from app.vnext.composition import (
    VNextSettings,
    build_vnext_registry,
    build_vnext_runtime,
    build_vnext_services,
)
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import ToolCall
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


def test_composition_is_lazy_and_retires_the_old_esports_search_tools() -> None:
    services = build_vnext_services(VNextSettings(pandascore_token="test-token"))
    assert services.pandascore._client is None  # type: ignore[attr-defined]
    assert services.opendota._client is None  # type: ignore[attr-defined]
    assert services.artifact_store is not None
    assert services.game_summary_producer is not None
    registry = build_vnext_registry(services)
    assert [tool.name for tool in registry.list()] == [
        "esports.search",
        "matches.get_detail",
        "teams.search",
        "teams.get_detail",
        "players.search",
        "players.get_detail",
        "artifact.search",
        "artifact.grep",
        "artifact.read",
    ]
    assert registry.get("matches.get_detail").read_only is False


def test_vnext_runtime_uses_the_shared_llm_configuration() -> None:
    settings = VNextSettings(
        llm_api_key="test-key",
        llm_base_url="https://provider.test/v1",
        llm_model="test-model",
        llm_timeout_seconds=12.5,
        pandascore_token="test-token",
    )

    runtime = build_vnext_runtime(settings)

    assert isinstance(runtime.model, OpenAICompatibleModelClient)
    assert runtime.model.api_key == "test-key"
    assert runtime.model.base_url == "https://provider.test/v1"
    assert runtime.model.model == "test-model"
    assert runtime.model.timeout == 12.5
    assert [tool.name for tool in runtime.tools.list()] == [
        "esports.search",
        "matches.get_detail",
        "teams.search",
        "teams.get_detail",
        "players.search",
        "players.get_detail",
        "artifact.search",
        "artifact.grep",
        "artifact.read",
    ]


def test_vnext_settings_read_shared_llm_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOTAMIND_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DOTAMIND_LLM_BASE_URL", "https://provider.test/v1")
    monkeypatch.setenv("DOTAMIND_LLM_MODEL", "test-model")
    monkeypatch.setenv("DOTAMIND_LLM_TIMEOUT_SECONDS", "12.5")

    settings = VNextSettings.from_env()

    assert settings.llm_api_key == "test-key"
    assert settings.llm_base_url == "https://provider.test/v1"
    assert settings.llm_model == "test-model"
    assert settings.llm_timeout_seconds == 12.5


def test_vnext_settings_use_literal_defaults_without_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app.vnext.composition._VNEXT_ENV_PATH",
        tmp_path / "missing.env",
    )
    for name in (
        "DOTAMIND_LLM_BASE_URL",
        "DOTAMIND_LLM_MODEL",
        "DOTAMIND_PANDASCORE_BASE_URL",
        "DOTAMIND_OPENDOTA_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = VNextSettings.from_env()

    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-chat"
    assert settings.pandascore_base_url == "https://api.pandascore.co"
    assert settings.opendota_base_url == "https://api.opendota.com/api"


def test_registry_uses_esports_locators_for_match_detail_and_artifacts() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, opendota)
    registry = build_vnext_registry(services)

    async def exercise():
        discovery = await registry.execute(
            ToolCall(
                id="event-search",
                name="esports.search",
                arguments={"query": "The International 2026"},
            )
        )
        schedule = await registry.execute(
            ToolCall(
                id="event-matches",
                name="esports.search",
                arguments={
                    "within": next(
                        record["locator"]
                        for record in discovery.content["records"]
                        if record["kind"] == "series"
                        and record["facts"]["name"] == "The International 2026"
                    ),
                    "time_scope": "recent",
                },
            )
        )
        detail = await registry.execute(
            ToolCall(
                id="match-detail",
                name="matches.get_detail",
                arguments={"locator": schedule.content["records"][0]["locator"]},
            )
        )
        return discovery, schedule, detail

    results = asyncio.run(exercise())
    assert all(result.status == "ok" for result in results)
    serialized = json.dumps([result.content for result in results], sort_keys=True)
    for forbidden in (
        "pandascore_id",
        "opendota_id",
        "league_id",
        "raw_response",
        "provider_payload",
    ):
        assert forbidden not in serialized
    assert "20001" not in serialized
    assert "30001" not in serialized
    assert "40001" in serialized


def test_registry_game_locator_selects_only_game_two_without_provider_ids() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )

    async def exercise():
        discovery = await registry.execute(
            ToolCall(
                id="bo3-search",
                name="esports.search",
                arguments={"query": "Grand Final", "time_scope": "recent"},
            )
        )
        games = await registry.execute(
            ToolCall(
                id="bo3-games",
                name="esports.search",
                arguments={
                    "within": next(
                        record["locator"]
                        for record in discovery.content["records"]
                        if record["kind"] == "match"
                        and record["facts"]["name"] == "Grand Final: Alpha vs Beta"
                    )
                },
            )
        )
        game_two_locator = next(
            record["locator"]
            for record in games.content["records"]
            if record["facts"]["position"] == 2
        )
        opendota.detail_calls.clear()
        game_two = await registry.execute(
            ToolCall(
                id="game-two-detail",
                name="matches.get_detail",
                arguments={"locator": game_two_locator},
            )
        )
        return discovery, games, game_two

    discovery, games, game_two = asyncio.run(exercise())

    assert discovery.status == games.status == game_two.status == "ok"
    assert len(games.content["records"]) == 3
    assert len(game_two.content["games"]) == 1
    assert game_two.content["games"][0]["position"] == 2
    assert opendota.detail_calls == [40003]
    assert panda.get_calls == []

    serialized = json.dumps(
        [discovery.content, games.content, game_two.content],
        sort_keys=True,
    )
    for forbidden in (
        "pandascore_id",
        "pandascore_game_id",
        "opendota_id",
        "league_id",
        "raw_response",
        "provider_payload",
    ):
        assert forbidden not in serialized
    for provider_id in ("30004", "72001", "72002", "72003"):
        assert provider_id not in serialized


def test_get_detail_requires_a_source_locator() -> None:
    _, _, panda, opendota = fixture_services()
    series_service, match_service, _, _ = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="invalid-detail",
                name="matches.get_detail",
                arguments={},
            )
        )
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
