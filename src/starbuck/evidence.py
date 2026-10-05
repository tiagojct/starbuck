"""Level 4 evidence: the best text available for a cited work, split into passages
and ranked against the sentence that cites it.

Order: a local text file given by the caller (for example Zotero's full text), then
Europe PMC open-access full text, then an abstract (PubMed, Europe PMC, Crossref,
OpenAlex). Every result says which one was used, so a verdict can state whether it
rests on the full text or on the abstract only.
"""

from __future__ import annotations

import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .models import Reference
from .sources import ServiceError, Sources

FULL_TEXT = "full text"
ABSTRACT = "abstract"
NONE = "none"
MAX_WORDS = 150  # longest passage; longer paragraphs are cut at sentence ends
ABSTRACT_WORDS = 80
MIN_ABSTRACT_WORDS = 30
TOP_K = 5

STOP = set("""a an and are as at be been but by can could did do does for from had has have how if in into is it
its may might more most no not of on or our than that the their them then there these they this those to was we
were what when where which while who will with would also between both each other such only over under after
before during per via""".split())

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")
CITATION_MARKUP = re.compile(r"\[[^\]]*@[^\]]*\]|(?<![\w.])@[\w:.#$%&\-+?<>~/]+|\[\d+(?:\s*[-,–]\s*\d+)*\]")


# ---------------------------------------------------------------- text handling

def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(text)) if len(w) > 1 and w not in STOP]


def normalise(text: str) -> str:
    """The form used to compare a quotation with the source: same characters, any spacing."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                                   "—": "-", "−": "-", " ": " ", " ": " ", " ": " "}))
    return re.sub(r"\s+", " ", t).strip()


def query_text(sentence: str) -> str:
    """The citing sentence without its citation markup."""
    return re.sub(r"\s+", " ", CITATION_MARKUP.sub(" ", sentence)).strip()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(re.sub(r"\s+", " ", text or "").strip()) if s.strip()]


def chunk(text: str, section: str, limit: int) -> list[dict]:
    """Passages of whole sentences, at most `limit` words each (a longer sentence stays whole)."""
    out, cur, n = [], [], 0
    for s in sentences(text):
        k = len(s.split())
        if cur and n + k > limit:
            out.append({"section": section, "text": " ".join(cur)})
            cur, n = [], 0
        cur.append(s)
        n += k
    if cur:
        out.append({"section": section, "text": " ".join(cur)})
    return out


def _flat(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def jats_passages(xml: str) -> list[dict]:
    """Paragraphs of a JATS article (abstract and body), with their section titles."""
    root = ET.fromstring(xml)
    out: list[dict] = []
    abstract = next(root.iter("abstract"), None)
    if abstract is not None:
        for p in abstract.iter("p"):
            out += chunk(_flat(p), "Abstract", MAX_WORDS)
    body = root.find(".//body")
    if body is None:
        return out

    def walk(el: ET.Element, title: str) -> None:
        for child in el:
            if child.tag == "sec":
                t = child.findtext("title") or title
                walk(child, re.sub(r"\s+", " ", t).strip())
            elif child.tag == "p":
                out.extend(chunk(_flat(child), title, MAX_WORDS))
            elif child.tag in ("list", "list-item", "boxed-text", "disp-quote"):
                walk(child, title)

    walk(body, "")
    return out


def text_passages(text: str) -> list[dict]:
    """Passages of a plain text file: paragraphs (blank-line separated), cut at sentence ends."""
    out: list[dict] = []
    for para in re.split(r"\n\s*\n", text):
        if para.strip():
            out += chunk(para, "", MAX_WORDS)
    return out


# ---------------------------------------------------------------- ranking

def rank(query: str, passages: list[dict], k: int = TOP_K, k1: float = 1.5, b: float = 0.75) -> list[dict]:
    """The k passages that best match the query (Okapi BM25), best first."""
    docs = [words(p["text"]) for p in passages]
    if not docs:
        return []
    n = len(docs)
    avg = sum(len(d) for d in docs) / n or 1.0
    df = Counter(w for d in docs for w in set(d))
    q = set(words(query))
    scored = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        score = 0.0
        for w in q:
            if w in tf:
                idf = math.log((n - df[w] + 0.5) / (df[w] + 0.5) + 1)
                score += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scored.append((score, i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{**passages[i], "score": round(s, 3)} for s, i in scored[:k]]


# ---------------------------------------------------------------- sources of text

def _ids(ref: Reference, res: dict) -> dict[str, str]:
    """Identifiers to use: the cited ones, or those of the record found by search."""
    rec = (res.get("match") or {}).get("record") or {}
    by_search = (res.get("exists") or {}).get("status") == "found_by_search"
    return {"doi": ref.doi or (rec.get("doi", "") if by_search else ""),
            "pmid": ref.pmid or (rec.get("pmid", "") if by_search else ""),
            "pmcid": ref.pmcid}


async def source_text(ref: Reference, res: dict, src: Sources, local_file: str | Path | None = None) -> dict:
    """The best text for one cited work: {basis, source, text, passages, notes}."""
    notes: list[str] = []
    if local_file:
        path = Path(local_file).expanduser()
        text = path.read_text(encoding="utf-8", errors="replace")
        passages = text_passages(text)
        if passages:
            return {"basis": FULL_TEXT, "source": f"local file {path.name}", "text": text, "passages": passages,
                    "notes": notes}
        notes.append(f"The local file {path.name} has no text.")

    ids = _ids(ref, res)
    epmc = None
    if any(ids.values()):
        try:
            epmc = await src.europepmc_work(doi=ids["doi"] or None, pmid=ids["pmid"] or None,
                                            pmcid=ids["pmcid"] or None)
        except ServiceError as exc:
            notes.append(str(exc))
    if epmc and epmc.get("open_access") and epmc.get("pmcid"):
        try:
            xml = await src.europepmc_fulltext(epmc["pmcid"])
            passages = jats_passages(xml) if xml else []
            if len(passages) >= 3:
                text = "\n\n".join(p["text"] for p in passages)
                return {"basis": FULL_TEXT, "source": f"Europe PMC {epmc['pmcid']}", "text": text,
                        "passages": passages, "notes": notes}
        except ServiceError as exc:
            notes.append(str(exc))
        except ET.ParseError:
            notes.append(f"The Europe PMC full text of {epmc['pmcid']} could not be read.")

    pmid = ids["pmid"] or (epmc or {}).get("pmid", "")
    doi = ids["doi"] or (epmc or {}).get("doi", "")
    candidates: list[tuple[str, str]] = []
    if pmid:
        try:
            rec = (await src.pubmed_fetch([pmid])).get(pmid)
            candidates.append((f"PubMed {pmid}", (rec or {}).get("abstract", "")))
        except ServiceError as exc:
            notes.append(str(exc))
    if epmc:
        candidates.append(("Europe PMC", epmc.get("abstract", "")))
    if doi and not any(len(t.split()) >= MIN_ABSTRACT_WORDS for _, t in candidates):
        for name, fetch in (("Crossref", src.crossref_work), ("OpenAlex", src.openalex_work)):
            try:
                rec = await fetch(doi)
                candidates.append((name, (rec or {}).get("abstract", "")))
            except ServiceError as exc:
                notes.append(str(exc))
            if candidates and len(candidates[-1][1].split()) >= MIN_ABSTRACT_WORDS:
                break
    for name, text in candidates:
        if len((text or "").split()) >= MIN_ABSTRACT_WORDS:
            return {"basis": ABSTRACT, "source": f"{name} abstract", "text": text,
                    "passages": chunk(text, "Abstract", ABSTRACT_WORDS), "notes": notes}
    return {"basis": NONE, "source": "", "text": "", "passages": [], "notes": notes}


def quote_in(quote: str, text: str) -> bool:
    """True when the quotation appears word for word in the text (spacing and quote marks aside)."""
    q = normalise(quote).strip(" \"'")
    return bool(q) and q in normalise(text)
