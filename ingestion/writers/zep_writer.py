"""
Writes conversation episodes (iMessage, email threads) to Zep.
Zep handles entity extraction and temporal fact management internally.
"""
import logging
from datetime import datetime

import httpx

import config

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Bearer {config.ZEP_API_KEY}",
    "Content-Type": "application/json",
}


async def _ensure_user() -> None:
    async with httpx.AsyncClient(base_url=config.ZEP_URL) as client:
        r = await client.get(f"/api/v2/users/{config.ZEP_USER_ID}", headers=HEADERS)
        if r.status_code == 404:
            r2 = await client.post(
                "/api/v2/users",
                headers=HEADERS,
                json={"user_id": config.ZEP_USER_ID},
            )
            r2.raise_for_status()


async def _ensure_session(session_id: str, metadata: dict | None = None) -> None:
    async with httpx.AsyncClient(base_url=config.ZEP_URL) as client:
        r = await client.get(f"/api/v2/sessions/{session_id}", headers=HEADERS)
        if r.status_code == 404:
            await client.post(
                "/api/v2/sessions",
                headers=HEADERS,
                json={
                    "session_id": session_id,
                    "user_id": config.ZEP_USER_ID,
                    "metadata": metadata or {},
                },
            )


async def add_message_episode(
    *,
    session_id: str,
    role: str,
    role_type: str,
    content: str,
    timestamp: datetime | None = None,
    metadata: dict | None = None,
) -> None:
    """Add a single message turn to a Zep session."""
    await _ensure_user()
    await _ensure_session(session_id)

    episode = {
        "type": "message",
        "role_mapping": {role: role_type},
        "messages": [
            {
                "role": role,
                "role_type": role_type,
                "content": content,
                "timestamp": (timestamp or datetime.utcnow()).isoformat() + "Z",
            }
        ],
    }
    if metadata:
        episode["metadata"] = metadata

    async with httpx.AsyncClient(base_url=config.ZEP_URL) as client:
        r = await client.post(
            f"/api/v2/sessions/{session_id}/memory",
            headers=HEADERS,
            json=episode,
        )
        r.raise_for_status()
        logger.debug("Zep episode added to session %s", session_id)


async def add_text_episode(
    *,
    session_id: str,
    content: str,
    source: str,
    metadata: dict | None = None,
) -> None:
    """Add a free-form text episode (e.g. email body summary) to Zep."""
    await _ensure_user()
    await _ensure_session(session_id, metadata={"source": source})

    episode = {
        "type": "text",
        "content": content,
        "source": source,
    }
    if metadata:
        episode["metadata"] = metadata

    async with httpx.AsyncClient(base_url=config.ZEP_URL) as client:
        r = await client.post(
            f"/api/v2/sessions/{session_id}/memory",
            headers=HEADERS,
            json=episode,
        )
        r.raise_for_status()
        logger.debug("Zep text episode added to session %s", session_id)
