#!/usr/bin/env bash
# PostToolUse hook - fire-and-forget ingestion of OpenClaw's actions into Zep.
# Reads tool input from stdin (Claude Code hook protocol).
# Runs async in background - does not block OpenClaw.

read -r -d '' INPUT

TOOL_NAME=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)
TOOL_INPUT=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('tool_input','')))" 2>/dev/null)

# Only ingest meaningful tool outputs - skip reads/searches
case "$TOOL_NAME" in
    Bash|Edit|Write)
        ;;
    *)
        echo "$INPUT"
        exit 0
        ;;
esac

ZEP_URL="${ZEP_URL:-http://localhost:8010}"
ZEP_API_KEY="${ZEP_API_KEY:-}"

# Build a short summary of what happened
SUMMARY="OpenClaw used $TOOL_NAME: $(echo "$TOOL_INPUT" | head -c 300)"

# Fire-and-forget POST to Zep in background
(python3 - <<EOF &
import urllib.request, json, os, sys

url = "${ZEP_URL}/api/v2/sessions/openclaw_session/memory"
headers = {
    "Authorization": f"Bearer ${ZEP_API_KEY}",
    "Content-Type": "application/json",
}
body = json.dumps({
    "type": "text",
    "content": """$SUMMARY""",
    "source": "openclaw_hook",
}).encode()

req = urllib.request.Request(url, data=body, headers=headers, method="POST")
try:
    urllib.request.urlopen(req, timeout=5)
except Exception:
    pass
EOF
) 2>/dev/null

# Pass input through unchanged (hooks must echo input back)
echo "$INPUT"
