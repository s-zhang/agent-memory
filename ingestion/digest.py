"""
Nightly digest builder.
Queries Graphiti for recent knowledge graph facts, summarizes with GPT,
writes to DIGEST_PATH. OpenClaw reads this at session start via the memory-mcp hook.
"""
import logging
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

import config
from writers import graphiti_writer

logger = logging.getLogger(__name__)


async def _get_recent_facts() -> list[str]:
    """Search Graphiti for recent facts."""
    results = await graphiti_writer.search(
        "recent activity and events",
        num_results=50,
    )
    return [r["fact"] for r in results if r.get("fact")]


async def build_digest() -> None:
    """Build a plain-text 24h summary and write to DIGEST_PATH."""
    logger.info("Building nightly digest")
    facts = await _get_recent_facts()

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
