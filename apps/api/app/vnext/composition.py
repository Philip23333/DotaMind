"""Composition root for the vNext runtime and its explicit tool surface."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.vnext.agent.instructions import AGENT_INSTRUCTION
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
)
from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.match_adapter import PandaScoreMatchAdapter
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.esports import register_match_tool
from app.vnext.tools.registry import ToolRegistry

_VNEXT_ENV_PATH = Path(__file__).with_name(".env")


@dataclass(frozen=True, slots=True)
class VNextSettings:
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 90.0
    pandascore_base_url: str = "https://api.pandascore.co"
    pandascore_token: str = ""
    pandascore_timeout_seconds: float = 20.0
    trace_ttl_seconds: int = 72 * 60 * 60

    @classmethod
    def from_env(cls) -> VNextSettings:
        defaults = cls()
        file_values = dotenv_values(_VNEXT_ENV_PATH)
        return cls(
            llm_api_key=_env_value("DOTAMIND_LLM_API_KEY", "", file_values) or "",
            llm_base_url=_env_value(
                "DOTAMIND_LLM_BASE_URL", defaults.llm_base_url, file_values
            )
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
    """Lifecycle container retained for the application composition seam."""

    match_search: Callable[[MatchSearchInput], Awaitable[MatchSearchResult]] | None = None

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
    adapter = PandaScoreMatchAdapter(client)
    return VNextServices(match_search=adapter.search)


def build_vnext_registry(
    services: VNextServices | None = None,
    *,
    settings: VNextSettings | None = None,
) -> ToolRegistry:
    config = settings or VNextSettings.from_env()
    resolved_services = services or build_vnext_services(config)
    registry = ToolRegistry()
    artifact_store = SessionArtifactStore()
    manuals = ManualResolver()
    register_artifact_tools(
        registry,
        ArtifactReader(artifact_store, manuals),
        ArtifactGrepper(artifact_store, manuals),
    )
    if resolved_services.match_search is not None:
        register_match_tool(registry, resolved_services.match_search)
    return registry


def build_vnext_runtime(
    settings: VNextSettings | None = None,
    *,
    services: VNextServices | None = None,
) -> AgentRuntime:
    """Compose the configured model client and current vNext tool surface."""

    config = settings or VNextSettings.from_env()
    resolved_services = services or build_vnext_services(config)
    model = OpenAICompatibleModelClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        timeout=config.llm_timeout_seconds,
    )
    return AgentRuntime(
        model,
        build_vnext_registry(resolved_services, settings=config),
        system_instruction=AGENT_INSTRUCTION,
    )


__all__ = [
    "VNextServices",
    "VNextSettings",
    "build_vnext_registry",
    "build_vnext_runtime",
    "build_vnext_services",
]
