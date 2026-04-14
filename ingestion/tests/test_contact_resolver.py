"""Unit tests for resolvers.contact_resolver."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the resolver cache before each test."""
    from resolvers import contact_resolver
    contact_resolver._cache.clear()
    yield
    contact_resolver._cache.clear()


@pytest.fixture(autouse=True)
def set_config(monkeypatch):
    monkeypatch.setenv("CONTACT_SERVER_URL", "http://contacts.local:9876")
    monkeypatch.setenv("CONTACT_SERVER_TOKEN", "test-token")
    import importlib, config
    importlib.reload(config)
    from resolvers import contact_resolver
    importlib.reload(contact_resolver)


def _mock_response(matches: list) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"matches": matches, "count": len(matches)}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_resolves_phone_to_name():
    from resolvers.contact_resolver import resolve_name
    match = {"name": "Alice Smith", "phones": ["+19175550100"], "emails": []}
    with patch("resolvers.contact_resolver.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_mock_response([match])
        )
        result = await resolve_name("+19175550100")
    assert result == "Alice Smith"


@pytest.mark.asyncio
async def test_resolves_email_to_name():
    from resolvers.contact_resolver import resolve_name
    match = {"name": "Bob Jones", "phones": [], "emails": ["bob@example.com"]}
    with patch("resolvers.contact_resolver.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_mock_response([match])
        )
        result = await resolve_name("bob@example.com")
    assert result == "Bob Jones"


@pytest.mark.asyncio
async def test_falls_back_when_no_match():
    from resolvers.contact_resolver import resolve_name
    with patch("resolvers.contact_resolver.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_mock_response([])
        )
        result = await resolve_name("+10000000000")
    assert result == "+10000000000"


@pytest.mark.asyncio
async def test_falls_back_on_http_error():
    from resolvers.contact_resolver import resolve_name
    with patch("resolvers.contact_resolver.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("connection refused")
        )
        result = await resolve_name("+19175550101")
    assert result == "+19175550101"


@pytest.mark.asyncio
async def test_caches_result():
    from resolvers.contact_resolver import resolve_name
    match = {"name": "Carol White", "phones": ["+19175550102"], "emails": []}
    with patch("resolvers.contact_resolver.httpx.AsyncClient") as mock_client:
        get_mock = AsyncMock(return_value=_mock_response([match]))
        mock_client.return_value.__aenter__.return_value.get = get_mock

        await resolve_name("+19175550102")
        await resolve_name("+19175550102")  # second call

    # HTTP should only be called once
    assert get_mock.call_count == 1


@pytest.mark.asyncio
async def test_empty_address_returns_empty():
    from resolvers.contact_resolver import resolve_name
    result = await resolve_name("")
    assert result == ""


@pytest.mark.asyncio
async def test_address_not_in_phones_falls_back():
    """Match found but address not in phones/emails of that match."""
    from resolvers.contact_resolver import resolve_name
    match = {"name": "Dave Brown", "phones": ["+19175550199"], "emails": []}
    with patch("resolvers.contact_resolver.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=_mock_response([match])
        )
        result = await resolve_name("+19175550103")
    assert result == "+19175550103"
