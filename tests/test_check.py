from fake_services import FakeServices
from starbuck.check import check_document, check_references
from starbuck.models import Citation, Document, Reference
from starbuck.sources import Sources

QUANJER_TITLE = ("Multi-ethnic reference values for spirometry for the 3-95-yr age range: "
                 "the global lung function 2012 equations")


def ref(key, **kw):
    kw.setdefault("kind", "csl")
    return Reference(key=key, **kw)


async def one(src, r):
    return (await check_references([r], src))[0]


def codes(res):
    return [f["code"] for f in res["findings"]]


async def test_correct_doi_passes(src):
    res = await one(src, ref("q", title=QUANJER_TITLE, authors=["Quanjer"], year="2012",
                            doi="10.1183/09031936.00080312"))
    assert res["verdict"] == "pass", res["findings"]
    assert res["exists"] == {"status": "found", "via": ["Crossref"]}
    assert res["match"]["status"] == "ok"
    assert res["status"]["status"] == "ok"
    assert set(res["status"]["checked_with"]) == {"Crossref", "OpenAlex"}


async def test_fabricated_doi_fails(src):
    res = await one(src, ref("f", title="Spirometry in astronauts", authors=["Nobody"], year="2020",
                            doi="10.1183/09031936.99999999"))
    assert res["verdict"] == "fail"
    assert codes(res) == ["doi_not_found"]
    assert res["exists"]["status"] == "not_found"


async def test_real_doi_for_another_paper_fails(src):
    # Quanjer's title with Miller's DOI: the DOI exists but belongs to a different work
    res = await one(src, ref("w", title=QUANJER_TITLE, authors=["Quanjer"], year="2012",
                            doi="10.1183/09031936.05.00034805"))
    assert res["verdict"] == "fail"
    assert "wrong_work" in codes(res)
    assert "Standardisation of spirometry" in res["findings"][0]["message"]


async def test_retracted_fails_with_several_sources(src):
    res = await one(src, ref("r", title="Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive "
                            "developmental disorder in children", authors=["Wakefield"], year="1998",
                            doi="10.1016/S0140-6736(97)11096-0".lower(), pmid="9500320"))
    assert res["verdict"] == "fail"
    assert res["status"]["status"] == "retracted"
    vias = {n["via"] for n in res["status"]["notices"]}
    assert "Retraction Watch" in vias and "PubMed" in vias
    assert codes(res).count("retracted") >= 1
    # the 2004 correction stays in the notices but adds no finding next to the retraction
    assert "correction" in {n["type"] for n in res["status"]["notices"]}
    assert "corrected" not in codes(res)


async def test_concern_corrected_notice(src):
    concern = await one(src, ref("c", title="A worrying trial of inhalers", authors=["Doubt"], year="2021",
                                doi="10.1000/concern"))
    assert concern["verdict"] == "warn" and concern["status"]["status"] == "concern"
    corrected = await one(src, ref("k", title="FeNO cut-offs in adults with asthma", authors=["Silva"], year="2019",
                                  doi="10.1000/corrected"))
    assert corrected["verdict"] == "note" and corrected["status"]["status"] == "corrected"
    notice = await one(src, ref("n", doi="10.1000/notice"))
    assert notice["verdict"] == "warn" and "is_notice" in codes(notice)


async def test_doi_pmid_conflict(src):
    res = await one(src, ref("x", title=QUANJER_TITLE, authors=["Quanjer"], year="2012",
                            doi="10.1183/09031936.00080312", pmid="16055882"))
    assert res["verdict"] == "fail" and "id_conflict" in codes(res)


async def test_pmid_only_and_missing_pmid(src):
    ok = await one(src, ref("m", title="Standardisation of spirometry", authors=["Miller"], year="2005",
                           pmid="16055882"))
    assert ok["verdict"] == "pass" and ok["exists"]["via"] == ["PubMed"]
    bad = await one(src, ref("b", title="Anything", pmid="99999999"))
    assert bad["verdict"] == "fail" and codes(bad) == ["pmid_not_found"]


async def test_arxiv(src):
    att = await one(src, ref("a", title="Attention is all you need", authors=["Vaswani"], year="2017",
                            arxiv="1706.03762"))
    assert att["verdict"] == "pass" and att["exists"]["via"] == ["arXiv"]
    assert att["status"]["status"] == "ok" and att["status"]["checked_with"] == ["arXiv"]
    pub = await one(src, ref("p", title="Deep learning for lung sounds", authors=["Silva"], year="2020",
                            arxiv="2001.00001"))
    assert pub["verdict"] == "note" and "preprint_published" in codes(pub)
    gone = await one(src, ref("g", title="x", arxiv="2999.99999"))
    assert gone["verdict"] == "fail"


async def test_crossref_preprint_with_published_version(src):
    res = await one(src, ref("pp", title="Machine learning for spirometry interpretation", authors=["Topalovic"],
                            year="2020", doi="10.1101/2020.01.01.000001"))
    assert res["verdict"] == "note" and res["status"]["status"] == "preprint_published"
    assert "10.1000/published" in res["findings"][0]["message"]


async def test_datacite_and_handle_only(src):
    dc = await one(src, ref("d", title="Lung function dataset from northern Portugal", authors=["Jacinto"],
                           year="2024", doi="10.5281/zenodo.123"))
    assert dc["verdict"] == "pass" and dc["exists"]["via"] == ["DataCite"]
    h = await one(src, ref("h", title="Some report", doi="10.9999/elsewhere"))
    assert h["verdict"] == "note" and h["exists"]["status"] == "found" and h["exists"]["metadata"] is False


async def test_partial_matches_warn(src):
    year = await one(src, ref("y", title="Standardisation of spirometry", authors=["Miller"], year="2009",
                             doi="10.1183/09031936.05.00034805"))
    assert year["verdict"] == "warn" and codes(year) == ["year_differs"]
    online_first = await one(src, ref("o", title="Standardisation of spirometry", authors=["Miller"], year="2004",
                                     doi="10.1183/09031936.05.00034805"))
    assert online_first["verdict"] == "pass"
    order = await one(src, ref("ao", title="Standardisation of spirometry", authors=["Hankinson"], year="2005",
                              doi="10.1183/09031936.05.00034805"))
    assert order["verdict"] == "warn" and codes(order) == ["author_order"]


async def test_search_without_identifier(src):
    found = await one(src, ref("s", title="Standardisation of spirometry", authors=["Miller"], year="2005"))
    assert found["verdict"] == "note" and found["exists"]["status"] == "found_by_search"
    assert found["suggestion"] == "doi:10.1183/09031936.05.00034805"
    possible = await one(src, ref("ps", title="Decision support systems for lung function interpretation",
                                  authors=["Fonseca"], year="2019"))
    assert possible["verdict"] == "warn" and possible["exists"]["status"] == "possible_match"
    nothing = await one(src, ref("n", title="A local hospital report on inhaler stocks", authors=["Porto"], year="2023"))
    assert nothing["verdict"] == "warn" and nothing["exists"]["status"] == "not_found_by_search"


async def test_web_pages_and_books(src):
    web = await one(src, ref("gina", title="Global Strategy for Asthma Management and Prevention",
                            authors=["Global Initiative for Asthma"], year="2024", url="https://ginasthma.org/reports/"))
    assert web["verdict"] == "note" and web["exists"]["status"] == "web_page"
    gone = await one(src, ref("gone", title="An old page about nothing much here", url="https://example.org/gone"))
    assert gone["verdict"] == "warn" and "web_unreachable" in codes(gone)
    book = await one(src, ref("west", title="Respiratory physiology: the essentials", authors=["West"], year="2008",
                             isbn="9780781772068"))
    assert book["verdict"] == "pass" and book["exists"]["via"] == ["Open Library"]
    unknown = await one(src, ref("ub", title="An obscure book", isbn="9780000000002"))
    assert unknown["verdict"] == "note" and unknown["exists"]["status"] == "unconfirmed"


async def test_numbered_entries_compare_free_text(src):
    good = await one(src, Reference(key="1", kind="numbered",
                                    raw="Miller MR et al. Standardisation of spirometry. Eur Respir J 2005. "
                                        "https://doi.org/10.1183/09031936.05.00034805",
                                    doi="10.1183/09031936.05.00034805", year="2005"))
    assert good["verdict"] == "pass", good["findings"]
    wrong = await one(src, Reference(key="2", kind="numbered",
                                     raw="Quanjer PH. Multi-ethnic reference values for spirometry. 2012. "
                                         "doi:10.1183/09031936.05.00034805",
                                     doi="10.1183/09031936.05.00034805", year="2012"))
    assert wrong["verdict"] == "fail" and "wrong_work" in codes(wrong)
    bare = await one(src, Reference(key="3", kind="numbered", raw="https://doi.org/10.1183/09031936.05.00034805",
                                    doi="10.1183/09031936.05.00034805"))
    assert bare["verdict"] == "pass" and bare["match"]["status"] == "not_compared"


async def test_service_down_gives_error_not_fail():
    fake = FakeServices(down={"api.crossref.org"})
    async with Sources(transport=fake.transport(), pacing=False, retry_delay=0) as s:
        res = (await check_references([ref("q", title=QUANJER_TITLE, authors=["Quanjer"], year="2012",
                                           doi="10.1183/09031936.00080312")], s))[0]
    assert res["verdict"] == "error"
    assert "service_error" in codes(res)


async def test_document_lists_missing_and_skips_uncited(src):
    doc = Document(path="/tmp/p.md", style="citekey",
                   citations=[Citation("miller", 3, "Standards matter [@miller]."), Citation("ghost", 5, "x")],
                   references={"miller": ref("miller", title="Standardisation of spirometry", authors=["Miller"],
                                             year="2005", doi="10.1183/09031936.05.00034805"),
                               "extra": ref("extra", doi="10.1183/99999")})
    result = await check_document(doc, src)
    assert [r["key"] for r in result["references"]] == ["miller"]
    assert result["missing"] == [{"key": "ghost", "lines": [5]}]
    assert result["uncited"] == ["extra"]
    assert result["summary"]["pass"] == 1 and result["summary"]["missing_entries"] == 1
    assert result["references"][0]["cited_in"] == [{"line": 3, "sentence": "Standards matter [@miller]."}]
    assert "Crossref" in result["sources"]


async def test_entries_with_only_a_link_or_nothing(src):
    link = await one(src, Reference(key="7", kind="numbered", raw="https://ginasthma.org/reports/",
                                    url="https://ginasthma.org/reports/"))
    assert link["verdict"] == "note" and link["exists"]["status"] == "web_page"
    empty = await one(src, Reference(key="8", kind="numbered", raw="Ibid."))
    assert empty["verdict"] == "warn" and empty["exists"]["status"] == "unidentifiable"
