"""
LLM Provider abstraction for v2.1 architecture.

Supports OpenAI-compatible APIs (OpenAI, DeepSeek, etc.) and Anthropic.
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from json import JSONDecodeError
from typing import Any, Literal, TypedDict

import httpx

logger = logging.getLogger(__name__)

ModelTier = Literal["fast", "balanced", "advanced"]


class ToolCallResult(TypedDict):
    name: str
    arguments: dict[str, Any]


class LLMJSONDecodeError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        raw_content: str,
        finish_reason: str,
    ) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.finish_reason = finish_reason


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

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> AsyncIterator[str]:
        """Yield text increments; providers without streaming yield one complete value."""

        yield await self.complete(messages, temperature=temperature, max_tokens=max_tokens)


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
        timeout: float = 90.0,
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
            return choice["message"]["content"]

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        """Generate a JSON response."""
        finish_reason = "unknown"
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
                message = choice["message"]
                content = (message.get("content") or "").strip()
                finish_reason = choice.get("finish_reason", "unknown")
                if not content:
                    raise LLMJSONDecodeError(
                        "Empty LLM JSON response "
                        f"message_keys={list(message.keys())}",
                        raw_content=content,
                        finish_reason=finish_reason,
                    )

                try:
                    parsed = json.loads(content)
                except JSONDecodeError as exc:
                    raise LLMJSONDecodeError(
                        str(exc),
                        raw_content=content,
                        finish_reason=finish_reason,
                    ) from exc
                if not isinstance(parsed, dict):
                    raise ValueError("LLM JSON response was not an object")

                return parsed
        except Exception:
            raise

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> AsyncIterator[str]:
        """Forward OpenAI-compatible SSE text deltas without buffering the answer."""

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
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
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content

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
                    return None

                call = tool_calls[0]
                name = call["function"]["name"]
                arguments = json.loads(call["function"]["arguments"])
                return {"name": name, "arguments": arguments}
        except Exception:
            raise


class LLMConfig:
    """Configuration for LLM providers."""

    def __init__(
        self,
        provider: Literal["openai", "deepseek", "anthropic"] = "deepseek",
        api_key: str = "",
        base_url: str = "",
        model: str = "",
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
            provider=getattr(settings, "llm_provider", "deepseek"),
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
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
