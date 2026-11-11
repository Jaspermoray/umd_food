"""Push events to a Google Calendar using a service account."""
import os
import sqlite3

from google.oauth2 import service_account
from googleapiclient.discovery import build

from . import db

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _service():
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _body(row: sqlite3.Row) -> dict:
    desc = row["description"] or ""
    if len(desc) > 1500:
        desc = desc[:1500] + "…"
    return {
        "summary": f"🍕 {row['title']}",
        "location": row["location"],
        "description": f"{row['url']}\n\n{desc}\n\n(source: {row['source']})",
        "start": {"dateTime": row["start"], "timeZone": "America/New_York"},
        "end": {"dateTime": row["end"], "timeZone": "America/New_York"},
        "source": {"title": "TerpLink", "url": row["url"]},
    }


def sync(conn: sqlite3.Connection) -> int:
    calendar_id = os.environ["CALENDAR_ID"]
    svc = _service()
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
    return len(rows)
