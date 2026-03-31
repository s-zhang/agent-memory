"""
Ingestion service entry point.
- Webhook receiver for Notion + BlueBubbles
- Pulls scheduler (IMAP, Notion, BlueBubbles)
- Startup: initial bulk-pull and Qdrant collection setup
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import BaseModel

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

MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

mcp_manager = StreamableHTTPSessionManager(
    app=mcp_module.server,
    event_store=None,
    stateless=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ingestion service starting up")

    await ensure_collection()

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

    async with mcp_manager.run():
        yield

    scheduler.shutdown(wait=False)
    logger.info("Ingestion service shut down")


app = FastAPI(title="Memory Ingestion Service", lifespan=lifespan)


def _verify_mcp_key(request: Request) -> None:
    if not MCP_API_KEY:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {MCP_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health():
    return {"status": "ok"}



async def _mcp_asgi(scope, receive, send):
    if MCP_API_KEY:
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if auth != f"Bearer {MCP_API_KEY}":
            response = Response(
                content='{"error":"unauthorized","error_description":"Invalid or missing bearer token"}',
                status_code=401,
                headers={
                    "WWW-Authenticate": "Bearer",
                    "Content-Type": "application/json",
                },
            )
            await response(scope, receive, send)
            return
    await mcp_manager.handle_request(scope, receive, send)


app.mount("/mcp", _mcp_asgi)


@app.post("/webhooks/notion")
async def webhook_notion(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    await notion_webhook.verify_signature(request, body)
    payload = await request.json()
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
