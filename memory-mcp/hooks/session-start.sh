#!/usr/bin/env bash
# SessionStart hook - prepend 24h digest to OpenClaw's context.
# Called by Claude Code before each session.

DIGEST_PATH="${DIGEST_PATH:-/data/digest.txt}"

if [ -f "$DIGEST_PATH" ]; then
    echo "--- Memory Digest ---"
    cat "$DIGEST_PATH"
    echo "--- End Digest ---"
fi
