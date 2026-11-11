"""
Usage:
  python -m freefood fetch    # scrape sources, save to SQLite, print what was found
  python -m freefood sync     # fetch, then push new/changed events to Google Calendar
                              # and delete ones that were cancelled / no longer listed
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db, terplink

ET = ZoneInfo("America/New_York")

# Safety valve: if a source suddenly "loses" lots of events, it's more likely the
# scrape broke than that everything got cancelled — so don't delete anything.
MAX_REMOVALS = 5
MAX_REMOVAL_FRACTION = 0.3


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (KEY=value lines); real env vars take precedence."""
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def stale_events(conn, source: str, fetched_uids: set[str]) -> list:
    """Upcoming events we have from `source` that the source no longer lists."""
    upcoming = db.upcoming(conn, source)
    stale = [r for r in upcoming if r["uid"] not in fetched_uids]
    limit = max(MAX_REMOVALS, int(len(upcoming) * MAX_REMOVAL_FRACTION))
    if stale and (not fetched_uids or len(stale) > limit):
        print(
            f"WARNING: {source} dropped {len(stale)}/{len(upcoming)} upcoming events — "
            "looks like a scrape problem, not deleting anything this run."
        )
        return []
    return stale


def fetch(conn) -> list:
    events = terplink.fetch_events()
    for e in events:
        db.upsert(conn, e)
    conn.commit()
    print(f"Found {len(events)} upcoming free-food events on TerpLink:\n")
    for e in events:
        start = datetime.fromisoformat(e.start).astimezone(ET)
        print(f"  {start:%a %b %d %I:%M %p}  {e.title[:60]:<60}  @ {e.location[:40]}")
    return stale_events(conn, "terplink", {e.uid for e in events})


def main() -> None:
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd not in ("fetch", "sync"):
        sys.exit(__doc__)
    conn = db.connect()
    stale = fetch(conn)
    if stale:
        print(f"\n{len(stale)} event(s) no longer listed:")
        for r in stale:
            print(f"  - {r['title']}")
    if cmd == "sync":
        from . import gcal

        print("\nSyncing to Google Calendar...")
        n, removed = gcal.sync(conn, stale)
        print(f"Done: {n} created/updated, {removed} removed.")


if __name__ == "__main__":
    main()
