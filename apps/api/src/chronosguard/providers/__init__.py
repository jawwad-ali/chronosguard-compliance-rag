"""AI provider abstraction — the rest of the codebase never imports `openai`."""

from chronosguard.providers.base import ChatProvider, EmbeddingProvider, TokenUsage
from chronosguard.providers.factory import get_chat_provider, get_embedding_provider
from chronosguard.providers.fake import FakeChat, FakeEmbeddings

__all__ = [
    "ChatProvider",
    "EmbeddingProvider",
    "FakeChat",
    "FakeEmbeddings",
    "TokenUsage",
    "get_chat_provider",
    "get_embedding_provider",
]
