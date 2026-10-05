"""Read a manuscript (Markdown or Quarto) and its reference list.

Two citation styles are understood:

- citekey: Pandoc citations ([@key], [see @key, p. 3; @other], narrative @key)
  with a bibliography file (BibTeX, BibLaTeX, CSL JSON or CSL YAML) named in the
  YAML header or given on the command line, or inline `references:` in the header.
- numbered: [1], [2, 5], [3-4] in the text and a numbered list under a heading
  such as "References" or "Sources" (the format Feynman and many agents write).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from . import bibtex
from .ids import detect, find_ids, norm_arxiv, norm_doi, norm_isbn
from .models import Citation, Document, Reference

TEXT_SUFFIXES = {".md", ".qmd", ".markdown", ".txt", ".rmd"}
CROSSREF_PREFIXES = ("fig-", "tbl-", "sec-", "eq-", "lst-", "thm-", "lem-", "cor-", "prp-", "cnj-", "def-",
                     "exm-", "exr-", "sol-", "rem-", "alg-")
KEY_PUNCT = ":.#$%&-+?<>~/"
CITE_RE = re.compile(r"(?<![\w.@/\\])-?@(?:\{([^{}\s]+)\}|([\w][\w:.#$%&\-+?<>~/]*))")
BRACKET_RE = re.compile(r"\[[^\[\]]*@[^\[\]]*\]")
REF_HEADING = re.compile(
    r"^[ \t]{0,3}(?:(#{1,6})[ \t]*|\*\*)\s*(sources|references|reference list|bibliography|works cited|"
    r"literature cited|citations|refer[eê]ncias(?: bibliogr[aá]ficas)?|bibliografia)\s*:?\s*(?:\*\*)?[ \t]*$",
    re.IGNORECASE | re.MULTILINE)
ENTRY_RE = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?(?:\[(\d{1,4})\]|(\d{1,4})[.)])[ \t]+(\S.*)$")
NUM_CITE_RE = re.compile(r"(?<![!\w\]])\[(\d{1,4}(?:\s*[-–]\s*\d{1,4})?(?:\s*[,;]\s*\d{1,4}"
                         r"(?:\s*[-–]\s*\d{1,4})?)*)\](?!\()")
ABBREV = re.compile(r"(?:\bet al|\be\.g|\bi\.e|\bcf|\bvs|\bFigs?|\bEqs?|\bpp?|\bNo|\bVol|\bRefs?|\bTab|\bSuppl|"
                    r"\bapprox|\bca|\bresp|\bed|\beds|\bDr|\bProf|\bSt|\b[A-Z])\.$")


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------- helpers

def _mask(text: str) -> str:
    """Blank out code, comments and raw blocks, keeping offsets and line numbers."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    t = re.sub(r"^([ \t]*)(`{3,}|~{3,}).*?^\1\2[ \t]*$", blank, text, flags=re.MULTILINE | re.DOTALL)
    t = re.sub(r"<!--.*?-->", blank, t, flags=re.DOTALL)
    t = re.sub(r"(`+)(?!`).+?(?<!`)\1(?!`)", blank, t)
    t = re.sub(r"https?://\S+", blank, t)
    return t


def _front_matter(text: str) -> tuple[dict, int]:
    """(metadata, length of the header in characters)."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", text, re.DOTALL)
    if not m:
        return {}, 0
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ParseError(f"The YAML header cannot be read: {exc}") from exc
    return (meta if isinstance(meta, dict) else {}), m.end()


def _sentence(original: str, masked: str, offset: int) -> str:
    """The sentence around offset, from the paragraph that contains it."""
    start = masked.rfind("\n\n", 0, offset)
    start = 0 if start < 0 else start + 2
    end = masked.find("\n\n", offset)
    end = len(masked) if end < 0 else end
    para = original[start:end]
    rel = offset - start
    bounds = [0]
    for m in re.finditer(r"[.!?][\"'”’)\]]*\s+(?=[A-Z0-9\[\"'“(])", para):
        before = para[: m.start() + 1]
        if ABBREV.search(before):
            continue
        bounds.append(m.end())
    bounds.append(len(para))
    for a, b in zip(bounds, bounds[1:]):
        if a <= rel < b:
            s = re.sub(r"\s+", " ", para[a:b]).strip()
            return s if len(s) <= 600 else s[:597] + "..."
    return re.sub(r"\s+", " ", para).strip()[:600]


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------- sentences without a citation

# A sentence "states a finding" when it has a number with a unit or a percentage, an effect
# measure, or one of the claim words below. English only. The list is short on purpose: the
# result is a list for a person to read, never a Fail or a Check.
NUMBER_UNIT = re.compile(
    r"\d(?:[\d,.]*\d)?\s*(?:%|‰|-?fold\b|(?:percent|per cent|times|mg|µg|mcg|g|kg|ml|mL|dL|L|mmol|µmol|mol|"
    r"mmHg|kPa|cm|mm|km|kcal|IU|bpm|Hz|h|hours?|min|minutes?|days?|weeks?|months?|years?|yr|million|billion|"
    r"thousand|deaths|cases|patients|people|participants|adults|children|individuals)\b|per\s+\d)")
EFFECT = re.compile(r"\b(?:a?OR|a?HR|RR|IRR|CI)\b|\bp\s*[<=>]\s*0?\.\d")
CLAIM_WORDS = re.compile(
    r"\b(?:show(?:s|ed|n)|f(?:ou|i)nds?|found|demonstrat(?:es|ed)|report(?:s|ed)|observed|associated with|"
    r"increas(?:es|ed)|reduc(?:es|ed)|decreas(?:es|ed)|improv(?:es|ed)|predict(?:s|ed)|linked to|"
    r"accounts? for|outperform(?:s|ed)|(?:the )?leading cause|most common|prevalence|incidence|mortality|"
    r"risk|odds)\b", re.IGNORECASE)
OWN_WORK_HEADING = re.compile(r"\b(?:methods?|methodology|results)\b", re.IGNORECASE)
REF_TITLE = re.compile(r"^\W*(?:\d+(?:\.\d+)*\.?\s*)?(?:sources|references|reference list|bibliography|works cited|"
                       r"literature cited|citations|refer[eê]ncias(?: bibliogr[aá]ficas)?|bibliografia)\W*$",
                       re.IGNORECASE)
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$")
NOT_PROSE = re.compile(r"^(?:\||\+[-=+:]+\+$|[-:| ]*-{3,}[-:| ]*$|!\[|: |Table:|<|\$\$|\\begin|\\end|\[\^[^\]]+\]:|"
                       r"(?:Figure|Fig\.|Table)\s+\d+[.:])")
SENTENCE_BOUND = re.compile(r"[.!?][\"'”’)\]]*\s+(?=[A-Z0-9\[\"'“(])")
MIN_SENTENCE = 50
MAX_UNCITED = 50


def _bounds(para: str) -> list[int]:
    """Sentence starts in a paragraph, and its end."""
    bounds = [0]
    for m in SENTENCE_BOUND.finditer(para):
        if not ABBREV.search(para[: m.start() + 1]):
            bounds.append(m.end())
    return bounds + [len(para)]


def has_citation(sentence: str) -> bool:
    """[@key], @key, [n] or a footnote mark [^n] (a footnote may hold the citation)."""
    return bool(BRACKET_RE.search(sentence) or CITE_RE.search(sentence) or NUM_CITE_RE.search(sentence)
                or "[^" in sentence)


def states_finding(sentence: str) -> bool:
    return bool(NUMBER_UNIT.search(sentence) or EFFECT.search(sentence) or CLAIM_WORDS.search(sentence))


def uncited_sentences(text: str, masked: str, body_start: int) -> list[dict]:
    """Sentences of the body text that state a finding and cite nothing: [{line, sentence}].

    Deterministic and English only. Body text only: the YAML header, code, comments
    and raw blocks are masked already; headings, tables, figures and their captions,
    display maths, HTML lines, footnote definitions and the reference list (a heading
    such as References, a bold **References** line, or a ::: {#refs} div) are skipped.
    Sections under a heading that names Methods or Results are skipped too: the
    authors' own methods and data need no citation. A sentence is listed when it has
    at least 50 characters, does not end with a question mark, has no citation markup
    and states a finding (states_finding).
    """
    out: list[dict] = []
    stack: list[tuple[int, str]] = []
    refs_block = False  # a ::: {#refs} div or a bold **References** line
    para: list[tuple[int, int]] = []  # (start, end) offsets of the prose of each line

    def flush() -> None:
        if not para:
            return
        joined, shown, starts = "", "", []
        for a, z in para:
            starts.append((len(joined), a))
            joined += masked[a:z] + " "
            shown += text[a:z] + " "  # the same characters before masking (same offsets)
        b = _bounds(joined)
        for a, z in zip(b, b[1:]):
            sentence = re.sub(r"\s+", " ", joined[a:z]).strip()
            if (len(sentence) < MIN_SENTENCE or sentence.endswith("?") or has_citation(sentence)
                    or not states_finding(sentence)):
                continue
            lead = a + len(joined[a:z]) - len(joined[a:z].lstrip())
            off = next(o + lead - q for q, o in reversed(starts) if q <= lead)
            original = re.sub(r"\s+", " ", shown[a:z]).strip()
            out.append({"line": _line(text, off), "sentence": original if len(original) <= 600
                        else original[:597] + "..."})
        para.clear()

    pos = body_start
    for raw_line in masked[body_start:].split("\n"):
        start, pos = pos, pos + len(raw_line) + 1
        line = raw_line.strip()
        if h := HEADING.match(raw_line):
            flush()
            level = len(h.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, h.group(2)))
            refs_block = False
            continue
        if line.startswith(":::"):
            flush()
            refs_block = "#refs" in line
            continue
        if REF_HEADING.match(raw_line):
            flush()
            refs_block = True
            continue
        if not line or NOT_PROSE.match(line):
            flush()
            continue
        if refs_block or any(OWN_WORK_HEADING.search(t) or REF_TITLE.match(t) for _, t in stack):
            continue
        lead = re.match(r"^\s*(?:>\s*)*(?:(?:[-*+]|\d+[.)])\s+)?", raw_line).end()
        para.append((start + lead, start + len(raw_line.rstrip())))
    flush()
    return out


# ---------------------------------------------------------------- bibliographies

def _csl_year(item: dict) -> str:
    issued = item.get("issued") or {}
    if isinstance(issued, dict):
        parts = issued.get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return str(parts[0][0])
        for k in ("raw", "literal"):
            if m := re.search(r"\d{4}", str(issued.get(k) or "")):
                return m.group(0)
    if m := re.search(r"\d{4}", str(issued or "")):
        return m.group(0)
    return ""


def _csl_name(a: dict | str) -> str:
    if isinstance(a, str):
        return a
    return str(a.get("family") or a.get("literal") or a.get("name") or "").strip()


def reference_from_csl(item: dict) -> Reference:
    key = str(item.get("id") or item.get("citation-key") or "").strip()
    title = str(item.get("title") or "")
    names = item.get("author") or item.get("editor") or []
    extra = " ".join(str(item.get(k) or "") for k in ("note", "URL", "number", "archive_location"))
    found = find_ids(extra)
    isbn = item.get("ISBN")
    isbn = isbn[0] if isinstance(isbn, list) and isbn else isbn
    arxiv = found.get("arxiv", "")
    if not arxiv and str(item.get("publisher") or "").lower() == "arxiv":
        arxiv = norm_arxiv(str(item.get("number") or "")) or ""
    ref = Reference(
        key=key, kind="csl", title=bibtex.latex_to_text(title) if "\\" in title else title,
        authors=[n for a in names if (n := _csl_name(a))], year=_csl_year(item),
        container=str(item.get("container-title") or ""), type=str(item.get("type") or ""),
        doi=norm_doi(str(item.get("DOI") or "")) or found.get("doi", ""),
        pmid=re.sub(r"\D", "", str(item.get("PMID") or "")) or found.get("pmid", ""),
        pmcid=str(item.get("PMCID") or "") or found.get("pmcid", ""),
        arxiv=arxiv, isbn=norm_isbn(str(isbn or "")) or "", url=str(item.get("URL") or ""),
    )
    ref.raw = ref.label()
    return ref


def reference_from_bibtex(entry: dict) -> Reference:
    f = entry["fields"]
    text = {k: bibtex.latex_to_text(v) for k, v in f.items()}
    extra = " ".join(text.get(k, "") for k in ("note", "howpublished", "url", "annote", "addendum"))
    found = find_ids(extra)
    arxiv = ""
    if (text.get("archiveprefix") or text.get("eprinttype") or "").lower() == "arxiv":
        arxiv = norm_arxiv(text.get("eprint", "")) or ""
    year = text.get("year") or ""
    if not re.fullmatch(r"\d{4}", year):
        m = re.search(r"\d{4}", year or text.get("date", ""))
        year = m.group(0) if m else ""
    ref = Reference(
        key=entry["key"], kind="bibtex", title=text.get("title", ""), authors=bibtex.authors(f), year=year,
        container=text.get("journal") or text.get("journaltitle") or text.get("booktitle") or "",
        type=entry["type"], doi=norm_doi(text.get("doi")) or found.get("doi", ""),
        pmid=re.sub(r"\D", "", text.get("pmid", "")) or found.get("pmid", ""),
        pmcid=text.get("pmcid", "") or found.get("pmcid", ""),
        arxiv=arxiv or found.get("arxiv", ""), isbn=norm_isbn(text.get("isbn")) or "",
        url=text.get("url", "") or found.get("url", ""),
    )
    ref.raw = ref.label()
    return ref


def read_bibliography(path: Path) -> tuple[list[Reference], list[str]]:
    if not path.exists():
        return [], [f"Bibliography file not found: {path}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in (".bib", ".bibtex", ".biblatex"):
        entries, problems = bibtex.parse(text)
        return [reference_from_bibtex(e) for e in entries], [f"{path.name}, {p}" for p in problems]
    if suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            return [], [f"{path.name} is not valid JSON: {exc}"]
        items = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
        return [reference_from_csl(i) for i in items if isinstance(i, dict)], []
    if suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return [], [f"{path.name} is not valid YAML: {exc}"]
        items = data.get("references", []) if isinstance(data, dict) else data or []
        return [reference_from_csl(i) for i in items if isinstance(i, dict)], []
    return [], [f"{path.name}: unsupported bibliography format (use .bib, .json or .yaml)"]


# ---------------------------------------------------------------- manuscripts

def _citekeys(text: str, masked: str, body_start: int, known: set[str]) -> list[Citation]:
    inside = [(m.start(), m.end()) for m in BRACKET_RE.finditer(masked, body_start)]
    out = []
    for m in CITE_RE.finditer(masked, body_start):
        key = (m.group(1) or m.group(2)).rstrip(KEY_PUNCT)
        if not key or key.startswith(CROSSREF_PREFIXES):
            continue
        bracketed = any(a <= m.start() < b for a, b in inside)
        # A bare @word outside brackets is only a citation when the bibliography has it;
        # otherwise it is more likely a handle or a decorator in prose.
        if not bracketed and key not in known:
            continue
        out.append(Citation(key=key, line=_line(text, m.start()), sentence=_sentence(text, masked, m.start())))
    return out


def _numbered(text: str, masked: str, body_start: int) -> tuple[list[Citation], list[Reference], int] | None:
    heads = [m for m in REF_HEADING.finditer(masked, body_start)]
    if not heads:
        return None
    head = heads[-1]
    level = len(head.group(1) or "")
    section = text[head.end():]
    stop = re.search(r"^#{1,%d}\s" % level, section, re.MULTILINE) if level else None
    section = section[: stop.start()] if stop else section
    refs: dict[str, Reference] = {}
    current: str | None = None
    for raw_line in section.splitlines():
        m = ENTRY_RE.match(raw_line)
        if m:
            current = m.group(1) or m.group(2)
            refs[current] = Reference(key=current, kind="numbered", raw=m.group(3).strip())
        elif current and raw_line.strip() and raw_line[:1].isspace():
            refs[current].raw += " " + raw_line.strip()
        elif not raw_line.strip():
            continue
        else:
            current = None
    if not refs:
        return None
    for r in refs.values():
        ids = find_ids(r.raw)
        r.doi, r.pmid, r.pmcid = ids.get("doi", ""), ids.get("pmid", ""), ids.get("pmcid", "")
        r.arxiv, r.isbn, r.url, r.year = ids.get("arxiv", ""), ids.get("isbn", ""), ids.get("url", ""), ids.get("year", "")
    cites: list[Citation] = []
    for m in NUM_CITE_RE.finditer(masked, body_start, head.start()):
        nums: list[str] = []
        for part in re.split(r"\s*[,;]\s*", m.group(1)):
            if r := re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", part):
                a, b = int(r.group(1)), int(r.group(2))
                nums += [str(n) for n in range(a, b + 1)] if 0 < b - a <= 200 else [str(a), str(b)]
            else:
                nums.append(part.strip())
        for n in nums:
            cites.append(Citation(key=n, line=_line(text, m.start()), sentence=_sentence(text, masked, m.start())))
    return cites, list(refs.values()), head.start()


def read_manuscript(path: str | Path, bibliography: list[str | Path] | None = None) -> Document:
    p = Path(path).expanduser()
    if p.suffix.lower() not in TEXT_SUFFIXES:
        raise ParseError(f"Only text manuscripts ({', '.join(sorted(TEXT_SUFFIXES))}); got {p.suffix or 'no suffix'}. "
                         "Convert Word files first, for example: quarto pandoc paper.docx -o paper.md")
    if not p.exists():
        raise ParseError(f"No file at {p}.")
    text = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    meta, body_start = _front_matter(text)
    masked = _mask(text)
    doc = Document(path=str(p), style="none", uncited_sentences=uncited_sentences(text, masked, body_start))

    bib_paths: list[Path] = [Path(b).expanduser() for b in (bibliography or [])]
    if not bib_paths:
        declared = meta.get("bibliography")
        for b in [declared] if isinstance(declared, str) else declared or []:
            bp = Path(str(b)).expanduser()
            bib_paths.append(bp if bp.is_absolute() else (p.parent / bp))
    refs: list[Reference] = []
    for bp in bib_paths:
        got, problems = read_bibliography(bp.resolve())
        refs += got
        doc.warnings += problems
        doc.bibliography.append(str(bp.resolve()))
    inline = meta.get("references")
    if isinstance(inline, list):
        refs += [reference_from_csl(i) for i in inline if isinstance(i, dict)]
    for r in refs:
        if not r.key:
            doc.warnings.append(f"A bibliography entry has no key and was skipped: {r.label()[:80]}")
        elif r.key in doc.references:
            doc.warnings.append(f"Duplicate key in the bibliography: {r.key} (the first entry is used)")
        else:
            doc.references[r.key] = r

    if doc.references or bib_paths or isinstance(inline, list):
        doc.style = "citekey"
        doc.citations = _citekeys(text, masked, body_start, set(doc.references))
        return doc
    numbered = _numbered(text, masked, body_start)
    if numbered:
        doc.style = "numbered"
        doc.citations, refs, _ = numbered
        doc.references = {r.key: r for r in refs}
        return doc
    cites = _citekeys(text, masked, body_start, set())
    if cites:
        doc.style = "citekey"
        doc.citations = cites
        doc.warnings.append("The manuscript cites [@keys] but names no bibliography file. "
                            "Add `bibliography:` to the YAML header or pass --bib.")
    return doc


def references_from_identifiers(items: list[dict]) -> list[Reference]:
    """References given directly (by an agent or the CLI): identifier and/or citation details."""
    out = []
    for n, it in enumerate(items, start=1):
        raw = str(it.get("raw") or it.get("citation") or "")
        ident = str(it.get("identifier") or "")
        ids = find_ids(f"{ident} {raw}")
        if ident and (d := detect(ident)):
            ids[d[0]] = d[1]
        authors = it.get("authors") or ([it["first_author"]] if it.get("first_author") else [])
        ref = Reference(key=str(it.get("key") or n), kind="given", raw=raw or ident,
                        title=str(it.get("title") or ""), authors=[str(a) for a in authors],
                        year=str(it.get("year") or ids.get("year", "")), container=str(it.get("container") or ""),
                        doi=ids.get("doi", ""), pmid=ids.get("pmid", ""), pmcid=ids.get("pmcid", ""),
                        arxiv=ids.get("arxiv", ""), isbn=ids.get("isbn", ""), url=ids.get("url", ""))
        if not ref.raw:
            ref.raw = ref.label()
        out.append(ref)
    return out
