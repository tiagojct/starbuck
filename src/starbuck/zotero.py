"""Full texts from a local Zotero library (level 4).

Starbuck reads a copy of zotero.sqlite, so Zotero can stay open and nothing in the library
changes. A cited work is matched by DOI, or by its exact title; its text comes from Zotero's
full-text cache (.zotero-ft-cache) or, when there is none, from the PDF attachment.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .ids import norm_doi, slug

FIELDS = """
SELECT d.itemID, f.fieldName, v.value FROM itemData d
JOIN fields f ON f.fieldID = d.fieldID JOIN itemDataValues v ON v.valueID = d.valueID
WHERE f.fieldName IN ('DOI', 'title', 'extra')
"""
ATTACHMENTS = """
SELECT a.parentItemID, i.key, a.contentType, a.path FROM itemAttachments a JOIN items i ON i.itemID = a.itemID
WHERE a.parentItemID IS NOT NULL AND (a.contentType = 'application/pdf' OR a.contentType LIKE 'text/%')
"""


def default_dir() -> Path:
    return Path(os.environ.get("STARBUCK_ZOTERO_DIR") or Path.home() / "Zotero").expanduser()


class ZoteroLibrary:
    def __init__(self, folder: str | Path | None = None) -> None:
        self.dir = Path(folder).expanduser() if folder else default_dir()
        db = self.dir / "zotero.sqlite"
        if not db.is_file():
            raise FileNotFoundError(f"No Zotero database at {db}")
        self.by_doi: dict[str, int] = {}
        self.by_title: dict[str, int] = {}
        self.attachments: dict[int, list[tuple[str, str, str]]] = {}
        with tempfile.TemporaryDirectory(prefix="starbuck-zotero-") as tmp:
            # A copy with its write-ahead log: the newest items are included and Zotero's lock is not touched.
            for suffix in ("", "-wal"):
                if (db.parent / (db.name + suffix)).is_file():
                    shutil.copyfile(db.parent / (db.name + suffix), Path(tmp) / (db.name + suffix))
            con = sqlite3.connect(Path(tmp) / db.name)
            try:
                for item, name, value in con.execute(FIELDS):
                    if name == "DOI" and (d := norm_doi(value)):
                        self.by_doi.setdefault(d, item)
                    elif name == "extra" and (m := re.search(r"^DOI:\s*(\S+)", value or "", re.M | re.I)):
                        if d := norm_doi(m.group(1)):
                            self.by_doi.setdefault(d, item)
                    elif name == "title" and (t := slug(value)) and len(t) >= 20:
                        self.by_title.setdefault(t, item)
                for parent, key, ctype, path in con.execute(ATTACHMENTS):
                    self.attachments.setdefault(parent, []).append((key, ctype or "", path or ""))
            finally:
                con.close()

    def find(self, doi: str = "", title: str = "") -> int | None:
        if doi and (item := self.by_doi.get(doi.lower())):
            return item
        return self.by_title.get(slug(title)) if title else None

    def text(self, doi: str = "", title: str = "") -> tuple[str, str] | None:
        """(text, description) of the matched item's attachment, or None."""
        item = self.find(doi, title)
        if item is None:
            return None
        from .sources import pdf_to_text

        for key, ctype, path in sorted(self.attachments.get(item, []), key=lambda a: a[1] != "application/pdf"):
            folder = self.dir / "storage" / key
            cache = folder / ".zotero-ft-cache"
            if cache.is_file():
                text = cache.read_text(encoding="utf-8", errors="replace")
                if len(text.split()) >= 200:
                    return text, f"Zotero full text ({key})"
            file = folder / path[len("storage:"):] if path.startswith("storage:") else Path(path)
            if not file.is_file():
                continue
            if ctype == "application/pdf":
                text = pdf_to_text(file.read_bytes())
            else:
                text = file.read_text(encoding="utf-8", errors="replace")
            if text and len(text.split()) >= 200:
                return text, f"Zotero attachment {file.name}"
        return None
