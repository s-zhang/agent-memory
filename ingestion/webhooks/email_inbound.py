"""
Inbound email webhook handler.
Receives raw RFC 822 email bytes from the Cloudflare Email Worker,
verifies the shared secret, and passes to the core ingestion pipeline.
"""
import logging

from fastapi import HTTPException, Request

import config
from connectors.email_imap import ingest_raw_email

logger = logging.getLogger(__name__)


def verify_secret(request: Request) -> None:
    """Raise 401 if the shared secret header doesn't match. Call before reading body."""
    if not config.EMAIL_WEBHOOK_SECRET:
        return
    secret = request.headers.get("X-Email-Webhook-Secret", "")
    if secret != config.EMAIL_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid email webhook secret")


async def handle(raw_bytes: bytes) -> None:
    """Ingest raw RFC 822 email bytes. Called as a background task after secret is verified."""
    if not raw_bytes:
        logger.warning("Email webhook received empty body — skipping")
        return
    logger.info("Email webhook: ingesting message (%d bytes)", len(raw_bytes))
    await ingest_raw_email(raw_bytes)
