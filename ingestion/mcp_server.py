"""
MCP server (SSE transport) mounted inside the ingestion FastAPI app.
Exposes: remember, recall, search_docs, get_digest
"""
import os
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool

from writers import qdrant_writer

ZEP_URL = os.environ["ZEP_URL"]
ZEP_API_KEY = os.environ["ZEP_API_KEY"]
ZEP_USER_ID = os.environ.get("ZEP_USER_ID", "owner")
DIGEST_PATH = os.environ.get("DIGEST_PATH", "/data/digest.txt")

ZEP_HEADERS = {
    "Authorization": f"Bearer {ZEP_API_KEY}",
    "Content-Type": "application/json",
}

server = Server("memory")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="remember",
            description=(
                "Store a fact, observation, or preference into long-term memory. "
                "Use this when you learn something worth keeping across sessions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact or observation to remember"}
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="recall",
            description=(
                "Semantic search over long-term memory (iMessages, emails, past facts). "
                "Use this to answer questions about past events or learned preferences."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in memory"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_docs",
            description=(
                "Semantic search over raw documents: Notion pages, email bodies. "
                "Use when you need the actual source text, not just extracted facts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "limit": {"type": "integer", "default": 5},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["notion", "email"]},
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_digest",
            description=(
                "Get the pre-built summary of the last 24 hours of activity. "
                "Fast - reads from cache, no LLM call."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "remember":
            session_id = "openclaw_session"
            async with httpx.AsyncClient(base_url=ZEP_URL) as client:
                r = await client.get(f"/api/v2/sessions/{session_id}", headers=ZEP_HEADERS)
                if r.status_code == 404:
                    await client.post(
                        "/api/v2/sessions",
                        headers=ZEP_HEADERS,
                        json={"session_id": session_id, "user_id": ZEP_USER_ID},
                    )
                r = await client.post(
                    f"/api/v2/sessions/{session_id}/memory",
                    headers=ZEP_HEADERS,
                    json={"type": "text", "content": arguments["content"], "source": "openclaw"},
                )
                r.raise_for_status()
            return [TextContent(type="text", text="Remembered.")]

        elif name == "recall":
            async with httpx.AsyncClient(base_url=ZEP_URL) as client:
                r = await client.post(
                    "/api/v2/graph/search",
                    headers=ZEP_HEADERS,
                    json={
                        "query": arguments["query"],
                        "user_id": ZEP_USER_ID,
                        "limit": arguments.get("limit", 5),
                        "search_type": "edge",
                    },
                )
                if not r.is_success:
                    return [TextContent(type="text", text="No relevant memories found.")]
                edges = r.json().get("edges", [])
                facts = [e for e in edges if e.get("fact")]
                if not facts:
                    return [TextContent(type="text", text="No relevant memories found.")]
                lines = []
                for e in facts:
                    line = f"- {e['fact']}"
                    if e.get("valid_at"):
                        line += f" (since {e['valid_at'][:10]})"
                    if e.get("invalid_at"):
                        line += " [superseded]"
                    lines.append(line)
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "search_docs":
            results = await qdrant_writer.search_docs(
                query=arguments["query"],
                limit=arguments.get("limit", 5),
                source_filter=arguments.get("sources"),
            )
            if not results:
                return [TextContent(type="text", text="No documents found.")]
            parts = []
            for r in results:
                header = f"[{r['source'].upper()}] {r['title']}"
                if r.get("url"):
                    header += f" - {r['url']}"
                parts.append(f"{header}\n{r['text']}\n(relevance: {r['score']})")
            return [TextContent(type="text", text="\n\n---\n\n".join(parts))]

        elif name == "get_digest":
            try:
                digest = Path(DIGEST_PATH).read_text()
            except FileNotFoundError:
                digest = "No digest available yet."
            return [TextContent(type="text", text=digest)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]
