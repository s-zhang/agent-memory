"""
Tests for inbound email webhook and core ingestion logic.
Covers: loop detection, thread ID derivation, secret verification, dedup.
"""
import email as email_lib
from email.mime.text import MIMEText
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw(
    subject="Hello",
    from_="alice@example.com",
    to="bob@example.com",
    body="Test body.",
    message_id="<msg-001@example.com>",
    references="",
    in_reply_to="",
    extra_headers: dict | None = None,
) -> bytes:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_
    msg["To"] = to
    msg["Message-ID"] = message_id
    if references:
        msg["References"] = references
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_dedup():
    with patch("connectors.email_imap.dedup") as m:
        m.content_hash.return_value = "hash123"
        m.is_changed.return_value = True
        m.mark_ingested = MagicMock()
        yield m


@pytest.fixture(autouse=True)
def mock_graphiti():
    with patch("connectors.email_imap.graphiti_writer") as m:
        m.add_episode = AsyncMock()
        yield m


@pytest.fixture(autouse=True)
def mock_qdrant():
    with patch("connectors.email_imap.qdrant_writer") as m:
        m.upsert_document = AsyncMock()
        yield m


# ---------------------------------------------------------------------------
# Loop / auto-generated detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_submitted_dropped(mock_graphiti):
    raw = _make_raw(extra_headers={"Auto-Submitted": "auto-replied"})
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_auto_submitted_no_is_kept(mock_graphiti):
    raw = _make_raw(extra_headers={"Auto-Submitted": "no"})
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_called_once()


@pytest.mark.asyncio
async def test_precedence_bulk_dropped(mock_graphiti):
    raw = _make_raw(extra_headers={"Precedence": "bulk"})
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_precedence_list_dropped(mock_graphiti):
    raw = _make_raw(extra_headers={"Precedence": "list"})
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_x_autoreply_dropped(mock_graphiti):
    raw = _make_raw(extra_headers={"X-Autoreply": "yes"})
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_not_called()


# ---------------------------------------------------------------------------
# Thread ID derivation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thread_id_uses_references_root(mock_graphiti):
    """First entry in References is used as thread root."""
    raw = _make_raw(
        references="<root-001@example.com> <mid-002@example.com>",
        message_id="<msg-003@example.com>",
    )
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert kwargs["name"] == "email_root-001_example.com"


@pytest.mark.asyncio
async def test_thread_id_falls_back_to_in_reply_to(mock_graphiti):
    raw = _make_raw(
        in_reply_to="<parent-001@example.com>",
        message_id="<msg-002@example.com>",
    )
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert kwargs["name"] == "email_parent-001_example.com"


@pytest.mark.asyncio
async def test_thread_id_uses_own_message_id_for_new_thread(mock_graphiti):
    raw = _make_raw(message_id="<brand-new-001@example.com>")
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert kwargs["name"] == "email_brand-new-001_example.com"


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_email_skipped(mock_graphiti, mock_dedup):
    mock_dedup.is_changed.return_value = False
    raw = _make_raw()
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_empty_body_skipped(mock_graphiti):
    raw = _make_raw(body="   ")
    from connectors.email_imap import ingest_raw_email
    await ingest_raw_email(raw)
    mock_graphiti.add_episode.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook handler — secret verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret():
    from fastapi import Request
    from webhooks.email_inbound import verify_secret

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"X-Email-Webhook-Secret": "wrong"}

    with patch("webhooks.email_inbound.config") as mock_config:
        mock_config.EMAIL_WEBHOOK_SECRET = "correct-secret"
        with pytest.raises(HTTPException) as exc_info:
            verify_secret(mock_request)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_correct_secret():
    from fastapi import Request
    from webhooks.email_inbound import verify_secret

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"X-Email-Webhook-Secret": "correct-secret"}

    with patch("webhooks.email_inbound.config") as mock_config:
        mock_config.EMAIL_WEBHOOK_SECRET = "correct-secret"
        verify_secret(mock_request)  # should not raise


@pytest.mark.asyncio
async def test_webhook_skips_check_when_no_secret_configured():
    from fastapi import Request
    from webhooks.email_inbound import verify_secret

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}

    with patch("webhooks.email_inbound.config") as mock_config:
        mock_config.EMAIL_WEBHOOK_SECRET = ""
        verify_secret(mock_request)  # should not raise


# ---------------------------------------------------------------------------
# Webhook handle() — passes bytes to ingest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_handle_calls_ingest(mock_graphiti):
    raw = _make_raw()
    with patch("webhooks.email_inbound.ingest_raw_email", new=AsyncMock()) as mock_ingest:
        from webhooks.email_inbound import handle
        await handle(raw)
        mock_ingest.assert_called_once_with(raw)


@pytest.mark.asyncio
async def test_webhook_handle_skips_empty_body(mock_graphiti):
    with patch("webhooks.email_inbound.ingest_raw_email", new=AsyncMock()) as mock_ingest:
        from webhooks.email_inbound import handle
        await handle(b"")
        mock_ingest.assert_not_called()
