"""
Usage:
  python -m freefood fetch    # scrape sources, save to SQLite, print what was found
  python -m freefood sync     # fetch, then push new/changed events to Google Calendar
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db, terplink

ET = ZoneInfo("America/New_York")


def fetch(conn) -> None:
    events = terplink.fetch_events()
    for e in events:
        db.upsert(conn, e)
    conn.commit()
    print(f"Found {len(events)} upcoming free-food events on TerpLink:\n")
    for e in events:
        start = datetime.fromisoformat(e.start).astimezone(ET)
        print(f"  {start:%a %b %d %I:%M %p}  {e.title[:60]:<60}  @ {e.location[:40]}")


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (KEY=value lines); real env vars take precedence."""
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def main() -> None:
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    conn = db.connect()
    fetch(conn)
    if cmd == "sync":
        from . import gcal

        print("\nSyncing to Google Calendar...")
        n = gcal.sync(conn)
        print(f"Done: {n} events created/updated.")
    elif cmd != "fetch":
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
