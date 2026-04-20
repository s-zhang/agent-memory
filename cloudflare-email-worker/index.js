/**
 * Cloudflare Email Worker — agent-memory ingest
 *
 * Receives every email delivered to ingest@yourdomain.com,
 * reads the raw RFC 822 bytes, and POSTs them to the Railway
 * ingestion service webhook.
 *
 * Required Worker secrets (set via `wrangler secret put`):
 *   WEBHOOK_SECRET  — must match EMAIL_WEBHOOK_SECRET on Railway
 *
 * Required Worker vars (set in wrangler.toml or dashboard):
 *   INGEST_URL  — https://your-service.up.railway.app/webhooks/email
 */
export default {
  async email(message, env, ctx) {
    // Read the full raw email into memory as an ArrayBuffer.
    const raw = await new Response(message.raw).arrayBuffer();

    const res = await fetch(env.INGEST_URL, {
      method: "POST",
      headers: {
        "Content-Type": "message/rfc822",
        "X-Email-Webhook-Secret": env.WEBHOOK_SECRET,
      },
      body: raw,
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "(unreadable)");
      // Throwing causes Cloudflare to retry delivery and alert on failure.
      throw new Error(`Ingest failed (${res.status}): ${body}`);
    }
  },
};
