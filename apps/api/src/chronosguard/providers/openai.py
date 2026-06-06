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
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from chronosguard.core.errors import ProviderError
from chronosguard.models import EMBEDDING_DIMS
from chronosguard.providers.base import TokenUsage
from chronosguard.providers.health import chat_health
from chronosguard.providers.pricing import chat_cost_usd, embedding_cost_usd

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


class OpenAIChat:
    """Strict Structured Outputs chat — deterministic (temperature 0)."""

    def __init__(self, api_key: str, model: str, client: AsyncOpenAI | None = None) -> None:
        self.model = model
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=_REQUEST_TIMEOUT_SECONDS)

    async def complete_structured[T: BaseModel](
        self, *, system: str, user: str, response_model: type[T]
    ) -> tuple[T, TokenUsage]:
        try:
            result = await self._complete(system=system, user=user, response_model=response_model)
        except Exception:
            chat_health.record_failure()  # one strike per fully-exhausted call
            raise
        chat_health.record_success()
        return result

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        reraise=True,
    )
    async def _complete[T: BaseModel](
        self, *, system: str, user: str, response_model: type[T]
    ) -> tuple[T, TokenUsage]:
        started = time.perf_counter()
        completion = await self._client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_model,
            temperature=0,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        usage = TokenUsage(
            prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
            completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
        )
        logger.info(
            "openai_call",
            operation="chat",
            model=self.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=chat_cost_usd(self.model, usage.prompt_tokens, usage.completion_tokens),
            latency_ms=latency_ms,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:  # refusal or schema failure — never silently compliant
            raise ProviderError("Model returned no parsed structured output")
        return parsed, usage
