"""Unit tests for writers.graphiti_writer."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_graphiti_state():
    """Reset module-level singleton before each test."""
    import writers.graphiti_writer as gw
    original = gw._graphiti
    gw._graphiti = None
    yield
    gw._graphiti = None


def _make_mock_graphiti():
    mock = AsyncMock()
    mock.build_indices_and_constraints = AsyncMock()
    mock.add_episode = AsyncMock()
    mock.search = AsyncMock(return_value=[])
    mock.close = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_init_graphiti_builds_indices():
    mock_client = _make_mock_graphiti()
    with patch("writers.graphiti_writer.Graphiti", return_value=mock_client, create=True), \
         patch("writers.graphiti_writer.OpenAIClient", MagicMock(), create=True), \
         patch("writers.graphiti_writer.LLMConfig", MagicMock(), create=True):
        import writers.graphiti_writer as gw
        # Patch imports inside the function
        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(Graphiti=MagicMock(return_value=mock_client)),
            "graphiti_core.llm_client.openai_client": MagicMock(OpenAIClient=MagicMock()),
            "graphiti_core.llm_client.config": MagicMock(LLMConfig=MagicMock()),
        }):
            await gw.init_graphiti()

    mock_client.build_indices_and_constraints.assert_called_once()
    assert gw._graphiti is mock_client


@pytest.mark.asyncio
async def test_init_graphiti_retries_on_failure():
    import writers.graphiti_writer as gw

    call_count = 0

    async def build_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("db not ready")

    mock_client = _make_mock_graphiti()
    mock_client.build_indices_and_constraints = AsyncMock(side_effect=build_side_effect)

    with patch.dict("sys.modules", {
        "graphiti_core": MagicMock(Graphiti=MagicMock(return_value=mock_client)),
        "graphiti_core.llm_client.openai_client": MagicMock(OpenAIClient=MagicMock()),
        "graphiti_core.llm_client.config": MagicMock(LLMConfig=MagicMock()),
    }):
        await gw.init_graphiti(retries=3, delay=0.01)

    assert call_count == 3
    assert gw._graphiti is mock_client


@pytest.mark.asyncio
async def test_init_graphiti_sets_none_after_all_retries_fail():
    import writers.graphiti_writer as gw

    mock_client = _make_mock_graphiti()
    mock_client.build_indices_and_constraints = AsyncMock(side_effect=ConnectionError("down"))

    with patch.dict("sys.modules", {
        "graphiti_core": MagicMock(Graphiti=MagicMock(return_value=mock_client)),
        "graphiti_core.llm_client.openai_client": MagicMock(OpenAIClient=MagicMock()),
        "graphiti_core.llm_client.config": MagicMock(LLMConfig=MagicMock()),
    }):
        await gw.init_graphiti(retries=2, delay=0.01)

    assert gw._graphiti is None


@pytest.mark.asyncio
async def test_add_episode_calls_graphiti(caplog):
    import writers.graphiti_writer as gw

    mock_client = _make_mock_graphiti()
    gw._graphiti = mock_client

    fake_episode_type = MagicMock()
    fake_episode_type.text = "text"

    with patch.dict("sys.modules", {
        "graphiti_core.nodes": MagicMock(EpisodeType=fake_episode_type),
    }):
        await gw.add_episode(
            name="test_ep",
            body="Shanna: hello world",
            source="imessage",
            source_description="iMessage test",
            reference_time=datetime(2026, 4, 14, 12, 0, 0),
        )

    mock_client.add_episode.assert_called_once()
    kwargs = mock_client.add_episode.call_args.kwargs
    assert kwargs["name"] == "test_ep"
    assert kwargs["episode_body"] == "Shanna: hello world"
    assert kwargs["source_description"] == "iMessage test"


@pytest.mark.asyncio
async def test_add_episode_logs_warning_on_failure(caplog):
    import writers.graphiti_writer as gw
    import logging

    mock_client = _make_mock_graphiti()
    mock_client.add_episode = AsyncMock(side_effect=RuntimeError("graph error"))
    gw._graphiti = mock_client

    with patch.dict("sys.modules", {
        "graphiti_core.nodes": MagicMock(EpisodeType=MagicMock()),
    }):
        with caplog.at_level(logging.WARNING, logger="writers.graphiti_writer"):
            # Should not raise
            await gw.add_episode(
                name="test_ep",
                body="some text",
                source="imessage",
                source_description="test",
            )

    assert any("graph error" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_add_episode_skips_when_client_is_none(caplog):
    import writers.graphiti_writer as gw
    import logging

    gw._graphiti = None

    with caplog.at_level(logging.WARNING, logger="writers.graphiti_writer"):
        await gw.add_episode(
            name="test_ep", body="text", source="imessage", source_description="test"
        )

    assert any("unavailable" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_search_returns_formatted_results():
    import writers.graphiti_writer as gw

    edge1 = MagicMock()
    edge1.fact = "Shanna likes sushi"
    edge1.name = "food_preference"
    edge1.valid_at = datetime(2026, 4, 14)
    edge1.invalid_at = None

    mock_client = _make_mock_graphiti()
    mock_client.search = AsyncMock(return_value=[edge1])
    gw._graphiti = mock_client

    results = await gw.search("food preferences")

    assert len(results) == 1
    assert results[0]["fact"] == "Shanna likes sushi"
    assert results[0]["valid_at"] == "2026-04-14T00:00:00"
    assert results[0]["invalid_at"] is None


@pytest.mark.asyncio
async def test_search_returns_empty_when_client_none():
    import writers.graphiti_writer as gw

    gw._graphiti = None
    results = await gw.search("anything")
    assert results == []


@pytest.mark.asyncio
async def test_search_returns_empty_on_exception():
    import writers.graphiti_writer as gw

    mock_client = _make_mock_graphiti()
    mock_client.search = AsyncMock(side_effect=RuntimeError("search error"))
    gw._graphiti = mock_client

    results = await gw.search("anything")
    assert results == []


@pytest.mark.asyncio
async def test_close_graphiti_closes_client():
    import writers.graphiti_writer as gw

    mock_client = _make_mock_graphiti()
    gw._graphiti = mock_client

    await gw.close_graphiti()

    mock_client.close.assert_called_once()
    assert gw._graphiti is None
