"""Provider protocols. One abstraction, consumed by retrieval AND ingestion —
the embedding model MUST be identical on both sides for cosine validity."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    model: str
    dims: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
