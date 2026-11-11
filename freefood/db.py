"""SQLite storage: remembers every event seen and whether it's been pushed to Google Calendar."""
import sqlite3
from dataclasses import fields

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    uid          TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    title        TEXT NOT NULL,
    start        TEXT NOT NULL,
    end          TEXT NOT NULL,
    location     TEXT,
    url          TEXT,
    description  TEXT,
    content_hash TEXT NOT NULL,
    gcal_id      TEXT,          -- Google Calendar event id, once synced
    synced_hash  TEXT,          -- content_hash at last successful sync
    first_seen   TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

EVENT_FIELDS = [f.name for f in fields(Event)]


def connect(path: str = "freefood.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, event: Event) -> None:
    cols = ["uid", *EVENT_FIELDS, "content_hash"]
    vals = [event.uid, *(getattr(event, f) for f in EVENT_FIELDS), event.content_hash()]
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
    conn.execute(
        f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        vals,
    )


def needing_sync(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """New events, or events whose details changed since the last sync."""
    return conn.execute(
        "SELECT * FROM events WHERE synced_hash IS NULL OR synced_hash != content_hash "
        "ORDER BY start"
    ).fetchall()


def mark_synced(conn: sqlite3.Connection, uid: str, gcal_id: str, content_hash: str) -> None:
    conn.execute(
        "UPDATE events SET gcal_id=?, synced_hash=? WHERE uid=?", (gcal_id, content_hash, uid)
    )
