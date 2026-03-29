"""
IMAP email connector - poll for new/updated emails.
- Email facts -> Zep (via text episode, one per thread)
- Email bodies -> Qdrant (raw chunks for verbatim retrieval)
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
from writers import qdrant_writer, zep_writer

logger = logging.getLogger(__name__)

_html_converter = html2text.HTML2Text()
_html_converter.ignore_links = True
_html_converter.ignore_images = True


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


def _session_id_for_thread(thread_id: str | None, subject: str) -> str:
    if thread_id:
        clean = re.sub(r"[^a-zA-Z0-9_-]", "", thread_id)
        return f"email_{clean}"
    # Fallback: normalize subject
    clean_subject = re.sub(r"\s+", "_", re.sub(r"[^a-zA-Z0-9\s]", "", subject.lower()))[:50]
    return f"email_{clean_subject}"


async def pull_recent(since_hours: int = 1) -> None:
    """Poll IMAP for emails since N hours ago."""
    logger.info("IMAP: polling for emails since %dh ago", since_hours)
    since = (datetime.utcnow() - timedelta(hours=since_hours)).strftime("%d-%b-%Y")

    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as imap:
            imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
            imap.select(config.IMAP_MAILBOX)
            _, data = imap.search(None, f"SINCE {since}")
            msg_ids = data[0].split() if data[0] else []
            logger.info("IMAP: found %d messages", len(msg_ids))

            for num in msg_ids:
                try:
                    _, raw = imap.fetch(num, "(RFC822)")
                    raw_bytes = raw[0][1] if raw and raw[0] else None
                    if not raw_bytes:
                        continue
                    await _ingest_raw_email(raw_bytes)
                except Exception as e:
                    logger.error("IMAP: error ingesting message %s: %s", num, e)
    except Exception as e:
        logger.error("IMAP connection error: %s", e)


async def _ingest_raw_email(raw_bytes: bytes) -> None:
    msg = email.message_from_bytes(raw_bytes)

    message_id = _decode_header(msg.get("Message-ID", "")).strip("<>").strip()
    if not message_id:
        return

    subject = _decode_header(msg.get("Subject", "(no subject)"))
    sender = _decode_header(msg.get("From", ""))
    recipient = _decode_header(msg.get("To", ""))
    thread_id = _decode_header(msg.get("Thread-Index") or msg.get("X-GM-THRID") or "")
    date_str = msg.get("Date", "")
    body = _extract_body(msg)

    if not body:
        return

    full_text = f"Subject: {subject}\nFrom: {sender}\nTo: {recipient}\n\n{body}"
    h = dedup.content_hash(full_text)
    if not dedup.is_changed("email", message_id, h):
        return

    # Qdrant: raw body for verbatim retrieval
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

    # Zep: feed as episode so facts get extracted
    session_id = _session_id_for_thread(thread_id, subject)
    summary = f"Email from {sender} about '{subject}':\n{body[:1000]}"
    await zep_writer.add_text_episode(
        session_id=session_id,
        content=summary,
        source="email",
        metadata={"message_id": message_id, "subject": subject, "sender": sender},
    )

    dedup.mark_ingested("email", message_id, h)
    logger.debug("Ingested email %s", message_id)
