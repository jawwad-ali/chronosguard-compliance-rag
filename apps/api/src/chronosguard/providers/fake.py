"""Deterministic fake embeddings — CI never spends OpenAI money.

Token-hash bag-of-words vectors: each token hashes to a dimension, counts are
L2-normalized. Texts sharing vocabulary get genuinely higher cosine similarity,
so retrieval-ranking tests are meaningful, deterministic, and free.
"""

import hashlib
import math
import re

from chronosguard.models import EMBEDDING_DIMS

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _vectorize(text: str, dims: int) -> list[float]:
    vector = [0.0] * dims
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        vector[index] += 1.0
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [component / norm for component in vector]


class FakeEmbeddings:
    model = "fake-token-hash-v1"
    dims = EMBEDDING_DIMS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vectorize(text, self.dims) for text in texts]
