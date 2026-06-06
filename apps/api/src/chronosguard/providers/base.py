"""Provider protocols. One abstraction, consumed by retrieval AND ingestion —
the embedding model MUST be identical on both sides for cosine validity."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


class EmbeddingProvider(Protocol):
    model: str
    dims: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatProvider(Protocol):
    model: str

    async def complete_structured[T: BaseModel](
        self, *, system: str, user: str, response_model: type[T]
    ) -> tuple[T, TokenUsage]: ...
