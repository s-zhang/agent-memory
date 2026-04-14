"""
Resolves phone numbers / email addresses to human-readable contact names
via the local Contact Server API.

Resolution order:
  1. In-memory cache (process-lifetime, avoids repeat HTTP calls)
  2. GET /api/contacts/search?q={address} on Contact Server
  3. Fall back to raw address if no match, timeout, or error
"""
import logging
from urllib.parse import quote

import httpx

import config

logger = logging.getLogger(__name__)

# Process-lifetime cache: address -> resolved name
_cache: dict[str, str] = {}

_TIMEOUT = 2.0  # seconds


async def resolve_name(address: str) -> str:
    """Return the contact name for a phone number or email, or the raw address as fallback."""
    if not address:
        return address

    if address in _cache:
        logger.debug("contact_resolver cache hit: %s -> %s", address, _cache[address])
        return _cache[address]

    name = await _lookup(address)
    _cache[address] = name
    return name


async def _lookup(address: str) -> str:
    if not config.CONTACT_SERVER_URL:
        return address

    url = f"{config.CONTACT_SERVER_URL}/api/contacts/search?q={quote(address)}"
    headers = {}
    if config.CONTACT_SERVER_TOKEN:
        headers["Authorization"] = f"Bearer {config.CONTACT_SERVER_TOKEN}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            matches = r.json().get("matches", [])
    except Exception as e:
        logger.warning("contact_resolver lookup failed for %s: %s", address, e)
        return address

    for match in matches:
        phones = match.get("phones") or []
        emails = match.get("emails") or []
        if address in phones or address in emails:
            name = match.get("name", "").strip()
            if name:
                logger.debug("contact_resolver resolved %s -> %s", address, name)
                return name

    return address
