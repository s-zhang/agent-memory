"""
Email connector — shared ingestion logic used by both:
  - IMAP polling (pull_recent)
  - Cloudflare Email Worker webhook (ingest_raw_email)

Threading uses RFC-standard References/In-Reply-To headers so it works
correctly for forwarded mail (which strips Gmail's X-GM-THRID).

Loop / auto-reply detection drops bounces, OOO replies, and list mail
before they reach the knowledge graph.
"""
import email
import email.header
import email.utils
import imaplib
import logging
import re
from datetime import datetime, timedelta

import html2text

import config
import dedup
from writers import graphiti_writer, qdrant_writer

logger = logging.getLogger(__name__)

_html_converter = html2text.HTML2Text()
_html_converter.ignore_links = True
_html_converter.ignore_images = True

# Auto-generated mail indicators (RFC 3834 + common vendor headers).
# If any header matches, the message is silently dropped to prevent loops
# and noise in the knowledge graph.
_AUTO_GENERATED_CHECKS: list[tuple[str, object]] = [
    ("Auto-Submitted",          lambda v: v.strip().lower() not in ("no", "")),
    ("Precedence",              lambda v: v.strip().lower() in ("bulk", "list", "junk")),
    ("X-Autoreply",             lambda _: True),
    ("X-Auto-Response-Suppress", lambda _: True),
]


def _decode_header(value: str | bytes | None) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _is_auto_generated(msg: email.message.Message) -> bool:
    """Return True for bounces, auto-replies, and list/bulk mail."""
    for header, check in _AUTO_GENERATED_CHECKS:
        value = msg.get(header, "")
        if value and check(value):
            logger.debug("Dropping auto-generated email (header=%s value=%r)", header, value)
            return True
    return False


def _extract_body(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
            elif ct == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    body = _html_converter.handle(html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            raw = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                body = _html_converter.handle(raw)
            else:
                body = raw
    return body.strip()


def _clean_id(raw_id: str) -> str:
    """Sanitise a Message-ID for use as a DB / session key."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", raw_id)


def _session_id_for_thread(msg: email.message.Message) -> str:
    """
    Derive a stable thread ID using RFC-standard headers.

    Priority:
      1. References (first entry = thread root, survives forwarding)
      2. In-Reply-To (single-reply case)
      3. Message-ID of this message (new thread)
      4. Normalised Subject (last resort)
    """
    references = _decode_header(msg.get("References", ""))
    if references:
        root_id = references.split()[0].strip("<>")
        if root_id:
            return f"email_{_clean_id(root_id)}"

    in_reply_to = _decode_header(msg.get("In-Reply-To", "")).strip("<>")
    if in_reply_to:
        return f"email_{_clean_id(in_reply_to)}"

    message_id = _decode_header(msg.get("Message-ID", "")).strip("<>")
    if message_id:
        return f"email_{_clean_id(message_id)}"

    subject = _decode_header(msg.get("Subject", "(no subject)"))
    clean = re.sub(r"\s+", "_", re.sub(r"[^a-zA-Z0-9\s]", "", subject.lower()))[:50]
    return f"email_{clean}"


async def ingest_raw_email(raw_bytes: bytes) -> None:
    """
    Parse and ingest a single raw RFC 822 email into Graphiti + Qdrant.
    Used by both IMAP polling and the Cloudflare webhook path.
    Silently drops auto-generated mail (bounces, OOO replies, list mail).
    """
    msg = email.message_from_bytes(raw_bytes)

    if _is_auto_generated(msg):
        return

    message_id = _decode_header(msg.get("Message-ID", "")).strip("<>").strip()
    if not message_id:
        return

    subject = _decode_header(msg.get("Subject", "(no subject)"))
    sender = _decode_header(msg.get("From", ""))
    recipient = _decode_header(msg.get("To", ""))
    date_str = msg.get("Date", "")
    body = _extract_body(msg)

    if not body:
        return

    full_text = f"Subject: {subject}\nFrom: {sender}\nTo: {recipient}\n\n{body}"
    h = dedup.content_hash(full_text)
    if not dedup.is_changed("email", message_id, h):
        return

    timestamp = None
    if date_str:
        try:
            timestamp = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            pass

    await qdrant_writer.upsert_document(
        source="email",
        source_id=message_id,
        title=f"{subject} - {sender}",
        text=full_text,
        extra_metadata={
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "date": (timestamp or datetime.utcnow()).isoformat(),
        },
    )

    session_id = _session_id_for_thread(msg)
    summary = f"Email from {sender} about '{subject}':\n{body[:1000]}"
    await graphiti_writer.add_episode(
        name=session_id,
        body=summary,
        source="email",
        source_description=f"Email from {sender} about '{subject}'",
        reference_time=timestamp,
    )

    dedup.mark_ingested("email", message_id, h)
    logger.debug("Ingested email message_id=%s session=%s", message_id, session_id)


async def pull_recent(since_hours: int = 1) -> None:
    """Poll IMAP for emails since N hours ago. Skipped if IMAP_HOST is not configured."""
    if not config.IMAP_HOST:
        logger.info("IMAP not configured — skipping poll")
        return

    logger.info("IMAP: polling for emails since %dh ago", since_hours)
    since = (datetime.utcnow() - timedelta(hours=since_hours)).strftime("%d-%b-%Y")

    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as imap:
            imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
            imap.select(config.IMAP_MAILBOX)
            _, data = imap.search(None, f"SINCE {since}")
            msg_ids = data[0].split() if data[0] else []
            logger.info("IMAP: found %d messages in %s", len(msg_ids), config.IMAP_MAILBOX)

            for num in msg_ids:
                try:
                    _, raw = imap.fetch(num, "(RFC822)")
                    raw_bytes = raw[0][1] if raw and raw[0] else None
                    if not raw_bytes:
                        continue
                    await ingest_raw_email(raw_bytes)
                except Exception as e:
                    logger.error("IMAP: error ingesting message %s: %s", num, e)
    except Exception as e:
        logger.error("IMAP connection error: %s", e)
