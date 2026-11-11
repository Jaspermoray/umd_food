"""Turn free-form email text into structured free-food events using Claude."""
import re
from datetime import datetime, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field

from .gmail import Email
from .models import Event

ET = ZoneInfo("America/New_York")
MODEL = "claude-opus-5-5"
MAX_BODY_CHARS = 30_000  # newsletters can be huge; events are almost always near the top

# Cheap pre-filter so we only pay for Claude on emails that might mention food.
FOOD_WORDS = re.compile(
    r"\b(free food|food|pizza|lunch|dinner|breakfast|brunch|snacks?|refreshments?|"
    r"catered|catering|donuts?|doughnuts?|bagels?|coffee|boba|cookies?|cupcakes?|"
    r"ice cream|tacos?|wings|chipotle|chick-fil-a|potluck|bbq|cookout|treats|"
    r"light fare|hors d'oeuvres|appetizers|dessert|meal)\b",
    re.I,
)

SYSTEM = """You extract free-food events at the University of Maryland, College Park from emails.

Return every distinct event in the email where attendees will get free food or drink \
(pizza, lunch, snacks, refreshments, coffee, etc.). Return an empty list when there are none.

Rules:
- Only include events where food is actually provided to attendees for free. Skip food \
sales, fundraisers, bake sales, restaurant promotions, and events that only mention \
food in passing (e.g. "bring your own lunch", a talk about nutrition).
- Only include in-person events on or near the UMD College Park campus.
- Resolve relative dates ("this Thursday", "tomorrow") using the date the email was sent.
- Times are US Eastern. Use 24-hour HH:MM. If no end time is given, leave end_time null.
- If the date or start time can't be determined, skip the event.
- location: as specific as the email allows (building + room). Use full building names \
where you know them (e.g. "ESJ" -> "Edward St. John Learning and Teaching Center").
- title: short and descriptive, the way it would appear on a calendar.
- confidence: "high" if date, time, location and free food are all explicit; "medium" \
if one detail is inferred; "low" if you're guessing."""


class ExtractedEvent(BaseModel):
    title: str
    date: str = Field(description="YYYY-MM-DD")
    start_time: str = Field(description="HH:MM, 24-hour, US Eastern")
    end_time: Optional[str] = Field(description="HH:MM, 24-hour, US Eastern, or null")
    location: str
    food: str = Field(description="What food is provided, e.g. 'pizza', 'lunch'")
    confidence: Literal["high", "medium", "low"]


class Extraction(BaseModel):
    events: list[ExtractedEvent]


def might_have_food(email: Email) -> bool:
    return bool(FOOD_WORDS.search(email.subject) or FOOD_WORDS.search(email.body))


def _to_event(email: Email, i: int, x: ExtractedEvent) -> Event | None:
    try:
        start = datetime.strptime(f"{x.date} {x.start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        if x.end_time:
            end = datetime.strptime(f"{x.date} {x.end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
            if end <= start:
                end = start + timedelta(hours=1)
        else:
            end = start + timedelta(hours=1)
    except ValueError:
        return None
    sender = re.sub(r"\s*<[^>]+>", "", email.sender).strip('" ') or email.sender
    return Event(
        source="email",
        source_id=f"{email.id}-{i}",
        title=x.title.strip(),
        start=start.isoformat(),
        end=end.isoformat(),
        location=x.location.strip() or "TBA",
        url="",
        # Deliberately not the raw email body: it can contain personal info.
        description=f"Food: {x.food}\nFrom an email by {sender}: \"{email.subject}\"\n"
        f"(Auto-extracted, confidence: {x.confidence} — double-check details.)",
    )


def extract_events(client: anthropic.Anthropic, email: Email) -> list[Event]:
    body = email.body
    if len(body) > MAX_BODY_CHARS:
        print(f"  note: truncated long email '{email.subject[:50]}' ({len(body)} chars)")
        body = body[:MAX_BODY_CHARS]
    sent_et = email.sent.astimezone(ET)
    prompt = (
        f"Sent: {sent_et:%A, %B %d, %Y %I:%M %p} (US Eastern)\n"
        f"From: {email.sender}\nSubject: {email.subject}\n\n{body}"
    )
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},  # simple extraction; low effort is plenty
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=Extraction,
    )
    if response.stop_reason == "refusal":
        print(f"  skipped (model declined): {email.subject[:60]}")
        return []
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        print(f"  skipped (incomplete response): {email.subject[:60]}")
        return []

    now = datetime.now(ET)
    events = []
    for i, x in enumerate(response.parsed_output.events):
        if x.confidence == "low":
            continue
        ev = _to_event(email, i, x)
        if ev and datetime.fromisoformat(ev.end) > now:
            events.append(ev)
    return events
