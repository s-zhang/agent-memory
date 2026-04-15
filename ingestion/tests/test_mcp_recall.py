"""Unit tests for mcp_server recall and remember tools."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def mock_graphiti_writer():
    with patch("mcp_server.graphiti_writer") as mock:
        mock.add_episode = AsyncMock()
        mock.search = AsyncMock(return_value=[])
        yield mock


@pytest.fixture(autouse=True)
def mock_qdrant_writer():
    with patch("mcp_server.qdrant_writer") as mock:
        mock.upsert_document = AsyncMock()
        mock.search_docs = AsyncMock(return_value=[])
        yield mock


@pytest.mark.asyncio
async def test_remember_writes_to_both_stores(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    await call_tool("remember", {"content": "I prefer dark roast coffee"})

    mock_qdrant_writer.upsert_document.assert_called_once()
    qdrant_kwargs = mock_qdrant_writer.upsert_document.call_args.kwargs
    assert qdrant_kwargs["source"] == "memory"
    assert qdrant_kwargs["text"] == "I prefer dark roast coffee"

    mock_graphiti_writer.add_episode.assert_called_once()
    graphiti_kwargs = mock_graphiti_writer.add_episode.call_args.kwargs
    assert graphiti_kwargs["body"] == "I prefer dark roast coffee"
    assert graphiti_kwargs["source"] == "memory"


@pytest.mark.asyncio
async def test_remember_returns_confirmed_text(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    result = await call_tool("remember", {"content": "test fact"})
    assert result[0].text == "Remembered."


@pytest.mark.asyncio
async def test_recall_merges_graphiti_and_qdrant_results(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    mock_graphiti_writer.search = AsyncMock(return_value=[
        {"fact": "Shanna likes sushi", "valid_at": "2026-04-14T00:00:00", "invalid_at": None, "name": "food"},
    ])
    mock_qdrant_writer.search_docs = AsyncMock(return_value=[
        {"source": "imessage", "text": "Hey, lunch tomorrow?", "score": 0.92, "title": "iMessage: Alex", "url": ""},
    ])

    result = await call_tool("recall", {"query": "food preferences"})
    text = result[0].text

    assert "[KNOWLEDGE" in text
    assert "Shanna likes sushi" in text
    assert "[IMESSAGE]" in text
    assert "Hey, lunch tomorrow?" in text


@pytest.mark.asyncio
async def test_recall_returns_no_memories_when_both_empty(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    result = await call_tool("recall", {"query": "something obscure"})
    assert result[0].text == "No relevant memories found."


@pytest.mark.asyncio
async def test_recall_falls_back_to_qdrant_when_graphiti_unavailable(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    mock_graphiti_writer.search = AsyncMock(return_value=[])
    mock_qdrant_writer.search_docs = AsyncMock(return_value=[
        {"source": "email", "text": "Meeting at 3pm", "score": 0.85, "title": "Email", "url": ""},
    ])

    result = await call_tool("recall", {"query": "meeting"})
    text = result[0].text

    assert "[EMAIL]" in text
    assert "Meeting at 3pm" in text


@pytest.mark.asyncio
async def test_recall_knowledge_results_shown_first(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    mock_graphiti_writer.search = AsyncMock(return_value=[
        {"fact": "Graphiti fact", "valid_at": None, "invalid_at": None, "name": "x"},
    ])
    mock_qdrant_writer.search_docs = AsyncMock(return_value=[
        {"source": "imessage", "text": "Qdrant result", "score": 0.9, "title": "t", "url": ""},
    ])

    result = await call_tool("recall", {"query": "test"})
    text = result[0].text
    knowledge_pos = text.index("[KNOWLEDGE")
    qdrant_pos = text.index("[IMESSAGE]")
    assert knowledge_pos < qdrant_pos


@pytest.mark.asyncio
async def test_recall_respects_limit(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    await call_tool("recall", {"query": "test", "limit": 3})

    mock_graphiti_writer.search.assert_called_once_with("test", num_results=3)
    mock_qdrant_writer.search_docs.assert_called_once()
    qdrant_kwargs = mock_qdrant_writer.search_docs.call_args.kwargs
    assert qdrant_kwargs["limit"] == 3


@pytest.mark.asyncio
async def test_search_docs_uses_qdrant_only(mock_graphiti_writer, mock_qdrant_writer):
    from mcp_server import call_tool

    mock_qdrant_writer.search_docs = AsyncMock(return_value=[
        {"source": "notion", "text": "Project notes", "score": 0.88, "title": "My Page", "url": "https://notion.so/x"},
    ])

    result = await call_tool("search_docs", {"query": "project"})

    mock_graphiti_writer.search.assert_not_called()
    assert "[NOTION]" in result[0].text
    assert "Project notes" in result[0].text
