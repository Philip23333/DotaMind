"""Map one discovered Tavily MCP search tool into a source-preserving result."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.vnext.integrations.mcp import DiscoveredMCPTool, MCPRemoteClient, MCPRemoteError
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.json_schema import compile_object_json_schema

TAVILY_SERVICE_ID = "tavily"
TAVILY_REMOTE_SEARCH_TOOL = "tavily_search"


class WebSearchResult(BaseModel):
    """MCP search observations with original content and optional structure."""

    model_config = ConfigDict(extra="forbid")

    service: Literal["tavily"] = TAVILY_SERVICE_ID
    remote_tool_name: str
    retrieved_at: datetime
    structured_content: dict[str, Any] | None = None
    content: list[dict[str, Any]] = Field(default_factory=list)
    empty_result: bool


class TavilyWebSearch:
    def __init__(self, client: MCPRemoteClient, tool: DiscoveredMCPTool) -> None:
        if tool.name != TAVILY_REMOTE_SEARCH_TOOL:
            raise ValueError("discovered MCP tool is not the configured search tool")
        self.client = client
        self.tool = tool
        self._output_validator = (
            compile_object_json_schema(tool.output_schema)
            if tool.output_schema is not None
            else None
        )

    async def search(self, arguments: dict[str, Any]) -> WebSearchResult:
        try:
            result = await self.client.call_tool(self.tool.name, arguments)
        except MCPRemoteError as exc:
            raise _tool_error(exc) from None

        if bool(_get_field(result, "is_error", "isError")):
            raise StructuredToolError(
                "provider_error",
                "web search provider returned an error",
                {"service": TAVILY_SERVICE_ID, "remote_tool_name": self.tool.name},
            )

        structured = _get_field(result, "structured_content", "structuredContent")
        if structured is not None:
            if not isinstance(structured, Mapping):
                raise _invalid_output_error("structured content must be an object")
            structured = dict(structured)
            errors = _schema_errors(self._output_validator, structured)
            if errors:
                raise _invalid_output_error("structured content failed its declared schema", errors)

        raw_content = _get_field(result, "content")
        if not isinstance(raw_content, list):
            raise _invalid_output_error("content must be an array")
        content = [_serialize_content_block(block) for block in raw_content]
        return WebSearchResult(
            remote_tool_name=self.tool.name,
            retrieved_at=datetime.now(timezone.utc),
            structured_content=structured,
            content=content,
            empty_result=_is_empty_search_result(structured, content),
        )


def _tool_error(error: MCPRemoteError) -> StructuredToolError:
    if error.category == "timeout":
        return StructuredToolError(
            "provider_timeout",
            "web search provider timed out",
            {"service": TAVILY_SERVICE_ID},
        )
    if error.status_code is not None:
        return StructuredToolError(
            "provider_http_error",
            "web search provider request failed",
            {"service": TAVILY_SERVICE_ID, "status_code": error.status_code},
        )
    return StructuredToolError(
        "provider_error",
        "web search provider request failed",
        {"service": TAVILY_SERVICE_ID, "category": error.category},
    )


def _invalid_output_error(
    reason: str,
    errors: list[dict[str, Any]] | None = None,
) -> StructuredToolError:
    details: dict[str, Any] = {"service": TAVILY_SERVICE_ID, "reason": reason}
    if errors:
        details["validation_errors"] = errors
    return StructuredToolError(
        "provider_schema_error",
        "web search provider returned an invalid result",
        details,
    )


def _schema_errors(validator: Any, value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if validator is None:
        return []
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        {"loc": list(error.absolute_path), "type": error.validator or "json_schema"}
        for error in errors[:10]
    ]


def _is_empty_search_result(
    structured: dict[str, Any] | None,
    content: list[dict[str, Any]],
) -> bool:
    candidates = [structured] if structured is not None else []
    candidates.extend(
        item["parsed_json"] for item in content if isinstance(item.get("parsed_json"), dict)
    )
    for candidate in candidates:
        results = candidate.get("results")
        if isinstance(results, list):
            return not results

    has_structured_data = bool(structured)
    has_text = any(
        item.get("type") == "text" and bool(str(item.get("text", "")).strip()) for item in content
    )
    return not has_structured_data and not has_text


def _serialize_content_block(block: Any) -> dict[str, Any]:
    raw = _to_json_object(block)
    block_type = raw.get("type")
    if block_type == "text":
        text = raw.get("text")
        if not isinstance(text, str):
            raise _invalid_output_error("text content block has no text")
        serialized = dict(raw)
        try:
            serialized["parsed_json"] = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        return serialized

    if block_type in {"image", "audio", "audio_video"}:
        return {
            "type": block_type,
            **_copy_if_present(raw, "mimeType", "mime_type"),
            "note": f"{block_type} content is not processed or embedded in the conversation.",
        }

    if block_type in {"resource_link", "resourceLink"}:
        return {
            "type": "resource_link",
            **_copy_if_present(raw, "uri", "name", "title", "description", "mimeType"),
            "note": "Resource links are not fetched automatically.",
        }

    if block_type == "resource":
        return _serialize_embedded_resource(raw)

    return {
        "type": "unsupported",
        "source_type": str(block_type or "unknown"),
        "note": "This MCP content type is not processed by web search.",
    }


def _serialize_embedded_resource(raw: dict[str, Any]) -> dict[str, Any]:
    resource = raw.get("resource")
    if not isinstance(resource, Mapping):
        return {"type": "resource", "note": "Invalid embedded MCP resource."}
    text = resource.get("text")
    if isinstance(text, str):
        serialized: dict[str, Any] = {
            "type": "resource_text",
            **_copy_if_present(resource, "uri", "mimeType", "mime_type"),
            "text": text,
        }
        try:
            serialized["parsed_json"] = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        return serialized
    return {
        "type": "resource_binary",
        **_copy_if_present(resource, "uri", "mimeType", "mime_type"),
        "note": "Binary MCP resource content is not embedded in the conversation.",
    }


def _to_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(result, dict):
            return result
    raise _invalid_output_error("content block is not an object")


def _copy_if_present(source: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _get_field(value: Any, snake_name: str, camel_name: str | None = None) -> Any:
    if isinstance(value, Mapping):
        if snake_name in value:
            return value[snake_name]
        return value.get(camel_name) if camel_name is not None else None
    result = getattr(value, snake_name, None)
    return result if result is not None or camel_name is None else getattr(value, camel_name, None)


__all__ = [
    "TAVILY_REMOTE_SEARCH_TOOL",
    "TAVILY_SERVICE_ID",
    "TavilyWebSearch",
    "WebSearchResult",
]
