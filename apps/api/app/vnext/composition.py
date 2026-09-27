"""Composition root for the vNext runtime and its explicit tool surface."""

from __future__ import annotations

import math
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from app.vnext.agent.instructions import AGENT_INSTRUCTION, PRODUCT_INSTRUCTION
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.artifacts.lifecycle import ArtifactObservationTranscriptRewriter
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
from app.vnext.capabilities.player.profile import PlayerProfileInput, PlayerProfileResult
from app.vnext.capabilities.player.recent_games import (
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
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
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.esports import (
    register_league_tool,
    register_match_tool,
    register_player_tool,
    register_series_teams_tool,
    register_series_tool,
    register_team_tool,
    register_tournament_tool,
)
from app.vnext.tools.player.profile import register_player_profile_tool
from app.vnext.tools.player.recent_games import register_player_recent_games_tool
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool

_VNEXT_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"

LeagueSearchService = Callable[[LeagueSearchInput], Awaitable[LeagueSearchResult]]
SeriesSearchService = Callable[[SeriesSearchInput], Awaitable[SeriesSearchResult]]
SeriesTeamsService = Callable[[SeriesTeamsInput], Awaitable[SeriesTeamsResult]]
TournamentSearchService = Callable[[TournamentSearchInput], Awaitable[TournamentSearchResult]]
MatchSearchService = Callable[[MatchSearchInput], Awaitable[MatchSearchResult]]
PlayerSearchService = Callable[[PlayerSearchInput], Awaitable[PlayerSearchResult]]
PlayerProfileService = Callable[[PlayerProfileInput], Awaitable[PlayerProfileResult]]
TeamSearchService = Callable[[TeamSearchInput], Awaitable[TeamSearchResult]]


@dataclass(frozen=True, slots=True)
class VNextSettings:
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 90.0
    pandascore_base_url: str = "https://api.pandascore.co"
    pandascore_token: str = ""
    stratz_graphql_url: str = "https://api.stratz.com/graphql"
    stratz_token: str = field(default="", repr=False)
    stratz_timeout_seconds: float = 20.0
    pandascore_timeout_seconds: float = 20.0
    trace_ttl_seconds: int = 72 * 60 * 60
    test_recording_enabled: bool = False
    agent_limits: AgentLimits = field(default_factory=AgentLimits)

    def __post_init__(self) -> None:
        if not math.isfinite(self.stratz_timeout_seconds) or self.stratz_timeout_seconds <= 0:
            raise ValueError("DOTAMIND_STRATZ_TIMEOUT_SECONDS must be a finite positive number")

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
            trace_ttl_seconds=int(
                _env_value("DOTAMIND_VNEXT_TRACE_TTL_SECONDS", "259200", file_values)
            ),
            test_recording_enabled=_parse_bool_value(
                "VNEXT_TEST_RECORDING_ENABLED",
                False,
                file_values,
            ),
            agent_limits=_agent_limits_from_env(file_values),
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
    ("DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS", "context_output_reserve_tokens"),
    ("DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS", "context_safety_margin_tokens"),
    ("DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN", "context_estimate_bytes_per_token"),
    ("DOTAMIND_COMPACTION_KEEP_RECENT_TOKENS", "compaction_keep_recent_tokens"),
    ("DOTAMIND_COMPACTION_MAX_INPUT_BYTES", "compaction_max_input_bytes"),
    ("DOTAMIND_COMPACTION_RESERVE_TOKENS", "compaction_reserve_tokens"),
    ("DOTAMIND_COMPACTION_MAX_RETRIES", "compaction_max_retries"),
)

_AGENT_DEADLINE_ENV_FIELDS = (
    ("DOTAMIND_EXECUTION_DEADLINE_SECONDS", "deadline_seconds"),
    ("DOTAMIND_ANSWER_DEADLINE_SECONDS", "answer_timeout_seconds"),
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
    return AgentLimits(**values)


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

    async def aclose(self) -> None:
        return None


def build_vnext_services(
    settings: VNextSettings | None = None,
    **_: object,
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
    )


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
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(artifact_store))
    )
    register_artifact_tools(
        registry,
        ArtifactReader(artifact_store, manuals),
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
    if task_state_coordinator is not None:
        register_task_plan_tool(registry, task_state_coordinator)
        register_task_checkpoint_tool(registry, task_state_coordinator)
    return registry


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
    )
    task_state_coordinator = TaskStateCoordinator()
    return AgentRuntime(
        model,
        build_vnext_registry(
            resolved_services,
            settings=config,
            task_state_coordinator=task_state_coordinator,
        ),
        system_instruction=AGENT_INSTRUCTION,
        shared_instruction=PRODUCT_INSTRUCTION,
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
]
