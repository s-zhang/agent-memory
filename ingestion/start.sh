#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Start tailscaled in userspace networking mode (no /dev/net/tun on Railway).
# Auth runs in the background so uvicorn starts immediately and Railway's
# health check doesn't time out.
# ---------------------------------------------------------------------------
mkdir -p /db/tailscale

tailscaled \
    --tun=userspace-networking \
    --socks5-server=localhost:1055 \
    --statedir=/db/tailscale \
    2>&1 | sed 's/^/[tailscale] /' &

# Authenticate asynchronously — uvicorn starts before this finishes.
# If state is already persisted in /db/tailscale, tailscaled auto-reconnects
# as the same node (stable hostname). tailscale up is only run on first boot
# or when the persisted state has no valid authentication.
(
    for i in $(seq 1 15); do
        tailscale status >/dev/null 2>&1 && break
        sleep 1
    done
    if tailscale status >/dev/null 2>&1; then
        echo "[tailscale] Already authenticated — skipping tailscale up (using persisted state)"
    else
        echo "[tailscale] No valid state found — running tailscale up..."
        tailscale up \
            --auth-key="${TS_AUTHKEY}" \
            --hostname="railway-ingestion" \
            --accept-dns=false \
            2>&1 | sed 's/^/[tailscale] /'
        echo "[tailscale] tailscale up exit code: $?"
    fi
    tailscale status 2>&1 | head -3 | sed 's/^/[tailscale] /' \
        && echo "[tailscale] Connected to tailnet" \
        || echo "[tailscale] WARNING: not connected — contact resolver will fall back to raw addresses"
) &

# Expose the SOCKS5 address for the contact resolver to use explicitly.
# We do NOT set ALL_PROXY globally — that would route Railway-internal
# traffic (Zep, Qdrant) through Tailscale and break startup.
export TAILSCALE_SOCKS5=socks5://localhost:1055

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
