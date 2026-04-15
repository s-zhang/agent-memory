"""
MCP server (SSE transport) mounted inside the ingestion FastAPI app.
Exposes: remember, recall, get_digest
"""
import asyncio
import uuid as _uuid
from datetime import datetime
from pathlib import Path
import os

from mcp.server import Server
from mcp.types import TextContent, Tool

from writers import graphiti_writer, qdrant_writer

DIGEST_PATH = os.environ.get("DIGEST_PATH", "/data/digest.txt")

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
                "Semantic search over all memory: extracted facts from the knowledge graph "
                "(iMessages, emails, Notion, remembered facts) plus raw document text "
                "(Notion pages, email bodies). Use this to answer any question about past "
                "events, preferences, decisions, or document content."
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
            content = arguments["content"]
            episode_name = f"memory_{_uuid.uuid4()}"

            # Store in Qdrant for fast vector retrieval
            await qdrant_writer.upsert_document(
                source="memory",
                source_id=episode_name,
                title="Remembered fact",
                text=content,
            )
            # Store in Graphiti for knowledge graph extraction
            await graphiti_writer.add_episode(
                name=episode_name,
                body=content,
                source="memory",
                source_description="Explicitly remembered fact from conversation",
                reference_time=datetime.utcnow(),
            )
            return [TextContent(type="text", text="Remembered.")]

        elif name == "recall":
            query = arguments["query"]
            limit = arguments.get("limit", 5)

            # Run both searches concurrently
            graph_results, raw_fact_results, doc_results = await asyncio.gather(
                graphiti_writer.search(query, num_results=limit),
                qdrant_writer.search_docs(query=query, limit=limit, source_filter=["imessage", "email", "memory"]),
                qdrant_writer.search_docs(query=query, limit=limit, source_filter=["notion", "email"]),
            )

            parts: list[str] = []

            if graph_results:
                parts.append("## Facts")
                for r in graph_results:
                    ts = f" ({r['valid_at'][:10]})" if r.get("valid_at") else ""
                    parts.append(f"[KNOWLEDGE{ts}] {r['fact']}")

            if raw_fact_results:
                parts.append("## Messages & Notes")
                for r in raw_fact_results:
                    parts.append(f"[{r['source'].upper()}] {r['text']} (relevance: {r['score']})")

            # Deduplicate doc results against raw_fact_results by source_id
            seen_ids = {r["source_id"] for r in raw_fact_results if r.get("source_id")}
            unique_docs = [r for r in doc_results if r.get("source_id") not in seen_ids]
            if unique_docs:
                parts.append("## Documents")
                for r in unique_docs:
                    header = f"[{r['source'].upper()}] {r['title']}"
                    if r.get("url"):
                        header += f" - {r['url']}"
                    parts.append(f"{header}\n{r['text']}\n(relevance: {r['score']})")

            if not parts:
                return [TextContent(type="text", text="No relevant memories found.")]
            return [TextContent(type="text", text="\n\n".join(parts))]

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
