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

from . import db, dedupe, terplink

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


def _fmt(e) -> str:
    start = datetime.fromisoformat(e.start).astimezone(ET)
    return f"  {start:%a %b %d %I:%M %p}  {e.title[:60]:<60}  @ {e.location[:40]}"


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


def fetch_terplink(conn) -> list:
    events = terplink.fetch_events()
    for e in events:
        db.upsert(conn, e)
    conn.commit()
    print(f"Found {len(events)} upcoming free-food events on TerpLink:\n")
    for e in events:
        print(_fmt(e))
    return stale_events(conn, "terplink", {e.uid for e in events})


def fetch_email(conn) -> None:
    from . import gmail

    if not gmail.is_configured():
        print("\nEmail: skipped (GMAIL_TOKEN not configured).")
        return

    from . import extract, rules

    # Free rule-based extraction by default; Claude only if an API key is configured.
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        extractor, api_errors, mode = (
            lambda m: extract.extract_events(client, m), (anthropic.APIError,), "Claude"
        )
    else:
        extractor, api_errors, mode = rules.extract_events, (), "rules"

    emails = gmail.fetch_recent(skip_ids=db.seen_email_ids(conn))
    eligible = [m for m in emails if m.is_bulk or m.labeled]  # never personal emails
    candidates = [m for m in eligible if extract.might_have_food(m)]
    print(
        f"\nEmail ({mode}): {len(emails)} new message(s), {len(eligible)} from lists/newsletters, "
        f"{len(candidates)} mention food."
    )
    for m in emails:
        if m not in candidates:
            db.mark_email_seen(conn, m.id, 0)
    conn.commit()

    known = db.upcoming(conn, "terplink") + db.upcoming(conn, "email")
    for m in candidates:
        try:
            found = extractor(m)
        except api_errors as err:
            # Leave it unseen so the next run retries it.
            print(f"  error on '{m.subject[:50]}': {err.__class__.__name__}; will retry")
            continue
        added = 0
        for ev in found:
            if any(dedupe.same_event(ev, k) for k in known):
                print(f"  duplicate, skipped: {ev.title}")
                continue
            db.upsert(conn, ev)
            known.append(ev)
            added += 1
            print(_fmt(ev))
        db.mark_email_seen(conn, m.id, added)
        conn.commit()


def email_dupes_of_terplink(conn) -> list:
    """Email-sourced events that TerpLink now also lists — TerpLink's version wins."""
    tl = db.upcoming(conn, "terplink")
    return [r for r in db.upcoming(conn, "email") if any(dedupe.same_event(r, t) for t in tl)]


def main() -> None:
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd not in ("fetch", "sync"):
        sys.exit(__doc__)
    conn = db.connect()
    to_remove = fetch_terplink(conn)
    fetch_email(conn)
    to_remove += email_dupes_of_terplink(conn)
    if to_remove:
        print(f"\n{len(to_remove)} event(s) to remove (cancelled, unlisted, or duplicate):")
        for r in to_remove:
            print(f"  - {r['title']}")
    if cmd == "sync":
        from . import gcal

        print("\nSyncing to Google Calendar...")
        n, removed = gcal.sync(conn, to_remove)
        print(f"Done: {n} created/updated, {removed} removed.")


if __name__ == "__main__":
    main()
