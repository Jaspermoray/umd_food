"""Read recent emails from the bot's Gmail inbox (listservs, newsletters, forwards)."""
import base64
import html
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# Scan the whole inbox, but only *bulk* mail (mailing lists, newsletters) is ever used —
# person-to-person emails are skipped so private mail can't end up on the public calendar.
# Mail with this label is always included, as a manual override.
LABEL = os.environ.get("GMAIL_LABEL", "free-food")
LOOKBACK_QUERY = "newer_than:3d -in:chats -in:sent -in:drafts"


@dataclass
class Email:
    id: str
    subject: str
    sender: str
    sent: datetime
    body: str
    is_bulk: bool = False   # sent via a mailing list / newsletter (vs. a personal email)
    labeled: bool = False   # has the manual-override label


def is_configured() -> bool:
    return bool(os.environ.get("GMAIL_TOKEN")) or os.path.exists("gmail_token.json")


def _is_bulk(headers: dict) -> bool:
    """Mailing lists and newsletters set these headers; personal emails don't."""
    return bool(
        headers.get("list-id")
        or headers.get("list-unsubscribe")
        or headers.get("precedence", "").lower() in ("bulk", "list")
    )


def _service():
    raw = os.environ.get("GMAIL_TOKEN") or open("gmail_token.json").read()
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _body(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    plain, htm = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            htm.append(_decode(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    return _html_to_text("\n".join(htm))


def fetch_recent(skip_ids: set[str]) -> list[Email]:
    svc = _service()
    ids, page = [], None
    while True:
        resp = svc.users().messages().list(
            userId="me", q=LOOKBACK_QUERY, maxResults=100, pageToken=page
        ).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        page = resp.get("nextPageToken")
        if not page:
            break

    label_ids = {
        l["id"] for l in svc.users().labels().list(userId="me").execute().get("labels", [])
        if l["name"].lower() == LABEL.lower()
    }
    emails = []
    for mid in ids:
        if mid in skip_ids:
            continue
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        emails.append(
            Email(
                id=mid,
                subject=headers.get("subject", ""),
                sender=headers.get("from", ""),
                sent=datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc),
                body=_body(msg["payload"]),
                is_bulk=_is_bulk(headers),
                labeled=bool(label_ids & set(msg.get("labelIds", []))),
            )
        )
    return emails
