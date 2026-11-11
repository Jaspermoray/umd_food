"""
Fetch upcoming TerpLink (Campus Labs Engage) events with free food: those tagged with the
"Free Food" perk, plus untagged ones whose description says food is provided (organizers
often forget the tag).
"""
import html
import re
from datetime import datetime, timedelta, timezone

import requests

from .models import Event

SEARCH_URL = "https://terplink.umd.edu/api/discovery/event/search"
EVENT_URL = "https://terplink.umd.edu/event/{id}"
HEADERS = {"User-Agent": "UMDFreeFoodBot/0.1 (student project)"}
PAGE_SIZE = 100
MAX_DURATION = timedelta(hours=12)


def _html_to_text(raw: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>", "\n", raw or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _mentions_free_food(text: str) -> bool:
    from . import rules

    return any(
        rules.FREE_FOOD.search(p) and not rules.NOT_FREE.search(p) for p in rules._paragraphs(text)
    )


def fetch_events() -> list[Event]:
    now = datetime.now(timezone.utc).isoformat()
    events: list[Event] = []
    skip = 0
    while True:
        resp = requests.get(
            SEARCH_URL,
            params={
                "endsAfter": now,
                "orderByField": "endsOn",
                "orderByDirection": "ascending",
                "status": "Approved",
                "take": PAGE_SIZE,
                "skip": skip,
            },
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("value", [])
        for e in batch:
            if e.get("visibility") != "Public":
                continue
            description = _html_to_text(e.get("description", ""))
            if "Free Food" not in (e.get("benefitNames") or []) and not _mentions_free_food(
                f"{e.get('name', '')}\n\n{description}"
            ):
                continue
            # Skip multi-day/semester-long "events" — they'd be giant calendar blocks.
            duration = datetime.fromisoformat(e["endsOn"]) - datetime.fromisoformat(e["startsOn"])
            if duration > MAX_DURATION:
                continue
            events.append(
                Event(
                    source="terplink",
                    source_id=str(e["id"]),
                    title=(e.get("name") or "").strip(),
                    start=e["startsOn"],
                    end=e["endsOn"],
                    location=(e.get("location") or "TBA").strip(),
                    url=EVENT_URL.format(id=e["id"]),
                    description=description,
                )
            )
        skip += len(batch)
        if not batch or skip >= data.get("@odata.count", 0):
            break
    return events
