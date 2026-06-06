"""Provider selection — settings-driven, cached, one instance per process."""

from functools import lru_cache

from chronosguard.core.config import get_settings
from chronosguard.providers.base import EmbeddingProvider
from chronosguard.providers.fake import FakeEmbeddings
from chronosguard.providers.openai import OpenAIEmbeddings


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embeddings_provider == "openai":
        return OpenAIEmbeddings(api_key=settings.openai_api_key, model=settings.openai_embed_model)
    return FakeEmbeddings()
