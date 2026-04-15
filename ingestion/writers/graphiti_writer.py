"""
Writes conversation episodes to Graphiti (temporal knowledge graph) backed by FalkorDB.
Graphiti extracts entities and relationships from free-form text episodes,
building a bi-temporal knowledge graph queryable by semantic search.

FalkorDB connection uses bolt protocol (port 7687).
"""
import asyncio
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)

_graphiti = None  # graphiti_core.Graphiti | None


async def init_graphiti(*, retries: int = 3, delay: float = 2.0) -> None:
    """
    Initialize the Graphiti client and build schema indices.
    Called once from main.py lifespan. Retries on connection failure.
    Sets _graphiti to None if all retries fail (service degrades gracefully).
    """
    global _graphiti
    from graphiti_core import Graphiti
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    from graphiti_core.llm_client.openai_client import OpenAIClient
    from graphiti_core.llm_client.config import LLMConfig

    llm_client = OpenAIClient(
        config=LLMConfig(
            api_key=config.OPENAI_API_KEY,
            model="gpt-4o-mini",
        )
    )

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            driver = FalkorDriver(
                host=config.FALKORDB_HOST,
                port=config.FALKORDB_PORT,
                password=config.FALKORDB_PASSWORD or None,
            )
            client = Graphiti(graph_driver=driver, llm_client=llm_client)
            await client.build_indices_and_constraints()
            _graphiti = client
            logger.info(
                "Graphiti initialized (host=%s port=%s)", config.FALKORDB_HOST, config.FALKORDB_PORT
            )
            return
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Graphiti init attempt %d/%d failed: %s", attempt, retries, exc
            )
            if attempt < retries:
                await asyncio.sleep(delay * attempt)

    logger.error(
        "Graphiti init failed after %d attempts — graph writes disabled: %s",
        retries,
        last_exc,
    )
    _graphiti = None


async def close_graphiti() -> None:
    """Close the Graphiti client connection."""
    global _graphiti
    if _graphiti is not None:
        try:
            await _graphiti.close()
        except Exception as exc:
            logger.warning("Graphiti close error: %s", exc)
        _graphiti = None
        logger.info("Graphiti connection closed")


async def add_episode(
    *,
    name: str,
    body: str,
    source: str,
    source_description: str,
    reference_time: datetime | None = None,
    group_id: str | None = None,
) -> None:
    """
    Add a free-form text episode to the Graphiti knowledge graph.
    Graphiti extracts entities and temporal facts from `body` via LLM.
    Failures are logged but do not raise — callers must not depend on this succeeding.
    """
    if _graphiti is None:
        logger.warning("Graphiti unavailable — skipping episode (name=%s)", name)
        return

    from graphiti_core.nodes import EpisodeType

    effective_group_id = group_id or config.GRAPHITI_GROUP_ID
    ts = reference_time or datetime.utcnow()

    try:
        await _graphiti.add_episode(
            name=name,
            episode_body=body,
            source=EpisodeType.text,
            source_description=source_description,
            reference_time=ts,
            group_id=effective_group_id,
        )
        logger.info("Graphiti episode added (name=%s source=%s)", name, source)
    except Exception as exc:
        logger.warning(
            "Graphiti episode write failed (name=%s source=%s): %s", name, source, exc
        )


async def search(
    query: str,
    *,
    num_results: int = 10,
    group_ids: list[str] | None = None,
) -> list[dict]:
    """
    Semantic search over the Graphiti knowledge graph.
    Returns a list of fact dicts with keys: fact, valid_at, invalid_at, name.
    Returns empty list if Graphiti is unavailable.
    """
    if _graphiti is None:
        logger.warning("Graphiti unavailable — search returning empty results")
        return []

    effective_group_ids = group_ids or [config.GRAPHITI_GROUP_ID]

    try:
        edges = await _graphiti.search(
            query=query,
            num_results=num_results,
            group_ids=effective_group_ids,
        )
        return [
            {
                "fact": getattr(edge, "fact", ""),
                "name": getattr(edge, "name", ""),
                "valid_at": _fmt_dt(getattr(edge, "valid_at", None)),
                "invalid_at": _fmt_dt(getattr(edge, "invalid_at", None)),
            }
            for edge in (edges or [])
            if getattr(edge, "fact", "")
        ]
    except Exception as exc:
        logger.warning("Graphiti search failed (query=%r): %s", query, exc)
        return []


def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
