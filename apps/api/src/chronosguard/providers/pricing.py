"""Pinned price table for cost telemetry (USD per 1M tokens).

Update deliberately when models change; unknown models log cost=None rather
than a wrong number.
"""

EMBED_PRICE_PER_1M_TOKENS: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}

#: (input, output) USD per 1M tokens.
CHAT_PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
}


def embedding_cost_usd(model: str, total_tokens: int) -> float | None:
    price = EMBED_PRICE_PER_1M_TOKENS.get(model)
    if price is None:
        return None
    return round(total_tokens * price / 1_000_000, 8)


def chat_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    prices = CHAT_PRICE_PER_1M_TOKENS.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    return round((prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000, 8)
