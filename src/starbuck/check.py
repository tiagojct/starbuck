"""The checks. Each reference gets a result for three levels:

1. exists   Does the identifier resolve? Without one, can the work be found?
2. match    Do title, first author and year agree with the record?
3. status   Retracted, under an expression of concern, corrected, a notice
            itself, or a preprint with a published version?

Findings carry a level (fail, warn, note). The reference's verdict is the worst
level among its findings, "pass" when there are none, and "error" when a
service failure left level 1 undecided.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Callable

from . import __version__
from .ids import ARXIV_RE, DOI_RE, PMID_RE, URL_RE, containment, same_name, slug, title_similarity, tokens
from .models import Document, Reference
from .parse import MAX_UNCITED
from .sources import ServiceError, Sources, family_of

# Thresholds (reported in every result, so a report states the rules it applied)
TITLE_OK = 0.90  # title similarity at or above: same title
TITLE_MISMATCH = 0.60  # below: a different work
CONTAIN_OK = 0.80  # numbered entries: share of record-title words found in the entry
CONTAIN_MISMATCH = 0.50
SEARCH_FOUND = 0.90  # bibliographic search: accept the best candidate
SEARCH_POSSIBLE = 0.75  # report as a possible match
YEAR_TOLERANCE = 1  # online-first vs print year

RETRACTED = {"retraction", "withdrawal", "removal", "partial_retraction", "partial-retraction"}
CONCERN = {"expression_of_concern", "expression-of-concern"}
CORRECTED = {"correction", "erratum", "corrigendum", "addendum", "clarification"}
ORDER = {"pass": 0, "note": 1, "warn": 2, "fail": 3, "error": 4}

THRESHOLDS = {"title_ok": TITLE_OK, "title_mismatch": TITLE_MISMATCH, "contain_ok": CONTAIN_OK,
              "contain_mismatch": CONTAIN_MISMATCH, "search_found": SEARCH_FOUND,
              "search_possible": SEARCH_POSSIBLE, "year_tolerance": YEAR_TOLERANCE}


def _who(rec: dict) -> str:
    names = [family_of(a) for a in rec.get("authors") or []]
    names = [n for n in names if n]
    if not names:
        return ""
    return names[0] + (" et al." if len(names) > 1 else "")


def describe(rec: dict) -> str:
    who, year = _who(rec), rec.get("year") or ""
    head = f"{who} ({year})" if who and year else who or year
    title = rec.get("title") or "(no title)"
    return f'{head}, "{title}"' if head else f'"{title}"'


def _year_ok(a: str, b: str) -> bool | None:
    if not (a and b and a[:4].isdigit() and b[:4].isdigit()):
        return None
    return abs(int(a[:4]) - int(b[:4])) <= YEAR_TOLERANCE


class Outcome:
    """Collects findings for one reference."""

    def __init__(self, ref: Reference) -> None:
        self.ref = ref
        self.findings: list[dict] = []
        self.exists: dict[str, Any] = {"status": "not_checked", "via": []}
        self.match: dict[str, Any] = {"status": "not_checked"}
        self.status: dict[str, Any] = {"status": "not_checked", "notices": []}
        self.record: dict | None = None
        self.suggestion = ""
        self.errors: list[str] = []

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append({"level": level, "code": code, "message": message})

    def verdict(self) -> str:
        if self.exists["status"] in ("error", "not_checked") and self.errors:
            return "error"
        worst = "pass"
        for f in self.findings:
            if ORDER[f["level"]] > ORDER[worst]:
                worst = f["level"]
        return worst


# ---------------------------------------------------------------- level 2

def entry_text(ref: Reference) -> str:
    """The free text of an entry without its identifiers and links."""
    t = URL_RE.sub(" ", ref.raw or "")
    t = DOI_RE.sub(" ", t)
    return PMID_RE.sub(" ", ARXIV_RE.sub(" ", t))


def compare(ref: Reference, rec: dict) -> dict:
    """Field-by-field comparison of the citation with a record."""
    fields: dict[str, dict] = {}
    rec_first = family_of((rec.get("authors") or [{}])[0]) if rec.get("authors") else ""
    text = entry_text(ref)
    if not ref.title and len(tokens(text)) < 3:
        # Only an identifier was given (for example a bare DOI link): nothing to compare.
        return {"status": "not_compared", "fields": {}}
    if ref.title:
        score = title_similarity(ref.title, rec.get("title"))
        fields["title"] = {"cited": ref.title, "found": rec.get("title") or "", "score": score,
                           "ok": score >= TITLE_OK}
        mismatch = score < TITLE_MISMATCH
    else:
        score = containment(rec.get("title"), text)
        fields["title"] = {"cited": ref.raw, "found": rec.get("title") or "", "score": score,
                           "ok": score >= CONTAIN_OK, "method": "words of the record title found in the entry"}
        mismatch = score < CONTAIN_MISMATCH
    if ref.authors and rec_first:
        same = same_name(ref.authors[0], rec_first)
        elsewhere = not same and any(same_name(ref.authors[0], family_of(a)) for a in (rec.get("authors") or [])[1:])
        fields["first_author"] = {"cited": ref.authors[0], "found": rec_first, "ok": same,
                                  **({"note": "listed later in the record"} if elsewhere else {})}
    elif not ref.title and rec_first:
        present = slug(rec_first) in {slug(w) for w in tokens(text)}
        fields["first_author"] = {"cited": "", "found": rec_first, "ok": present,
                                  "method": "record first author found in the entry"}
    cited_year = ref.year
    if cited_year and rec.get("year"):
        fields["year"] = {"cited": cited_year, "found": rec["year"], "ok": bool(_year_ok(cited_year, rec["year"]))}
    bad = [k for k, v in fields.items() if not v["ok"]]
    if mismatch or ("title" in bad and "first_author" in bad):
        status = "mismatch"
    elif bad:
        status = "partial"
    else:
        status = "ok"
    return {"status": status, "fields": fields}


def _record_summary(rec: dict) -> dict:
    authors = [a.get("name") or " ".join(x for x in (a.get("given"), a.get("family")) if x)
               for a in (rec.get("authors") or [])[:3]]
    return {k: v for k, v in {
        "source": rec.get("source"), "title": rec.get("title"), "authors": authors,
        "more_authors": max(0, len(rec.get("authors") or []) - 3), "year": rec.get("year"),
        "container": rec.get("container"), "doi": rec.get("doi"), "pmid": rec.get("pmid"),
        "arxiv": rec.get("arxiv"), "kind": rec.get("kind")}.items() if v}


def _match_findings(out: Outcome, cmp: dict, what: str) -> None:
    f = cmp["fields"]
    rec = out.record or {}
    if cmp["status"] == "mismatch":
        out.add("fail", "wrong_work", f"The {what} points to a different work: {describe(rec)}.")
        return
    t = f.get("title")
    if t and not t["ok"]:
        out.add("warn", "title_differs", f"The title differs from the record ({t['found']!r}; similarity {t['score']}).")
    a = f.get("first_author")
    if a and not a["ok"]:
        if a.get("note"):
            out.add("warn", "author_order", f"First author differs: cited {a['cited']}, record lists {a['found']} "
                    f"first ({a['cited']} appears later).")
        elif a["cited"]:
            out.add("warn", "author_differs", f"First author differs: cited {a['cited']}, record {a['found']}.")
        else:
            out.add("warn", "author_differs", f"The record's first author ({a['found']}) is not in the entry.")
    y = f.get("year")
    if y and not y["ok"]:
        out.add("warn", "year_differs", f"Year differs: cited {y['cited']}, record {y['found']}.")


# ---------------------------------------------------------------- level 3

def _notice_text(ns: list[dict]) -> str:
    """One description for notices of the same kind found by several services."""
    main = max(ns, key=lambda n: (bool(n.get("notice_doi")), bool(n.get("date"))))
    vias = list(dict.fromkeys(n["via"] for n in ns if n.get("via")))
    bits = [x for x in (main.get("date"), f"notice doi:{main['notice_doi']}" if main.get("notice_doi") else "") if x]
    who = f"reported by {', '.join(vias)}" if vias else ""
    return "; ".join(x for x in (", ".join(bits), who) if x)


async def _status(out: Outcome, src: Sources, crossref_doi: str | None, pubmed: dict | None,
                  arxiv: dict | None) -> None:
    ref = out.ref
    notices: list[dict] = []
    checked: list[str] = []
    if crossref_doi:
        try:
            for n in await src.crossref_updates(crossref_doi):
                via = "Retraction Watch" if "retraction" in (n.get("source") or "").lower() else "Crossref"
                notices.append({**n, "via": via})
            checked.append("Crossref")
        except ServiceError as exc:
            out.errors.append(str(exc))
    if ref.doi or ref.pmid:
        try:
            oa = await src.openalex_work(doi=ref.doi or None, pmid=None if ref.doi else ref.pmid)
            checked.append("OpenAlex")
            if oa and oa.get("is_retracted"):
                notices.append({"type": "retraction", "label": "Retracted", "via": "OpenAlex", "date": "",
                                "notice_doi": ""})
        except ServiceError as exc:
            out.errors.append(str(exc))
    if pubmed:
        checked.append("PubMed")
        kinds = {"RetractionIn": "retraction", "RetractedandRepublishedIn": "retracted_and_republished",
                 "ExpressionOfConcernIn": "expression_of_concern", "ErratumIn": "correction"}
        for c in pubmed.get("comments") or []:
            if c["type"] in kinds:
                notices.append({"type": kinds[c["type"]], "label": c["type"], "via": "PubMed",
                                "date": "", "notice_doi": "", "detail": c.get("source", "")})
        types = set(pubmed.get("publication_types") or [])
        if "Retracted Publication" in types:
            notices.append({"type": "retraction", "label": "Retracted Publication", "via": "PubMed",
                            "date": "", "notice_doi": ""})
        if "Retraction of Publication" in types:
            out.add("warn", "is_notice", "The cited item is a retraction notice, not a research article.")
        if "Published Erratum" in types:
            out.add("warn", "is_notice", "The cited item is an erratum notice, not a research article.")

    rec = out.record or {}
    for n in rec.get("notice_of") or []:
        what = n.get("type") or "update"
        out.add("warn", "is_notice", f"The cited DOI is a {what.replace('_', ' ')} notice for {n.get('doi')}, "
                "not the work itself.")
    if arxiv:
        checked.append("arXiv")
    published = rec.get("published_version") or (arxiv or {}).get("journal_doi")
    if published and published != ref.doi:
        out.add("note", "preprint_published", f"Cited as a preprint; a published version exists: doi:{published}.")

    groups: dict[str, list[dict]] = {"retracted": [], "republished": [], "concern": [], "corrected": []}
    for n in notices:
        t = n["type"]
        cat = ("retracted" if t in RETRACTED else "republished" if t == "retracted_and_republished"
               else "concern" if t in CONCERN else "corrected" if t in CORRECTED else None)
        if cat:
            groups[cat].append(n)
    state = "ok"
    for cat in ("corrected", "concern", "republished", "retracted"):  # later ones win
        ns = groups[cat]
        if not ns:
            continue
        state = cat
        if cat == "corrected" and groups["retracted"]:
            continue  # a correction to a retracted work changes nothing for the citing author
        text = _notice_text(ns)
        if cat == "retracted":
            out.add("fail", "retracted", f"Retracted ({text}).")
        elif cat == "republished":
            out.add("warn", "republished", f"Retracted and republished ({text}); cite the republished version.")
        elif cat == "concern":
            out.add("warn", "concern", f"Expression of concern ({text}).")
        else:
            out.add("note", "corrected", f"Corrected ({text}). Check that the cited result was not changed.")
    out.findings.sort(key=lambda f: -ORDER[f["level"]])
    if any(f["code"] == "is_notice" for f in out.findings) and state == "ok":
        state = "notice"
    if any(f["code"] == "preprint_published" for f in out.findings) and state == "ok":
        state = "preprint_published"
    out.status = {"status": state if checked else "not_checked", "checked_with": checked, "notices": notices}


# ---------------------------------------------------------------- one reference

async def _search(out: Outcome, src: Sources) -> None:
    """A reference without a usable identifier: search Crossref, then try its web page."""
    ref = out.ref
    first = ref.authors[0] if ref.authors else ""
    query = " ".join(x for x in (ref.title, first, ref.year) if x) if ref.title else entry_text(ref)
    searched = len(tokens(query)) >= 3
    if searched:
        try:
            cands = await src.crossref_search(query, rows=5)
        except ServiceError as exc:
            out.errors.append(str(exc))
            out.exists = {"status": "error", "via": []}
            return
        best, best_score = None, 0.0
        for c in cands:
            f = compare(ref, c)["fields"]
            if "title" not in f:
                continue
            score = f["title"]["score"]
            if "year" in f and not f["year"]["ok"]:
                score *= 0.6
            if "first_author" in f and not f["first_author"]["ok"]:
                score *= 0.8
            if score > best_score:
                best, best_score = c, round(score, 3)
        if best and best_score >= SEARCH_FOUND:
            out.record = best
            out.exists = {"status": "found_by_search", "via": ["Crossref search"], "confidence": best_score}
            out.match = {**compare(ref, best), "record": _record_summary(best)}
            if best.get("doi"):
                out.suggestion = f"doi:{best['doi']}"
                out.add("note", "add_identifier", f"No identifier given; Crossref has a matching record, "
                        f"doi:{best['doi']} (confidence {best_score}). Adding the DOI makes the reference checkable.")
            return
        if best and best_score >= SEARCH_POSSIBLE and not ref.url:
            out.exists = {"status": "possible_match", "via": ["Crossref search"], "confidence": best_score}
            out.match = {"status": "not_checked", "record": _record_summary(best)}
            out.add("warn", "possible_match", f"No identifier given; the closest Crossref record is {describe(best)}"
                    f"{', doi:' + best['doi'] if best.get('doi') else ''} (confidence {best_score}). "
                    "Check that it is the intended work.")
            return
    if ref.url:
        try:
            code = await src.url_status(ref.url)
        except ServiceError as exc:
            out.exists = {"status": "web_page_unreachable", "via": ["web"]}
            out.add("warn", "web_unreachable", f"Web page not reachable ({exc}): {ref.url}")
            return
        if code < 400:
            out.exists = {"status": "web_page", "via": ["web"], "http": code}
            out.add("note", "web_page", f"Web page reachable (HTTP {code}); its content was not checked.")
        else:
            out.exists = {"status": "web_page_unreachable", "via": ["web"], "http": code}
            out.add("warn", "web_unreachable", f"Web page not reachable (HTTP {code}): {ref.url}")
        return
    if not searched:
        out.exists = {"status": "unidentifiable", "via": []}
        out.add("warn", "unidentifiable", "The entry has no identifier and too little text to search for.")
        return
    out.exists = {"status": "not_found_by_search", "via": ["Crossref search"]}
    out.add("warn", "not_found", "No identifier given, and no matching record in Crossref. Books, reports and "
            "web pages are often missing from Crossref; check this reference by hand.")


async def check_reference(ref: Reference, src: Sources, pubmed: dict[str, dict], arxiv: dict[str, dict],
                          prefetch_errors: dict[str, str]) -> dict:
    out = Outcome(ref)
    records: dict[str, dict] = {}
    via: list[str] = []
    crossref_doi = None

    if ref.doi:
        try:
            rec = await src.crossref_work(ref.doi)
            if rec:
                records["doi"], crossref_doi = rec, ref.doi
                via.append("Crossref")
            else:
                rec = await src.datacite_work(ref.doi)
                if rec:
                    records["doi"] = rec
                    via.append("DataCite")
                elif await src.doi_registered(ref.doi):
                    via.append("doi.org")
                    out.add("note", "no_metadata", f"doi:{ref.doi} is registered, but neither Crossref nor DataCite "
                            "has its metadata, so it was not compared with the citation.")
                else:
                    out.add("fail", "doi_not_found", f"doi:{ref.doi} does not exist (not in Crossref, DataCite "
                            "or the DOI system).")
        except ServiceError as exc:
            out.errors.append(str(exc))
    if ref.pmid:
        if "pubmed" in prefetch_errors:
            out.errors.append(prefetch_errors["pubmed"])
        elif ref.pmid in pubmed:
            records["pmid"] = pubmed[ref.pmid]
            via.append("PubMed")
        else:
            out.add("fail", "pmid_not_found", f"PubMed has no record with PMID {ref.pmid}.")
    if ref.arxiv:
        if "arxiv" in prefetch_errors:
            out.errors.append(prefetch_errors["arxiv"])
        elif ref.arxiv in arxiv:
            records["arxiv"] = arxiv[ref.arxiv]
            via.append("arXiv")
        else:
            out.add("fail", "arxiv_not_found", f"arXiv has no paper {ref.arxiv}.")
    if ref.isbn and not records:
        try:
            rec = await src.openlibrary_isbn(ref.isbn)
            if rec:
                records["isbn"] = rec
                via.append("Open Library")
            else:
                out.add("note", "isbn_unconfirmed", f"Open Library has no record for ISBN {ref.isbn}; its coverage "
                        "is incomplete, so this does not show that the book does not exist.")
        except ServiceError as exc:
            out.errors.append(str(exc))

    failed_ids = {f["code"] for f in out.findings} & {"doi_not_found", "pmid_not_found", "arxiv_not_found"}
    checkable = bool(ref.doi or ref.pmid or ref.arxiv or ref.isbn)
    if records:
        out.exists = {"status": "found", "via": via}
    elif via:  # the DOI is registered, but no agency gave metadata
        out.exists = {"status": "found", "via": via, "metadata": False}
    elif failed_ids:
        out.exists = {"status": "not_found", "via": via}
    elif checkable and out.errors:
        out.exists = {"status": "error", "via": []}
    elif ref.isbn:
        out.exists = {"status": "unconfirmed", "via": []}
    else:
        if ref.pmcid:
            out.add("note", "pmcid_only", f"{ref.pmcid} was not looked up; Starbuck searched by the citation instead.")
        await _search(out, src)

    # Two identifiers that disagree
    if "doi" in records and "pmid" in records:
        d, p = records["doi"], records["pmid"]
        if (p.get("doi") and p["doi"] != ref.doi) or (not p.get("doi") and
                                                       title_similarity(d.get("title"), p.get("title")) < TITLE_MISMATCH):
            out.add("fail", "id_conflict", f"The DOI and the PMID point to different works: doi:{ref.doi} is "
                    f"{describe(d)}; PMID {ref.pmid} is {describe(p)}.")
    if "doi" in records and "arxiv" in records:
        if title_similarity(records["doi"].get("title"), records["arxiv"].get("title")) < 0.5:
            out.add("warn", "id_conflict", f"The DOI and the arXiv ID seem to be different works: "
                    f"{describe(records['doi'])} and {describe(records['arxiv'])}.")

    primary_key = next((k for k in ("doi", "pmid", "arxiv", "isbn") if k in records), None)
    if primary_key:
        out.record = records[primary_key]
        cmp = compare(ref, out.record)
        out.match = {**cmp, "record": _record_summary(out.record), "compared_with": primary_key}
        _match_findings(out, cmp, {"doi": "DOI", "pmid": "PMID", "arxiv": "arXiv ID", "isbn": "ISBN"}[primary_key])

    if out.exists["status"] in ("found", "found_by_search"):
        if out.exists["status"] == "found_by_search" and out.record and out.record.get("doi"):
            crossref_doi = out.record["doi"]
        await _status(out, src, crossref_doi, records.get("pmid"), records.get("arxiv"))

    if out.errors:
        level = "note" if out.exists["status"] not in ("error", "not_checked") else "warn"
        out.add(level, "service_error", "Some checks could not run: " + "; ".join(dict.fromkeys(out.errors)))

    return {
        "key": ref.key, "label": ref.label(), "verdict": out.verdict(), "reference": ref.to_dict(),
        "exists": out.exists, "match": out.match, "status": out.status, "findings": out.findings,
        **({"suggestion": out.suggestion} if out.suggestion else {}),
    }


# ---------------------------------------------------------------- whole documents

async def check_references(refs: list[Reference], src: Sources,
                           progress: Callable[[int, int], None] | None = None) -> list[dict]:
    pmids = [r.pmid for r in refs if r.pmid]
    arxivs = [r.arxiv for r in refs if r.arxiv]
    pubmed: dict[str, dict] = {}
    arxiv: dict[str, dict] = {}
    errors: dict[str, str] = {}
    if pmids:
        try:
            pubmed = await src.pubmed_fetch(pmids)
        except ServiceError as exc:
            errors["pubmed"] = str(exc)
    if arxivs:
        try:
            arxiv = await src.arxiv_works(arxivs)
        except ServiceError as exc:
            errors["arxiv"] = str(exc)
    done = 0

    async def one(r: Reference) -> dict:
        nonlocal done
        res = await check_reference(r, src, pubmed, arxiv, errors)
        done += 1
        if progress:
            progress(done, len(refs))
        return res

    return list(await asyncio.gather(*(one(r) for r in refs)))


def summarise(results: list[dict]) -> dict[str, int]:
    counts = {k: 0 for k in ORDER}
    for r in results:
        counts[r["verdict"]] += 1
    return counts


async def check_document(doc: Document, src: Sources, include_uncited: bool = False,
                         progress: Callable[[int, int], None] | None = None) -> dict:
    cited = doc.cited_keys()
    keys = [k for k in cited if k in doc.references]
    if doc.style == "numbered" or include_uncited:
        # Numbered lists are written for this text, so every entry is checked, cited or not.
        keys += [k for k in doc.references if k not in cited]
    results = await check_references([doc.references[k] for k in keys], src, progress)
    for res in results:
        res["cited_in"] = [{"line": c.line, "sentence": c.sentence} for c in doc.citing(res["key"])]
    missing = [{"key": k, "lines": lines} for k, lines in doc.missing().items()]
    uncited = doc.unused()
    counts = summarise(results)
    return {
        "starbuck": __version__,
        "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "document": doc.path, "style": doc.style, "bibliography": doc.bibliography, "warnings": doc.warnings,
        "levels": [1, 2, 3],
        "summary": {"references_checked": len(results), **counts, "citations": len(doc.citations),
                    "cited_keys": len(cited), "missing_entries": len(missing), "uncited_entries": len(uncited),
                    "uncited_sentences": len(doc.uncited_sentences)},
        "references": results, "missing": missing, "uncited": uncited,
        # sentences that state a finding and cite nothing (parse.uncited_sentences); never a Fail or a Check
        "uncited_sentences": doc.uncited_sentences[:MAX_UNCITED],
        "sources": sorted(src.used), "thresholds": THRESHOLDS,
    }


async def check_given(refs: list[Reference], src: Sources) -> dict:
    results = await check_references(refs, src)
    return {"starbuck": __version__,
            "checked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "levels": [1, 2, 3], "summary": {"references_checked": len(results), **summarise(results)},
            "references": results, "sources": sorted(src.used), "thresholds": THRESHOLDS}
