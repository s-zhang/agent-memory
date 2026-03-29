"""Thin async wrapper around Qdrant for the MCP server."""
import os
from typing import Any

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ["QDRANT_API_KEY"]
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "documents")
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBEDDING_MODEL = "text-embedding-3-small"

_qdrant: AsyncQdrantClient | None = None
_openai: AsyncOpenAI | None = None


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai


async def search_docs(
    query: str,
    limit: int = 5,
    source_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over Qdrant document chunks."""
    resp = await _get_openai().embeddings.create(
        model=EMBEDDING_MODEL, input=[query]
    )
    vector = resp.data[0].embedding

    qdrant_filter = None
    if source_filter:
        qdrant_filter = Filter(
            must=[FieldCondition(key="source", match=MatchAny(any=source_filter))]
        )

    results = await _get_qdrant().search(
        collection_name=QDRANT_COLLECTION,
        query_vector=vector,
        limit=limit,
        query_filter=qdrant_filter,
        with_payload=True,
    )

    return [
        {
            "text": r.payload.get("text", ""),
            "title": r.payload.get("title", ""),
            "source": r.payload.get("source", ""),
            "url": r.payload.get("url", ""),
            "score": round(r.score, 3),
            "date": r.payload.get("date", ""),
        }
        for r in results
    ]
