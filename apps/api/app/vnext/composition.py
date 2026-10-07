"""Composition root for the vNext runtime and its explicit tool surface."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from app.integrations.valve.catalog_repository import (
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.vnext.agent.instructions import (
    AGENT_INSTRUCTION,
    PRODUCT_INSTRUCTION,
    WEB_SEARCH_INSTRUCTION,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactLimits,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.artifacts.lifecycle import ArtifactObservationTranscriptRewriter
from app.vnext.capabilities.catalog.lookup import CatalogLookupInput, CatalogLookupResult
from app.vnext.capabilities.esports.league import LeagueSearchInput, LeagueSearchResult
from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.capabilities.esports.player import PlayerSearchInput, PlayerSearchResult
from app.vnext.capabilities.esports.series import (
    SeriesSearchInput,
    SeriesSearchResult,
    SeriesTeamsInput,
    SeriesTeamsResult,
)
from app.vnext.capabilities.esports.team import TeamSearchInput, TeamSearchResult
from app.vnext.capabilities.esports.tournament import TournamentSearchInput, TournamentSearchResult
from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.capabilities.hero.guide import HeroGuideInput, HeroGuideResult
from app.vnext.capabilities.hero.service import HeroGuideService
from app.vnext.capabilities.player.profile import PlayerProfileInput, PlayerProfileResult
from app.vnext.capabilities.player.recent_games import (
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)
from app.vnext.catalog import EntityNameResolver
from app.vnext.data_updates.image_reader import ImageManifestReader
from app.vnext.hero_guides.cache import HeroGuideReader
from app.vnext.homepage.recent_series import (
    HomepageRecentSeriesService,
    RecentSeriesCache,
)
from app.vnext.integrations.mcp import MCPRemoteClient, MCPRemoteError
from app.vnext.llm.diagnostic_limits import ModelDiagnosticLimits
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.providers.opendota import OpenDotaClient, OpenDotaGameDetailAdapter
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.league_adapter import PandaScoreLeagueAdapter
from app.vnext.providers.pandascore.match_adapter import PandaScoreMatchAdapter
from app.vnext.providers.pandascore.player_adapter import PandaScorePlayerAdapter
from app.vnext.providers.pandascore.series_adapter import PandaScoreSeriesAdapter
from app.vnext.providers.pandascore.team_adapter import PandaScoreTeamAdapter
from app.vnext.providers.pandascore.tournament_adapter import PandaScoreTournamentAdapter
from app.vnext.providers.stratz import (
    StratzGraphQLClient,
    StratzPlayerProfileAdapter,
    StratzPlayerRecentGamesAdapter,
)
from app.vnext.providers.tavily import TavilyWebSearch
from app.vnext.providers.tavily.web_search import (
    TAVILY_REMOTE_SEARCH_TOOL,
)
from app.vnext.providers.valve.catalog_lookup import ValveCatalogLookupAdapter
from app.vnext.session_limits import SessionContextLimits
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.catalog import register_catalog_lookup_tool
from app.vnext.tools.esports import (
    register_league_tool,
    register_match_tool,
    register_player_tool,
    register_series_teams_tool,
    register_series_tool,
    register_team_tool,
    register_tournament_tool,
)
from app.vnext.tools.game.detail import register_game_detail_tool
from app.vnext.tools.hero.guide import register_hero_guide_tool
from app.vnext.tools.json_schema import compile_object_json_schema
from app.vnext.tools.player.profile import register_player_profile_tool
from app.vnext.tools.player.recent_games import register_player_recent_games_tool
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool
from app.vnext.tools.web import register_web_search_tool

_VNEXT_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
logger = logging.getLogger(__name__)

LeagueSearchService = Callable[[LeagueSearchInput], Awaitable[LeagueSearchResult]]
SeriesSearchService = Callable[[SeriesSearchInput], Awaitable[SeriesSearchResult]]
SeriesTeamsService = Callable[[SeriesTeamsInput], Awaitable[SeriesTeamsResult]]
TournamentSearchService = Callable[[TournamentSearchInput], Awaitable[TournamentSearchResult]]
MatchSearchService = Callable[[MatchSearchInput], Awaitable[MatchSearchResult]]
PlayerSearchService = Callable[[PlayerSearchInput], Awaitable[PlayerSearchResult]]
TeamSearchService = Callable[[TeamSearchInput], Awaitable[TeamSearchResult]]
PlayerProfileService = Callable[[PlayerProfileInput], Awaitable[PlayerProfileResult]]
GameDetailService = Callable[[GameDetailInput], Awaitable[GameDetailResult]]
CatalogLookupService = Callable[[CatalogLookupInput], Awaitable[CatalogLookupResult]]
HeroGuideLookup = Callable[[HeroGuideInput], Awaitable[HeroGuideResult]]


@dataclass(frozen=True, slots=True)
class VNextSettings:
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 90.0
    pandascore_base_url: str = "https://api.pandascore.co"
    pandascore_token: str = ""
    pandascore_timeout_seconds: float = 20.0
    stratz_graphql_url: str = "https://api.stratz.com/graphql"
    stratz_token: str = field(default="", repr=False)
    stratz_timeout_seconds: float = 20.0
    opendota_enabled: bool = False
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_api_key: str = field(default="", repr=False)
    opendota_timeout_seconds: float = 20.0
    tavily_mcp_enabled: bool = False
    tavily_mcp_url: str = "https://mcp.tavily.com/mcp"
    tavily_api_key: str = field(default="", repr=False)
    tavily_mcp_timeout_seconds: float = 30.0
    trace_ttl_seconds: int = 72 * 60 * 60
    test_recording_enabled: bool = False
    data_dir: Path | None = None
    agent_limits: AgentLimits = field(default_factory=AgentLimits)
    artifact_limits: ArtifactLimits = field(default_factory=ArtifactLimits)
    session_context_limits: SessionContextLimits = field(default_factory=SessionContextLimits)
    model_diagnostic_limits: ModelDiagnosticLimits = field(
        default_factory=ModelDiagnosticLimits
    )

    def __post_init__(self) -> None:
        if self.data_dir is not None and (
            not isinstance(self.data_dir, Path) or not self.data_dir.is_absolute()
        ):
            raise ValueError("DOTAMIND_DATA_DIR must be an absolute path when set")
        if not math.isfinite(self.stratz_timeout_seconds) or self.stratz_timeout_seconds <= 0:
            raise ValueError("DOTAMIND_STRATZ_TIMEOUT_SECONDS must be a finite positive number")
        if (
            isinstance(self.opendota_timeout_seconds, bool)
            or not math.isfinite(self.opendota_timeout_seconds)
            or self.opendota_timeout_seconds <= 0
        ):
            raise ValueError("DOTAMIND_OPENDOTA_TIMEOUT_SECONDS must be a finite positive number")
        if not math.isfinite(self.tavily_mcp_timeout_seconds) or (
            self.tavily_mcp_timeout_seconds <= 0
        ):
            raise ValueError("DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS must be a finite positive number")

    @classmethod
    def from_env(cls) -> VNextSettings:
        defaults = cls()
        file_values = dotenv_values(_VNEXT_ENV_PATH)
        return cls(
            llm_api_key=_env_value("DOTAMIND_LLM_API_KEY", "", file_values) or "",
            llm_base_url=_env_value("DOTAMIND_LLM_BASE_URL", defaults.llm_base_url, file_values)
            or defaults.llm_base_url,
            llm_model=_env_value("DOTAMIND_LLM_MODEL", defaults.llm_model, file_values)
            or defaults.llm_model,
            llm_timeout_seconds=float(
                _env_value("DOTAMIND_LLM_TIMEOUT_SECONDS", "90", file_values)
            ),
            pandascore_base_url=_env_value(
                "DOTAMIND_PANDASCORE_BASE_URL", defaults.pandascore_base_url, file_values
            )
            or defaults.pandascore_base_url,
            pandascore_token=_env_value(
                "DOTAMIND_PANDASCORE_TOKEN", defaults.pandascore_token, file_values
            )
            or defaults.pandascore_token,
            pandascore_timeout_seconds=float(
                _env_value("DOTAMIND_PANDASCORE_TIMEOUT_SECONDS", "20", file_values)
            ),
            stratz_graphql_url=(
                _env_value(
                    "DOTAMIND_STRATZ_GRAPHQL_URL",
                    defaults.stratz_graphql_url,
                    file_values,
                )
                or defaults.stratz_graphql_url
            ),
            stratz_token=_env_value("DOTAMIND_STRATZ_TOKEN", "", file_values) or "",
            stratz_timeout_seconds=_parse_positive_finite_float(
                "DOTAMIND_STRATZ_TIMEOUT_SECONDS",
                _env_value("DOTAMIND_STRATZ_TIMEOUT_SECONDS", "20", file_values) or "",
            ),
            opendota_enabled=_parse_bool_value(
                "DOTAMIND_OPENDOTA_ENABLED",
                False,
                file_values,
            ),
            opendota_base_url=(
                _env_value(
                    "DOTAMIND_OPENDOTA_BASE_URL",
                    defaults.opendota_base_url,
                    file_values,
                )
                or defaults.opendota_base_url
            ),
            opendota_api_key=_env_value("DOTAMIND_OPENDOTA_API_KEY", "", file_values) or "",
            opendota_timeout_seconds=_parse_positive_finite_float(
                "DOTAMIND_OPENDOTA_TIMEOUT_SECONDS",
                _env_value("DOTAMIND_OPENDOTA_TIMEOUT_SECONDS", "20", file_values) or "",
            ),
            tavily_mcp_enabled=_parse_bool_value(
                "DOTAMIND_TAVILY_MCP_ENABLED",
                False,
                file_values,
            ),
            tavily_mcp_url=_env_value(
                "DOTAMIND_TAVILY_MCP_URL",
                defaults.tavily_mcp_url,
                file_values,
            )
            or defaults.tavily_mcp_url,
            tavily_api_key=_env_value("DOTAMIND_TAVILY_API_KEY", "", file_values) or "",
            tavily_mcp_timeout_seconds=_parse_positive_finite_float(
                "DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS",
                _env_value("DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS", "30", file_values),
            ),
            trace_ttl_seconds=int(
                _env_value("DOTAMIND_VNEXT_TRACE_TTL_SECONDS", "259200", file_values)
            ),
            test_recording_enabled=_parse_bool_value(
                "VNEXT_TEST_RECORDING_ENABLED",
                False,
                file_values,
            ),
            data_dir=_parse_data_dir(
                _env_value("DOTAMIND_DATA_DIR", None, file_values)
            ),
            agent_limits=_agent_limits_from_env(file_values),
            artifact_limits=_artifact_limits_from_env(file_values),
            session_context_limits=_session_context_limits_from_env(file_values),
            model_diagnostic_limits=_model_diagnostic_limits_from_env(file_values),
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


def _parse_data_dir(value: str | None) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("DOTAMIND_DATA_DIR must be a non-empty absolute path when set")
    path = Path(value.strip())
    if not path.is_absolute():
        raise ValueError("DOTAMIND_DATA_DIR must be an absolute path when set")
    return path


def build_image_manifest_reader(data_dir: Path | None) -> ImageManifestReader | None:
    """Enable persistent answer images only when the shared data directory is configured."""

    return ImageManifestReader(data_dir) if data_dir is not None else None


def _parse_bool_value(
    name: str,
    default: bool,
    file_values: dict[str, str | None],
) -> bool:
    value = _env_value(name, "true" if default else "false", file_values)
    normalized = (value or "").strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"{name} must be one of true, false, 1, or 0")


_AGENT_LIMIT_ENV_FIELDS = (
    ("DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS", "context_safety_margin_tokens"),
    ("DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN", "context_estimate_bytes_per_token"),
    ("DOTAMIND_COMPACTION_KEEP_RECENT_TOKENS", "compaction_keep_recent_tokens"),
    ("DOTAMIND_COMPACTION_RESERVE_TOKENS", "compaction_reserve_tokens"),
    ("DOTAMIND_COMPACTION_MAX_RETRIES", "compaction_max_retries"),
)

_AGENT_DEADLINE_ENV_FIELDS = (
    ("DOTAMIND_EXECUTION_DEADLINE_SECONDS", "deadline_seconds"),
    ("DOTAMIND_ANSWER_DEADLINE_SECONDS", "answer_timeout_seconds"),
    ("DOTAMIND_TOOL_TIMEOUT_SECONDS", "default_tool_timeout"),
)


def _agent_limits_from_env(file_values: dict[str, str | None]) -> AgentLimits:
    window_name = "DOTAMIND_CONTEXT_WINDOW_TOKENS"
    window_value = _env_value(window_name, None, file_values)
    values: dict[str, int | float | None] = {
        "context_window_tokens": _parse_window_value(window_name, window_value),
    }
    for name, field_name in _AGENT_DEADLINE_ENV_FIELDS:
        raw_value = _env_value(name, None, file_values)
        if raw_value is not None:
            values[field_name] = _parse_positive_finite_float(name, raw_value)
    for name, field_name in _AGENT_LIMIT_ENV_FIELDS:
        raw_value = _env_value(name, None, file_values)
        if raw_value is None:
            if name in file_values:
                raise ValueError(f"{name} must be an integer")
            continue
        values[field_name] = _parse_required_integer(name, raw_value)
    test_trigger_name = "DOTAMIND_CONTEXT_COMPACTION_TEST_TRIGGER_PERCENT"
    test_trigger_value = _env_value(test_trigger_name, None, file_values)
    if test_trigger_value is not None and test_trigger_value.strip():
        values["context_compaction_test_trigger_percent"] = _parse_required_integer(
            test_trigger_name,
            test_trigger_value,
        )
    model_output_name = "DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS"
    model_output_value = _env_value(model_output_name, None, file_values)
    if model_output_value is not None and model_output_value.strip():
        values["compaction_model_max_output_tokens"] = _parse_required_integer(
            model_output_name,
            model_output_value,
        )
    for name, field_name in (
        ("DOTAMIND_MODEL_MAX_OUTPUT_TOKENS", "model_max_output_tokens"),
        ("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "application_max_output_tokens"),
    ):
        raw_value = _env_value(name, None, file_values)
        if raw_value is not None and raw_value.strip():
            values[field_name] = _parse_positive_integer(name, raw_value)
    if (
        values.get("model_max_output_tokens") is None
        and values.get("application_max_output_tokens") is None
    ):
        raise ValueError(
            "configure DOTAMIND_MODEL_MAX_OUTPUT_TOKENS or "
            "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS before model calls"
        )
    return AgentLimits(**values)


def _artifact_limits_from_env(file_values: dict[str, str | None]) -> ArtifactLimits:
    defaults = ArtifactLimits()
    values: dict[str, int] = {}
    for name, field_name in (
        ("DOTAMIND_TOOL_INLINE_MAX_BYTES", "inline_max_bytes"),
        ("DOTAMIND_TOOL_OBSERVATION_MAX_BYTES", "observation_max_bytes"),
    ):
        default = getattr(defaults, field_name)
        raw_value = _env_value(name, str(default), file_values)
        if raw_value is None:
            if name in file_values:
                raise ValueError(f"{name} must be a positive integer")
            raw_value = str(default)
        values[field_name] = _parse_positive_integer(name, raw_value)
    return ArtifactLimits(**values)


def _session_context_limits_from_env(
    file_values: dict[str, str | None],
) -> SessionContextLimits:
    defaults = SessionContextLimits()
    values: dict[str, int] = {}
    for name, field_name in (
        ("DOTAMIND_HISTORY_BOOTSTRAP_MAX_TURNS", "history_bootstrap_max_turns"),
        ("DOTAMIND_HISTORY_BOOTSTRAP_MAX_CHARS", "history_bootstrap_max_chars"),
        ("DOTAMIND_ARTIFACT_LOCATOR_CAPACITY", "artifact_locator_capacity"),
        ("DOTAMIND_ARTIFACT_LOCATOR_HINT_CHARS", "artifact_locator_hint_chars"),
    ):
        default = getattr(defaults, field_name)
        raw_value = _env_value(name, str(default), file_values)
        if raw_value is None:
            if name in file_values:
                raise ValueError(f"{name} must be a positive integer")
            raw_value = str(default)
        values[field_name] = _parse_positive_integer(name, raw_value)
    return SessionContextLimits(**values)


def _model_diagnostic_limits_from_env(
    file_values: dict[str, str | None],
) -> ModelDiagnosticLimits:
    defaults = ModelDiagnosticLimits()
    values: dict[str, int] = {}
    for name, field_name in (
        ("DOTAMIND_DIAGNOSTIC_MAX_TOOL_CALLS", "max_tool_calls"),
        ("DOTAMIND_DIAGNOSTIC_ARGUMENT_MAX_BYTES", "argument_max_bytes"),
        ("DOTAMIND_DIAGNOSTIC_TOTAL_ARGUMENT_MAX_BYTES", "total_argument_max_bytes"),
        ("DOTAMIND_DIAGNOSTIC_ARGUMENT_EDGE_BYTES", "argument_edge_bytes"),
    ):
        default = getattr(defaults, field_name)
        raw_value = _env_value(name, str(default), file_values)
        if raw_value is None:
            if name in file_values:
                raise ValueError(f"{name} must be a positive integer")
            raw_value = str(default)
        values[field_name] = _parse_positive_integer(name, raw_value)
    return ModelDiagnosticLimits(**values)


def _parse_positive_finite_float(name: str, value: str) -> float:
    try:
        parsed = float(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


def _parse_window_value(name: str, value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return _parse_integer(name, value)


def _parse_required_integer(name: str, value: str) -> int:
    if not value.strip():
        raise ValueError(f"{name} must be an integer")
    return _parse_integer(name, value)


def _parse_positive_integer(name: str, value: str) -> int:
    parsed = _parse_required_integer(name, value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _parse_integer(name: str, value: str) -> int:
    stripped = value.strip()
    signless = stripped[1:] if stripped[:1] in {"+", "-"} else stripped
    if not signless or not signless.isascii() or not signless.isdecimal():
        raise ValueError(f"{name} must be an integer")
    try:
        return int(stripped, 10)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(slots=True)
class VNextServices:
    """Lifecycle container retained for the application composition seam."""

    league_search: LeagueSearchService | None = None
    series_search: SeriesSearchService | None = None
    series_teams: SeriesTeamsService | None = None
    tournament_search: TournamentSearchService | None = None
    match_search: MatchSearchService | None = None
    team_search: TeamSearchService | None = None
    player_search: PlayerSearchService | None = None
    player_profile: PlayerProfileService | None = None
    player_recent_games: (
        Callable[[PlayerRecentGamesInput], Awaitable[PlayerRecentGamesResult]] | None
    ) = None
    game_detail: GameDetailService | None = None
    hero_guide: HeroGuideLookup | None = None
    homepage_recent_series: HomepageRecentSeriesService | None = None
    catalog_lookup: CatalogLookupService | None = None
    tavily_web_search: TavilyWebSearch | None = None

    async def aclose(self) -> None:
        if self.homepage_recent_series is not None:
            await self.homepage_recent_series.aclose()


def build_vnext_services(
    settings: VNextSettings | None = None,
    *,
    hero_guide_cache: HeroGuideReader | None = None,
    recent_series_cache: RecentSeriesCache | None = None,
    catalog_repository_provider: Callable[[], DotaCatalogRepository] | None = None,
) -> VNextServices:
    config = settings or VNextSettings.from_env()
    client = PandaScoreClient(
        base_url=config.pandascore_base_url,
        token=config.pandascore_token,
        timeout_seconds=config.pandascore_timeout_seconds,
    )
    league_adapter = PandaScoreLeagueAdapter(client)
    series_adapter = PandaScoreSeriesAdapter(client)
    tournament_adapter = PandaScoreTournamentAdapter(client)
    match_adapter = PandaScoreMatchAdapter(client)
    team_adapter = PandaScoreTeamAdapter(client)
    player_adapter = PandaScorePlayerAdapter(client)
    homepage_recent_series = None
    if recent_series_cache is not None:
        homepage_recent_series = HomepageRecentSeriesService(
            read_lifecycle=series_adapter.list_by_lifecycle,
            search_team=team_adapter.search,
            list_tournament_winner_sources=tournament_adapter.list_winner_sources,
            cache=recent_series_cache,
        )
    player_profile: PlayerProfileService | None = None
    player_recent_games: (
        Callable[[PlayerRecentGamesInput], Awaitable[PlayerRecentGamesResult]] | None
    ) = None
    stratz_token = config.stratz_token.strip()
    if stratz_token:
        stratz_client = StratzGraphQLClient(
            graphql_url=config.stratz_graphql_url,
            token=stratz_token,
            timeout_seconds=config.stratz_timeout_seconds,
        )
        player_profile = StratzPlayerProfileAdapter(stratz_client).get_profile
        player_recent_games = StratzPlayerRecentGamesAdapter(stratz_client).get_recent_games
    game_detail: GameDetailService | None = None
    if config.opendota_enabled:
        opendota_client = OpenDotaClient(
            base_url=config.opendota_base_url,
            api_key=config.opendota_api_key,
            timeout_seconds=config.opendota_timeout_seconds,
        )
        game_detail = OpenDotaGameDetailAdapter(opendota_client).get_game_detail
    repository_provider = (
        catalog_repository_provider
        if catalog_repository_provider is not None
        else load_default_catalog_repository
    )
    catalog_lookup = ValveCatalogLookupAdapter(repository_provider).lookup
    hero_guide: HeroGuideLookup | None = None
    if hero_guide_cache is not None:
        hero_guide = HeroGuideService(
            hero_guide_cache,
            lambda: EntityNameResolver(repository_provider()),
        ).get_guide
    return VNextServices(
        league_search=league_adapter.search,
        series_search=series_adapter.search,
        series_teams=series_adapter.teams,
        tournament_search=tournament_adapter.search,
        match_search=match_adapter.search,
        team_search=team_adapter.search,
        player_search=player_adapter.search,
        player_profile=player_profile,
        player_recent_games=player_recent_games,
        game_detail=game_detail,
        hero_guide=hero_guide,
        homepage_recent_series=homepage_recent_series,
        catalog_lookup=catalog_lookup,
    )


async def initialize_vnext_services(
    settings: VNextSettings | None = None,
    services: VNextServices | None = None,
) -> VNextServices:
    """Explicitly discover optional remote MCP tools before Runtime creation."""

    config = settings or VNextSettings.from_env()
    resolved_services = services or build_vnext_services(config)
    if not config.tavily_mcp_enabled:
        return resolved_services
    api_key = config.tavily_api_key.strip()
    if not api_key:
        logger.error(
            "Tavily MCP is enabled but DOTAMIND_TAVILY_API_KEY is missing; web.search disabled"
        )
        return resolved_services

    try:
        client = MCPRemoteClient(
            url=config.tavily_mcp_url,
            api_key=api_key,
            timeout_seconds=config.tavily_mcp_timeout_seconds,
        )
        remote_tools = await client.list_tools()
        matches = [tool for tool in remote_tools if tool.name == TAVILY_REMOTE_SEARCH_TOOL]
        if len(matches) != 1:
            logger.error(
                "Tavily MCP search discovery expected one %s tool; web.search disabled",
                TAVILY_REMOTE_SEARCH_TOOL,
            )
            return resolved_services
        search_tool = TavilyWebSearch(client, matches[0])
        compile_object_json_schema(search_tool.tool.input_schema)
    except MCPRemoteError as exc:
        if exc.status_code is None:
            logger.error("Tavily MCP discovery failed: category=%s", exc.category)
        else:
            logger.error(
                "Tavily MCP discovery failed: category=%s status_code=%s",
                exc.category,
                exc.status_code,
            )
        return resolved_services
    except Exception as exc:
        logger.error("Tavily MCP discovery disabled web.search (%s)", type(exc).__name__)
        return resolved_services

    resolved_services.tavily_web_search = search_tool
    logger.info("Tavily MCP search discovered; web.search is available")
    return resolved_services


def build_vnext_registry(
    services: VNextServices | None = None,
    *,
    settings: VNextSettings | None = None,
    task_state_coordinator: TaskStateCoordinator | None = None,
) -> ToolRegistry:
    config = settings or VNextSettings.from_env()
    resolved_services = services or build_vnext_services(config)
    artifact_store = SessionArtifactStore()
    manuals = ManualResolver()
    artifact_limits = config.artifact_limits
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(
            ToolResponseExternalizer(
                artifact_store,
                inline_max_bytes=artifact_limits.inline_max_bytes,
            ),
            observation_max_bytes=artifact_limits.observation_max_bytes,
        )
    )
    register_artifact_tools(
        registry,
        ArtifactReader(
            artifact_store,
            manuals,
            observation_max_bytes=artifact_limits.observation_max_bytes,
        ),
        ArtifactGrepper(artifact_store, manuals),
    )
    if resolved_services.league_search is not None:
        register_league_tool(registry, resolved_services.league_search)
    if resolved_services.series_search is not None:
        register_series_tool(registry, resolved_services.series_search)
    if resolved_services.series_teams is not None:
        register_series_teams_tool(registry, resolved_services.series_teams)
    if resolved_services.tournament_search is not None:
        register_tournament_tool(registry, resolved_services.tournament_search)
    if resolved_services.match_search is not None:
        register_match_tool(registry, resolved_services.match_search)
    if resolved_services.team_search is not None:
        register_team_tool(registry, resolved_services.team_search)
    if resolved_services.player_search is not None:
        register_player_tool(registry, resolved_services.player_search)
    if resolved_services.player_profile is not None:
        register_player_profile_tool(registry, resolved_services.player_profile)
    if resolved_services.player_recent_games is not None:
        register_player_recent_games_tool(registry, resolved_services.player_recent_games)
    if config.opendota_enabled and resolved_services.game_detail is not None:
        register_game_detail_tool(registry, resolved_services.game_detail)
    if resolved_services.hero_guide is not None:
        register_hero_guide_tool(registry, resolved_services.hero_guide)
    if resolved_services.catalog_lookup is not None:
        register_catalog_lookup_tool(registry, resolved_services.catalog_lookup)
    if resolved_services.tavily_web_search is not None:
        register_web_search_tool(registry, resolved_services.tavily_web_search)
    if task_state_coordinator is not None:
        register_task_plan_tool(registry, task_state_coordinator)
        register_task_checkpoint_tool(registry, task_state_coordinator)
    return registry


def _format_enabled_tool_inventory(registry: ToolRegistry) -> str:
    names = [tool.name for tool in registry.list()]
    listing = "\n".join(f"- {name}" for name in names) if names else "none"
    return (
        f"Enabled tools for this run:\n{listing}\n\n"
        "This inventory describes enabled capabilities, not permission to call tools in\n"
        "every stage. During the answer stage, tool calls are disabled because execution\n"
        "has ended; this does not mean these capabilities are absent from the product.\n"
        "The inventory is not evidence that any lookup succeeded."
    )


def build_vnext_runtime(
    settings: VNextSettings | None = None,
    *,
    services: VNextServices | None = None,
) -> AgentRuntime:
    """Compose the configured model client and current vNext tool surface."""

    config = settings or VNextSettings.from_env()
    limits = config.agent_limits.model_copy(deep=True)
    resolved_services = services or build_vnext_services(config)
    model = OpenAICompatibleModelClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        timeout=config.llm_timeout_seconds,
        diagnostic_limits=config.model_diagnostic_limits,
    )
    task_state_coordinator = TaskStateCoordinator()
    registry = build_vnext_registry(
        resolved_services,
        settings=config,
        task_state_coordinator=task_state_coordinator,
    )
    shared_instruction = PRODUCT_INSTRUCTION
    if resolved_services.tavily_web_search is not None:
        shared_instruction = f"{PRODUCT_INSTRUCTION}\n\n{WEB_SEARCH_INSTRUCTION}"
    shared_instruction = f"{shared_instruction}\n\n{_format_enabled_tool_inventory(registry)}"
    return AgentRuntime(
        model,
        registry,
        system_instruction=AGENT_INSTRUCTION,
        shared_instruction=shared_instruction,
        limits=limits,
        transcript_rewriter=ArtifactObservationTranscriptRewriter(),
        task_state_coordinator=task_state_coordinator,
    )


__all__ = [
    "VNextServices",
    "VNextSettings",
    "build_vnext_registry",
    "build_vnext_runtime",
    "build_vnext_services",
    "initialize_vnext_services",
]
