"""What a manuscript cites and what Starbuck finds out about each reference."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Reference:
    """One entry of the reference list, as the authors wrote it."""

    key: str
    kind: str  # csl, bibtex, numbered, given
    raw: str = ""  # the entry as written (numbered lists) or a short label
    title: str = ""
    authors: list[str] = field(default_factory=list)  # family names (or group names) in order
    year: str = ""
    container: str = ""
    type: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    arxiv: str = ""
    isbn: str = ""
    url: str = ""

    def identifiers(self) -> dict[str, str]:
        return {k: v for k in ("doi", "pmid", "pmcid", "arxiv", "isbn") if (v := getattr(self, k))}

    def label(self) -> str:
        if self.title:
            who = self.authors[0] if self.authors else ""
            if len(self.authors) > 1:
                who += " et al."
            head = f"{who} ({self.year})" if who and self.year else who or self.year
            return f"{head}. {self.title}".strip(". ") if head else self.title
        return self.raw

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", [], None)}


@dataclass
class Citation:
    key: str
    line: int
    sentence: str


@dataclass
class Document:
    path: str
    style: str  # citekey, numbered or none
    citations: list[Citation] = field(default_factory=list)
    references: dict[str, Reference] = field(default_factory=dict)
    bibliography: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    uncited_sentences: list[dict] = field(default_factory=list)  # sentences that state a finding, no citation

    def cited_keys(self) -> list[str]:
        seen: list[str] = []
        for c in self.citations:
            if c.key not in seen:
                seen.append(c.key)
        return seen

    def missing(self) -> dict[str, list[int]]:
        """Cited keys without a reference entry, with the lines that cite them."""
        out: dict[str, list[int]] = {}
        for c in self.citations:
            if c.key not in self.references:
                out.setdefault(c.key, []).append(c.line)
        return out

    def unused(self) -> list[str]:
        cited = set(self.cited_keys())
        return [k for k in self.references if k not in cited]

    def citing(self, key: str) -> list[Citation]:
        return [c for c in self.citations if c.key == key]
