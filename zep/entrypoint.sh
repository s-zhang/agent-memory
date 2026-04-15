#!/bin/sh
# Generate Zep config.yaml from environment variables.
# This is needed because the pre-release ghcr.io/getzep/zep image has a broken
# Viper env-var binding for store.type — it must come from the config file.
set -e

cat > /app/config.yaml << EOF
llm:
  service: openai
  model: gpt-4o-mini

extractors:
  documents:
    embeddings:
      enabled: true
      service: openai
      dimensions: 1536
  messages:
    embeddings:
      enabled: true
      service: openai
      dimensions: 1536
    summarizer:
      embeddings:
        enabled: true
        service: openai
        dimensions: 1536

store:
  type: ${ZEP_STORE_TYPE:-falkordb}
  falkordb:
    url: ${ZEP_FALKORDB_URL:-redis://falkordb.railway.internal:6379}
  postgres:
    dsn: "${ZEP_STORE_POSTGRES_DSN:-}"

server:
  host: "0.0.0.0"
  port: 8000

auth:
  required: ${ZEP_AUTH_REQUIRED:-false}
  secret: "${ZEP_AUTH_SECRET:-}"

openai_endpoint: ""
openai_org_id: ""
EOF

echo "[zep-entrypoint] Generated config.yaml with store.type=${ZEP_STORE_TYPE:-falkordb}"

exec /app/zep
