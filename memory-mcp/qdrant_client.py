"""Calls the ingestion service /search endpoint — no local OpenAI key needed."""
import os
from typing import Any

import httpx

INGESTION_URL = os.environ["INGESTION_URL"]


async def search_docs(
    query: str,
    limit: int = 5,
    source_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{INGESTION_URL}/search",
            json={"query": query, "limit": limit, "sources": source_filter},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["results"]
