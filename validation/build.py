"""Build the seeded validation set from the hand-picked identifiers in sources.csv.

    uv run python validation/build.py

Every source and every injected error is checked against the live services
first. When a check fails, the script names it and writes nothing. Output:

    references.bib       the bibliography (clean entries and injected errors)
    manuscript.qmd       one citation per entry
    truth.csv            key, error_type, expected_verdict, expected_code
    injections.csv       what was changed in each entry, and how it was confirmed
    evidence/build.json  the service records the build used, with the build time

Needs STARBUCK_EMAIL (or ZOTERO_CONTACT_EMAIL) for polite use of the services.
The address is sent to the services but not written to any output file.
"""

from __future__ import annotations

import csv
import datetime as dt
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

HERE = Path(__file__).parent
EMAIL = os.environ.get("STARBUCK_EMAIL") or os.environ.get("ZOTERO_CONTACT_EMAIL") or ""
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NOTICE_TYPES = {"ErratumIn", "RetractionIn", "ExpressionOfConcernIn", "RetractedandRepublishedIn",
                "CorrectedandRepublishedIn"}
YEAR_TOLERANCE = 1  # Starbuck's tolerance; injected years must be further off than this from every source

# ---------------------------------------------------------------- injection plan
# Each injected entry copies one base reference and changes one thing.
# A base reference is the target of at most one injection.

FABRICATED_DOI = ["pellegrino2005", "tashkin2008", "garg2005", "kung2023"]
DOI_OF_OTHER = [("wanger2005", "koppel2005"), ("celli2004", "rajkomar2018"),
                ("sittig2010", "ortega2014"), ("ayers2023", "juniper1999")]
PMID_OF_OTHER = [("calverley2007", "mandel2016"), ("jones2009", "wong2021"),
                 ("bates2003", "bestall1999"), ("kelly2019", "king2014")]
DOI_PMID_DISAGREE = [("lange2015", "harris2009"), ("dweik2011", "obermeyer2019"),
                     ("johnson2016", "pavord2012"), ("walters2023", "richeldi2014")]
WRONG_YEAR = [("bateman2018", -3), ("kerstjens2012", -3), ("greenhalgh2017", -3), ("adams2022", -3)]
WRONG_FIRST_AUTHOR = [("beasley2019", "Kawamoto"), ("bhakta2023", "Esteva"),
                      ("ash2004", "Lipson"), ("wang2018", "Albert")]
AUTHOR_ORDER = ["hurst2010", "raghu2011", "kawamoto2005", "pinnock2013"]
NO_ID_REAL = ["bowerman2023", "castro2018", "bhattacharyya2023", "topol2019"]
# Invented references, labelled as such. The author names are Melville's harpooners.
NO_ID_INVENTED = [
    ("invented-queequeg", "Queequeg, Q.", "2021", "Thorax",
     "Smartwatch-derived forced expiratory volume compared with laboratory spirometry in 812 adults with COPD"),
    ("invented-tashtego", "Tashtego, T.", "2019", "European Respiratory Journal",
     "Oscillometry reference equations for Portuguese schoolchildren from the Azores lung cohort"),
    ("invented-daggoo", "Daggoo, D.", "2023", "Journal of the American Medical Informatics Association",
     "Federated triage of spirometry referrals by a language model in 14 Portuguese health centres: a stepped-wedge cluster trial"),
    ("invented-fedallah", "Fedallah, F.", "2020", "BMJ Health & Care Informatics",
     "Interoperability of home spirometers with national electronic health records: a mixed-methods evaluation"),
]
DEAD_PAGES = [
    ("deadpage-ers", "European Respiratory Society", "2024", "Spirometry quality statement for primary care",
     "https://www.ersnet.org/starbuck-validation-missing-page"),
    ("deadpage-who", "World Health Organization", "2023", "Global report on chronic respiratory disease surveillance",
     "https://www.who.int/starbuck-validation-missing-page"),
    ("deadpage-invalid", "Starbuck validation", "2024", "Report on a domain that cannot exist (RFC 6761 .invalid)",
     "https://starbuck-validation.invalid/report-2024"),
]

EXPECTED = {  # error_type: (expected_verdict, expected_code)
    "none": ("pass", ""),
    "fabricated_doi": ("fail", "doi_not_found"),
    "doi_of_other_paper": ("fail", "wrong_work"),
    "pmid_of_other_paper": ("fail", "wrong_work"),
    "doi_pmid_disagree": ("fail", "id_conflict"),
    "wrong_year": ("warn", "year_differs"),
    "wrong_first_author": ("warn", "author_differs"),
    "author_order": ("warn", "author_order"),
    "retracted": ("fail", "retracted"),
    "expression_of_concern": ("warn", "concern"),
    "corrected": ("note", "corrected"),
    "preprint_published": ("note", "preprint_published"),
    "no_identifier_real": ("note", "add_identifier"),
    "no_identifier_invented": ("warn", "not_found"),
    "dead_web_page": ("warn", "web_unreachable"),
}

# ---------------------------------------------------------------- services

client = httpx.Client(timeout=40, follow_redirects=True, headers={
    "User-Agent": "starbuck-validation/0.1 (+https://github.com/tiagojct/starbuck" + (f"; mailto:{EMAIL})" if EMAIL else ")")})


def get(url: str, **params) -> httpx.Response:
    if "eutils" in url:
        time.sleep(0.4)
        params = {**params, **({"email": EMAIL} if EMAIL else {})}
    elif "crossref" in url or "openalex" in url:
        params = {**params, **({"mailto": EMAIL} if EMAIL else {})}
    for attempt in range(5):
        try:
            r = client.get(url, params=params)
        except httpx.HTTPError:
            time.sleep(2 + 3 * attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 + 3 * attempt)
            continue
        return r
    sys.exit(f"build: {url} did not answer")


CROSSREF_KEEP = ("DOI", "type", "title", "author", "container-title", "institution", "issued", "published-print",
                 "published-online", "posted", "relation", "updated-by")


def crossref(doi: str) -> dict | None:
    """The Crossref record, cut to the fields the build uses (the evidence file stays small)."""
    r = get(f"https://api.crossref.org/works/{doi}")
    if r.status_code != 200:
        return None
    m = r.json()["message"]
    return {k: m[k] for k in CROSSREF_KEEP if k in m}


def crossref_updates(doi: str) -> list[dict]:
    items = get("https://api.crossref.org/works", filter=f"updates:{doi}", rows=50).json()["message"]["items"]
    return [{"type": (u.get("type") or "").lower(), "source": u.get("source") or "", "notice": it["DOI"].lower()}
            for it in items for u in it.get("update-to") or [] if (u.get("DOI") or "").lower() == doi]


def pubmed_summary(pmid: str) -> dict | None:
    res = get(f"{EUTILS}/esummary.fcgi", db="pubmed", id=pmid, retmode="json").json()["result"]
    rec = res.get(pmid)
    return rec if rec and not rec.get("error") else None


def pubmed_comments(pmid: str) -> list[dict]:
    """Notices PubMed links to the record (CommentsCorrections): errata, retractions, expressions of concern."""
    text = get(f"{EUTILS}/efetch.fcgi", db="pubmed", id=pmid, retmode="xml").text
    root = ET.fromstring(text)
    return [{"type": c.get("RefType"), "source": c.findtext("RefSource") or "", "pmid": c.findtext("PMID") or ""}
            for c in root.iter("CommentsCorrections") if c.get("RefType") in NOTICE_TYPES]


def pubmed_by_doi(doi: str) -> list[str]:
    return get(f"{EUTILS}/esearch.fcgi", db="pubmed", term=f"{doi}[doi]", retmode="json").json()["esearchresult"]["idlist"]


def pubmed_title_hits(title: str) -> list[str]:
    return get(f"{EUTILS}/esearch.fcgi", db="pubmed", term=f'"{title}"[ti]', retmode="json").json()["esearchresult"]["idlist"]


def openalex(doi: str) -> dict | None:
    r = get(f"https://api.openalex.org/works/doi:{doi}")
    return r.json() if r.status_code == 200 else None


def datacite_exists(doi: str) -> bool:
    return get(f"https://api.datacite.org/dois/{doi}").status_code == 200


def handle_code(doi: str) -> int:
    r = get(f"https://doi.org/api/handles/{doi}")
    return r.json().get("responseCode", 0) if r.status_code in (200, 404) else -r.status_code


def page_status(url: str) -> str:
    try:
        with client.stream("GET", url) as r:
            return str(r.status_code)
    except httpx.HTTPError as exc:
        return type(exc).__name__


# ---------------------------------------------------------------- helpers

def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a: str | None, b: str | None) -> float:
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def year_of(m: dict, field: str = "issued") -> str:
    parts = ((m.get(field) or {}).get("date-parts") or [[None]])[0]
    return str(parts[0]) if parts and parts[0] else ""


def clean_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t or "").strip()
    t = re.sub(r"^(RETRACTED( ARTICLE)?|Retracted Article|WITHDRAWN)\s*:\s*", "", t)
    return t.rstrip(".")


def crossref_authors(m: dict) -> list[tuple[str, str]]:
    return [(a.get("family") or a.get("name") or "", a.get("given") or "") for a in m.get("author") or []
            if a.get("family") or a.get("name")]


def bib_escape(s: str) -> str:
    s = s.replace("\\", " ").replace("{", "").replace("}", "")
    s = s.replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#")
    return re.sub(r"\s+", " ", s).strip()


def bib_authors(authors: list[tuple[str, str]], limit: int = 6) -> str:
    names = [f"{{{bib_escape(f)}}}" if not g else f"{bib_escape(f)}, {bib_escape(g)}" for f, g in authors[:limit]]
    return " and ".join(names + (["others"] if len(authors) > limit else []))


def bib_entry(key: str, kind: str, fields: dict[str, str]) -> str:
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@{kind}{{{key},\n{body}\n}}\n"


problems: list[str] = []


def require(ok: bool, message: str) -> None:
    if not ok:
        problems.append(message)


# ---------------------------------------------------------------- sources

def load_sources() -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    with open(HERE / "sources.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        key, group, pmid, doi = row["key"], row["group"], row["pmid"], row["doi"].lower()
        print(f"  source {key}", file=sys.stderr)
        e = {"key": key, "group": group, "pmid": pmid, "doi": doi, "crossref": crossref(doi),
             "updates": crossref_updates(doi), "doi_to_pmid": pubmed_by_doi(doi), "handle": handle_code(doi)}
        oa = openalex(doi)
        e["openalex"] = {k: oa.get(k) for k in ("id", "publication_year", "is_retracted", "type", "ids")} if oa else None
        e["pubmed"] = pubmed_summary(pmid) if pmid else None
        e["pubmed_notices"] = pubmed_comments(pmid) if pmid else []
        evidence[key] = e
        check_source(e)
    return evidence


def check_source(e: dict) -> None:
    key, group, cr, pm = e["key"], e["group"], e["crossref"], e["pubmed"]
    require(cr is not None, f"{key}: DOI {e['doi']} not in Crossref")
    require(e["handle"] == 1, f"{key}: doi.org does not confirm {e['doi']} ({e['handle']})")
    if not cr:
        return
    types = {u["type"] for u in e["updates"]} | {(u.get("type") or "").lower() for u in cr.get("updated-by") or []}
    pm_types = set((pm or {}).get("pubtype") or [])
    pm_notices = {n["type"] for n in e["pubmed_notices"]}
    oa_retracted = bool((e["openalex"] or {}).get("is_retracted"))
    if e["pmid"]:
        require(pm is not None, f"{key}: PMID {e['pmid']} not in PubMed")
        pm_doi = next((a["value"].lower() for a in (pm or {}).get("articleids", []) if a["idtype"] == "doi"), "")
        require(pm_doi == e["doi"], f"{key}: PubMed gives DOI {pm_doi!r}, expected {e['doi']}")
        require(e["doi_to_pmid"] == [e["pmid"]], f"{key}: DOI search in PubMed gives {e['doi_to_pmid']}")
        if pm:
            cr_title = clean_title((cr.get("title") or [""])[0])
            pm_title = clean_title(pm["title"])
            require(sim(pm_title, cr_title) >= 0.9 or norm(pm_title).startswith(norm(cr_title)),
                    f"{key}: PubMed and Crossref titles differ")
            pm_first = (pm.get("sortfirstauthor") or "").split(" ")[0]
            cr_auth = crossref_authors(cr)
            require(bool(cr_auth) and norm(pm_first) == norm(cr_auth[0][0]),
                    f"{key}: first author PubMed {pm_first!r}, Crossref {cr_auth[:1]}")
    if group.startswith("base_"):
        require(not types, f"{key}: base reference has update notices {sorted(types)}")
        require(not pm_notices, f"{key}: PubMed links notices {sorted(pm_notices)}")
        require(not oa_retracted, f"{key}: OpenAlex marks a base reference as retracted")
        require(not pm_types & {"Retracted Publication", "Published Erratum", "Retraction of Publication",
                                "Expression of Concern"}, f"{key}: PubMed types {sorted(pm_types)}")
    elif group == "retracted":
        require("retraction" in types, f"{key}: no retraction notice in Crossref")
        require("Retracted Publication" in pm_types or "RetractionIn" in pm_notices,
                f"{key}: PubMed does not mark it retracted")
        require(oa_retracted, f"{key}: OpenAlex does not mark it retracted")
    elif group == "concern":
        require("expression_of_concern" in types, f"{key}: no expression of concern in Crossref")
        require(not types & {"retraction", "withdrawal", "removal", "partial_retraction"},
                f"{key}: also retracted ({sorted(types)})")
        require(not oa_retracted and "Retracted Publication" not in pm_types and "RetractionIn" not in pm_notices,
                f"{key}: retracted elsewhere")
    elif group == "corrected":
        require(bool(types & {"correction", "erratum", "corrigendum", "addendum"}) or "ErratumIn" in pm_notices,
                f"{key}: no correction notice in Crossref or PubMed")
        require(not types & {"retraction", "withdrawal", "removal", "expression_of_concern"}
                and not pm_notices - {"ErratumIn"}, f"{key}: has stronger notices ({sorted(types | pm_notices)})")
        require(not oa_retracted, f"{key}: OpenAlex marks it retracted")
    elif group == "preprint":
        require(cr.get("type") == "posted-content", f"{key}: Crossref type {cr.get('type')}, not a preprint")
        pubs = [r["id"].lower() for r in (cr.get("relation") or {}).get("is-preprint-of", []) if r.get("id-type") == "doi"]
        require(len(pubs) >= 1, f"{key}: no published version in Crossref")
        for p in pubs:
            pc = crossref(p)
            e.setdefault("published", []).append({"doi": p, "title": (pc or {}).get("title"), "type": (pc or {}).get("type")})
            require(pc is not None and pc.get("type") == "journal-article", f"{key}: published version {p} not found")
            require(pc is not None and sim(cr["title"][0], pc["title"][0]) >= 0.8, f"{key}: published title differs")
    else:
        problems.append(f"{key}: unknown group {group}")


def entry_fields(e: dict) -> dict[str, str]:
    """The correct citation of a source: title and year from PubMed when there is a PMID, else Crossref."""
    cr, pm = e["crossref"], e["pubmed"]
    title = clean_title(pm["title"] if pm else cr["title"][0])
    year = pm["pubdate"][:4] if pm else year_of(cr, "posted") or year_of(cr)
    journal = (cr.get("container-title") or [""])[0] or ((cr.get("institution") or [{}])[0].get("name") or "")
    return {"title": title, "author": bib_authors(crossref_authors(cr)), "journal": journal, "year": year,
            "doi": e["doi"], "pmid": e["pmid"]}


def all_years(e: dict) -> set[int]:
    ys = {year_of(e["crossref"]), year_of(e["crossref"], "published-print"), year_of(e["crossref"], "published-online")}
    if e["pubmed"]:
        ys.add(e["pubmed"]["pubdate"][:4])
    if e["openalex"]:
        ys.add(str(e["openalex"].get("publication_year") or ""))
    return {int(y) for y in ys if y and y.isdigit()}


# ---------------------------------------------------------------- build

def build() -> None:
    today = dt.date.today().isoformat()
    print("Checking sources ...", file=sys.stderr)
    src = load_sources()
    base = [k for k, e in src.items() if e["group"].startswith("base_")]
    entries: list[tuple[str, str, dict]] = []  # key, BibTeX type, fields
    truth: list[tuple[str, str]] = []  # key, error_type
    inj: list[dict] = []
    checks: dict[str, dict] = {}

    def add(key: str, error_type: str, fields: dict, kind: str = "article") -> None:
        require(key not in {k for k, _, _ in entries}, f"duplicate key {key}")
        entries.append((key, kind, fields))
        truth.append((key, error_type))

    def note(key, error_type, base_key, field, original, injected, confirmed):
        inj.append({"key": key, "error_type": error_type, "base": base_key, "field": field,
                    "original": original, "injected": injected, "confirmed": confirmed})

    for k in base:
        add(k, "none", entry_fields(src[k]))
    for group, error_type in (("retracted", "retracted"), ("concern", "expression_of_concern"),
                              ("corrected", "corrected"), ("preprint", "preprint_published")):
        for k, e in src.items():
            if e["group"] == group:
                add(k, error_type, entry_fields(e))
                kinds = sorted({u["type"] for u in e["updates"]})
                pm_kinds = sorted({n["type"] for n in e["pubmed_notices"]})
                note(k, error_type, k, "", "", "", f"Crossref notices {kinds}; PubMed notices {pm_kinds}"
                     if group != "preprint" else f"Crossref is-preprint-of {[p['doi'] for p in e.get('published', [])]}")

    print("Checking injections ...", file=sys.stderr)
    used: set[str] = set()

    def target(k: str) -> dict:
        require(k in src and src[k]["group"].startswith("base_"), f"{k} is not a base reference")
        require(k not in used, f"{k} is the target of two injections")
        used.add(k)
        return dict(entry_fields(src[k]))

    for k in FABRICATED_DOI:
        f = target(k)
        doi = src[k]["doi"]
        m = re.search(r"(\d+)(\D*)$", doi)
        tried, fake = [], ""
        digits = m.group(1)
        # change the last two digits; for journals with dense sequential numbers, the last four
        for width, shift in ((2, 37), (2, 53), (2, 71), (4, 4729), (4, 7351)):
            if len(digits) < width:
                continue
            tail = str((int(digits[-width:]) + shift) % 10 ** width).zfill(width)
            candidate = doi[:m.start(1)] + digits[:-width] + tail + m.group(2)
            r = {"crossref": crossref(candidate) is not None, "datacite": datacite_exists(candidate),
                 "handle": handle_code(candidate), "pubmed": pubmed_by_doi(candidate)}
            tried.append({"doi": candidate, **r})
            if not r["crossref"] and not r["datacite"] and r["handle"] == 100 and not r["pubmed"]:
                fake = candidate
                break
        require(bool(fake), f"{k}: no perturbed DOI found that does not exist")
        checks[f"{k}-fabdoi"] = {"tried": tried}
        f.update(doi=fake, pmid="")
        add(f"{k}-fabdoi", "fabricated_doi", f)
        note(f"{k}-fabdoi", "fabricated_doi", k, "doi", doi, fake,
             "not in Crossref or DataCite; doi.org responseCode 100; no PubMed record")

    for k, donor in DOI_OF_OTHER:
        f = target(k)
        d = src[donor]
        require(sim(f["title"], entry_fields(d)["title"]) < 0.5, f"{k}: donor {donor} title too close")
        f.update(doi=d["doi"], pmid="")
        add(f"{k}-otherdoi", "doi_of_other_paper", f)
        note(f"{k}-otherdoi", "doi_of_other_paper", k, "doi", src[k]["doi"], d["doi"], f"DOI of {donor} (verified source)")

    for k, donor in PMID_OF_OTHER:
        f = target(k)
        d = src[donor]
        require(sim(f["title"], entry_fields(d)["title"]) < 0.5, f"{k}: donor {donor} title too close")
        f.update(doi="", pmid=d["pmid"])
        add(f"{k}-otherpmid", "pmid_of_other_paper", f)
        note(f"{k}-otherpmid", "pmid_of_other_paper", k, "pmid", src[k]["pmid"], d["pmid"], f"PMID of {donor} (verified source)")

    for k, donor in DOI_PMID_DISAGREE:
        f = target(k)
        d = src[donor]
        f.update(pmid=d["pmid"])
        add(f"{k}-idconflict", "doi_pmid_disagree", f)
        note(f"{k}-idconflict", "doi_pmid_disagree", k, "pmid", src[k]["pmid"], d["pmid"],
             f"DOI kept; PMID of {donor} (verified source)")

    for k, shift in WRONG_YEAR:
        f = target(k)
        years = all_years(src[k])
        new = int(f["year"]) + shift
        require(all(abs(new - y) > YEAR_TOLERANCE for y in years), f"{k}: year {new} within tolerance of {years}")
        orig = f["year"]
        f["year"] = str(new)
        add(f"{k}-year", "wrong_year", f)
        note(f"{k}-year", "wrong_year", k, "year", orig, str(new), f"source years {sorted(years)}")

    for k, surname in WRONG_FIRST_AUTHOR:
        f = target(k)
        authors = crossref_authors(src[k]["crossref"])
        pm_authors = [a["name"].split(" ")[0] for a in (src[k]["pubmed"] or {}).get("authors", [])]
        require(norm(surname) not in {norm(a) for a, _ in authors} | {norm(a) for a in pm_authors},
                f"{k}: {surname} is an author of the record")
        f["author"] = bib_authors([(surname, "")] + authors[1:])
        add(f"{k}-author", "wrong_first_author", f)
        note(f"{k}-author", "wrong_first_author", k, "author", authors[0][0], surname,
             f"{surname} not among {len(authors)} Crossref or {len(pm_authors)} PubMed authors")

    for k in AUTHOR_ORDER:
        f = target(k)
        authors = crossref_authors(src[k]["crossref"])
        require(len(authors) >= 2 and norm(authors[0][0]) != norm(authors[1][0]), f"{k}: cannot swap authors")
        f["author"] = bib_authors([authors[1], authors[0]] + authors[2:])
        add(f"{k}-order", "author_order", f)
        note(f"{k}-order", "author_order", k, "author", f"{authors[0][0]}; {authors[1][0]}",
             f"{authors[1][0]}; {authors[0][0]}", "first two Crossref authors swapped")

    for k in NO_ID_REAL:
        f = target(k)
        f.update(doi="", pmid="")
        add(f"{k}-noid", "no_identifier_real", f)
        note(f"{k}-noid", "no_identifier_real", k, "doi, pmid", f"{src[k]['doi']}; {src[k]['pmid']}", "",
             "identifiers removed; the work is a verified source")

    for key, author, year, journal, title in NO_ID_INVENTED:
        items = get("https://api.crossref.org/works", **{"query.bibliographic": f"{title} {author} {year}",
                                                        "rows": 5}).json()["message"]["items"]
        best = max((sim(title, (i.get("title") or [""])[0]) for i in items), default=0.0)
        hits = pubmed_title_hits(title)
        checks[key] = {"crossref_best_title_similarity": best, "pubmed_title_hits": hits}
        require(best < 0.6 and not hits, f"{key}: a similar real work exists (similarity {best}, PubMed {hits})")
        add(key, "no_identifier_invented", {"title": title, "author": author, "journal": journal, "year": year})
        note(key, "no_identifier_invented", "", "all", "", "invented reference",
             f"best Crossref title similarity {best}; PubMed title search {len(hits)} hits")

    for key, author, year, title, url in DEAD_PAGES:
        status = page_status(url)
        checks[key] = {"url": url, "status": status}
        require(not status.isdigit() or int(status) >= 400, f"{key}: {url} answers HTTP {status}")
        add(key, "dead_web_page", {"title": title, "author": f"{{{author}}}", "year": year, "url": url}, kind="online")
        note(key, "dead_web_page", "", "url", "", url, f"GET gives {status}")

    if problems:
        print("Build stopped. Nothing was written.", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------ write
    with open(HERE / "references.bib", "w") as f:
        f.write(f"% Starbuck validation set, built {today} by validation/build.py. Do not edit by hand.\n"
                "% Entries whose key has a suffix carry one injected error; see truth.csv and injections.csv.\n\n")
        for key, kind, fields in entries:
            f.write(bib_entry(key, kind, {k: bib_escape(v) if k not in ("author", "url", "doi") else v
                                          for k, v in fields.items()}) + "\n")
    with open(HERE / "manuscript.qmd", "w") as f:
        f.write('---\ntitle: "Starbuck validation set"\nbibliography: references.bib\n---\n\n'
                "Each line cites one entry of the validation set.\n\n")
        for i, (key, _, _) in enumerate(entries, 1):
            f.write(f"Entry {i} [@{key}].\n")
    with open(HERE / "truth.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "error_type", "expected_verdict", "expected_code"])
        for key, error_type in truth:
            w.writerow([key, error_type, *EXPECTED[error_type]])
    with open(HERE / "injections.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["key", "error_type", "base", "field", "original", "injected", "confirmed"])
        w.writeheader()
        w.writerows(inj)
    (HERE / "evidence").mkdir(exist_ok=True)
    with open(HERE / "evidence" / "build.json", "w") as f:
        json.dump({"built": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "sources": src, "injection_checks": checks}, f, indent=1, ensure_ascii=False)
    counts: dict[str, int] = {}
    for _, t in truth:
        counts[t] = counts.get(t, 0) + 1
    print(f"Wrote {len(entries)} entries: " + ", ".join(f"{k} {v}" for k, v in counts.items()), file=sys.stderr)


if __name__ == "__main__":
    build()
