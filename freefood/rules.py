"""
Free, rule-based extraction of free-food events from email text (no AI / no API cost).

Works well on clearly written announcements ("Pizza provided! Thursday, Nov 12, 6-8pm,
ESJ 0202"). It will miss or skip vaguer emails — anything without a findable date and
start time is dropped rather than guessed.
"""
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .gmail import Email
from .models import Event

ET = ZoneInfo("America/New_York")
MAX_DAYS_AHEAD = 120  # anything further out is probably a parsing mistake

# ---------------------------------------------------------------- food ---------
FOODS = (
    r"food|pizzas?|lunch|dinner|breakfast|brunch|snacks?|refreshments|drinks|beverages|"
    r"donuts?|doughnuts?|bagels?|coffee|boba|bubble tea|cookies|cupcakes?|cake|ice cream|"
    r"tacos?|burritos?|wings|chipotle|chick-fil-a|sandwiches|subs|bbq|barbecue|"
    r"desserts?|treats|sweets|catering|light fare|hors d'oeuvres|appetizers|meals?|"
    r"popcorn|cider|hot cocoa|hot chocolate|smoothies|bubble tea|kabobs|halal|dumplings|"
    r"empanadas|samosas|wraps|salads?|fruit|candy|baked goods|pastries|muffins"
)
FREE_FOOD = re.compile(
    rf"\bfree\s+(?:\w+\s+){{0,2}}(?:{FOODS})\b"
    rf"|\b(?:{FOODS})\b(?:[\s,&]+(?:and\s+)?\w+){{0,4}}\s+(?:will\s+be\s+|is\s+|are\s+)?"
    r"(?:provided|served|available|included|on us|for all|free)\b"
    r"|\b(?:light\s+)?refreshments\b"
    rf"|\b(?:enjoy|grab|join us for|come for|stop by for|there will be)\s+(?:some\s+|free\s+)?(?:\w+\s+)?(?:{FOODS})\b"
    r"|\bcatered\b|\bpotluck\b|\bcookout\b|\bfood\s+and\s+drinks\b",
    re.I,
)
NOT_FREE = re.compile(
    r"\$\s?\d|\bbake sale\b|\bfor sale\b|\bfundraiser\b|\bfundraising\b|\bpurchase\b|"
    r"\bbuy\b|\bproceeds\b|\bdine[- ]?out\b|\brestaurant night\b|\btickets?\s+(?:are|cost)\b|"
    r"\bbring your own\b|\bbyo[lfb]?\b",
    re.I,
)

# ---------------------------------------------------------------- dates --------
MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MONTH_DAY = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})"
    r"(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?",
    re.I,
)
NUMERIC_DATE = re.compile(r"(?<![\d/$.])(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?![\d/])")
WEEKDAY = re.compile(
    r"\b(this\s+|next\s+)?(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?\b\.?",
    re.I,
)
RELATIVE = re.compile(r"\b(today|tonight|tomorrow)\b", re.I)

# ---------------------------------------------------------------- times --------
_T = r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?\s*m?\.?"
TIME_RANGE = re.compile(
    rf"(?<![\d:/$]){_T}\s*(?:-|–|—|to|until|till)\s*{_T}(?![\d/])|"
    r"\b(noon)\s*(?:-|–|—|to|until)\s*" + _T,
    re.I,
)
TIME_SINGLE = re.compile(r"(?<![\d:/$])(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?|\b(noon)\b", re.I)

# ---------------------------------------------------------------- places -------
_BUILDINGS = json.loads((Path(__file__).parent / "data" / "buildings.json").read_text())
# Common names/abbreviations people actually write, beyond the official list.
ALIASES = {
    "ESJ": "Edward St. John Learning and Teaching Center",
    "IRB": "Brendan Iribe Center",
    "Iribe": "Brendan Iribe Center",
    "STAMP": "Adele H. Stamp Student Union",
    "Stamp Student Union": "Adele H. Stamp Student Union",
    "the Stamp": "Adele H. Stamp Student Union",
    "Student Union": "Adele H. Stamp Student Union",
    "Colony Ballroom": "Adele H. Stamp Student Union (Colony Ballroom)",
    "Grand Ballroom": "Adele H. Stamp Student Union (Grand Ballroom)",
    "Prince George's Room": "Adele H. Stamp Student Union (Prince George's Room)",
    "McKeldin": "McKeldin Library",
    "Hornbake": "Hornbake Library",
    "Van Munching": "Van Munching Hall",
    "PSC": "Physical Sciences Complex",
    "ERC": "Eppley Campus Recreation Center",
    "Eppley": "Eppley Campus Recreation Center",
    "Clarice": "The Clarice Smith Performing Arts Center",
    "Unity Center": "The Unity Center",
    "Yahentamitsi": "Yahentamitsi Dining Hall",
    "251 North": "251 North Dining Hall",
    "South Campus Dining Hall": "South Campus Dining Hall",
    "Thurgood Marshall": "Adele H. Stamp Student Union (Thurgood Marshall Room)",
    "Physical Sciences Complex": "Physical Sciences Complex",
    "Kim Engineering": "Jeong H. Kim Engineering Building",
    "Kim Building": "Jeong H. Kim Engineering Building",
    "Eppley Recreation Center": "Eppley Campus Recreation Center",
    "Iribe Center": "Brendan Iribe Center",
}
CODE_TO_NAME = {b["code"]: b["name"] for b in _BUILDINGS if b["code"]}
CODE_TO_NAME.update({k: v for k, v in ALIASES.items() if k.isupper()})
NAME_TO_NAME = {b["name"].lower(): b["name"] for b in _BUILDINGS}
NAME_TO_NAME.update({k.lower(): v for k, v in ALIASES.items() if not k.isupper()})
# A short official name (e.g. "Hornbake Plaza") should win only if it appears verbatim.
_names_sorted = sorted(NAME_TO_NAME, key=len, reverse=True)
BUILDING_NAME = re.compile(r"\b(" + "|".join(re.escape(n) for n in _names_sorted) + r")\b", re.I)
BUILDING_CODE_ROOM = re.compile(
    r"\b(" + "|".join(sorted(CODE_TO_NAME, key=len, reverse=True)) + r")\s*-?\s*(\d{4}[A-Z]?)\b"
)
# Well-known abbreviations used on their own ("in ESJ"). Case-sensitive so "stamp" the
# verb doesn't match; limited to ALIASES because many official codes are real words.
ALIAS_CODE = re.compile(r"\b(" + "|".join(k for k in ALIASES if k.isupper()) + r")\b")
ROOM = re.compile(r"\b(?:room|rm\.?)\s*#?\s*(\d{3,4}[A-Z]?)\b", re.I)
LABELED_LOCATION = re.compile(r"^\s*(?:where|location|place|venue)\s*[:\-–]\s*(.+)$", re.I | re.M)


def _next_weekday(start: date, wd: int, force_next: bool = False) -> date:
    days = (wd - start.weekday()) % 7
    if force_next and days == 0:
        days = 7
    return start + timedelta(days=days)


def _year_for(sent: date, month: int, day: int) -> date | None:
    for y in (sent.year, sent.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if d >= sent - timedelta(days=7):
            return d
    return None


def find_date(text: str, sent: date) -> date | None:
    if m := MONTH_DAY.search(text):
        month = MONTHS[m.group(1)[:3].lower()]
        if m.group(3):
            try:
                return date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                pass
        elif d := _year_for(sent, month, int(m.group(2))):
            return d
    if m := NUMERIC_DATE.search(text):
        mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            if yr:
                try:
                    return date(int(yr) + (2000 if len(yr) == 2 else 0), mo, dy)
                except ValueError:
                    pass
            elif d := _year_for(sent, mo, dy):
                return d
    if m := RELATIVE.search(text):
        return sent + timedelta(days=1 if m.group(1).lower() == "tomorrow" else 0)
    if m := WEEKDAY.search(text):
        wd = WEEKDAYS[m.group(2)[:3].lower()]
        return _next_weekday(sent, wd, force_next=bool(m.group(1) and "next" in m.group(1).lower()))
    return None


def _to_24h(h: int, mins: int, ap: str | None) -> tuple[int, int] | None:
    if not (1 <= h <= 12 or (ap is None and 0 <= h <= 23)) or mins > 59:
        return None
    if ap:
        h = h % 12 + (12 if ap.lower() == "p" else 0)
    return h, mins


def find_times(text: str) -> tuple[tuple[int, int], tuple[int, int] | None] | None:
    """Returns ((start_h, start_m), (end_h, end_m) or None)."""
    if m := TIME_RANGE.search(text):
        g = m.groups()
        if g[6]:  # "noon - 2pm"
            start = (12, 0)
            end = _to_24h(int(g[7]), int(g[8] or 0), g[9] or "p")
        else:
            end_ap = g[5]
            start_ap = g[2] or end_ap
            if start_ap or end_ap:
                start = _to_24h(int(g[0]), int(g[1] or 0), start_ap)
                end = _to_24h(int(g[3]), int(g[4] or 0), end_ap)
                # "11-1pm": the start inherited pm but should be am
                if start and end and not g[2] and start > end:
                    start = (start[0] - 12, start[1])
            else:
                start = end = None
        if start and end and start < end:
            return start, end
    if m := TIME_SINGLE.search(text):
        if m.group(4):
            return (12, 0), None
        if t := _to_24h(int(m.group(1)), int(m.group(2) or 0), m.group(3)):
            return t, None
    return None


def find_location(text: str) -> str | None:
    if m := LABELED_LOCATION.search(text):
        loc = re.split(r"\s{2,}|\s+(?:when|time|date)\s*:", m.group(1), flags=re.I)[0]
        return loc.strip(" .")[:120] or None
    if m := BUILDING_CODE_ROOM.search(text):
        code, room = m.group(1), m.group(2)
        return f"{code} {room} ({CODE_TO_NAME[code]})"
    if m := BUILDING_NAME.search(text):
        name = NAME_TO_NAME[m.group(1).lower()]
        tail = text[m.end(): m.end() + 40]
        head = text[max(0, m.start() - 40): m.start()]
        if r := (ROOM.search(tail) or ROOM.search(head)):
            return f"{name}, Room {r.group(1)}"
        return name
    if m := ALIAS_CODE.search(text):
        return CODE_TO_NAME[m.group(1)]
    if m := ROOM.search(text):
        return f"Room {m.group(1)}"
    return None


def _clean_subject(s: str) -> str:
    s = re.sub(r"^\s*((re|fwd?|fw)\s*:\s*)+", "", s, flags=re.I)
    s = re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", s)
    return s.strip() or "Free food event"


def _paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def extract_events(email: Email) -> list[Event]:
    sent = email.sent.astimezone(ET).date()
    subject = _clean_subject(email.subject)
    paras = _paragraphs(email.body)
    events, seen = [], set()

    for i, p in enumerate(paras):
        food = FREE_FOOD.search(p) or (i == 0 and FREE_FOOD.search(subject))
        if not food or NOT_FREE.search(p):
            continue
        # Look for details in this paragraph first, then widen to its neighbors + subject.
        nearby = "\n".join(paras[max(0, i - 2): i + 3])
        contexts = [p, f"{subject}\n{nearby}"]
        when = next((d for c in contexts if (d := find_date(c, sent))), None)
        times = next((t for c in contexts if (t := find_times(c))), None)
        if not when or not times:
            continue
        where = next((loc for c in contexts if (loc := find_location(c))), None)
        if not where and len(paras) <= 6:  # short email: location may be anywhere
            where = find_location(email.body)

        (sh, sm), end_t = times
        start = datetime(when.year, when.month, when.day, sh, sm, tzinfo=ET)
        end = (datetime(when.year, when.month, when.day, *end_t, tzinfo=ET)
               if end_t else start + timedelta(hours=1))
        if start in seen:
            continue
        if not (datetime.now(ET) < end and start.date() <= sent + timedelta(days=MAX_DAYS_AHEAD)):
            continue
        seen.add(start)

        # Multi-event newsletter: title from the paragraph; otherwise the subject.
        title = subject
        if len(paras) > 6:
            first_line = re.split(r"(?<=[.!?])\s|\n", p)[0]
            title = first_line[:80].strip(" :-") or subject
        sender = re.sub(r"\s*<[^>]+>", "", email.sender).strip('" ') or email.sender
        events.append(Event(
            source="email",
            source_id=f"{email.id}-{len(events)}",
            title=title,
            start=start.isoformat(),
            end=end.isoformat(),
            location=where or "See email",
            url="",
            description=f"Food: \"{food.group(0).strip()}\"\n"
            f"From an email by {sender}: \"{email.subject}\"\n"
            "(Auto-extracted — double-check details.)",
        ))
    return events
