"""Provider-neutral model protocol and transport adapters."""

from app.vnext.llm.openai_compatible import (
    MalformedToolArgumentsError,
    OpenAICompatibleAdapter,
    OpenAICompatibleModelClient,
    ProviderHTTPError,
    ProviderProtocolError,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ModelTool,
    StreamingModelClient,
    SystemMessage,
    ToolCall,
    ToolError,
    ToolErrorCode,
    ToolResultMessage,
    UserMessage,
)

__all__ = [
    "AssistantMessage",
    "FinalMessage",
    "MalformedToolArgumentsError",
    "Message",
    "ModelClient",
    "ModelRequest",
    "ModelResponse",
    "ModelTextDelta",
    "ModelTool",
    "OpenAICompatibleAdapter",
    "OpenAICompatibleModelClient",
    "ProviderHTTPError",
    "ProviderProtocolError",
    "SystemMessage",
    "StreamingModelClient",
    "ToolError",
    "ToolErrorCode",
    "ToolCall",
    "ToolResultMessage",
    "UserMessage",
]
