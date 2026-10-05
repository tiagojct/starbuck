"""Identifiers (DOI, PMID, PMCID, arXiv, ISBN) and text normalisation for matching."""

from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import unquote

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>|\\{}]+", re.IGNORECASE)
PMID_RE = re.compile(
    r"(?:\bPMID\s*:?\s*|pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)(\d{1,9})\b", re.IGNORECASE)
PMCID_RE = re.compile(r"\b(PMC\d{4,9})\b", re.IGNORECASE)
ARXIV_NEW = r"\d{4}\.\d{4,5}"
ARXIV_OLD = r"[a-z][a-z\-]+(?:\.[A-Z]{2})?/\d{7}"
ARXIV_RE = re.compile(
    rf"(?:\barXiv\s*:\s*|arxiv\.org/(?:abs|pdf|html)/)({ARXIV_NEW}|{ARXIV_OLD})(?:v\d+)?", re.IGNORECASE)
ISBN_RE = re.compile(r"\bISBN(?:-1[03])?\s*:?\s*([\dXx][\d\-\s]{8,16}[\dXx])")
URL_RE = re.compile(r"https?://[^\s<>\"'|]+")

PAIRS = {")": "(", "]": "[", "}": "{"}


def trim(value: str) -> str:
    """Drop trailing punctuation and unbalanced closing brackets.

    DOIs may contain balanced parentheses (10.1016/S0140-6736(97)11096-0), so a
    closing bracket is removed only when it has no opening partner.
    """
    v = value
    while v:
        last = v[-1]
        if last in ".,;:'\"*_>`":
            v = v[:-1]
        elif last in PAIRS and v.count(last) > v.count(PAIRS[last]):
            v = v[:-1]
        else:
            break
    return v


def norm_doi(value: str | None) -> str | None:
    if not value:
        return None
    v = unquote(value.strip())
    v = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", v, flags=re.IGNORECASE)
    m = DOI_RE.search(v)
    return trim(m.group(0)).lower() if m else None


def norm_isbn(value: str | None) -> str | None:
    if not value:
        return None
    v = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"\d{9}[\dX]|\d{13}", v):
        return None
    if len(v) == 10:
        core = "978" + v[:9]
        total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(core))
        return core + str((10 - total % 10) % 10)
    return v


def norm_arxiv(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    m = ARXIV_RE.search(v) or re.fullmatch(rf"({ARXIV_NEW}|{ARXIV_OLD})(?:v\d+)?", v, re.IGNORECASE)
    return m.group(1) if m else None


def detect(identifier: str) -> tuple[str, str] | None:
    """A single identifier typed by a person or an agent: (kind, normalised value).

    kind is doi, pmid, pmcid, arxiv or isbn.
    """
    s = identifier.strip()
    low = s.lower()
    if low.startswith("pmid:") or re.fullmatch(r"\d{1,9}", s):
        digits = re.sub(r"\D", "", s)
        return ("pmid", digits) if digits else None
    if re.fullmatch(r"(?:pmcid:\s*)?pmc\d{4,9}", low):
        return ("pmcid", "PMC" + re.sub(r"\D", "", s))
    if low.startswith("isbn:"):
        isbn = norm_isbn(s[5:])
        return ("isbn", isbn) if isbn else None
    if low.startswith("arxiv:") or "arxiv.org/" in low or re.fullmatch(rf"{ARXIV_NEW}(?:v\d+)?", s):
        a = norm_arxiv(s if not low.startswith("arxiv:") else s[6:].strip())
        if a:
            return ("arxiv", a)
    if m := PMID_RE.search(s):
        return ("pmid", m.group(1))
    doi = norm_doi(s)
    if doi:
        return ("doi", doi)
    isbn = norm_isbn(s)
    if isbn and re.fullmatch(r"[\d\-\sXx]{10,17}", s):
        return ("isbn", isbn)
    return None


def find_ids(text: str) -> dict[str, str]:
    """Identifiers written anywhere in a free-text reference entry."""
    out: dict[str, str] = {}
    if doi := norm_doi(text):
        out["doi"] = doi
    if m := PMID_RE.search(text):
        out["pmid"] = m.group(1)
    if m := PMCID_RE.search(text):
        out["pmcid"] = m.group(1).upper()
    if m := ARXIV_RE.search(text):
        out["arxiv"] = m.group(1)
    if (m := ISBN_RE.search(text)) and (isbn := norm_isbn(m.group(1))):
        out["isbn"] = isbn
    for m in URL_RE.finditer(text):
        url = trim(m.group(0))
        low = url.lower()
        if not any(h in low for h in ("doi.org/", "pubmed.ncbi", "ncbi.nlm.nih.gov/pubmed", "arxiv.org/",
                                      "ncbi.nlm.nih.gov/pmc")):
            out["url"] = url
            break
    bare = DOI_RE.sub(" ", URL_RE.sub(" ", text))
    bare = PMID_RE.sub(" ", ARXIV_RE.sub(" ", ISBN_RE.sub(" ", bare)))
    if m := re.search(r"(?<![\d.])(1[5-9]\d\d|20\d\d)(?![\d.]\d)", bare):
        out["year"] = m.group(1)
    return out


# ---------------------------------------------------------------- text

STOP = {"the", "and", "for", "with", "from", "into", "that", "this", "are", "was", "were", "its", "their",
        "of", "in", "on", "to", "an", "a", "by", "at", "or", "as", "is", "be", "vs", "via"}


def plain(text: str | None) -> str:
    """Strip markup (HTML, JATS, LaTeX braces) and decode entities."""
    t = html.unescape(text or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", t).strip()


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.replace("ß", "ss").replace("ø", "o").replace("æ", "ae").replace("ł", "l").replace("đ", "d").lower()


def slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(plain(text)))


def tokens(text: str | None) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(plain(text))) if len(w) >= 2 and w not in STOP]


def _main_title(title: str) -> str:
    t = re.sub(r"^\[|\]\.?$", "", title.strip())  # PubMed brackets translated titles
    return re.split(r"[:?.]\s", t, maxsplit=1)[0]


FLAG_PREFIX = re.compile(r"^\s*(?:retracted|withdrawn|retraction|expression of concern)(?: article)?\s*[:\-\u2013\u2014]\s*",
                         re.IGNORECASE)


def title_similarity(a: str | None, b: str | None) -> float:
    """0..1. The better of full-title and main-title (before a colon) comparisons.

    Prefixes that publishers add to flagged records ("RETRACTED: ...") are ignored.
    """
    if not a or not b:
        return 0.0
    a, b = FLAG_PREFIX.sub("", plain(a)), FLAG_PREFIX.sub("", plain(b))
    full = SequenceMatcher(None, slug(a), slug(b)).ratio()
    ma, mb = slug(_main_title(plain(a))), slug(_main_title(plain(b)))
    main = SequenceMatcher(None, ma, mb).ratio() if len(ma) >= 15 and len(mb) >= 15 else 0.0
    return round(max(full, main), 3)


def containment(title: str | None, text: str | None) -> float:
    """Share of the title's words that appear in a free-text entry (0..1)."""
    words = tokens(FLAG_PREFIX.sub("", plain(title)))
    if not words:
        return 0.0
    have = set(tokens(text))
    return round(sum(1 for w in words if w in have) / len(words), 3)


def same_name(a: str | None, b: str | None) -> bool:
    sa, sb = slug(a), slug(b)
    if not sa or not sb:
        return False
    # "van der Berg" vs "Berg", "Silva" vs "da Silva": accept when one ends with the other.
    return sa == sb or (len(min(sa, sb, key=len)) >= 4 and (sa.endswith(sb) or sb.endswith(sa)))
