"""Lightweight Phase 2 composition root.

Importing this module only defines configuration and factories; no HTTP client
is created until an adapter receives its first request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    ArtifactSearcher,
    ArtifactStore,
    GameSummaryArtifactProducer,
    MemoryArtifactScopeStore,
    MemoryArtifactStore,
)
from app.vnext.artifacts.game_summary_builder_v5 import GameSummaryBuilderV5
from app.vnext.domain.matches.service import MatchService
from app.vnext.domain.players.service import PlayerService
from app.vnext.domain.series.service import SeriesService
from app.vnext.domain.team_player_index import TeamPlayerRefIndex
from app.vnext.domain.teams.service import TeamService
from app.vnext.identity.ability_v4 import AbilityResolverV4
from app.vnext.identity.hero_v4 import HeroResolverV4
from app.vnext.identity.item_v4 import ItemResolverV4
from app.vnext.identity.localized import LocalizedName
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaGameConstructionAdapter,
)
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.domain.matches import register_match_tools
from app.vnext.tools.domain.players import register_player_tools
from app.vnext.tools.domain.series import register_series_tools
from app.vnext.tools.domain.teams import register_team_tools
from app.vnext.tools.registry import ToolRegistry

_VNEXT_ENV_PATH = Path(__file__).with_name(".env")


@dataclass(frozen=True, slots=True)
class VNextSettings:
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 90.0
    pandascore_base_url: str = "https://api.pandascore.co"
    pandascore_token: str | None = None
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_api_key: str | None = None
    pandascore_timeout_seconds: float = 20.0
    opendota_timeout_seconds: float = 20.0
    pandascore_max_page_size: int = 100
    resolution_start_tolerance_seconds: int = 1800
    resolution_duration_tolerance_seconds: int = 5
    artifact_ttl_seconds: int = 7 * 24 * 60 * 60
    trace_ttl_seconds: int = 72 * 60 * 60

    @classmethod
    def from_env(cls) -> VNextSettings:
        defaults = cls()
        file_values = dotenv_values(_VNEXT_ENV_PATH)
        return cls(
            llm_api_key=_env_value("DOTAMIND_LLM_API_KEY", "", file_values) or "",
            llm_base_url=_env_value(
                "DOTAMIND_LLM_BASE_URL",
                defaults.llm_base_url,
                file_values,
            )
            or defaults.llm_base_url,
            llm_model=_env_value("DOTAMIND_LLM_MODEL", defaults.llm_model, file_values)
            or defaults.llm_model,
            llm_timeout_seconds=float(
                _env_value("DOTAMIND_LLM_TIMEOUT_SECONDS", "90", file_values)
            ),
            pandascore_base_url=_env_value(
                "DOTAMIND_PANDASCORE_BASE_URL",
                defaults.pandascore_base_url,
                file_values,
            ),
            pandascore_token=_env_value("DOTAMIND_PANDASCORE_TOKEN", None, file_values),
            opendota_base_url=_env_value(
                "DOTAMIND_OPENDOTA_BASE_URL",
                defaults.opendota_base_url,
                file_values,
            ),
            opendota_api_key=_env_value("DOTAMIND_OPENDOTA_API_KEY", None, file_values),
            pandascore_timeout_seconds=float(
                _env_value("DOTAMIND_PANDASCORE_TIMEOUT_SECONDS", "20", file_values)
            ),
            opendota_timeout_seconds=float(
                _env_value("DOTAMIND_OPENDOTA_TIMEOUT_SECONDS", "20", file_values)
            ),
            pandascore_max_page_size=int(
                _env_value("DOTAMIND_PANDASCORE_MAX_PAGE_SIZE", "100", file_values)
            ),
            resolution_start_tolerance_seconds=int(
                _env_value(
                    "DOTAMIND_RESOLUTION_START_TOLERANCE_SECONDS",
                    "1800",
                    file_values,
                )
            ),
            resolution_duration_tolerance_seconds=int(
                _env_value(
                    "DOTAMIND_RESOLUTION_DURATION_TOLERANCE_SECONDS",
                    "5",
                    file_values,
                )
            ),
            artifact_ttl_seconds=int(
                _env_value("DOTAMIND_VNEXT_ARTIFACT_TTL_SECONDS", "604800", file_values)
            ),
            trace_ttl_seconds=int(
                _env_value("DOTAMIND_VNEXT_TRACE_TTL_SECONDS", "259200", file_values)
            ),
        )


def _env_value(
    name: str,
    default: str | None,
    file_values: dict[str, str | None],
) -> str | None:
    value = os.getenv(name)
    if value is not None:
        return value
    return file_values.get(name, default)


@dataclass(slots=True)
class VNextServices:
    pandascore: PandaScoreAdapter
    opendota: OpenDotaAdapter
    series: SeriesService
    matches: MatchService
    teams: TeamService
    players: PlayerService
    artifact_store: ArtifactStore
    game_summary_producer: GameSummaryArtifactProducer
    artifact_searcher: ArtifactSearcher
    artifact_reader: ArtifactReader
    artifact_grepper: ArtifactGrepper
    artifact_scope_store: MemoryArtifactScopeStore | None = None

    async def aclose(self) -> None:
        await self.pandascore.aclose()
        await self.opendota.aclose()


def _build_game_summary_builder() -> GameSummaryBuilderV5:
    catalog = load_default_catalog_repository()
    return GameSummaryBuilderV5(
        hero_resolver=HeroResolverV4(
            {
                hero.hero_id: LocalizedName(
                    name_en=hero.name_en or None,
                    name_zh=hero.name_zh or None,
                )
                for hero in catalog.list_heroes()
            }
        ),
        item_resolver=ItemResolverV4(
            {
                item.item_id: LocalizedName(
                    name_en=item.name_en or None,
                    name_zh=item.name_zh or None,
                )
                for item in catalog.list_items()
            },
            item_key_to_id=catalog.item_key_index(),
        ),
        ability_resolver=AbilityResolverV4(
            {
                ability.ability_id: LocalizedName(
                    name_en=ability.name_en or None,
                    name_zh=ability.name_zh or None,
                )
                for ability in catalog.list_abilities()
            }
        ),
    )


def build_vnext_services(
    settings: VNextSettings | None = None,
    *,
    pandascore: PandaScoreAdapter | None = None,
    opendota: OpenDotaAdapter | None = None,
    artifact_store: ArtifactStore | None = None,
) -> VNextServices:
    config = settings or VNextSettings.from_env()
    panda_adapter = pandascore or PandaScoreAdapter(
        base_url=config.pandascore_base_url,
        token=config.pandascore_token,
        request_timeout_seconds=config.pandascore_timeout_seconds,
        max_page_size=config.pandascore_max_page_size,
    )
    open_adapter = opendota or OpenDotaAdapter(
        base_url=config.opendota_base_url,
        api_key=config.opendota_api_key,
        request_timeout_seconds=config.opendota_timeout_seconds,
    )
    series_service = SeriesService(panda_adapter)
    team_player_index = TeamPlayerRefIndex()
    team_service = TeamService(panda_adapter, team_player_index)
    player_service = PlayerService(panda_adapter, team_player_index)
    match_service = MatchService(
        panda_adapter,
        open_adapter,
        series_service=series_service,
        team_player_index=team_player_index,
    )
    series_service.set_match_cache(match_service.remember_fixture)
    store = artifact_store if artifact_store is not None else MemoryArtifactStore()
    scope_store = MemoryArtifactScopeStore()
    producer = GameSummaryArtifactProducer(
        opendota=open_adapter,
        construction_adapter=OpenDotaGameConstructionAdapter(),
        builder=_build_game_summary_builder(),
        store=store,
        scope_store=scope_store,
    )
    artifact_searcher = ArtifactSearcher(store)
    artifact_reader = ArtifactReader(store)
    artifact_grepper = ArtifactGrepper(store, scope_store)
    return VNextServices(
        pandascore=panda_adapter,
        opendota=open_adapter,
        series=series_service,
        matches=match_service,
        teams=team_service,
        players=player_service,
        artifact_store=store,
        game_summary_producer=producer,
        artifact_searcher=artifact_searcher,
        artifact_reader=artifact_reader,
        artifact_grepper=artifact_grepper,
        artifact_scope_store=scope_store,
    )


def build_vnext_registry(
    services: VNextServices | None = None,
    *,
    settings: VNextSettings | None = None,
) -> ToolRegistry:
    resolved_services = services or build_vnext_services(settings)
    registry = ToolRegistry()
    register_series_tools(registry, resolved_services.series)
    register_match_tools(
        registry,
        resolved_services.matches,
        resolved_services.game_summary_producer,
    )
    register_team_tools(registry, resolved_services.teams)
    register_player_tools(registry, resolved_services.players)
    register_artifact_tools(
        registry,
        resolved_services.artifact_searcher,
        resolved_services.artifact_reader,
        resolved_services.artifact_grepper,
    )
    return registry


def build_vnext_runtime(
    settings: VNextSettings | None = None,
    *,
    services: VNextServices | None = None,
) -> AgentRuntime:
    """Compose the configured provider-neutral model client and vNext tool surface."""

    config = settings or VNextSettings.from_env()
    model = OpenAICompatibleModelClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        timeout=config.llm_timeout_seconds,
    )
    return AgentRuntime(model, build_vnext_registry(services, settings=config))


__all__ = [
    "VNextServices",
    "VNextSettings",
    "build_vnext_registry",
    "build_vnext_runtime",
    "build_vnext_services",
]
