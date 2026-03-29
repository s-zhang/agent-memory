# Memory Stack Setup

## 1. Configure environment

```bash
cp .env.example .env
# Fill in: OPENAI_API_KEY, ZEP_API_KEY, QDRANT_API_KEY,
#          BLUEBUBBLES_*, IMAP_*, NOTION_*
```

## 2. Start Docker stack

```bash
docker compose up -d
```

Services:
- Zep API: http://localhost:8010
- Qdrant UI: http://localhost:6333/dashboard
- Ingestion webhooks: http://localhost:8000

## 3. Install MCP server dependencies

```bash
cd memory-mcp
pip install -r requirements.txt
cp .env.example .env   # fill in same values as above
```

## 4. Register MCP server in Claude Code

Add to `~/.claude/settings.json` under `mcpServers`:

```json
"memory": {
  "command": "python3",
  "args": ["/Users/shanna/agent-memory/memory-mcp/server.py"],
  "env": {
    "ZEP_URL": "http://localhost:8010",
    "ZEP_API_KEY": "your_zep_api_key",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_API_KEY": "your_qdrant_api_key",
    "OPENAI_API_KEY": "your_openai_api_key",
    "DIGEST_PATH": "/data/digest.txt"
  }
}
```

## 5. Add hooks to Claude Code

Add to `~/.claude/settings.json` under `hooks`:

```json
"PostToolUse": [
  {
    "matcher": "Bash|Edit|Write",
    "hooks": [{
      "type": "command",
      "command": "ZEP_URL=http://localhost:8010 ZEP_API_KEY=your_key /Users/shanna/agent-memory/memory-mcp/hooks/post-tool-ingest.sh"
    }]
  }
]
```

## 6. Configure webhooks

### BlueBubbles
In BlueBubbles server settings -> Webhooks:
- URL: `http://your-railway-url/webhooks/bluebubbles`
- Events: `new-message`, `updated-message`
- Set the same secret as `BLUEBUBBLES_WEBHOOK_SECRET`

### Notion
In Notion integration settings -> Webhooks:
- URL: `http://your-railway-url/webhooks/notion`
- Events: page.created, page.content_updated, page.properties_updated, page.deleted

## 7. Deploy to Railway

```bash
# Install Railway CLI
brew install railway

# Login and link project
railway login
railway init

# Deploy
railway up
```

Set all variables from `.env` as Railway shared variables.
Public webhook URL will be: `https://<ingestion-service>.railway.app`

## Architecture

```
BlueBubbles (Mac) --webhook--> /webhooks/bluebubbles --> Zep
Notion ------------webhook--> /webhooks/notion        --> Qdrant
Email IMAP ------scheduled--> email connector  -------> Zep + Qdrant
                                                            |
                                                     memory-mcp server
                                                            |
                                                        OpenClaw
```

## OpenClaw tools available

| Tool | What it does |
|------|-------------|
| `remember(content)` | Store a fact into Zep |
| `recall(query)` | Semantic search over Zep knowledge graph |
| `search_docs(query)` | Semantic search over Qdrant (Notion, email bodies) |
| `get_digest()` | Pre-built 24h activity summary |
