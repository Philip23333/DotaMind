"""
LLM Provider abstraction for v2.1 architecture.

Supports OpenAI-compatible APIs (OpenAI, DeepSeek, etc.) and Anthropic.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Literal, TypedDict

import httpx

logger = logging.getLogger(__name__)

ModelTier = Literal["fast", "balanced", "advanced"]


class ToolCallResult(TypedDict):
    name: str
    arguments: dict[str, Any]


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """Generate a completion from messages."""

    @abstractmethod
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        """Generate a JSON response from messages."""

    @abstractmethod
    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> ToolCallResult | None:
        """Send a function-calling request; return the first tool call or None."""


class OpenAICompatibleProvider(LLMProvider):
    """
    Provider for OpenAI-compatible APIs (OpenAI, DeepSeek, etc.).

    Uses OpenAI's chat completions format.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """Generate a completion."""
        started_at = time.perf_counter()
        finish_reason = "unknown"
        logger.info(
            "LLM complete start provider=openai_compatible model=%s base_url=%s "
            "messages=%s max_tokens=%s temperature=%s",
            self.model,
            self.base_url,
            len(messages),
            max_tokens,
            temperature,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                finish_reason = choice.get("finish_reason", "unknown")
                logger.info(
                    "LLM complete success model=%s elapsed_ms=%s output_chars=%s finish_reason=%s",
                    self.model,
                    round((time.perf_counter() - started_at) * 1000),
                    len(content),
                    finish_reason,
                )
                return content
        except Exception as e:
            logger.error(
                "LLM complete failed model=%s elapsed_ms=%s finish_reason=%s error=%s",
                self.model,
                round((time.perf_counter() - started_at) * 1000),
                finish_reason,
                e,
            )
            raise

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        """Generate a JSON response."""
        started_at = time.perf_counter()
        finish_reason = "unknown"
        logger.info(
            "LLM complete_json start provider=openai_compatible model=%s base_url=%s "
            "messages=%s max_tokens=%s temperature=%s",
            self.model,
            self.base_url,
            len(messages),
            max_tokens,
            temperature,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                finish_reason = choice.get("finish_reason", "unknown")

                # Parse JSON from content
                import json

                parsed = json.loads(content)
                logger.info(
                    "LLM complete_json success model=%s elapsed_ms=%s output_chars=%s "
                    "finish_reason=%s keys=%s",
                    self.model,
                    round((time.perf_counter() - started_at) * 1000),
                    len(content),
                    finish_reason,
                    list(parsed.keys()) if isinstance(parsed, dict) else [],
                )
                return parsed
        except Exception as e:
            logger.error(
                "LLM complete_json failed model=%s elapsed_ms=%s finish_reason=%s error=%s",
                self.model,
                round((time.perf_counter() - started_at) * 1000),
                finish_reason,
                e,
            )
            raise

    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> ToolCallResult | None:
        """Send a function-calling request using the tools payload.

        Returns the first parsed tool call or None when the model
        declines to call any tool.
        """
        import json

        started_at = time.perf_counter()
        logger.info(
            "LLM complete_with_tools start model=%s tools=%s messages=%s",
            self.model,
            [t["function"]["name"] for t in tools],
            len(messages),
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "tools": tools,
                        "tool_choice": "auto",
                    },
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]
                message = choice["message"]

                tool_calls = message.get("tool_calls")
                if not tool_calls:
                    logger.info(
                        "LLM complete_with_tools no_tool_call model=%s elapsed_ms=%s",
                        self.model,
                        round((time.perf_counter() - started_at) * 1000),
                    )
                    return None

                call = tool_calls[0]
                name = call["function"]["name"]
                arguments = json.loads(call["function"]["arguments"])
                logger.info(
                    "LLM complete_with_tools success model=%s elapsed_ms=%s tool=%s",
                    self.model,
                    round((time.perf_counter() - started_at) * 1000),
                    name,
                )
                return {"name": name, "arguments": arguments}
        except Exception as e:
            logger.error(
                "LLM complete_with_tools failed model=%s error=%s",
                self.model,
                e,
            )
            raise


class LLMConfig:
    """Configuration for LLM providers."""

    def __init__(
        self,
        provider: Literal["openai", "deepseek", "anthropic"] = "deepseek",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model


class LLMFactory:
    """Factory for creating LLM providers."""

    @staticmethod
    def create(config: LLMConfig) -> LLMProvider:
        """Create an LLM provider from config."""
        if config.provider in ["openai", "deepseek"]:
            logger.info(
                "LLM provider create provider=%s model=%s base_url=%s api_key_configured=%s",
                config.provider,
                config.model,
                config.base_url,
                bool(config.api_key),
            )
            return OpenAICompatibleProvider(
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
            )
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")


# Singleton instance for the app
_default_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Get the default LLM provider."""
    global _default_provider

    if _default_provider is None:
        # Initialize from environment or default config
        from app.core.config import get_settings

        settings = get_settings()

        config = LLMConfig(
            provider="deepseek",
            api_key=getattr(settings, "llm_api_key", ""),
            base_url=getattr(settings, "llm_base_url", "https://api.deepseek.com"),
            model=getattr(settings, "llm_model", "deepseek-chat"),
        )

        _default_provider = LLMFactory.create(config)
        logger.info(
            "LLM provider initialized provider=%s model=%s enabled_api_key=%s",
            config.provider,
            config.model,
            bool(config.api_key),
        )

    return _default_provider


def set_llm_provider(provider: LLMProvider) -> None:
    """Set the default LLM provider (for testing)."""
    global _default_provider
    _default_provider = provider
