"""SQLite storage: remembers every event seen and whether it's been pushed to Google Calendar."""
import sqlite3
from datetime import datetime, timezone
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
    first_seen   TEXT DEFAULT CURRENT_TIMESTAMP,
    removed      INTEGER NOT NULL DEFAULT 0  -- 1 = cancelled / no longer listed
);

-- Every email we've looked at, so each is processed once. Deliberately stores no
-- subject/sender: this database is committed to a public repo.
CREATE TABLE IF NOT EXISTS emails_seen (
    id         TEXT PRIMARY KEY,
    subject    TEXT,
    n_events   INTEGER NOT NULL,
    seen_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

EVENT_FIELDS = [f.name for f in fields(Event)]


def connect(path: str = "freefood.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    if "removed" not in cols:  # migrate databases created before this column existed
        conn.execute("ALTER TABLE events ADD COLUMN removed INTEGER NOT NULL DEFAULT 0")
    return conn


def upsert(conn: sqlite3.Connection, event: Event) -> None:
    cols = ["uid", *EVENT_FIELDS, "content_hash"]
    vals = [event.uid, *(getattr(event, f) for f in EVENT_FIELDS), event.content_hash()]
    # Re-listing a previously removed event revives it (it'll be re-created on the calendar).
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols[1:]) + ", removed=0"
    conn.execute(
        f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        vals,
    )


def needing_sync(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """New events, or events whose details changed since the last sync."""
    return conn.execute(
        "SELECT * FROM events WHERE removed = 0 "
        "AND (synced_hash IS NULL OR synced_hash != content_hash) ORDER BY start"
    ).fetchall()


def mark_synced(conn: sqlite3.Connection, uid: str, gcal_id: str, content_hash: str) -> None:
    conn.execute(
        "UPDATE events SET gcal_id=?, synced_hash=? WHERE uid=?", (gcal_id, content_hash, uid)
    )


def upcoming(conn: sqlite3.Connection, source: str) -> list[sqlite3.Row]:
    """Events from `source` that haven't ended yet and haven't been removed."""
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT * FROM events WHERE source = ? AND removed = 0", (source,)
    ).fetchall()
    return [r for r in rows if datetime.fromisoformat(r["end"]) > now]


def mark_removed(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute(
        "UPDATE events SET removed=1, gcal_id=NULL, synced_hash=NULL WHERE uid=?", (uid,)
    )


def seen_email_ids(conn: sqlite3.Connection) -> set[str]:
    return {r["id"] for r in conn.execute("SELECT id FROM emails_seen")}


def mark_email_seen(conn: sqlite3.Connection, email_id: str, n_events: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO emails_seen (id, n_events) VALUES (?, ?)", (email_id, n_events)
    )
