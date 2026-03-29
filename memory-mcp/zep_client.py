"""Thin async wrapper around Zep's REST API for the MCP server."""
import os
from typing import Any

import httpx

ZEP_URL = os.environ["ZEP_URL"]
ZEP_API_KEY = os.environ["ZEP_API_KEY"]
ZEP_USER_ID = os.environ.get("ZEP_USER_ID", "owner")

HEADERS = {
    "Authorization": f"Bearer {ZEP_API_KEY}",
    "Content-Type": "application/json",
}


async def remember(content: str) -> str:
    """Store a free-form fact into Zep."""
    session_id = "openclaw_session"
    async with httpx.AsyncClient(base_url=ZEP_URL) as client:
        # Ensure session exists
        r = await client.get(f"/api/v2/sessions/{session_id}", headers=HEADERS)
        if r.status_code == 404:
            await client.post(
                "/api/v2/sessions",
                headers=HEADERS,
                json={"session_id": session_id, "user_id": ZEP_USER_ID},
            )

        r = await client.post(
            f"/api/v2/sessions/{session_id}/memory",
            headers=HEADERS,
            json={
                "type": "text",
                "content": content,
                "source": "openclaw",
            },
        )
        r.raise_for_status()
    return "Remembered."


async def recall(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Semantic search over Zep knowledge graph."""
    async with httpx.AsyncClient(base_url=ZEP_URL) as client:
        r = await client.post(
            "/api/v2/graph/search",
            headers=HEADERS,
            json={
                "query": query,
                "user_id": ZEP_USER_ID,
                "limit": limit,
                "search_type": "edge",
            },
        )
        if not r.is_success:
            return []

        edges = r.json().get("edges", [])
        return [
            {
                "fact": e.get("fact", ""),
                "valid_from": e.get("valid_at", ""),
                "invalid_at": e.get("invalid_at", ""),
                "source": e.get("episodes", [{}])[0].get("source", "") if e.get("episodes") else "",
            }
            for e in edges
            if e.get("fact")
        ]
