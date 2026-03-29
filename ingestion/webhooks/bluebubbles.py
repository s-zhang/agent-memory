"""
BlueBubbles webhook handler.
Verifies bearer token, routes new-message events to ingestion.
"""
import logging

from fastapi import HTTPException, Request

import config
from connectors import bluebubbles as bb_connector

logger = logging.getLogger(__name__)

# BlueBubbles event types that carry a new message
MESSAGE_EVENTS = {"new-message", "updated-message"}


async def verify_token(request: Request) -> None:
    if not config.BLUEBUBBLES_WEBHOOK_SECRET:
        return
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if token != config.BLUEBUBBLES_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid BlueBubbles webhook token")


async def handle(payload: dict) -> None:
    event_type = payload.get("type", "")

    if event_type in MESSAGE_EVENTS:
        logger.info("BlueBubbles: ingesting message event '%s'", event_type)
        await bb_connector.ingest_webhook_message(payload)
    else:
        logger.debug("BlueBubbles: unhandled event type '%s'", event_type)
