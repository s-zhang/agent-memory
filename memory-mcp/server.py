#!/usr/bin/env python3
"""
Memory MCP server for OpenClaw.
Exposes: remember, recall, search_docs, get_digest
Runs as a stdio MCP server - registered in ~/.claude/settings.json
"""
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

load_dotenv(Path(__file__).parent / ".env")

import qdrant_client as qdrant
import zep_client as zep

DIGEST_PATH = os.environ.get("DIGEST_PATH", "/data/digest.txt")

app = Server("memory")


@app.list_tools()
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
                    "content": {
                        "type": "string",
                        "description": "The fact or observation to remember",
                    }
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
                    "query": {
                        "type": "string",
                        "description": "What to search for in memory",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results (default 5)",
                        "default": 5,
                    },
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
                    "query": {
                        "type": "string",
                        "description": "What to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results (default 5)",
                        "default": 5,
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["notion", "email"]},
                        "description": "Filter by source type (optional)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_digest",
            description=(
                "Get the pre-built summary of the last 24 hours of activity "
                "(messages, emails). Fast - reads from cache, no LLM call."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "remember":
            result = await zep.remember(arguments["content"])
            return [TextContent(type="text", text=result)]

        elif name == "recall":
            facts = await zep.recall(
                query=arguments["query"],
                limit=arguments.get("limit", 5),
            )
            if not facts:
                return [TextContent(type="text", text="No relevant memories found.")]
            lines = []
            for f in facts:
                line = f"- {f['fact']}"
                if f.get("valid_from"):
                    line += f" (since {f['valid_from'][:10]})"
                if f.get("invalid_at"):
                    line += " [superseded]"
                lines.append(line)
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "search_docs":
            results = await qdrant.search_docs(
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
                digest = "No digest available yet. It will be generated tonight."
            return [TextContent(type="text", text=digest)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
