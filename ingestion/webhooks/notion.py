"""
Notion webhook handler.
Verifies HMAC signature, routes page events to ingest or delete.
"""
import hashlib
import hmac
import logging

from fastapi import HTTPException, Request

import config
from connectors import notion as notion_connector

logger = logging.getLogger(__name__)


async def verify_signature(request: Request, body: bytes) -> None:
    if not config.NOTION_WEBHOOK_SECRET:
        return
    signature = request.headers.get("X-Notion-Signature", "")
    expected = hmac.new(
        config.NOTION_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, f"sha256={expected}"):
        raise HTTPException(status_code=401, detail="Invalid Notion webhook signature")


async def handle(payload: dict) -> None:
    event_type = payload.get("type", "")
    page = payload.get("page") or payload.get("data", {})
    page_id = page.get("id", "")

    if not page_id:
        logger.warning("Notion webhook missing page ID: %s", payload)
        return

    # Normalize page ID to UUID format
    page_id = page_id.replace("-", "")
    page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    if event_type in ("page.created", "page.content_updated", "page.properties_updated"):
        logger.info("Notion: ingesting page %s (event: %s)", page_id, event_type)
        await notion_connector.ingest_page(page_id)

    elif event_type in ("page.deleted", "page.undeleted"):
        if event_type == "page.deleted":
            logger.info("Notion: deleting page %s", page_id)
            await notion_connector.delete_page(page_id)
        else:
            logger.info("Notion: re-ingesting undeleted page %s", page_id)
            await notion_connector.ingest_page(page_id)

    else:
        logger.debug("Notion: unhandled event type '%s'", event_type)
