"""Word and LaTeX manuscripts, turned into the Markdown that parse.py reads.

Word (.docx): citation fields of Zotero (ADDIN ZOTERO_ITEM), Mendeley Desktop and other
CSL tools (ADDIN CSL_CITATION), EndNote (ADDIN EN.CITE) and Citavi (ADDIN CitaviPlaceholder),
and the content controls of Mendeley Cite (w:tag MENDELEY_CITATION_v3_), hold the cited
records; each citation becomes a [@key] citation and its record a reference. A document without fields
is read as text: numbered or author-year citations with a reference list. Word's own
list numbers are not in the text, so the paragraphs of a numbered list in the reference
section get their numbers back. Headings become Markdown headings; tables are left out.

LaTeX (.tex): \\cite and its natbib and biblatex forms become [@key] citations, the
\\bibliography and \\addbibresource files are the bibliography, and a thebibliography
environment is read as a numbered list. Line numbers stay those of the .tex file.
"""

from __future__ import annotations

import base64
import html
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .ids import find_ids, norm_doi, norm_isbn

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------- Word

def _endnote_records(instr: str) -> list[dict]:
    """CSL items from an EndNote field (ADDIN EN.CITE <EndNote>...)."""
    if "<EndNote>" not in instr and "&lt;EndNote&gt;" in instr:
        instr = html.unescape(instr)  # escaped twice by some exports
    start = instr.find("<EndNote>")
    if start < 0:
        return []
    xml = instr[start:]
    try:
        root = ET.fromstring(xml[: xml.find("</EndNote>") + len("</EndNote>")])  # the first of several copies
    except ET.ParseError:
        return []

    def text(el: ET.Element | None) -> str:
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""

    out = []
    for cite in root.iter("Cite"):
        rec = cite.find("record")
        author = text(cite.find("Author"))
        year = text(cite.find("Year"))
        num = text(cite.find("RecNum")) or text(rec.find("rec-number") if rec is not None else None)
        item: dict = {"id": f"{re.sub(r'[^A-Za-z0-9]', '', author)[:20] or 'ref'}{year}-{num or len(out) + 1}",
                      "type": "article-journal"}
        if rec is not None:
            item["title"] = text(rec.find("titles/title"))
            item["container-title"] = text(rec.find("titles/secondary-title")) or text(rec.find("periodical/full-title"))
            names = [text(a) for a in rec.findall("contributors/authors/author")]
            item["author"] = [{"family": n.split(",")[0].strip()} for n in names if n]
            year = text(rec.find("dates/year")) or year
            ids = find_ids(" ".join(text(rec.find(x)) for x in ("electronic-resource-num", "urls", "notes",
                                                                 "accession-num")))
            if d := norm_doi(text(rec.find("electronic-resource-num"))) or ids.get("doi"):
                item["DOI"] = d
            acc = text(rec.find("accession-num"))
            if re.fullmatch(r"\d{1,9}", acc) and "pubmed" in text(rec.find("remote-database-name")).lower():
                item["PMID"] = acc
            if isbn := norm_isbn(text(rec.find("isbn"))):
                item["ISBN"] = isbn
            if url := text(rec.find("urls/related-urls/url")):
                item["URL"] = url
        elif author:
            item["author"] = [{"family": author}]
        if year[:4].isdigit():
            item["issued"] = {"date-parts": [[int(year[:4])]]}
        out.append(item)
    return out


UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)


def _key(item: dict, key: str, n: int) -> str:
    """A citation key; a bare UUID (Mendeley Cite, Citavi) becomes author + year + its first 4 characters."""
    key = re.sub(r"[^\w:.\-]", "", str(key))
    if not key or UUID.fullmatch(key):
        author = (item.get("author") or [{}])[0]
        name = re.sub(r"[^A-Za-z0-9]", "", str(author.get("family") or author.get("literal") or ""))[:20]
        year = str(((item.get("issued") or {}).get("date-parts") or [[""]])[0][0])
        key = f"{name or 'ref'}{year}-{key[:4] or n}"
    return key


def _csl_items(data: dict) -> list[dict]:
    out = []
    for n, ci in enumerate(data.get("citationItems") or [], 1):
        item = dict(ci.get("itemData") or {})
        uri = (ci.get("uris") or ci.get("uri") or [""])
        uri = uri[0] if isinstance(uri, list) and uri else uri if isinstance(uri, str) else ""
        key = uri.rstrip("/").rsplit("/", 1)[-1] if uri else str(item.get("id") or ci.get("id") or n)
        item["id"] = _key(item, key, n)
        out.append(item)
    return out


def _csl_records(instr: str) -> list[dict]:
    """CSL items from a Zotero or Mendeley field (ADDIN ZOTERO_ITEM / CSL_CITATION {json})."""
    start = instr.find("{")
    if start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(instr[start:])
    except ValueError:
        return []
    return _csl_items(data) if isinstance(data, dict) else []


def _b64json(raw: str) -> object:
    try:
        text = base64.b64decode(re.sub(r"\s", "", raw) + "=" * (-len(re.sub(r"\s", "", raw)) % 4)).decode("utf-8-sig")
        return json.loads(text)
    except (ValueError, UnicodeDecodeError):
        return None


def mendeley_cite_records(tag: str) -> list[dict]:
    """CSL items from a Mendeley Cite content control (w:tag MENDELEY_CITATION_v3_<base64 JSON>)."""
    data = _b64json(tag[len("MENDELEY_CITATION_v3_"):]) if tag.startswith("MENDELEY_CITATION_v3_") else None
    return _csl_items(data) if isinstance(data, dict) else []


def _resolve_refs(data: object) -> object:
    """Replace the {"$ref": id} objects of Newtonsoft JSON with the object of that $id."""
    ids: dict[str, object] = {}

    def collect(x: object) -> None:
        if isinstance(x, dict):
            if "$id" in x:
                ids[str(x["$id"])] = x
            for v in x.values():
                collect(v)
        elif isinstance(x, list):
            for v in x:
                collect(v)

    def resolve(x: object, depth: int = 0) -> object:
        if depth > 40:
            return x
        if isinstance(x, dict):
            if set(x) == {"$ref"}:
                return ids.get(str(x["$ref"]), {})
            return {k: resolve(v, depth + 1) for k, v in x.items()}
        if isinstance(x, list):
            return [resolve(v, depth + 1) for v in x]
        return x

    collect(data)
    return resolve(data)


CITAVI_TYPES = {"JournalArticle": "article-journal", "NewspaperArticle": "article-newspaper", "Book": "book",
                "BookEdited": "book", "Contribution": "chapter", "ContributionInBookEdited": "chapter",
                "InternetDocument": "webpage", "Thesis": "thesis", "ConferenceProceedings": "book",
                "UnpublishedWork": "manuscript", "Report": "report", "PressRelease": "article"}


def _citavi_item(ref: dict) -> dict:
    def s(x: object) -> str:
        return re.sub(r"\s+", " ", x).strip() if isinstance(x, str) else ""

    item: dict = {"type": CITAVI_TYPES.get(s(ref.get("ReferenceType")), "article-journal")}
    title = s(ref.get("Title")) or s(ref.get("Title1"))
    if sub := s(ref.get("Subtitle")):
        title = f"{title}: {sub}" if title else sub
    if title:
        item["title"] = title
    people = ref.get("Authors") or ref.get("Editors") or []
    authors = []
    for p in people if isinstance(people, list) else []:
        if not isinstance(p, dict):
            continue
        if family := s(p.get("LastName")):
            authors.append({"family": family, "given": " ".join(x for x in (s(p.get("FirstName")),
                                                                            s(p.get("MiddleName"))) if x)})
        elif name := s(p.get("Name")):
            authors.append({"literal": name})
    if authors:
        item["author"] = authors
    if m := re.search(r"\b(1[5-9]\d\d|20\d\d)\b", s(ref.get("YearResolved")) or s(ref.get("Year"))):
        item["issued"] = {"date-parts": [[int(m.group(1))]]}
    parent = ref.get("ParentReference") if isinstance(ref.get("ParentReference"), dict) else {}
    periodical = ref.get("Periodical") if isinstance(ref.get("Periodical"), dict) else {}
    if container := s(periodical.get("Name")) or s(parent.get("Title")):
        item["container-title"] = container
    if d := norm_doi(s(ref.get("Doi"))):
        item["DOI"] = d
    if re.fullmatch(r"\d{1,9}", s(ref.get("PubMedId"))):
        item["PMID"] = s(ref.get("PubMedId"))
    if re.fullmatch(r"(?i)PMC\d+", s(ref.get("PmcId"))):
        item["PMCID"] = s(ref.get("PmcId")).upper()
    if isbn := norm_isbn(s(ref.get("Isbn")) or s(parent.get("Isbn"))):
        item["ISBN"] = isbn
    if url := s(ref.get("OnlineAddress")):
        item["URL"] = url
    if vol := s(ref.get("Volume")):
        item["volume"] = vol
    if item["type"] == "article-journal" and (issue := s(ref.get("Number"))):
        item["issue"] = issue
    pages = ref.get("PageRange")
    pages = pages.get("OriginalString") if isinstance(pages, dict) else pages
    if isinstance(pages, str) and (p := s((re.findall(r"<os>([^<]*)</os>", pages) or [pages])[-1])):
        item["page"] = p  # the last <os> of Citavi's XML form is the whole range
    return item


def citavi_records(instr: str) -> list[dict]:
    """CSL items from a Citavi field (ADDIN CitaviPlaceholder{<base64 JSON>})."""
    m = re.search(r"CITAVI\.?PLACEHOLDER\s*(?:\{?[0-9a-f-]{36}\}?)?\s*\{?\s*([A-Za-z0-9+/=\s]{40,})", instr, re.I)
    data = _b64json(m.group(1)) if m else None
    if data is None and (start := instr.find("{")) >= 0:  # older versions: JSON in the field itself
        try:
            data, _ = json.JSONDecoder().raw_decode(instr[start:])
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return []
    data = _resolve_refs(data)
    out = []
    for n, e in enumerate(data.get("Entries") or [], 1):
        ref = e.get("Reference") if isinstance(e, dict) else None
        if not isinstance(ref, dict):
            continue
        item = _citavi_item(ref)
        key = ref.get("CitationKey") or ref.get("BibTeXKey") or e.get("ReferenceId") or ref.get("Id") or ""
        item["id"] = _key(item, str(key), n)
        out.append(item)
    return out


def field_records(instr: str) -> list[dict]:
    if "EN.CITE" in instr:
        return _endnote_records(instr)
    if "ZOTERO_ITEM" in instr or "CSL_CITATION" in instr:
        return _csl_records(instr)
    if re.search(r"CITAVI\.?PLACEHOLDER", instr, re.I):
        return citavi_records(instr)
    return []


SUP_CITE = re.compile(r"\s*\d{1,3}(?:\s*[,\u2013\-]\s*\d{1,3})*\s*")
UNIT_BEFORE = re.compile(r"(?:\b(?:k?g/)?[cdkmµ]?m|\bs|\bL|\bmin|\bh|[×x]\s?10|\b10|\^)\s*$")


def _decode(data: list[str]) -> str:
    """The EndNote XML held in w:fldData (base64; UTF-8 or UTF-16)."""
    out = []
    for d in data:
        if not d.strip():
            continue
        try:
            raw = base64.b64decode(re.sub(r"\s", "", d))
        except ValueError:
            continue
        out.append(raw.decode("utf-16", "replace") if raw[1:2] == b"\x00" else raw.decode("utf-8", "replace"))
    return " ".join(out)


def _is_heading(p: ET.Element, styles: dict[str, int]) -> int:
    sid = p.find(f"{W}pPr/{W}pStyle")
    sid = sid.get(f"{W}val") if sid is not None else ""
    if sid in styles:
        return styles[sid]
    m = re.fullmatch(r"(?i)heading\s*(\d)|titre(\d)|berschrift(\d)|ttulo(\d)", sid or "")
    return int(next(g for g in m.groups() if g)) if m else 0


def _heading_styles(z: zipfile.ZipFile) -> dict[str, int]:
    """Style id -> heading level, from styles.xml (style ids are localised, names are not)."""
    try:
        root = ET.fromstring(z.read("word/styles.xml"))
    except (KeyError, ET.ParseError):
        return {}
    out = {}
    for s in root.iter(f"{W}style"):
        name = s.find(f"{W}name")
        m = re.fullmatch(r"(?i)heading (\d)", name.get(f"{W}val") if name is not None else "")
        if m:
            out[s.get(f"{W}styleId")] = int(m.group(1))
    return out


def docx_to_markdown(path: Path) -> tuple[str, list[dict], list[int], str]:
    """(Markdown text, CSL items from the citation fields, paragraph number of each line, date)."""
    try:
        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise FormatError(f"{path.name} is not a readable Word document ({exc}).") from exc
    styles = _heading_styles(z)
    date = ""
    try:
        core = z.read("docProps/core.xml").decode("utf-8", "replace")
        if m := re.search(r"<dcterms:created[^>]*>(\d{4}-\d{2}-\d{2})", core):
            date = m.group(1)
    except KeyError:
        pass
    items: dict[str, dict] = {}
    lines: list[str] = []
    para_of_line: list[int] = []
    in_refs = False
    counters: dict[str, int] = {}
    body = root.find(f"{W}body")
    paragraphs = []
    for el in body if body is not None else []:
        if el.tag == f"{W}p":
            paragraphs.append(el)
        elif el.tag == f"{W}sdt":  # a content control around whole paragraphs (a bibliography, a section)
            paragraphs += [p for p in el.iter(f"{W}p")]
    seen_heading = False  # superscript numbers before the first heading are affiliations, not citations
    for n, p in enumerate(paragraphs, 1):
        out: list[str] = []
        depth = 0  # field nesting
        instr: list[str] = []
        data: list[str] = []  # EndNote keeps the record base64-encoded in w:fldData (EN.CITE.DATA)
        in_result = False
        field_keys: list[str] = []
        sup: list[str] = []
        superscript = False

        def flush(sup: list[str] = sup, out: list[str] = out, seen_heading: bool = seen_heading) -> None:
            if not sup:
                return
            raw = "".join(sup)
            sup.clear()
            before = "".join(out)
            if seen_heading and SUP_CITE.fullmatch(raw) and not UNIT_BEFORE.search(before):
                out.append(f" [{raw.strip()}]")
            else:
                out.append(raw)

        hidden: set[int] = set()  # text of Mendeley Cite citations, replaced by the keys
        for el in p.iter():
            if id(el) in hidden:
                continue
            if el.tag == f"{W}sdt":
                tag = el.find(f"{W}sdtPr/{W}tag")
                recs = mendeley_cite_records(tag.get(f"{W}val") or "") if tag is not None else []
                if recs:
                    flush()
                    for r in recs:
                        items.setdefault(r["id"], r)
                    out.append(" [" + "; ".join(f"@{r['id']}" for r in recs) + "]")
                    hidden.update(id(t) for t in el.iter(f"{W}t"))
                continue
            if el.tag == f"{W}r":
                va = el.find(f"{W}rPr/{W}vertAlign")
                superscript = va is not None and va.get(f"{W}val") == "superscript"
            if el.tag != f"{W}t" or not superscript:
                if el.tag in (f"{W}t", f"{W}fldChar", f"{W}fldSimple", f"{W}tab", f"{W}br"):
                    flush()
            if el.tag == f"{W}fldSimple":
                recs = field_records(el.get(f"{W}instr") or "")
                if recs:
                    for r in recs:
                        items.setdefault(r["id"], r)
                    out.append(" [" + "; ".join(f"@{r['id']}" for r in recs) + "]")
                    for t in el.iter(f"{W}t"):
                        t.text = ""  # the shown citation is replaced by the keys
            elif el.tag == f"{W}fldChar":
                kind = el.get(f"{W}fldCharType")
                if kind == "begin":
                    depth += 1
                    if depth == 1:
                        instr, data, in_result, field_keys = [], [], False, []
                    data.append(el.findtext(f"{W}fldData") or "")
                elif kind == "separate" and depth == 1:
                    recs = field_records("".join(instr) + _decode(data))
                    if recs:
                        for r in recs:
                            items.setdefault(r["id"], r)
                        field_keys = [r["id"] for r in recs]
                        out.append(" [" + "; ".join(f"@{k}" for k in field_keys) + "]")
                    in_result = True
                elif kind == "end":
                    depth = max(0, depth - 1)  # a field can end in a later paragraph than it began
                    if depth == 0:
                        in_result, field_keys = False, []
            elif el.tag == f"{W}instrText" and depth >= 1:
                instr.append(el.text or "")
            elif el.tag == f"{W}t" and el.text:
                if depth and in_result and field_keys:
                    continue  # the citation as Word shows it, replaced by the keys
                if depth and not in_result:
                    continue
                if superscript:
                    sup.append(el.text)
                else:
                    out.append(el.text)
            elif el.tag in (f"{W}tab",):
                out.append(" ")
            elif el.tag in (f"{W}br", f"{W}cr"):
                out.append(" ")
        flush()
        text = re.sub(r"\s+", " ", "".join(out)).strip()
        if not text:
            continue
        level = _is_heading(p, styles)
        if level or re.fullmatch(r"(?i)\W*(abstract|summary|introduction|background|resumo)\W*", text):
            seen_heading = True
        if level:
            in_refs = bool(re.fullmatch(r"(?i)\W*(?:\d+\.?\s*)?(references|bibliography|reference list|"
                                        r"works cited|literature cited|sources|refer[eê]ncias(?: bibliogr[aá]ficas)?|"
                                        r"bibliografia)\W*", text))
            text = "#" * level + " " + text
        else:
            if re.fullmatch(r"(?i)\W*(references|bibliography|reference list|refer[eê]ncias)\W*", text):
                in_refs, text = True, "## " + text
            num = p.find(f"{W}pPr/{W}numPr/{W}numId")
            if in_refs and num is not None and not re.match(r"\[?\d+[.)\]]", text):
                nid = num.get(f"{W}val") or ""
                counters[nid] = counters.get(nid, 0) + 1
                text = f"{counters[nid]}. {text}"
        lines += [text, ""]
        para_of_line += [n, n]
    return "\n".join(lines) + "\n", list(items.values()), para_of_line, date


# ---------------------------------------------------------------- LaTeX

CITE_CMD = re.compile(
    r"\\(?:[Cc]ite[a-z]*|[Pp]arencite|[Tt]extcite|[Aa]utocite|[Ff]ootcite[a-z]*|[Ss]martcite|[Ss]upercite|"
    r"citep|citet|citealp|citealt|citeauthor|citeyear|nocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^{}]*)\}")
BIB_CMD = re.compile(r"\\(?:bibliography|addbibresource|addglobalbib)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
FLOATS = re.compile(r"\\begin\{(figure|table|equation|align|gather|multline|eqnarray|tabular|lstlisting|"
                    r"verbatim|minted|tikzpicture)\*?\}.*?\\end\{\1\*?\}", re.S)
SECTION = re.compile(r"\\(chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")


def _keep_lines(m: re.Match) -> str:
    return "\n" * m.group(0).count("\n")


def latex_to_markdown(path: Path) -> tuple[str, list[Path], str]:
    """(Markdown text with the same line numbers, bibliography files, date)."""
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    text = re.sub(r"(?<!\\)%.*", "", text)  # comments
    bibs: list[Path] = []
    for m in BIB_CMD.finditer(text):
        for name in m.group(1).split(","):
            name = name.strip()
            if not name:
                continue
            f = Path(name if name.endswith(".bib") else name + ".bib")
            bibs.append(f if f.is_absolute() else path.parent / f)
    date = ""
    if m := re.search(r"\\date\s*\{\s*(\d{4}(?:-\d{2}(?:-\d{2})?)?)", text):
        date = m.group(1)

    # thebibliography: numbered entries, cited by key
    keys: dict[str, str] = {}

    def bibitems(m: re.Match) -> str:
        out = ["## References", ""]
        for n, item in enumerate(re.split(r"\\bibitem", m.group(1))[1:], 1):
            km = re.match(r"\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}(.*)", item, re.S)
            if not km:
                continue
            keys[km.group(1).strip()] = str(n)
            entry = re.sub(r"\s+", " ", _plain(km.group(2))).strip()
            out.append(f"{n}. {entry}")
        body = "\n".join(out)
        return body + "\n" * max(0, m.group(0).count("\n") - body.count("\n"))

    text = re.sub(r"\\begin\{thebibliography\}(?:\{[^{}]*\})?(.*?)\\end\{thebibliography\}", bibitems, text,
                  flags=re.S)

    def cite(m: re.Match) -> str:
        names = [k.strip() for k in m.group(1).split(",") if k.strip() and k.strip() != "*"]
        if m.group(0).startswith("\\nocite") or not names:
            return ""
        if keys:  # thebibliography: numbered citations
            return "[" + ", ".join(keys.get(k, k) for k in names) + "]"
        return "[" + "; ".join(f"@{k}" for k in names) + "]"

    if (start := text.find("\\begin{document}")) >= 0:
        text = "\n" * text.count("\n", 0, start) + text[start:]  # the preamble, keeping line numbers
    text = FLOATS.sub(_keep_lines, text)
    text = re.sub(r"\\begin\{document\}|\\end\{document\}|\\maketitle", "", text)
    text = CITE_CMD.sub(cite, text)
    text = SECTION.sub(lambda m: "#" * {"chapter": 1, "section": 2, "subsection": 3}.get(m.group(1), 4)
                       + " " + m.group(2), text)
    return _plain(text), [b for b in dict.fromkeys(bibs)], date


def _plain(text: str) -> str:
    """Common LaTeX markup to text, keeping line breaks."""
    t = re.sub(r"\\(?:emph|textit|textbf|textsc|texttt|textrm|mbox|url|href\{[^{}]*\})\s*\{([^{}]*)\}", r"\1", text)
    t = re.sub(r"\\(?:label|ref|eqref|autoref|cref|Cref|footnotemark)\s*\{[^{}]*\}", "", t)
    t = re.sub(r"\\begin\{[^{}]*\}|\\end\{[^{}]*\}", "", t)
    t = re.sub(r"\$[^$\n]*\$", "", t)
    t = t.replace("~", " ").replace("\\%", "%").replace("\\&", "&").replace("``", '"').replace("''", '"')
    t = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", t)
    return t.replace("{", "").replace("}", "")
