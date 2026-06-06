"""Pinned price table for cost telemetry (USD per 1M tokens).

Update deliberately when models change; unknown models log cost=None rather
than a wrong number.
"""

EMBED_PRICE_PER_1M_TOKENS: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}


def embedding_cost_usd(model: str, total_tokens: int) -> float | None:
    price = EMBED_PRICE_PER_1M_TOKENS.get(model)
    if price is None:
        return None
    return round(total_tokens * price / 1_000_000, 8)
