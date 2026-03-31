"""
Ingestion service entry point.
- Webhook receiver for Notion + BlueBubbles
- Pulls scheduler (IMAP, Notion, BlueBubbles)
- Startup: initial bulk-pull and Qdrant collection setup
"""
import asyncio
import logging
from contextlib import asynccontextmanager

import os

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from mcp.server.sse import SseServerTransport
from pydantic import BaseModel

MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

import mcp_server as mcp_module
from connectors import bluebubbles, email_imap, notion
from scheduler import create_scheduler
from webhooks import bluebubbles as bb_webhook
from webhooks import notion as notion_webhook
from writers import qdrant_writer
from writers.qdrant_writer import ensure_collection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Ingestion service starting up")

    await ensure_collection()

    # Initial bulk pull (runs in background to not block startup)
    async def initial_pull():
        logger.info("Running initial bulk pull")
        await asyncio.gather(
            bluebubbles.pull_recent(messages_per_chat=200),
            email_imap.pull_recent(since_hours=48),
            notion.pull_recent(since_hours=48),
            return_exceptions=True,
        )
        logger.info("Initial bulk pull complete")

    asyncio.create_task(initial_pull())

    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Ingestion service shut down")


app = FastAPI(title="Memory Ingestion Service", lifespan=lifespan)
sse = SseServerTransport("/mcp/messages/")


@app.get("/health")
async def health():
    return {"status": "ok"}


def _verify_mcp_key(request: Request) -> None:
    if not MCP_API_KEY:
        return  # not configured — allow (dev mode)
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {MCP_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/mcp/sse")
async def mcp_sse(request: Request):
    _verify_mcp_key(request)
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp_module.server.run(
            streams[0], streams[1], mcp_module.server.create_initialization_options()
        )


@app.post("/mcp/messages/")
async def mcp_messages(request: Request):
    _verify_mcp_key(request)
    await sse.handle_post_message(request.scope, request.receive, request._send)


@app.post("/webhooks/notion")
async def webhook_notion(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    await notion_webhook.verify_signature(request, body)
    payload = await request.json()
    # ACK immediately, process in background
    background_tasks.add_task(notion_webhook.handle, payload)
    return Response(status_code=200)


class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    sources: list[str] | None = None


@app.post("/search")
async def search(req: SearchRequest):
    results = await qdrant_writer.search_docs(
        query=req.query,
        limit=req.limit,
        source_filter=req.sources,
    )
    return {"results": results}


@app.post("/webhooks/bluebubbles")
async def webhook_bluebubbles(request: Request, background_tasks: BackgroundTasks):
    await bb_webhook.verify_token(request)
    payload = await request.json()
    background_tasks.add_task(bb_webhook.handle, payload)
    return Response(status_code=200)
