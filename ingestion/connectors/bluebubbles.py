"""
BlueBubbles connector.
Webhook-driven: BlueBubbles pushes new-message events to the ingestion service.
Pull-based polling is disabled by default (BLUEBUBBLES_PULL_ENABLED=false) because
Railway cannot reach the local Mac running BlueBubbles.
"""
import logging
from datetime import datetime

import httpx

import config
import dedup
from resolvers.contact_resolver import resolve_name
from writers import zep_writer

logger = logging.getLogger(__name__)

BASE = config.BLUEBUBBLES_URL
AUTH = {"password": config.BLUEBUBBLES_PASSWORD}

# Log each unique handle address once so we can inspect the raw payload shape.
_handles_logged: set[str] = set()


async def _get_chats() -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/api/v1/chat/query", params={**AUTH, "limit": 100})
        r.raise_for_status()
        return r.json().get("data", [])


async def _get_messages(chat_guid: str, limit: int = 50) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/api/v1/chat/{chat_guid}/message",
            params={**AUTH, "limit": limit, "sort": "DESC"},
        )
        r.raise_for_status()
        return r.json().get("data", [])


async def _ingest_message(msg: dict, chat_guid: str) -> None:
    msg_id = msg.get("guid", "")
    text = msg.get("text", "") or ""
    if not text.strip():
        return

    h = dedup.content_hash(text)
    if not dedup.is_changed("imessage", msg_id, h):
        return

    is_from_me = msg.get("isFromMe", False)
    handle = msg.get("handle", {}) or {}
    address = handle.get("address", "")

    # Log the raw handle once per address to help diagnose payload shape.
    if address and address not in _handles_logged:
        logger.info("BlueBubbles handle sample (address=%s): %s", address, handle)
        _handles_logged.add(address)

    if is_from_me:
        sender = "me"
    else:
        sender = await resolve_name(address) if address else "unknown"

    # Both sides are humans — role_type "user" is correct for Zep human-to-human threads.
    role_type = "user"

    timestamp_ms = msg.get("dateCreated") or msg.get("date")
    timestamp = (
        datetime.utcfromtimestamp(timestamp_ms / 1000)
        if timestamp_ms
        else datetime.utcnow()
    )

    # Use chat GUID as Zep session so all messages in a thread share context.
    session_id = f"imessage_{chat_guid.replace(':', '_').replace('+', '')}"

    await zep_writer.add_message_episode(
        session_id=session_id,
        role=sender,
        role_type=role_type,
        content=text,
        timestamp=timestamp,
        metadata={"source": "imessage", "chat_guid": chat_guid, "contact": sender},
    )
    dedup.mark_ingested("imessage", msg_id, h)


async def pull_recent(messages_per_chat: int = 50) -> None:
    """Pull recent messages from all chats. Disabled on Railway (BLUEBUBBLES_PULL_ENABLED=false)."""
    if not config.BLUEBUBBLES_PULL_ENABLED:
        logger.info("BlueBubbles pull disabled — relying on webhooks only")
        return

    logger.info("BlueBubbles: pulling recent messages")
    try:
        chats = await _get_chats()
    except Exception as e:
        logger.error("BlueBubbles pull failed: %s", e)
        return

    for chat in chats:
        guid = chat.get("guid", "")
        try:
            messages = await _get_messages(guid, limit=messages_per_chat)
            for msg in reversed(messages):  # oldest first for Zep ordering
                await _ingest_message(msg, guid)
        except Exception as e:
            logger.error("BlueBubbles: error ingesting chat %s: %s", guid, e)


async def ingest_webhook_message(payload: dict) -> None:
    """Handle a single message pushed via BlueBubbles webhook."""
    msg = payload.get("data", {})
    chat = payload.get("chat", {}) or {}
    chat_guid = chat.get("guid") or msg.get("chats", [{}])[0].get("guid", "unknown")
    await _ingest_message(msg, chat_guid)
