"""Regulatory semantic search — the audit pipeline's retrieval, exposed raw.

Powers UI exploration and retrieval debugging; uses the exact same temporal
predicate and candidate logic as audits so the two can never diverge.
"""

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from chronosguard.providers import EmbeddingProvider
from chronosguard.retrieval.candidates import (
    Candidate,
    citation_lookup,
    merge_candidates,
    vector_search,
)


async def search_regulations(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    *,
    query: str,
    jurisdiction: str,
    as_of: dt.date,
    top_k: int,
) -> list[Candidate]:
    [query_vector] = await embedder.embed([query])
    vector_hits = await vector_search(
        session, query_vector, jurisdiction=jurisdiction, as_of=as_of, top_k=top_k
    )
    citation_hits = await citation_lookup(session, query, jurisdiction=jurisdiction, as_of=as_of)
    return merge_candidates(vector_hits, citation_hits, top_k=top_k)
