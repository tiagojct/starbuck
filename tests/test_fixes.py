"""Defects found in the review of 0.2.0: each test failed before its fix."""

import httpx

from fake_services import FakeServices
from starbuck import bibtex
from starbuck.check import check_references, compare
from starbuck.claims import judge
from starbuck.ids import find_ids, name_in_text, norm_doi
from starbuck.models import Reference
from starbuck.sources import Sources, parse_pubmed_xml

SICI = "10.1002/(SICI)1097-0258(19980815/30)17:15/16<1661::AID-SIM968>3.0.CO;2-2"
TITLE = "Effects of inhaled corticosteroids on asthma control in adults"


def test_sici_doi_keeps_its_angle_brackets():
    assert norm_doi(SICI) == SICI.lower()
    assert norm_doi("10.1175/1520-0442(1997)010<1004:AEORMS>2.0.CO;2") == "10.1175/1520-0442(1997)010<1004:aeorms>2.0.co;2"
    assert find_ids(f"Smith J. A title. Stat Med 1998. doi:{SICI}.")["doi"] == SICI.lower()


def test_other_angle_brackets_still_end_a_doi():
    assert norm_doi("<https://doi.org/10.1000/abc>") == "10.1000/abc"
    assert norm_doi("10.1000/abc<br>") == "10.1000/abc"
    assert norm_doi("10.1000/abc</a>") == "10.1000/abc"


def test_first_author_of_a_numbered_entry():
    for family in ("An", "To", "Smith-Jones", "van der Berg", "O'Brien", "Li"):
        r = Reference(key="1", kind="numbered", raw=f"{family} J, Doe K. {TITLE}. Lancet 2019;1:1-2.")
        rec = {"title": TITLE, "authors": [{"family": family, "given": "J"}], "year": "2019"}
        assert compare(r, rec)["fields"]["first_author"]["ok"], family
    assert name_in_text("van der Berg", "Berg J van der, Doe K. A title.")
    assert not name_in_text("Quanjer", "Miller MR, Hankinson J. Standardisation of spirometry.")


def test_numbered_entry_with_years_in_the_title():
    r = Reference(key="1", kind="numbered", raw="Vos T, Lim S. Global burden of 369 diseases and injuries in 204 "
                  "countries and territories, 1990-2019: a systematic analysis. Lancet 2020;396:1204-22.")
    rec = {"title": "Global burden of 369 diseases and injuries in 204 countries and territories, 1990-2019: a "
           "systematic analysis", "authors": [{"family": "Vos", "given": "T"}], "year": "2020"}
    cmp = compare(r, rec)
    assert cmp["fields"]["year"] == {"cited": "2020", "found": "2020", "ok": True}
    assert cmp["status"] == "ok"
    wrong = compare(r, {**rec, "year": "2012"})  # no year of the entry is near 2012
    assert not wrong["fields"]["year"]["ok"]


def test_title_in_the_original_language_matches():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2015</Year></PubDate></JournalIssue><Title>Acta Med Port</Title></Journal>
<ArticleTitle>[Reference values for spirometry in Portuguese adults].</ArticleTitle>
<VernacularTitle>Valores de referência da espirometria em adultos portugueses.</VernacularTitle>
<AuthorList><Author><LastName>Silva</LastName><ForeName>Ana</ForeName></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    rec = parse_pubmed_xml(xml)[0]
    assert rec["alt_titles"] == ["Valores de referência da espirometria em adultos portugueses"]
    r = Reference(key="s", kind="bibtex", title="Valores de referência da espirometria em adultos portugueses",
                  authors=["Silva"], year="2015", pmid="1")
    assert compare(r, rec)["status"] == "ok"
    other = Reference(key="s", kind="bibtex", title="Standardisation of spirometry", authors=["Silva"], year="2015")
    assert compare(other, rec)["status"] == "mismatch"


def test_bibtex_bare_words_and_entries_on_one_line():
    entries, problems = bibtex.parse("@article{a, title={X}, journal=marcel, month=mar, year=2020}"
                                     "@article{b, title={Y}, month=september}")
    assert not problems
    assert [e["key"] for e in entries] == ["a", "b"]
    assert entries[0]["fields"]["journal"] == "marcel" and entries[0]["fields"]["month"] == "3"
    assert entries[1]["fields"]["month"] == "9"


async def test_unreadable_answer_is_a_service_error_not_a_crash():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(200, text="<html>maintenance</html>")
        return FakeServices().handle(request)

    async with Sources(transport=httpx.MockTransport(handle), pacing=False, retry_delay=0) as src:
        res = (await check_references([Reference(key="q", kind="csl", title="X y z w", doi="10.1183/09031936.00080312")],
                                      src))[0]
    assert res["verdict"] == "error"
    assert "unreadable answer" in res["findings"][0]["message"]


async def test_same_doi_under_two_keys_is_asked_once(fake, src):
    refs = [Reference(key=k, kind="csl", doi="10.1183/09031936.00080312") for k in ("a", "b")]
    await check_references(refs, src)
    works = [u for u in fake.requests if "/works/10.1183" in u]
    assert len(works) == 1


async def test_web_page_that_refuses_programs_is_a_note():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "blocked.example":
            return httpx.Response(403, text="Just a moment...")
        return FakeServices().handle(request)

    async with Sources(transport=httpx.MockTransport(handle), pacing=False, retry_delay=0) as src:
        r = Reference(key="1", kind="numbered", raw="Agency. https://blocked.example/report", url="https://blocked.example/report")
        res = (await check_references([r], src))[0]
    assert res["verdict"] == "note"
    assert res["exists"]["status"] == "web_page_blocked"
    assert [f["code"] for f in res["findings"]] == ["web_blocked"]


async def test_judge_that_refuses_temperature_is_asked_again():
    bodies = []

    def handle(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0"}})
        answer = {"verdict": "cannot_assess", "quote": "", "reason": "x"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    claim = {"id": "c001", "key": "k", "line": 1, "sentence": "S.", "basis": "abstract", "source": "PubMed",
             "status": "ready", "passages": [{"section": "", "text": "Some passage."}]}
    out = await judge([claim], {"url": "https://judge.test/v1/chat/completions", "model": "m", "key": ""},
                      httpx.MockTransport(handle))
    assert out["c001"]["reason"] == "x"
    assert "temperature" in bodies[0] and "temperature" not in bodies[1]


async def test_openalex_only_retraction_is_a_check():
    import fake_services as fs
    fs.OPENALEX_RETRACTED.add("10.1000/corrected")
    try:
        async with Sources(transport=FakeServices().transport(), pacing=False, retry_delay=0) as src:
            r = Reference(key="c", kind="csl", title="FeNO cut-offs in adults with asthma", authors=["Silva"],
                          year="2019", doi="10.1000/corrected")
            res = (await check_references([r], src))[0]
    finally:
        fs.OPENALEX_RETRACTED.discard("10.1000/corrected")
    assert res["verdict"] == "warn"
    assert "retraction_unconfirmed" in [f["code"] for f in res["findings"]]
    assert "retracted" not in [f["code"] for f in res["findings"]]


async def test_doi_and_pmid_with_the_same_title_is_a_check(src):
    # Miller's PMID; a second DOI of the same work in Crossref
    import fake_services as fs
    fs.CROSSREF["10.1000/miller-copy"] = {**fs.MILLER, "DOI": "10.1000/miller-copy"}
    try:
        r = Reference(key="m", kind="csl", title="Standardisation of spirometry", authors=["Miller"], year="2005",
                      doi="10.1000/miller-copy", pmid="16055882")
        res = (await check_references([r], src))[0]
    finally:
        del fs.CROSSREF["10.1000/miller-copy"]
    assert res["verdict"] == "warn"
    assert [f["code"] for f in res["findings"]] == ["id_doi_differs"]


def test_crossref_concurrency_depends_on_the_contact_address():
    assert Sources(email=None)._sem("api.crossref.org")._value == 1
    assert Sources(email="a@example.org")._sem("api.crossref.org")._value == 3


# ---------------------------------------------------------------- 0.3.0: wider search, PMCID, dates

async def test_pubmed_only_record_is_found_by_search(src):
    r = Reference(key="1", kind="numbered", raw="Fonseca J, Lima R. Home spirometry telemonitoring after lung "
                  "transplantation: a cohort study. Respir Med. 2018;140:1-7.")
    r.year = "2018"
    res = (await check_references([r], src))[0]
    assert res["exists"]["status"] == "found_by_search"
    assert res["exists"]["via"] == ["PubMed search"]
    assert res["suggestion"] == "pmid:30000001"
    assert res["verdict"] == "note"
    assert "PubMed" in res["status"]["checked_with"]


async def test_dataset_is_found_in_datacite(src):
    r = Reference(key="d", kind="csl", type="dataset", title="Lung function dataset from northern Portugal",
                  authors=["Jacinto"], year="2024")
    res = (await check_references([r], src))[0]
    assert res["exists"]["via"] == ["DataCite search"]
    assert res["suggestion"] == "doi:10.5281/zenodo.123"


async def test_book_is_found_in_open_library(src):
    r = Reference(key="b", kind="bibtex", type="book", title="Respiratory physiology: the essentials",
                  authors=["West"], year="2008")
    res = (await check_references([r], src))[0]
    assert res["exists"]["via"] == ["Open Library search"]
    assert res["suggestion"] == "isbn:9780781772068"


async def test_dead_link_offers_an_archived_copy(src):
    r = Reference(key="1", kind="numbered", raw="Gone page. https://example.org/gone", url="https://example.org/gone")
    res = (await check_references([r], src))[0]
    assert res["verdict"] == "warn"
    assert "web.archive.org/web/20190312101010" in res["findings"][0]["message"]
    assert res["suggestion"].startswith("https://web.archive.org/")


async def test_pmcid_only_is_resolved_through_europe_pmc(src):
    import fake_services as fs
    fs.EUROPEPMC["PMC0000001"] = fs.EUROPEPMC[fs.QUANJER["DOI"]]
    try:
        r = Reference(key="q", kind="csl", title=fs.QUANJER["title"][0], authors=["Quanjer"], year="2012",
                      pmcid="PMC0000001")
        res = (await check_references([r], src))[0]
    finally:
        del fs.EUROPEPMC["PMC0000001"]
    assert res["exists"]["status"] == "found"
    assert "pmcid_resolved" in [f["code"] for f in res["findings"]]
    assert "pmid" not in res["reference"]  # the reference is reported as written


async def test_retraction_date_against_the_manuscript_date(src):
    r = Reference(key="w", kind="csl", title="Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and "
                  "pervasive developmental disorder in children", authors=["Wakefield"], year="1998",
                  doi="10.1016/s0140-6736(97)11096-0")
    before = (await check_references([r], src, as_of="2015-03-01"))[0]
    after = (await check_references([r], src, as_of="2005"))[0]
    msg = lambda res: next(f["message"] for f in res["findings"] if f["code"] == "retracted")
    assert "came before the manuscript date (2015-03-01)" in msg(before)
    assert "came after the manuscript date (2005)" in msg(after)


def test_manuscript_date_from_yaml(tmp_path):
    from starbuck.parse import read_manuscript
    f = tmp_path / "p.md"
    f.write_text("---\ndate: 2024-05-02\n---\nText [@a].\n")
    assert read_manuscript(f).date == "2024-05-02"
    f.write_text("---\ndate: today\n---\nText [@a].\n")
    assert read_manuscript(f).date == ""


async def test_disk_cache_answers_a_second_run(tmp_path):
    from starbuck.cache import DiskCache
    fake = FakeServices()
    r = Reference(key="q", kind="csl", doi="10.1183/09031936.00080312")
    for _ in range(2):
        async with Sources(transport=fake.transport(), pacing=False, retry_delay=0, cache=DiskCache(tmp_path)) as s:
            await check_references([r], s)
    assert sum("/works/10.1183" in u for u in fake.requests) == 1
