"""A cache on disk for the answers of the services, so that a second run asks again only
what it did not ask before, or what can have changed since.

One SQLite file (cache.sqlite) in STARBUCK_CACHE_DIR or the user's cache folder. Only
answers that the services gave are kept; a failure is never kept. Each kind of answer
has its own age limit: a retraction or a correction can appear at any time, so the
answers that report them are kept for one day only.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

DAY = 86400
# Key prefix -> age limit in seconds. Keys are made in sources.py.
TTL = {
    "cru:": DAY,  # Crossref update notices (retractions, corrections)
    "oa:": DAY,  # OpenAlex is_retracted
    "pm:": DAY,  # PubMed publication types and linked notices
    "url:": DAY,  # web pages
    "wb:": DAY,  # Wayback Machine
    "cr:": 7 * DAY, "dc:": 7 * DAY, "h:": 7 * DAY, "ax:": 7 * DAY, "ol:": 7 * DAY,
    "epmc:": 7 * DAY, "pmc:": 30 * DAY,
    "crs:": 7 * DAY, "pms:": 7 * DAY, "oas:": 7 * DAY, "dcs:": 7 * DAY, "ols:": 7 * DAY,
    "epmcft:": 30 * DAY, "upw:": 7 * DAY, "pdf:": 30 * DAY,
}
NOT_FOUND_TTL = DAY  # an empty answer (404, no record) can change when a record is added
MISSING = object()


def default_dir() -> Path:
    if env := os.environ.get("STARBUCK_CACHE_DIR"):
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "starbuck"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "starbuck" / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "starbuck"


def ttl(key: str, value: Any) -> int:
    limit = next((s for p, s in TTL.items() if key.startswith(p)), DAY)
    return min(limit, NOT_FOUND_TTL) if value in (None, [], {}) else limit


class DiskCache:
    def __init__(self, folder: str | Path | None = None) -> None:
        path = Path(folder).expanduser() if folder else default_dir()
        path.mkdir(parents=True, exist_ok=True)
        self.path = path / "cache.sqlite"
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, saved REAL, expires REAL, "
                        "value TEXT)")
        self.db.commit()
        self.hits = 0

    def get(self, key: str) -> Any:
        row = self.db.execute("SELECT expires, value FROM answers WHERE key = ?", (key,)).fetchone()
        if not row or row[0] < time.time():
            return MISSING
        self.hits += 1
        return json.loads(row[1])

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?, ?, ?)",
                        (key, now, now + ttl(key, value), json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def clear(self) -> int:
        n = self.db.execute("DELETE FROM answers").rowcount
        self.db.commit()
        return n

    def close(self) -> None:
        self.db.close()
