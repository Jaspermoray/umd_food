"""Detect the same event showing up from more than one source (e.g. TerpLink + a listserv)."""
import re
from datetime import datetime
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
STOPWORDS = {"the", "a", "an", "and", "of", "at", "with", "for", "in", "on", "free", "food", "umd"}


def _get(obj, key: str):
    """Read a field from an Event dataclass or a sqlite3.Row."""
    return getattr(obj, key) if hasattr(obj, "__dataclass_fields__") else obj[key]


def _norm(s: str) -> str:
    words = re.findall(r"[a-z0-9]+", (s or "").lower())
    return " ".join(w for w in words if w not in STOPWORDS)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def same_event(a, b) -> bool:
    sa = datetime.fromisoformat(_get(a, "start"))
    sb = datetime.fromisoformat(_get(b, "start"))
    if sa.astimezone(ET).date() != sb.astimezone(ET).date():
        return False
    close_in_time = abs((sa - sb).total_seconds()) <= 45 * 60
    return _similar(_get(a, "title"), _get(b, "title")) >= 0.6 or (
        close_in_time and _similar(_get(a, "location"), _get(b, "location")) >= 0.5
    )
