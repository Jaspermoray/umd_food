"""Push events to a Google Calendar using a service account."""
import os
import sqlite3

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import db

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _service():
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


SOURCE_LABELS = {"terplink": "TerpLink", "email": "Email"}


def _body(row: sqlite3.Row) -> dict:
    desc = row["description"] or ""
    if len(desc) > 1500:
        desc = desc[:1500] + "…"
    label = SOURCE_LABELS.get(row["source"], row["source"])
    link = f"{row['url']}\n\n" if row["url"] else ""
    body = {
        "summary": f"🍕 {row['title']}",
        "location": row["location"],
        "description": f"{link}{desc}\n\n(source: {label})",
        "start": {"dateTime": row["start"], "timeZone": "America/New_York"},
        "end": {"dateTime": row["end"], "timeZone": "America/New_York"},
    }
    if row["url"]:
        body["source"] = {"title": label, "url": row["url"]}
    return body


def sync(conn: sqlite3.Connection, to_remove: list[sqlite3.Row] = ()) -> tuple[int, int]:
    """Create/update changed events and delete `to_remove`. Returns (upserted, removed)."""
    calendar_id = os.environ["CALENDAR_ID"]
    svc = _service()

    for row in to_remove:
        if row["gcal_id"]:
            try:
                svc.events().delete(calendarId=calendar_id, eventId=row["gcal_id"]).execute()
            except HttpError as e:
                if e.resp.status not in (404, 410):  # already gone is fine
                    raise
        db.mark_removed(conn, row["uid"])
        conn.commit()
        print(f"  removed: {row['title']}")

    rows = db.needing_sync(conn)
    for row in rows:
        body = _body(row)
        if row["gcal_id"]:
            result = svc.events().update(
                calendarId=calendar_id, eventId=row["gcal_id"], body=body
            ).execute()
        else:
            result = svc.events().insert(calendarId=calendar_id, body=body).execute()
        db.mark_synced(conn, row["uid"], result["id"], row["content_hash"])
        conn.commit()
        print(f"  synced: {row['title']}")
    return len(rows), len(to_remove)
