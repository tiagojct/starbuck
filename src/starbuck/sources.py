"""Clients for the public services Starbuck consults.

Crossref (works, bibliographic search, update notices including Retraction Watch
data), DataCite, the DOI handle system, PubMed (NCBI E-utilities), OpenAlex,
the arXiv API, Open Library and Europe PMC (abstracts and open-access full text,
for level 4). Every client returns a plain record dict:

    source, kind, title, authors [{family, given, name}], year, container,
    doi, pmid, pmcid, arxiv, isbn, url, plus service-specific extras
    (publication_types, comments, is_retracted, published_version, notice_of,
    journal_doi, abstract)

Rules: one shared HTTP client, a small number of parallel requests per host,
pacing where a service asks for it (NCBI, arXiv), retries with back-off on 429
and 5xx, an identifying User-Agent with a contact address when one is given,
and an in-memory cache so one run never asks the same question twice.
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from . import APP_NAME, __version__
from .ids import norm_doi, norm_isbn, plain

CROSSREF = "https://api.crossref.org"
DATACITE = "https://api.datacite.org"
HANDLES = "https://doi.org/api/handles"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX = "https://api.openalex.org"
ARXIV = "https://export.arxiv.org/api/query"
OPENLIBRARY = "https://openlibrary.org"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}

PARALLEL = {"api.crossref.org": 3, "eutils.ncbi.nlm.nih.gov": 1, "export.arxiv.org": 1}


class ServiceError(RuntimeError):
    def __init__(self, service: str, message: str) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service


def _first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


class Sources:
    def __init__(self, email: str | None = None, ncbi_api_key: str | None = None,
                 openalex_api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 30.0, pacing: bool = True, retry_delay: float = 1.5) -> None:
        self.email = email
        self.ncbi_api_key = ncbi_api_key
        self.openalex_api_key = openalex_api_key
        ua = f"{APP_NAME}/{__version__} (+https://github.com/tiagojct/starbuck" + (f"; mailto:{email})" if email else ")")
        self.http = httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=True,
                                      headers={"User-Agent": ua})
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._cache: dict[str, Any] = {}
        self.intervals = {"eutils.ncbi.nlm.nih.gov": 0.11 if ncbi_api_key else 0.34,
                          "export.arxiv.org": 3.0} if pacing else {}
        self.used: set[str] = set()
        self.retry_delay = retry_delay

    async def aclose(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> "Sources":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------ transport

    def _sem(self, host: str) -> asyncio.Semaphore:
        if host not in self._sems:
            self._sems[host] = asyncio.Semaphore(PARALLEL.get(host, 4))
        return self._sems[host]

    async def _pace(self, host: str) -> None:
        interval = self.intervals.get(host)
        if not interval:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def _get(self, service: str, url: str, params: dict | None = None,
                   ok: tuple[int, ...] = (200, 404)) -> httpx.Response:
        host = urlsplit(url).netloc
        self.used.add(service)
        async with self._sem(host):
            last = ""
            for attempt in range(4):
                await self._pace(host)
                try:
                    r = await self.http.get(url, params=params)
                except httpx.HTTPError as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    wait = r.headers.get("Retry-After")
                    last = f"HTTP {r.status_code}"
                    delay = min(float(wait), 30.0) if wait and wait.isdigit() else self.retry_delay * 1.5 * (attempt + 1)
                    await asyncio.sleep(delay if self.retry_delay else 0)
                    continue
                if r.status_code not in ok:
                    raise ServiceError(service, f"HTTP {r.status_code}")
                return r
            raise ServiceError(service, f"not reachable ({last})")

    async def _cached(self, key: str, make):
        if key not in self._cache:
            self._cache[key] = await make()
        return self._cache[key]

    # ------------------------------------------------------------ Crossref

    def _cr(self, extra: dict | None = None) -> dict:
        return {**({"mailto": self.email} if self.email else {}), **(extra or {})}

    async def crossref_work(self, doi: str) -> dict | None:
        async def make():
            r = await self._get("Crossref", f"{CROSSREF}/works/{quote(doi, safe='/:;()')}", self._cr())
            return None if r.status_code == 404 else from_crossref(r.json()["message"])
        return await self._cached(f"cr:{doi}", make)

    async def crossref_search(self, bibliographic: str, rows: int = 5) -> list[dict]:
        async def make():
            r = await self._get("Crossref", f"{CROSSREF}/works",
                                self._cr({"query.bibliographic": bibliographic[:500], "rows": rows}), ok=(200,))
            return [from_crossref(m) for m in r.json()["message"].get("items", [])]
        return await self._cached(f"crs:{bibliographic}:{rows}", make)

    async def crossref_updates(self, doi: str) -> list[dict]:
        """Notices that update this DOI: retraction, correction, expression of concern, withdrawal..."""
        async def make():
            r = await self._get("Crossref", f"{CROSSREF}/works",
                                self._cr({"filter": f"updates:{doi}", "rows": 20}), ok=(200,))
            out = []
            for item in r.json()["message"].get("items", []):
                for u in item.get("update-to") or []:
                    if norm_doi(u.get("DOI")) == doi:
                        parts = (u.get("updated") or {}).get("date-parts") or [[None]]
                        out.append({"type": (u.get("type") or "").lower(), "label": u.get("label") or "",
                                    "source": u.get("source") or "", "notice_doi": norm_doi(item.get("DOI")) or "",
                                    "date": "-".join(f"{p:02d}" if i else str(p)
                                                     for i, p in enumerate(x for x in parts[0] if x))})
            return out
        return await self._cached(f"cru:{doi}", make)

    # ------------------------------------------------------------ DataCite and DOI handles

    async def datacite_work(self, doi: str) -> dict | None:
        async def make():
            r = await self._get("DataCite", f"{DATACITE}/dois/{quote(doi, safe='/:;()')}")
            return None if r.status_code == 404 else from_datacite(r.json().get("data") or {})
        return await self._cached(f"dc:{doi}", make)

    async def doi_registered(self, doi: str) -> bool:
        """Whether the DOI exists at all (any registration agency)."""
        async def make():
            r = await self._get("doi.org", f"{HANDLES}/{quote(doi, safe='/:;()')}")
            if r.status_code == 404:
                return False
            try:
                return r.json().get("responseCode") == 1
            except ValueError:
                return False
        return await self._cached(f"h:{doi}", make)

    # ------------------------------------------------------------ PubMed

    def _ncbi(self, extra: dict) -> dict:
        p = {"tool": APP_NAME, **extra}
        if self.email:
            p["email"] = self.email
        if self.ncbi_api_key:
            p["api_key"] = self.ncbi_api_key
        return p

    async def pubmed_fetch(self, pmids: list[str]) -> dict[str, dict]:
        """PMID -> record, for the PMIDs PubMed knows."""
        todo = [p for p in dict.fromkeys(pmids) if f"pm:{p}" not in self._cache]
        for i in range(0, len(todo), 100):
            chunk = todo[i : i + 100]
            r = await self._get("PubMed", f"{EUTILS}/efetch.fcgi",
                                self._ncbi({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}), ok=(200,))
            found = {rec["pmid"]: rec for rec in parse_pubmed_xml(r.text)}
            for p in chunk:
                self._cache[f"pm:{p}"] = found.get(p)
        return {p: rec for p in pmids if (rec := self._cache.get(f"pm:{p}"))}

    # ------------------------------------------------------------ OpenAlex

    async def openalex_work(self, doi: str | None = None, pmid: str | None = None) -> dict | None:
        path = f"doi:{doi}" if doi else f"pmid:{pmid}" if pmid else None
        if not path:
            return None

        async def make():
            params = {**({"mailto": self.email} if self.email else {}),
                      **({"api_key": self.openalex_api_key} if self.openalex_api_key else {})}
            r = await self._get("OpenAlex", f"{OPENALEX}/works/{path}", params)
            return None if r.status_code == 404 else from_openalex(r.json())
        return await self._cached(f"oa:{path}", make)

    # ------------------------------------------------------------ arXiv

    async def arxiv_works(self, ids: list[str]) -> dict[str, dict]:
        todo = [a for a in dict.fromkeys(ids) if f"ax:{a}" not in self._cache]
        for i in range(0, len(todo), 50):
            chunk = todo[i : i + 50]
            r = await self._get("arXiv", ARXIV, {"id_list": ",".join(chunk), "max_results": len(chunk)}, ok=(200,))
            found = {rec["arxiv"]: rec for rec in parse_arxiv_atom(r.text)}
            for a in chunk:
                self._cache[f"ax:{a}"] = found.get(a)
        return {a: rec for a in ids if (rec := self._cache.get(f"ax:{a}"))}

    # ------------------------------------------------------------ Europe PMC (level 4)

    async def europepmc_work(self, doi: str | None = None, pmid: str | None = None,
                             pmcid: str | None = None) -> dict | None:
        """The Europe PMC record: PMCID, open-access flags and the abstract."""
        # PMCID must not be quoted: Europe PMC finds nothing for PMCID:"PMC123".
        query = (f"PMCID:{pmcid.upper()}" if pmcid else f"EXT_ID:{pmid} AND SRC:MED" if pmid
                 else f'DOI:"{doi}"' if doi else "")
        if not query:
            return None

        async def make():
            params = {"query": query, "resultType": "core", "format": "json", "pageSize": 1,
                      **({"email": self.email} if self.email else {})}
            r = await self._get("Europe PMC", f"{EUROPEPMC}/search", params, ok=(200,))
            hits = (r.json().get("resultList") or {}).get("result") or []
            return from_europepmc(hits[0]) if hits else None
        return await self._cached(f"epmc:{query}", make)

    async def europepmc_fulltext(self, pmcid: str) -> str | None:
        """Open-access full text as JATS XML, or None when Europe PMC has none."""
        async def make():
            r = await self._get("Europe PMC", f"{EUROPEPMC}/{quote(pmcid)}/fullTextXML", ok=(200, 404))
            return None if r.status_code == 404 else r.text
        return await self._cached(f"epmcft:{pmcid}", make)

    # ------------------------------------------------------------ Open Library and web pages

    async def openlibrary_isbn(self, isbn: str) -> dict | None:
        async def make():
            key = f"ISBN:{isbn}"
            r = await self._get("Open Library", f"{OPENLIBRARY}/api/books",
                                {"bibkeys": key, "format": "json", "jscmd": "data"}, ok=(200,))
            data = r.json().get(key)
            return from_openlibrary(data, isbn) if data else None
        return await self._cached(f"ol:{isbn}", make)

    async def url_status(self, url: str) -> int:
        """HTTP status of a web page (after redirects). Only the first bytes are read."""
        async def make():
            host = urlsplit(url).netloc
            self.used.add("web")
            async with self._sem(host):
                try:
                    async with self.http.stream("GET", url) as r:
                        return r.status_code
                except httpx.HTTPError as exc:
                    raise ServiceError("web", f"{type(exc).__name__}") from exc
        return await self._cached(f"url:{url}", make)


# ---------------------------------------------------------------- parsers

def _names(people: list[dict], family: str, given: str, literal: str) -> list[dict]:
    return [{"family": p.get(family) or "", "given": p.get(given) or "", "name": p.get(literal) or ""}
            for p in people or []]


def from_crossref(m: dict) -> dict:
    parts = ((m.get("issued") or m.get("published-print") or m.get("published-online") or {})
             .get("date-parts") or [[None]])[0]
    parts = [p for p in parts if p]
    title = _first(m.get("title"))
    subtitle = _first(m.get("subtitle"))
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title}: {subtitle}"
    kind = m.get("type") or ""
    if kind == "posted-content":
        kind = "preprint" if m.get("subtype") in (None, "preprint") else "posted-content"
    relation = m.get("relation") or {}
    published = next((norm_doi(r.get("id")) for r in relation.get("is-preprint-of") or []
                      if (r.get("id-type") or "doi") == "doi" and norm_doi(r.get("id"))), None)
    authors = _names(m.get("author") or [], "family", "given", "name")
    if not authors:
        authors = _names(m.get("editor") or [], "family", "given", "name")
    return {
        "source": "Crossref", "kind": kind, "title": plain(title), "authors": authors,
        "year": str(parts[0]) if parts else "", "container": plain(_first(m.get("container-title"))),
        "container_abbr": _first(m.get("short-container-title")), "doi": norm_doi(m.get("DOI")) or "",
        "isbn": norm_isbn(_first(m.get("ISBN"))) or "", "url": m.get("URL") or "",
        "published_version": published or "",
        "abstract": plain(m.get("abstract")),
        # A work that itself updates another DOI is a notice (retraction, correction...).
        "notice_of": [{"doi": norm_doi(u.get("DOI")) or "", "type": (u.get("type") or "").lower()}
                      for u in m.get("update-to") or []],
    }


def from_datacite(d: dict) -> dict:
    a = d.get("attributes") or {}
    titles = a.get("titles") or [{}]
    authors = [{"family": c.get("familyName") or "", "given": c.get("givenName") or "",
                "name": c.get("name") or ""} for c in a.get("creators") or []]
    publisher = a.get("publisher")
    publisher = publisher if isinstance(publisher, str) else (publisher or {}).get("name") or ""
    return {
        "source": "DataCite", "kind": ((a.get("types") or {}).get("resourceTypeGeneral") or "").lower(),
        "title": plain(titles[0].get("title") if titles else ""), "authors": authors,
        "year": str(a.get("publicationYear") or ""),
        "container": (a.get("container") or {}).get("title") or publisher,
        "doi": norm_doi(a.get("doi") or d.get("id")) or "", "url": a.get("url") or "",
    }


def _text(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def parse_pubmed_xml(text: str) -> list[dict]:
    root = ET.fromstring(text)
    out = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        a = mc.find("Article") if mc is not None else None
        if a is None:
            continue
        authors = []
        for au in a.findall("AuthorList/Author"):
            if au.findtext("CollectiveName"):
                authors.append({"family": "", "given": "", "name": au.findtext("CollectiveName") or ""})
            elif au.findtext("LastName"):
                authors.append({"family": au.findtext("LastName") or "",
                                "given": au.findtext("ForeName") or au.findtext("Initials") or "", "name": ""})
        pd = a.find("Journal/JournalIssue/PubDate")
        year = (pd.findtext("Year") if pd is not None else "") or ""
        if not year and pd is not None:
            m = re.search(r"\d{4}", pd.findtext("MedlineDate") or "")
            year = m.group(0) if m else ""
        doi = next((e.text or "" for e in a.findall("ELocationID") if e.get("EIdType") == "doi"), "")
        pmcid = ""
        for e in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if e.get("IdType") == "doi" and not doi:
                doi = e.text or ""
            if e.get("IdType") == "pmc":
                pmcid = e.text or ""
        sections = [((t.get("Label") or "").strip(), _text(t)) for t in a.findall("Abstract/AbstractText")]
        abstract = " ".join(f"{label}: {text}" if label else text for label, text in sections if text)
        comments = [{"type": c.get("RefType") or "", "source": c.findtext("RefSource") or "",
                     "pmid": c.findtext("PMID") or ""}
                    for c in mc.findall("CommentsCorrectionsList/CommentsCorrections")]
        out.append({
            "source": "PubMed", "kind": "journal-article", "title": _text(a.find("ArticleTitle")).rstrip("."),
            "authors": authors, "year": year, "container": a.findtext("Journal/Title") or "",
            "container_abbr": a.findtext("Journal/ISOAbbreviation") or "", "doi": norm_doi(doi) or "",
            "pmid": mc.findtext("PMID") or "", "pmcid": pmcid,
            "publication_types": [pt.text or "" for pt in a.findall("PublicationTypeList/PublicationType")],
            "comments": comments, "abstract": abstract,
        })
    return out


def from_openalex(w: dict) -> dict:
    src = ((w.get("primary_location") or {}).get("source") or {})
    return {
        "source": "OpenAlex", "kind": w.get("type") or "", "title": plain(w.get("display_name") or w.get("title")),
        "authors": [{"family": "", "given": "", "name": (au.get("author") or {}).get("display_name") or ""}
                    for au in w.get("authorships") or []],
        "year": str(w.get("publication_year") or ""), "container": src.get("display_name") or "",
        "doi": norm_doi(w.get("doi")) or "",
        "pmid": ((w.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1],
        "is_retracted": bool(w.get("is_retracted")),
        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1],
        "abstract": openalex_abstract(w.get("abstract_inverted_index")),
    }


def openalex_abstract(index: dict | None) -> str:
    """OpenAlex keeps abstracts as an inverted index (word -> positions)."""
    if not index:
        return ""
    words: dict[int, str] = {}
    for word, positions in index.items():
        for p in positions:
            words[p] = word
    return " ".join(words[p] for p in sorted(words))


def from_europepmc(r: dict) -> dict:
    ft = (r.get("fullTextIdList") or {}).get("fullTextId") or []
    return {
        "source": "Europe PMC", "title": plain(r.get("title")), "doi": norm_doi(r.get("doi")) or "",
        "pmid": r.get("pmid") or "", "pmcid": r.get("pmcid") or "",
        "open_access": r.get("isOpenAccess") == "Y" and r.get("inEPMC") == "Y",
        "fulltext_ids": list(ft), "abstract": plain(r.get("abstractText")),
    }


def parse_arxiv_atom(text: str) -> list[dict]:
    root = ET.fromstring(text)
    out = []
    for e in root.findall("a:entry", ATOM):
        ident = e.findtext("a:id", "", ATOM)
        if "/api/errors" in ident or not ident:
            continue
        m = re.search(r"arxiv\.org/abs/(.+?)(?:v\d+)?$", ident)
        if not m:
            continue
        names = [n.findtext("a:name", "", ATOM) for n in e.findall("a:author", ATOM)]
        out.append({
            "source": "arXiv", "kind": "preprint", "title": re.sub(r"\s+", " ", e.findtext("a:title", "", ATOM)).strip(),
            "authors": [{"family": "", "given": "", "name": n} for n in names if n],
            "year": (e.findtext("a:published", "", ATOM) or "")[:4], "container": "arXiv",
            "arxiv": m.group(1), "journal_doi": norm_doi(e.findtext("x:doi", "", ATOM)) or "",
            "journal_ref": e.findtext("x:journal_ref", "", ATOM) or "",
        })
    return out


def from_openlibrary(d: dict, isbn: str) -> dict:
    authors = [{"family": "", "given": "", "name": a.get("name") or ""} for a in d.get("authors") or []]
    title = d.get("title") or ""
    if d.get("subtitle"):
        title = f"{title}: {d['subtitle']}"
    m = re.search(r"\d{4}", d.get("publish_date") or "")
    return {"source": "Open Library", "kind": "book", "title": title, "authors": authors,
            "year": m.group(0) if m else "",
            "container": ", ".join(p.get("name", "") for p in d.get("publishers") or []),
            "isbn": isbn, "url": d.get("url") or ""}


def family_of(person: dict) -> str:
    """Family name of a record author; for a display name, its last word."""
    if person.get("family"):
        return person["family"]
    name = (person.get("name") or "").strip()
    if "," in name:
        return name.split(",", 1)[0].strip()
    return name.split()[-1] if name.split() else ""
