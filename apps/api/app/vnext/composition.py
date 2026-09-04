"""Composition root for the artifact-only vNext runtime."""

from __future__ import annotations

import os
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
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.registry import ToolRegistry

_VNEXT_ENV_PATH = Path(__file__).with_name(".env")


@dataclass(frozen=True, slots=True)
class VNextSettings:
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 90.0
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

    async def aclose(self) -> None:
        return None


def build_vnext_services(
    settings: VNextSettings | None = None,
    **_: object,
) -> VNextServices:
    del settings
    return VNextServices()


def build_vnext_registry(
    services: VNextServices | None = None,
    *,
    settings: VNextSettings | None = None,
) -> ToolRegistry:
    del services, settings
    registry = ToolRegistry()
    artifact_store = SessionArtifactStore()
    manuals = ManualResolver()
    register_artifact_tools(
        registry,
        ArtifactReader(artifact_store, manuals),
        ArtifactGrepper(artifact_store, manuals),
    )
    return registry


def build_vnext_runtime(
    settings: VNextSettings | None = None,
    *,
    services: VNextServices | None = None,
) -> AgentRuntime:
    """Compose the configured model client and artifact-only tool surface."""

    del services
    config = settings or VNextSettings.from_env()
    model = OpenAICompatibleModelClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        timeout=config.llm_timeout_seconds,
    )
    return AgentRuntime(
        model,
        build_vnext_registry(settings=config),
        system_instruction=AGENT_INSTRUCTION,
    )


__all__ = [
    "VNextServices",
    "VNextSettings",
    "build_vnext_registry",
    "build_vnext_runtime",
    "build_vnext_services",
]
