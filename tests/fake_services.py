"""Canned answers for Crossref, DataCite, doi.org, PubMed, OpenAlex, arXiv, Open Library, Europe PMC,
web pages and a level 4 judge (an OpenAI-compatible endpoint at judge.test).

The records are modelled on real ones but trimmed; tests never reach the network.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import json

import httpx

QUANJER = {
    "DOI": "10.1183/09031936.00080312", "type": "journal-article",
    "title": ["Multi-ethnic reference values for spirometry for the 3–95-yr age range: "
              "the global lung function 2012 equations"],
    "author": [{"given": "Philip H.", "family": "Quanjer"}, {"given": "Sanja", "family": "Stanojevic"},
               {"given": "Tim J.", "family": "Cole"}],
    "issued": {"date-parts": [[2012, 12]]}, "container-title": ["European Respiratory Journal"],
}
MILLER = {
    "DOI": "10.1183/09031936.05.00034805", "type": "journal-article", "title": ["Standardisation of spirometry"],
    "author": [{"given": "M.R.", "family": "Miller"}, {"given": "J.", "family": "Hankinson"}],
    "issued": {"date-parts": [[2005, 8]]}, "container-title": ["European Respiratory Journal"],
}
WAKEFIELD = {
    "DOI": "10.1016/s0140-6736(97)11096-0", "type": "journal-article",
    "title": ["Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children"],
    "author": [{"given": "AJ", "family": "Wakefield"}], "issued": {"date-parts": [[1998, 2]]},
    "container-title": ["The Lancet"],
}
CROSSREF = {
    QUANJER["DOI"]: QUANJER, MILLER["DOI"]: MILLER, WAKEFIELD["DOI"]: WAKEFIELD,
    "10.1000/concern": {"DOI": "10.1000/concern", "type": "journal-article", "title": ["A worrying trial of inhalers"],
                        "author": [{"family": "Doubt", "given": "A"}], "issued": {"date-parts": [[2021]]}},
    "10.1000/corrected": {"DOI": "10.1000/corrected", "type": "journal-article",
                          "title": ["FeNO cut-offs in adults with asthma"],
                          "author": [{"family": "Silva", "given": "Ana"}], "issued": {"date-parts": [[2019]]}},
    "10.1101/2020.01.01.000001": {"DOI": "10.1101/2020.01.01.000001", "type": "posted-content", "subtype": "preprint",
                                  "title": ["Machine learning for spirometry interpretation"],
                                  "author": [{"family": "Topalovic", "given": "Marko"}],
                                  "issued": {"date-parts": [[2020, 1]]},
                                  "relation": {"is-preprint-of": [{"id-type": "doi", "id": "10.1000/published"}]}},
    "10.1000/notice": {"DOI": "10.1000/notice", "type": "journal-article", "title": ["Retraction notice"],
                       "author": [], "issued": {"date-parts": [[2022]]},
                       "update-to": [{"DOI": "10.1000/other", "type": "retraction"}]},
}
UPDATES = {
    WAKEFIELD["DOI"]: [{"DOI": "10.1016/s0140-6736(04)15715-2", "update-to": [
        {"DOI": WAKEFIELD["DOI"], "type": "correction", "source": "retraction-watch", "label": "Correction",
         "updated": {"date-parts": [[2004, 3, 6]]}}]},
                       {"DOI": "10.1016/s0140-6736(10)60175-4", "update-to": [
        {"DOI": WAKEFIELD["DOI"], "type": "retraction", "source": "retraction-watch", "label": "Retraction",
         "updated": {"date-parts": [[2010, 2, 6]]}}]}],
    "10.1000/concern": [{"DOI": "10.1000/eoc", "update-to": [
        {"DOI": "10.1000/concern", "type": "expression_of_concern", "source": "publisher",
         "updated": {"date-parts": [[2023, 5]]}}]}],
    "10.1000/corrected": [{"DOI": "10.1000/erratum", "update-to": [
        {"DOI": "10.1000/corrected", "type": "correction", "source": "publisher",
         "updated": {"date-parts": [[2020, 6]]}}]}],
}
DATACITE = {
    "10.5281/zenodo.123": {"id": "10.5281/zenodo.123", "attributes": {
        "doi": "10.5281/zenodo.123", "titles": [{"title": "Lung function dataset from northern Portugal"}],
        "creators": [{"name": "Jacinto, Tiago", "familyName": "Jacinto", "givenName": "Tiago"}],
        "publicationYear": 2024, "types": {"resourceTypeGeneral": "Dataset"}, "publisher": "Zenodo"}},
}
HANDLES = {"10.9999/elsewhere"}
PUBMED = {
    "22743675": {"title": QUANJER["title"][0] + ".", "doi": QUANJER["DOI"], "authors": [("Quanjer", "Philip H")],
                 "journal": "The European respiratory journal", "year": "2012", "types": ["Journal Article"],
                 "comments": []},
    "16055882": {"title": "Standardisation of spirometry.", "doi": MILLER["DOI"], "authors": [("Miller", "M R")],
                 "journal": "The European respiratory journal", "year": "2005", "types": ["Journal Article"],
                 "comments": [], "abstract": [
                     ("BACKGROUND", "Synthetic test text, not the published abstract. Spirometry needs standard "
                                    "procedures so that results from different laboratories can be compared."),
                     ("RESULTS", "The standards cover equipment, quality control, test procedures and the "
                                 "acceptability and repeatability of forced expiratory manoeuvres.")]},
    "9500320": {"title": WAKEFIELD["title"][0] + ".", "doi": WAKEFIELD["DOI"], "authors": [("Wakefield", "A J")],
                "journal": "Lancet", "year": "1998", "types": ["Journal Article", "Retracted Publication"],
                "comments": [("RetractionIn", "Lancet. 2010 Feb 6;375(9713):445", "20137807")]},
}
OPENALEX_RETRACTED = {WAKEFIELD["DOI"]}
ARXIV = {
    "1706.03762": {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani", "Noam Shazeer"],
                   "published": "2017-06-12T17:57:34Z", "doi": ""},
    "2001.00001": {"title": "Deep learning for lung sounds", "authors": ["Ana Silva"],
                   "published": "2020-01-01T00:00:00Z", "doi": "10.1000/published-lungsounds"},
}
OPENLIBRARY = {"9780781772068": {"title": "Respiratory physiology", "subtitle": "the essentials",
                                 "authors": [{"name": "John B. West"}], "publish_date": "2008",
                                 "publishers": [{"name": "Lippincott Williams & Wilkins"}]}}
# Europe PMC: Quanjer has open-access full text (synthetic JATS below); Miller only an abstract.
EUROPEPMC = {
    QUANJER["DOI"]: {"id": "22743675", "source": "MED", "pmid": "22743675", "pmcid": "PMC0000001",
                     "doi": QUANJER["DOI"], "isOpenAccess": "Y", "inEPMC": "Y",
                     "fullTextIdList": {"fullTextId": ["PMC0000001"]}, "abstractText": "Short abstract."},
    MILLER["DOI"]: {"id": "16055882", "source": "MED", "pmid": "16055882", "doi": MILLER["DOI"],
                    "isOpenAccess": "N", "inEPMC": "N", "abstractText": "Synthetic Europe PMC abstract."},
}
FULLTEXT = {"PMC0000001": """<?xml version="1.0"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.4//EN" "x.dtd">
<article><front><article-meta><abstract><p>Synthetic test text. Reference equations for spirometry
were derived for several ethnic groups.</p></abstract></article-meta></front><body>
<sec><title>Introduction</title><p>Interpretation of spirometry needs reference values that cover the whole
age range.</p></sec>
<sec><title>Results</title><p>The equations were derived from 74,187 records of healthy non-smokers from
26 countries, aged 3 to 95 years.</p><p>Equations for North East Asians and South East Asians fitted the data
less well than those for Caucasians.</p></sec>
<sec><title>Discussion</title><p>The equations do not cover people of mixed ethnic origin directly.</p></sec>
</body></article>"""}
WEB = {"https://ginasthma.org/reports/": 200, "https://example.org/gone": 404}


def search_results(query: str) -> list[dict]:
    q = query.lower()
    if "standardisation" in q:
        return [MILLER, QUANJER]
    if "spirometry" in q and "multi-ethnic" in q:
        return [QUANJER]
    if "decision support" in q:
        return [{"DOI": "10.1000/near", "type": "journal-article",
                 "title": ["Decision support systems for lung function interpretation in primary care"],
                 "author": [{"family": "Fonseca", "given": "J"}], "issued": {"date-parts": [[2019]]}}]
    return [{"DOI": "10.1000/unrelated", "type": "journal-article", "title": ["Something else entirely"],
             "author": [{"family": "Nobody"}], "issued": {"date-parts": [[2001]]}}]


def pubmed_xml(ids: list[str]) -> str:
    arts = []
    for pmid in ids:
        r = PUBMED.get(pmid)
        if not r:
            continue
        authors = "".join(f"<Author><LastName>{f}</LastName><ForeName>{g}</ForeName></Author>" for f, g in r["authors"])
        types = "".join(f"<PublicationType>{t}</PublicationType>" for t in r["types"])
        abstract = "".join(f'<AbstractText Label="{label}">{text}</AbstractText>'
                           for label, text in r.get("abstract", []))
        abstract = f"<Abstract>{abstract}</Abstract>" if abstract else ""
        comments = "".join(f'<CommentsCorrections RefType="{t}"><RefSource>{s}</RefSource><PMID>{p}</PMID>'
                           f"</CommentsCorrections>" for t, s, p in r["comments"])
        arts.append(f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
<Journal><JournalIssue><PubDate><Year>{r['year']}</Year></PubDate></JournalIssue><Title>{r['journal']}</Title></Journal>
<ArticleTitle>{r['title']}</ArticleTitle><ELocationID EIdType="doi">{r['doi']}</ELocationID>{abstract}
<AuthorList>{authors}</AuthorList><PublicationTypeList>{types}</PublicationTypeList></Article>
<CommentsCorrectionsList>{comments}</CommentsCorrectionsList></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">{pmid}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>""")
    return f"<PubmedArticleSet>{''.join(arts)}</PubmedArticleSet>"


def arxiv_atom(ids: list[str]) -> str:
    entries = []
    for a in ids:
        r = ARXIV.get(a)
        if not r:
            continue
        authors = "".join(f"<author><name>{n}</name></author>" for n in r["authors"])
        doi = f"<arxiv:doi>{r['doi']}</arxiv:doi>" if r["doi"] else ""
        entries.append(f"<entry><id>http://arxiv.org/abs/{a}v1</id><published>{r['published']}</published>"
                       f"<title>{r['title']}</title>{authors}{doi}</entry>")
    return ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">'
            + "".join(entries) + "</feed>")


class FakeServices:
    def __init__(self, down: set[str] | None = None) -> None:
        self.requests: list[str] = []
        self.down = down or set()
        # Level 4 judge: the first entry whose text appears in the prompt gives the answer.
        self.judge_answers: list[tuple[str, dict]] = []
        self.judge_prompts: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        parts = urlsplit(url)
        host, path = parts.netloc, unquote(parts.path)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if host in self.down:
            raise httpx.ConnectError("down", request=request)

        def js(obj, status=200):
            return httpx.Response(status, json=obj)

        if host == "api.crossref.org":
            if path.startswith("/works/"):
                doi = path[len("/works/"):].lower()
                return js({"message": CROSSREF[doi]}) if doi in CROSSREF else js({"message": "not found"}, 404)
            if "query.bibliographic" in q:
                return js({"message": {"items": search_results(q["query.bibliographic"])}})
            if q.get("filter", "").startswith("updates:"):
                return js({"message": {"items": UPDATES.get(q["filter"][len("updates:"):], [])}})
        if host == "api.datacite.org":
            doi = path[len("/dois/"):].lower()
            return js({"data": DATACITE[doi]}) if doi in DATACITE else js({"errors": []}, 404)
        if host == "doi.org":
            doi = path[len("/api/handles/"):].lower()
            return js({"responseCode": 1}) if doi in HANDLES else js({"responseCode": 100}, 404)
        if host == "eutils.ncbi.nlm.nih.gov" and path.endswith("efetch.fcgi"):
            return httpx.Response(200, text=pubmed_xml(q.get("id", "").split(",")))
        if host == "api.openalex.org" and path.startswith("/works/doi:"):
            doi = path[len("/works/doi:"):].lower()
            if doi in CROSSREF:
                return js({"id": "https://openalex.org/W1", "doi": f"https://doi.org/{doi}",
                           "display_name": "x", "is_retracted": doi in OPENALEX_RETRACTED})
            return js({"error": "not found"}, 404)
        if host == "api.openalex.org":
            return js({"error": "not found"}, 404)
        if host == "export.arxiv.org":
            return httpx.Response(200, text=arxiv_atom(q.get("id_list", "").split(",")))
        if host == "openlibrary.org":
            key = q.get("bibkeys", "")
            isbn = key.split(":", 1)[-1]
            return js({key: OPENLIBRARY[isbn]} if isbn in OPENLIBRARY else {})
        if host == "www.ebi.ac.uk" and path.endswith("/search"):
            query = q.get("query", "")
            hit = next((r for doi, r in EUROPEPMC.items() if doi in query or r["pmid"] in query), None)
            return js({"hitCount": int(bool(hit)), "resultList": {"result": [hit] if hit else []}})
        if host == "www.ebi.ac.uk" and path.endswith("/fullTextXML"):
            pmcid = path.split("/")[-2]
            return httpx.Response(200, text=FULLTEXT[pmcid]) if pmcid in FULLTEXT else httpx.Response(404)
        if host == "judge.test":
            prompt = json.loads(request.content)["messages"][-1]["content"]
            self.judge_prompts.append(prompt)
            answer = next((a for text, a in self.judge_answers if text in prompt),
                          {"verdict": "cannot_assess", "quote": "", "reason": "No canned answer."})
            return js({"choices": [{"message": {"content": "<think>x</think>" + json.dumps(answer)}}]})
        if url in WEB:
            return httpx.Response(WEB[url], text="page")
        return httpx.Response(404, text="unknown")
