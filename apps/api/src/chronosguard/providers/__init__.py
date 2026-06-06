"""AI provider abstraction — the rest of the codebase never imports `openai`."""

from chronosguard.providers.base import EmbeddingProvider
from chronosguard.providers.fake import FakeEmbeddings

__all__ = ["EmbeddingProvider", "FakeEmbeddings"]
