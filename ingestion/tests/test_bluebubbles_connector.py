"""Unit tests for connectors.bluebubbles."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

# Test payloads use fake/placeholder phone numbers.
# NEVER use real contact numbers in outbound test sends.
# These payloads are injected as webhook data — no real messages are sent.
WEBHOOK_PAYLOAD = {
    "type": "new-message",
    "data": {
        "guid": "TEST-GUID-001",
        "text": "Hey, lunch tomorrow?",
        "isFromMe": False,
        "dateCreated": 1776210267801,
        "handle": {
            "address": "+10000000001",
            "service": "iMessage",
            "country": "US",
        },
        "chats": [{"guid": "iMessage;-;+10000000001"}],
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
            "address": "+10000000001",
            "service": "iMessage",
            "country": "US",
        },
        "chats": [{"guid": "iMessage;-;+10000000001"}],
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
def mock_graphiti():
    with patch("connectors.bluebubbles.graphiti_writer") as mock:
        mock.add_episode = AsyncMock()
        yield mock


@pytest.fixture(autouse=True)
def mock_qdrant():
    with patch("connectors.bluebubbles.qdrant_writer") as mock:
        mock.upsert_document = AsyncMock()
        yield mock


@pytest.fixture(autouse=True)
def clear_handle_log():
    from connectors import bluebubbles
    bluebubbles._handles_logged.clear()
    yield
    bluebubbles._handles_logged.clear()


@pytest.mark.asyncio
async def test_webhook_resolves_contact_name(mock_graphiti):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alex Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    mock_graphiti.add_episode.assert_called_once()
    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert "Alex Test: Hey, lunch tomorrow?" == kwargs["body"]
    assert kwargs["source"] == "imessage"


@pytest.mark.asyncio
async def test_webhook_from_me_skips_resolver(mock_graphiti):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock()) as mock_resolve:
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD_FROM_ME)

        mock_resolve.assert_not_called()

    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert kwargs["body"].startswith("me: ")


@pytest.mark.asyncio
async def test_webhook_falls_back_to_address_when_resolver_returns_number(mock_graphiti):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="+10000000001")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert kwargs["body"].startswith("+10000000001: ")


@pytest.mark.asyncio
async def test_empty_text_skipped(mock_graphiti):
    payload = dict(WEBHOOK_PAYLOAD)
    payload["data"] = {**WEBHOOK_PAYLOAD["data"], "text": "   "}
    from connectors.bluebubbles import ingest_webhook_message
    await ingest_webhook_message(payload)
    mock_graphiti.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_pull_disabled_by_default(mock_graphiti):
    with patch("connectors.bluebubbles.config") as mock_config:
        mock_config.BLUEBUBBLES_PULL_ENABLED = False
        from connectors.bluebubbles import pull_recent
        await pull_recent()
    mock_graphiti.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_session_id_derived_from_chat_guid(mock_graphiti):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alex Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    kwargs = mock_graphiti.add_episode.call_args.kwargs
    # chat_guid "iMessage;-;+10000000001" → strip ':', replace '+' with '', replace ';' with '_'
    assert kwargs["name"] == "imessage_iMessage_-_10000000001"


@pytest.mark.asyncio
async def test_episode_reference_time_is_datetime(mock_graphiti):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alex Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert isinstance(kwargs["reference_time"], datetime)


@pytest.mark.asyncio
async def test_qdrant_also_written(mock_qdrant):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alex Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    mock_qdrant.upsert_document.assert_called_once()
    kwargs = mock_qdrant.upsert_document.call_args.kwargs
    assert kwargs["source"] == "imessage"
    assert "Alex Test" in kwargs["text"]


# --- Group chat tests ---

GROUP_WEBHOOK_PAYLOAD = {
    "type": "new-message",
    "chat": {
        "guid": "iMessage;+;chat000000000001",
        "displayName": "Weekend Plans",
        "participants": [
            {"address": "+10000000002"},
            {"address": "+10000000003"},
        ],
    },
    "data": {
        "guid": "TEST-GUID-GROUP-001",
        "text": "Anyone free Saturday?",
        "isFromMe": False,
        "dateCreated": 1776210400000,
        "handle": {
            "address": "+10000000002",
            "service": "iMessage",
        },
        "chats": [{"guid": "iMessage;+;chat000000000001"}],
    },
}


@pytest.mark.asyncio
async def test_group_chat_detected_in_source_description(mock_graphiti):
    async def fake_resolve(address: str) -> str:
        return {"+ 10000000002": "Alice Test", "+10000000003": "Bob Test"}.get(address, address)

    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(side_effect=fake_resolve)):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(GROUP_WEBHOOK_PAYLOAD)

    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert "group chat" in kwargs["source_description"]
    assert "Weekend Plans" in kwargs["source_description"]


@pytest.mark.asyncio
async def test_group_chat_metadata_in_qdrant(mock_qdrant):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alice Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(GROUP_WEBHOOK_PAYLOAD)

    kwargs = mock_qdrant.upsert_document.call_args.kwargs
    meta = kwargs["extra_metadata"]
    assert meta["is_group_chat"] is True
    assert meta["chat_name"] == "Weekend Plans"
    assert isinstance(meta["participants"], list)


@pytest.mark.asyncio
async def test_dm_is_not_flagged_as_group(mock_qdrant):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alex Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(WEBHOOK_PAYLOAD)

    kwargs = mock_qdrant.upsert_document.call_args.kwargs
    assert kwargs["extra_metadata"]["is_group_chat"] is False
    assert kwargs["extra_metadata"]["participants"] == []


@pytest.mark.asyncio
async def test_group_chat_sender_resolved_via_contact_resolver(mock_graphiti):
    with patch("connectors.bluebubbles.resolve_name", new=AsyncMock(return_value="Alice Test")):
        from connectors.bluebubbles import ingest_webhook_message
        await ingest_webhook_message(GROUP_WEBHOOK_PAYLOAD)

    kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert kwargs["body"].startswith("Alice Test: ")


def test_is_group_chat_detection():
    from connectors.bluebubbles import _is_group_chat
    assert _is_group_chat("iMessage;+;chat123456789") is True
    assert _is_group_chat("iMessage;-;+12345678900") is False
    assert _is_group_chat("iMessage;-;user@example.com") is False
