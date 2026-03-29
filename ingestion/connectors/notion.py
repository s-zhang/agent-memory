"""
Notion connector - pull pages via API + handle webhook events.
Pages -> Qdrant (documents with stable IDs).
"""
import logging
from datetime import datetime, timedelta

import httpx

import config
import dedup
from writers import qdrant_writer

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {config.NOTION_API_KEY}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


async def _get_page_blocks(page_id: str) -> str:
    """Recursively extract plain text from a Notion page's blocks."""
    text_parts = []

    async def _fetch_blocks(block_id: str) -> None:
        async with httpx.AsyncClient() as client:
            cursor = None
            while True:
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                r = await client.get(
                    f"{NOTION_API}/blocks/{block_id}/children",
                    headers=HEADERS,
                    params=params,
                )
                r.raise_for_status()
                data = r.json()

                for block in data.get("results", []):
                    btype = block.get("type", "")
                    content = block.get(btype, {})
                    rich_text = content.get("rich_text", [])
                    line = "".join(rt.get("plain_text", "") for rt in rich_text)
                    if line:
                        text_parts.append(line)
                    if block.get("has_children"):
                        await _fetch_blocks(block["id"])

                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")

    await _fetch_blocks(page_id)
    return "\n".join(text_parts)


async def _get_page_meta(page_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{NOTION_API}/pages/{page_id}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


def _extract_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            items = prop.get("title", [])
            return "".join(i.get("plain_text", "") for i in items)
    return "Untitled"


async def ingest_page(page_id: str) -> None:
    """Fetch and upsert a Notion page into Qdrant."""
    try:
        page = await _get_page_meta(page_id)
        title = _extract_title(page)
        url = page.get("url", "")
        body = await _get_page_blocks(page_id)

        if not body.strip():
            logger.debug("Notion page %s has no text content, skipping", page_id)
            return

        full_text = f"{title}\n\n{body}"
        h = dedup.content_hash(full_text)

        if not dedup.is_changed("notion", page_id, h):
            return

        await qdrant_writer.upsert_document(
            source="notion",
            source_id=page_id,
            title=title,
            text=full_text,
            url=url,
            extra_metadata={"last_edited": page.get("last_edited_time", "")},
        )
        dedup.mark_ingested("notion", page_id, h)
        logger.debug("Ingested Notion page: %s", title)

    except Exception as e:
        logger.error("Notion: error ingesting page %s: %s", page_id, e)


async def delete_page(page_id: str) -> None:
    """Remove a deleted Notion page from Qdrant."""
    await qdrant_writer.delete_document(source="notion", source_id=page_id)
    dedup.delete_record("notion", page_id)
    logger.info("Deleted Notion page %s from Qdrant", page_id)


async def pull_recent(since_hours: int = 1) -> None:
    """Search for Notion pages edited in the last N hours."""
    logger.info("Notion: pulling pages edited in last %dh", since_hours)
    since = (datetime.utcnow() - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        async with httpx.AsyncClient() as client:
            cursor = None
            while True:
                body: dict = {
                    "filter": {"value": "page", "property": "object"},
                    "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                    "page_size": 100,
                }
                if cursor:
                    body["start_cursor"] = cursor

                r = await client.post(
                    f"{NOTION_API}/search", headers=HEADERS, json=body
                )
                r.raise_for_status()
                data = r.json()

                for page in data.get("results", []):
                    last_edited = page.get("last_edited_time", "")
                    if last_edited < since:
                        return  # Results are sorted descending; stop when past window
                    await ingest_page(page["id"])

                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")

    except Exception as e:
        logger.error("Notion pull failed: %s", e)
