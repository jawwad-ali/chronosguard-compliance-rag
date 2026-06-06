"""OpenAI embedding provider — batched, retried, cost-metered.

Every call emits one structured telemetry event (model, tokens, cost, latency)
bound to the ambient request/tenant context. Per-tenant cost visibility from
the first request is a day-1 requirement (docs/ARCHITECTURE.md §4.4).
"""

import time

import structlog
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from chronosguard.models import EMBEDDING_DIMS
from chronosguard.providers.pricing import embedding_cost_usd

logger = structlog.get_logger(__name__)

#: ≤256 inputs per call keeps requests comfortably under API limits.
EMBED_BATCH_SIZE = 256
_REQUEST_TIMEOUT_SECONDS = 30.0

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


class OpenAIEmbeddings:
    dims = EMBEDDING_DIMS

    def __init__(self, api_key: str, model: str, client: AsyncOpenAI | None = None) -> None:
        self.model = model
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=_REQUEST_TIMEOUT_SECONDS)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        reraise=True,
    )
    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        response = await self._client.embeddings.create(model=self.model, input=batch)
        latency_ms = round((time.perf_counter() - started) * 1000)
        total_tokens = response.usage.total_tokens if response.usage else 0
        logger.info(
            "openai_call",
            operation="embed",
            model=self.model,
            input_count=len(batch),
            total_tokens=total_tokens,
            cost_usd=embedding_cost_usd(self.model, total_tokens),
            latency_ms=latency_ms,
        )
        return [item.embedding for item in response.data]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + EMBED_BATCH_SIZE]))
        return vectors
