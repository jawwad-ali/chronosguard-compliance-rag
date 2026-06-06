"""Provider selection — settings-driven, cached, one instance per process."""

from functools import lru_cache

from chronosguard.core.config import get_settings
from chronosguard.providers.base import ChatProvider, EmbeddingProvider
from chronosguard.providers.fake import FakeChat, FakeEmbeddings
from chronosguard.providers.openai import OpenAIChat, OpenAIEmbeddings


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.ai_provider == "openai":
        return OpenAIEmbeddings(api_key=settings.openai_api_key, model=settings.openai_embed_model)
    return FakeEmbeddings()


@lru_cache
def get_chat_provider() -> ChatProvider:
    settings = get_settings()
    if settings.ai_provider == "openai":
        return OpenAIChat(api_key=settings.openai_api_key, model=settings.openai_audit_model)
    return FakeChat()
