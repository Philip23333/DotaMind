"""Application-boundary product integration for vNext."""

from app.vnext.product.chat import VNextChatService
from app.vnext.product.context import ConversationContextBuilder

__all__ = ["ConversationContextBuilder", "VNextChatService"]
