"""
MCP server (SSE transport) mounted inside the ingestion FastAPI app.
Exposes: remember, recall, search_docs, get_digest
"""
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

            # Search Graphiti knowledge graph for extracted facts (higher signal)
            graph_results = await graphiti_writer.search(query, num_results=limit)

            # Search Qdrant for raw content matches
            qdrant_results = await qdrant_writer.search_docs(
                query=query,
                limit=limit,
                source_filter=["imessage", "email", "memory"],
            )

            lines: list[str] = []
            for r in graph_results:
                ts = f" ({r['valid_at'][:10]})" if r.get("valid_at") else ""
                lines.append(f"[KNOWLEDGE{ts}] {r['fact']}")
            for r in qdrant_results:
                source_label = r["source"].upper()
                lines.append(f"[{source_label}] {r['text']} (relevance: {r['score']})")

            if not lines:
                return [TextContent(type="text", text="No relevant memories found.")]
            return [TextContent(type="text", text="\n\n".join(lines))]

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
