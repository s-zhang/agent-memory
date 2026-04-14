"""Unit tests for connectors.bluebubbles."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock


WEBHOOK_PAYLOAD = {
    "type": "new-message",
    "data": {
        "guid": "TEST-GUID-001",
        "text": "Hey, lunch tomorrow?",
        "isFromMe": False,
        "dateCreated": 1776210267801,
        "handle": {
            "address": "+19172325246",
            "service": "iMessage",
            "country": "US",
        },
        "chats": [{"guid": "iMessage;-;+19172325246"}],
    },
}

WEBHOOK_PAYLOAD_FROM_ME = {
    "type": "new-message",
    "data": {
        "guid": "TEST-GUID-002",
        "text": "Sure, noon works!",
        "isFromMe": True,
        "dateCreated": 1776210300000,
        "handle": {
            "address": "+14127089192",
            "service": "iMessage",
            "country": "US",
        },
        "chats": [{"guid": "iMessage;-;+19172325246"}],
    },
}


@pytest.fixture(autouse=True)
def mock_dedup():
    with patch("connectors.bluebubbles.dedup") as mock:
        mock.content_hash.return_value = "abc123"
        mock.is_changed.return_value = True
        mock.mark_ingested = MagicMock()
        yield mock


@pytest.fixture(autouse=True)
def mock_zep():
    with patch("connectors.bluebubbles.zep_writer") as mock:
        mock.add_message_episode = AsyncMock()
        yield mock


@pytest.fixture(autouse=True)
def clear_handle_log():
    from connectors import bluebubbles
    bluebubbles._handles_logged.clear()
    yield
    bluebubbles._handles_logged.clear()


@pytest.mark.asyncio
async def test_webhook_resolves_contact_name(mock_zep):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Andrew Chang")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    mock_zep.add_message_episode.assert_called_once()
    call_kwargs = mock_zep.add_message_episode.call_args.kwargs
    assert call_kwargs["role"] == "Andrew Chang"
    assert call_kwargs["role_type"] == "user"


@pytest.mark.asyncio
async def test_webhook_from_me_skips_resolver(mock_zep):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock()) as mock_resolve:
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD_FROM_ME)

        mock_resolve.assert_not_called()

    call_kwargs = mock_zep.add_message_episode.call_args.kwargs
    assert call_kwargs["role"] == "me"
    assert call_kwargs["role_type"] == "user"


@pytest.mark.asyncio
async def test_webhook_falls_back_to_address_when_resolver_fails(mock_zep):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="+19172325246")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    call_kwargs = mock_zep.add_message_episode.call_args.kwargs
    assert call_kwargs["role"] == "+19172325246"


@pytest.mark.asyncio
async def test_empty_text_skipped(mock_zep):
    payload = dict(WEBHOOK_PAYLOAD)
    payload["data"] = {**WEBHOOK_PAYLOAD["data"], "text": "   "}
    from connectors.bluebubbles import ingest_webhook_message
    await ingest_webhook_message(payload)
    mock_zep.add_message_episode.assert_not_called()


@pytest.mark.asyncio
async def test_pull_disabled_by_default(mock_zep):
    with patch("connectors.bluebubbles.config") as mock_config:
        mock_config.BLUEBUBBLES_PULL_ENABLED = False
        from connectors.bluebubbles import pull_recent
        await pull_recent()
    mock_zep.add_message_episode.assert_not_called()


@pytest.mark.asyncio
async def test_session_id_derived_from_chat_guid(mock_zep):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Andrew Chang")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    call_kwargs = mock_zep.add_message_episode.call_args.kwargs
    assert call_kwargs["session_id"] == "imessage_iMessage;-;19172325246"
    assert call_kwargs["metadata"]["chat_guid"] == "iMessage;-;+19172325246"
    assert call_kwargs["metadata"]["contact"] == "Andrew Chang"
