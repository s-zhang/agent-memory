"""
Writes document chunks to Qdrant with stable IDs.
Supports clean upsert (update) and delete-by-source-id.
"""
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

import config

logger = logging.getLogger(__name__)

_qdrant: AsyncQdrantClient | None = None
_openai: AsyncOpenAI | None = None


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(
            url=config.QDRANT_URL,
            api_key=config.QDRANT_API_KEY,
        )
    return _qdrant


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _openai


async def ensure_collection() -> None:
    client = _get_qdrant()
    existing = await client.get_collections()
    names = [c.name for c in existing.collections]
    if config.QDRANT_COLLECTION not in names:
        await client.create_collection(
            collection_name=config.QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=config.EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection '%s'", config.QDRANT_COLLECTION)


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    size = config.CHUNK_SIZE
    overlap = config.CHUNK_OVERLAP
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + size])
        chunks.append(chunk)
        i += size - overlap
    return chunks or [text]


async def _embed(texts: list[str]) -> list[list[float]]:
    if config.EMBEDDING_PROVIDER == "openai":
        resp = await _get_openai().embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in resp.data]
    raise ValueError(f"Unknown embedding provider: {config.EMBEDDING_PROVIDER}")


async def upsert_document(
    *,
    source: str,
    source_id: str,
    title: str,
    text: str,
    url: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """
    Chunk, embed, and upsert a document.
    Uses stable IDs: f"{source}_{source_id}_{chunk_index}"
    Previous chunks for this source_id are deleted first to handle shrinking docs.
    """
    await ensure_collection()
    client = _get_qdrant()

    # Delete existing chunks for this document first (handles edits/deletions)
    await delete_document(source=source, source_id=source_id)

    chunks = _chunk_text(text)
    embeddings = await _embed(chunks)

    points = [
        PointStruct(
            id=abs(hash(f"{source}_{source_id}_{i}")) % (2**63),
            vector=embedding,
            payload={
                "source": source,
                "source_id": source_id,
                "chunk_index": i,
                "title": title,
                "url": url,
                "text": chunk,
                **(extra_metadata or {}),
            },
        )
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    await client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)
    logger.debug("Upserted %d chunks for %s/%s", len(points), source, source_id)


async def delete_document(*, source: str, source_id: str) -> None:
    """Delete all chunks for a given source document."""
    client = _get_qdrant()
    await client.delete(
        collection_name=config.QDRANT_COLLECTION,
        points_selector=Filter(
            must=[
                FieldCondition(key="source", match=MatchValue(value=source)),
                FieldCondition(key="source_id", match=MatchValue(value=source_id)),
            ]
        ),
    )
    logger.debug("Deleted chunks for %s/%s", source, source_id)
