#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Start tailscaled in userspace networking mode (no /dev/net/tun on Railway).
# Auth runs in the background so uvicorn starts immediately and Railway's
# health check doesn't time out.
# ---------------------------------------------------------------------------
mkdir -p /var/lib/tailscale

tailscaled \
    --tun=userspace-networking \
    --socks5-server=localhost:1055 \
    --statedir=/var/lib/tailscale \
    2>&1 | sed 's/^/[tailscale] /' &

# Authenticate asynchronously — uvicorn starts before this finishes.
# The contact resolver falls back to raw phone numbers until Tailscale is up,
# then routes correctly once the SOCKS5 proxy is ready.
(
    for i in $(seq 1 15); do
        tailscale status >/dev/null 2>&1 && break
        sleep 1
    done
    tailscale up \
        --auth-key="${TS_AUTHKEY}" \
        --hostname="railway-ingestion" \
        --accept-dns=false \
        --ephemeral \
        && echo "[tailscale] Connected to tailnet" \
        || echo "[tailscale] WARNING: tailscale up failed — contact resolver will fall back to raw addresses"
) &

# Expose the SOCKS5 address for the contact resolver to use explicitly.
# We do NOT set ALL_PROXY globally — that would route Railway-internal
# traffic (Zep, Qdrant) through Tailscale and break startup.
export TAILSCALE_SOCKS5=socks5h://localhost:1055

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
