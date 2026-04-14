#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Start Tailscale in userspace networking mode.
# Railway containers don't have /dev/net/tun, so we use the SOCKS5 proxy
# that tailscaled exposes instead of a kernel TUN device.
# ---------------------------------------------------------------------------
mkdir -p /var/lib/tailscale

tailscaled \
    --tun=userspace-networking \
    --socks5-server=localhost:1055 \
    --statedir=/var/lib/tailscale \
    &

# Wait for the daemon socket to appear
for i in $(seq 1 10); do
    tailscale status >/dev/null 2>&1 && break
    sleep 1
done

# Authenticate with a pre-auth key (set TS_AUTHKEY in Railway env vars).
# --ephemeral removes the node from the tailnet automatically when the
# container exits, keeping the admin console tidy.
tailscale up \
    --authkey="${TS_AUTHKEY}" \
    --hostname="railway-ingestion" \
    --accept-dns=false \
    --ephemeral

echo "Tailscale up — routing Tailscale traffic via socks5h://localhost:1055"

# Route all outbound traffic through the Tailscale SOCKS5 proxy.
# NO_PROXY ensures Railway-internal services (Zep, Qdrant) bypass it.
export ALL_PROXY=socks5h://localhost:1055
export NO_PROXY="localhost,127.0.0.1,*.railway.internal"

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
