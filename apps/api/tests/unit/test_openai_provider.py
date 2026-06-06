"""OpenAI embedding provider: batching, ordering, pricing."""

from types import SimpleNamespace
from typing import Any

import pytest

from chronosguard.providers.openai import EMBED_BATCH_SIZE, OpenAIEmbeddings
from chronosguard.providers.pricing import embedding_cost_usd

pytestmark = pytest.mark.anyio


class _StubEmbeddingsAPI:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    async def create(self, *, model: str, input: list[str]) -> Any:
        self.batch_sizes.append(len(input))
        data = [
            SimpleNamespace(embedding=[float(hash(text) % 97)] * 4, index=i)
            for i, text in enumerate(input)
        ]
        return SimpleNamespace(data=data, usage=SimpleNamespace(total_tokens=len(input) * 3))


class _StubClient:
    def __init__(self) -> None:
        self.embeddings = _StubEmbeddingsAPI()


class TestBatching:
    async def test_splits_into_max_size_batches(self) -> None:
        stub = _StubClient()
        provider = OpenAIEmbeddings(api_key="unused", model="text-embedding-3-small", client=stub)  # type: ignore[arg-type]
        texts = [f"text {i}" for i in range(EMBED_BATCH_SIZE * 2 + 10)]

        vectors = await provider.embed(texts)

        assert stub.embeddings.batch_sizes == [EMBED_BATCH_SIZE, EMBED_BATCH_SIZE, 10]
        assert len(vectors) == len(texts)

    async def test_preserves_input_order(self) -> None:
        stub = _StubClient()
        provider = OpenAIEmbeddings(api_key="unused", model="text-embedding-3-small", client=stub)  # type: ignore[arg-type]
        texts = ["alpha", "beta", "gamma"]

        vectors = await provider.embed(texts)

        expected_first_components = [float(hash(text) % 97) for text in texts]
        assert [vec[0] for vec in vectors] == expected_first_components


class TestPricing:
    def test_known_model_priced(self) -> None:
        assert embedding_cost_usd("text-embedding-3-small", 1_000_000) == 0.02

    def test_unknown_model_returns_none_not_zero(self) -> None:
        assert embedding_cost_usd("mystery-model", 1000) is None
