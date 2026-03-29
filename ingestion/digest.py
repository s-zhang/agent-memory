"""
Nightly digest builder.
Queries Zep for recent memory, summarizes with GPT, writes to DIGEST_PATH.
OpenClaw reads this at session start via the memory-mcp hook.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)

ZEP_HEADERS = {
    "Authorization": f"Bearer {config.ZEP_API_KEY}",
    "Content-Type": "application/json",
}


async def _get_recent_facts(since_hours: int = 24) -> list[str]:
    """Search Zep for facts added in the last N hours."""
    facts = []
    try:
        async with httpx.AsyncClient(base_url=config.ZEP_URL) as client:
            r = await client.post(
                "/api/v2/graph/search",
                headers=ZEP_HEADERS,
                json={
                    "query": "recent activity",
                    "user_id": config.ZEP_USER_ID,
                    "limit": 50,
                    "search_type": "edge",
                },
            )
            if r.is_success:
                for edge in r.json().get("edges", []):
                    facts.append(edge.get("fact", ""))
    except Exception as e:
        logger.error("Failed to fetch Zep facts for digest: %s", e)
    return [f for f in facts if f]


async def build_digest() -> None:
    """Build a plain-text 24h summary and write to DIGEST_PATH."""
    logger.info("Building nightly digest")
    facts = await _get_recent_facts(since_hours=24)

    if not facts:
        summary = f"No recent activity recorded as of {datetime.utcnow().strftime('%Y-%m-%d')}."
    else:
        facts_text = "\n".join(f"- {f}" for f in facts)
        prompt = (
            "You are summarizing recent personal activity for a personal AI assistant. "
            "Below are facts extracted from messages and emails in the last 24 hours. "
            "Write a concise, readable summary (max 300 words) covering what happened, "
            "any pending actions, and anything worth remembering. Be specific.\n\n"
            f"Facts:\n{facts_text}"
        )

        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        summary = resp.choices[0].message.content.strip()

    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    output = f"# Daily Digest - {date_str}\n\n{summary}\n"

    Path(config.DIGEST_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(config.DIGEST_PATH).write_text(output)
    logger.info("Digest written to %s", config.DIGEST_PATH)
