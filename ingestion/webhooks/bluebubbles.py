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
    # BlueBubbles sends the secret as ?password= query param
    secret = request.query_params.get("password", "")
    if secret != config.BLUEBUBBLES_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid BlueBubbles webhook secret")


async def handle(payload: dict) -> None:
    event_type = payload.get("type", "")

    if event_type in MESSAGE_EVENTS:
        logger.info("BlueBubbles: ingesting message event '%s'", event_type)
        await bb_connector.ingest_webhook_message(payload)
    else:
        logger.debug("BlueBubbles: unhandled event type '%s'", event_type)
