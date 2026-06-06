"""Document download (httpx). ETag is stored as a latency hint only —
content-hash dedup is the correctness mechanism, never the ETag."""

from dataclasses import dataclass

import httpx

_FETCH_TIMEOUT_SECONDS = 60.0
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024  # 50 MB gazette ceiling


@dataclass(frozen=True)
class FetchedDocument:
    content: bytes
    etag: str | None
    content_type: str | None


async def fetch_document(url: str) -> FetchedDocument:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.content
        if len(content) > MAX_DOCUMENT_BYTES:
            msg = f"Document exceeds {MAX_DOCUMENT_BYTES} bytes"
            raise ValueError(msg)
        return FetchedDocument(
            content=content,
            etag=response.headers.get("ETag"),
            content_type=response.headers.get("Content-Type"),
        )
