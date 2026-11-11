import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass
class Event:
    source: str        # e.g. "terplink", "email"
    source_id: str     # id unique within the source
    title: str
    start: str         # ISO 8601 with timezone
    end: str           # ISO 8601 with timezone
    location: str
    url: str
    description: str   # plain text

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    def content_hash(self) -> str:
        """Changes whenever any field changes, so we know when to re-sync."""
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()
