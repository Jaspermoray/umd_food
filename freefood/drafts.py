"""
Create (not send) "please add me to your list" email drafts in your Gmail.

  python -m freefood.drafts --name "Your Name"            # create drafts
  python -m freefood.drafts --name "Your Name" --dry-run  # preview only

Reads contacts.csv with columns: name,email,list_name,kind
  kind = ask       -> polite "please add me" email to a person/office (default)
  kind = listserv  -> SUBSCRIBE command to UMD LISTSERV (email = listserv@listserv.umd.edu)
  kind = mailman   -> "subscribe" command to a Mailman list's -request address
Each row gets one draft; rows already drafted are skipped (tracked in drafts_log.csv). Review the drafts in Gmail and send them yourself — a handful
per day is best, since a burst of near-identical emails looks like spam.

This uses its own login (gmail_drafts_token.json, "compose" permission) that stays
on this computer; the sync bot's login remains read-only.
"""
import argparse
import base64
import csv
import os
from datetime import datetime
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
TOKEN = "gmail_drafts_token.json"
CONTACTS = "contacts.csv"
LOG = "drafts_log.csv"


def _service():
    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def key(contact: dict) -> str:
    """Several rows can share an address (all LISTSERV commands go to one), so key on both."""
    return f"{contact['email'].strip().lower()}|{(contact.get('list_name') or '').strip().upper()}"


def compose(contact: dict, sender_name: str) -> EmailMessage:
    name = (contact.get("name") or "").strip()
    list_name = (contact.get("list_name") or "").strip()
    kind = (contact.get("kind") or "ask").strip().lower()
    msg = EmailMessage()
    msg["To"] = contact["email"].strip()
    if kind == "listserv":
        # LISTSERV reads commands from the body; no subject, and no signature
        # (extra lines get parsed as more commands).
        msg["Subject"] = ""
        msg.set_content(f"SUBSCRIBE {list_name} {sender_name}")
        return msg
    if kind == "mailman":
        msg["Subject"] = "subscribe"
        msg.set_content("subscribe")
        return msg
    greeting = f"Hi {name.split()[0]}," if name else "Hi,"
    msg = EmailMessage()
    msg["To"] = f"{name} <{contact['email'].strip()}>" if name else contact["email"].strip()
    msg["Subject"] = f"Joining the {list_name} email list" if list_name else "Joining your email list"
    msg.set_content(
        f"{greeting}\n\n"
        "I'm new UMD faculty, could you add me to your email list?\n\n"
        f"Thanks,\n{sender_name}\n"
    )
    return msg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="how to sign the emails")
    ap.add_argument("--dry-run", action="store_true", help="print drafts without creating them")
    args = ap.parse_args()

    with open(CONTACTS, newline="") as f:
        contacts = [c for c in csv.DictReader(f) if (c.get("email") or "").strip()]
    done = set()
    if os.path.exists(LOG):
        with open(LOG, newline="") as f:
            done = {r["key"] for r in csv.DictReader(f)}
    todo = [c for c in contacts if key(c) not in done]
    print(f"{len(contacts)} contact(s), {len(contacts) - len(todo)} already drafted, {len(todo)} to go.\n")

    if args.dry_run:
        for c in todo:
            m = compose(c, args.name)
            print(f"To: {m['To']}\nSubject: {m['Subject']}\n\n{m.get_content()}\n{'-' * 40}")
        return

    svc = _service()
    new_log = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["key", "draft_id", "created"])
        if new_log:
            w.writeheader()
        for c in todo:
            raw = base64.urlsafe_b64encode(compose(c, args.name).as_bytes()).decode()
            d = svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
            w.writerow({"key": key(c), "draft_id": d["id"],
                        "created": datetime.now().isoformat(timespec="seconds")})
            f.flush()
            print(f"  drafted: {c['email'].strip()}  {c.get('list_name') or ''}")
    print(f"\nDone. Open Gmail → Drafts to review and send.")


if __name__ == "__main__":
    main()
