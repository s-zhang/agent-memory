"""
Idempotency tracker - prevents duplicate ingestion from both webhooks and
scheduled pulls hitting the same content.
"""
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import config


def _conn() -> sqlite3.Connection:
    Path(config.DEDUP_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DEDUP_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingested (
            source       TEXT NOT NULL,
            external_id  TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            ingested_at  TEXT NOT NULL,
            PRIMARY KEY (source, external_id)
        )
    """)
    conn.commit()
    return conn


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def is_changed(source: str, external_id: str, new_hash: str) -> bool:
    """Returns True if this item is new or its content has changed."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT content_hash FROM ingested WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
    return row is None or row[0] != new_hash


def mark_ingested(source: str, external_id: str, new_hash: str) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO ingested (source, external_id, content_hash, ingested_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                ingested_at  = excluded.ingested_at
            """,
            (source, external_id, new_hash, datetime.utcnow().isoformat()),
        )
        conn.commit()


def delete_record(source: str, external_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM ingested WHERE source=? AND external_id=?",
            (source, external_id),
        )
        conn.commit()
