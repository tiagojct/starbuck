import json

import pytest

from starbuck import server
from starbuck.check import check_document
from starbuck.claims import apply, judge_settings, parse_answer, prepare, validate
from starbuck.cli import parser, run_check
from starbuck.evidence import jats_passages, query_text, quote_in, rank
from starbuck.parse import read_manuscript
from starbuck.report import to_quarto
from starbuck.sources import Sources

from fake_services import FULLTEXT

MS = """---
title: Draft
bibliography: refs.json
---

Spirometry results from different laboratories can be compared only with standard procedures [@miller].
Reference equations were derived from records of 26 countries [@quanjer].
The equations fit every ethnic group equally well [@quanjer].
A retracted paper is cited here [@wakefield].
"""
REFS = [
    {"id": "miller", "title": "Standardisation of spirometry", "author": [{"family": "Miller"}],
     "issued": {"date-parts": [[2005]]}, "DOI": "10.1183/09031936.05.00034805", "PMID": "16055882"},
    {"id": "quanjer", "title": "Multi-ethnic reference values for spirometry for the 3-95-yr age range: "
     "the global lung function 2012 equations", "author": [{"family": "Quanjer"}],
     "issued": {"date-parts": [[2012]]}, "DOI": "10.1183/09031936.00080312"},
    {"id": "wakefield", "title": "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive "
     "developmental disorder in children", "author": [{"family": "Wakefield"}],
     "issued": {"date-parts": [[1998]]}, "DOI": "10.1016/S0140-6736(97)11096-0"},
]
JUDGE_ENV = {"STARBUCK_JUDGE_URL": "https://judge.test/v1", "STARBUCK_JUDGE_MODEL": "test-model",
             "STARBUCK_JUDGE_KEY": "k"}


@pytest.fixture
def manuscript(tmp_path):
    (tmp_path / "refs.json").write_text(json.dumps(REFS), encoding="utf-8")
    ms = tmp_path / "draft.md"
    ms.write_text(MS, encoding="utf-8")
    return ms


@pytest.fixture
async def prepared(manuscript, src):
    doc = read_manuscript(manuscript)
    result = await check_document(doc, src)
    return doc, result, await prepare(doc, result, src)


def ids_of(p: dict) -> dict[str, str]:
    return {c["key"] + str(c["line"]): c["id"] for c in p["claims"]}


def canned(fake):
    fake.judge_answers = [
        ("standard procedures [@miller]", {"verdict": "supported", "reason": "Stated in the abstract.",
                                          "quote": "Spirometry needs standard procedures so that results from "
                                                   "different laboratories can be compared."}),
        ("records of 26 countries", {"verdict": "Supported", "reason": "Results section.",
                                     "quote": "derived from 74,187 records of healthy non-smokers from 26 countries"}),
        ("every ethnic group", {"verdict": "not supported", "reason": "Fit differed by group.",
                                "quote": "Equations for North East Asians and South East Asians fitted the data "
                                         "less well than those for Caucasians."}),
    ]


# ---------------------------------------------------------------- evidence

def test_jats_passages_keep_sections():
    passages = jats_passages(FULLTEXT["PMC0000001"])
    assert [p["section"] for p in passages] == ["Abstract", "Introduction", "Results", "Results", "Discussion"]


def test_rank_and_query_text():
    assert query_text("Values differ [@a; @b, p. 3] and @c says so [2-4].") == "Values differ and says so ."
    passages = [{"section": "", "text": t} for t in ("Bone density in adults.", "Spirometry reference values "
                                                    "for children and adults.", "Spirometry in sport.")]
    top = rank("reference values for spirometry", passages, k=2)
    assert top[0]["text"].startswith("Spirometry reference values")
    assert len(top) == 2


def test_quote_in_ignores_spacing_and_quote_marks_only():
    text = "The equations were derived from\n74,187 records – healthy non-smokers."
    assert quote_in("derived from 74,187 records - healthy", text)
    assert quote_in("“derived from  74,187 records”", text)
    assert not quote_in("derived from 74,000 records", text)
    assert not quote_in("", text)


def test_parse_answer_and_settings():
    assert parse_answer('<think>hm {"x"}</think>```json\n{"verdict": "supported"}\n```')["verdict"] == "supported"
    with pytest.raises(ValueError):
        parse_answer("no json here")
    assert judge_settings({}) is None
    s = judge_settings({"STARBUCK_JUDGE_URL": "http://localhost:11434/v1/", "STARBUCK_JUDGE_MODEL": "m"})
    assert s == {"url": "http://localhost:11434/v1/chat/completions", "model": "m", "key": ""}


# ---------------------------------------------------------------- prepare, validate, apply

async def test_prepare_chooses_full_text_abstract_or_skips(prepared):
    _, _, p = prepared
    assert len(p["claims"]) == 4
    miller = next(c for c in p["claims"] if c["key"] == "miller")
    assert miller["status"] == "ready" and miller["basis"] == "abstract"
    assert miller["source"] == "PubMed 16055882 abstract"
    quanjer = [c for c in p["claims"] if c["key"] == "quanjer"]
    assert len(quanjer) == 2 and all(c["basis"] == "full text" for c in quanjer)
    assert quanjer[0]["source"] == "Europe PMC PMC0000001"
    assert "74,187 records" in quanjer[0]["passages"][0]["text"]
    wakefield = next(c for c in p["claims"] if c["key"] == "wakefield")
    assert wakefield["status"] == "skipped" and "failed levels 1 to 3" in wakefield["reason"]
    assert "wakefield" not in p["texts"]


async def test_validate_rejects_quotes_not_in_the_source(prepared):
    _, _, p = prepared
    ids = ids_of(p)
    miller, q1, q2 = ids["miller6"], ids["quanjer7"], ids["quanjer8"]
    out = {c["id"]: c for c in validate(p, {
        miller: {"verdict": "supported", "quote": "Spirometry needs standard procedures so that results"},
        q1: {"verdict": "supported", "quote": "derived from 80,000 records of healthy non-smokers"},
        q2: {"verdict": "not_supported", "quote": ""},
    })}
    assert out[miller]["verdict"] == "supported" and not out[miller].get("rejected")
    assert out[q1]["verdict"] == "cannot_assess" and out[q1]["rejected_verdict"] == "supported"
    assert "word for word" in out[q1]["reason"]
    assert out[q2]["verdict"] == "not_supported"  # no quote needed when the source is silent
    skipped = next(c for c in out.values() if c["key"] == "wakefield")
    assert skipped["verdict"] == "cannot_assess" and not skipped["judged"]


async def test_validate_other_rejections(prepared):
    _, _, p = prepared
    miller = ids_of(p)["miller6"]
    for given, why in (({"verdict": "supported", "quote": ""}, "no quotation"),
                       ({"verdict": "partly_supported", "quote": "Spirometry"}, "characters"),
                       ({"verdict": "proven", "quote": ""}, "unknown verdict")):
        row = next(c for c in validate(p, {miller: given}) if c["id"] == miller)
        assert row["verdict"] == "cannot_assess" and why in row["reason"]


async def test_apply_never_fails_a_reference(prepared):
    _, result, p = prepared
    ids = ids_of(p)
    final = validate(p, {ids["quanjer7"]: {"verdict": "partly_supported",
                                           "quote": "derived from 74,187 records of healthy"},
                         ids["quanjer8"]: {"verdict": "not_supported", "quote": ""}})
    apply(result, final, "test-model")
    quanjer = next(r for r in result["references"] if r["key"] == "quanjer")
    assert quanjer["verdict"] == "warn"
    assert [f["code"] for f in quanjer["findings"]] == ["claim_not_supported", "claim_partly_supported"]
    assert next(r for r in result["references"] if r["key"] == "wakefield")["verdict"] == "fail"
    assert result["levels"] == [1, 2, 3, 4]
    assert result["claims_run"]["verdicts"]["not_supported"] == 1
    assert result["summary"]["warn"] == 1
    # applying again with other verdicts replaces the level 4 findings
    apply(result, validate(p, {}), "test-model")
    assert next(r for r in result["references"] if r["key"] == "quanjer")["verdict"] == "pass"
    qmd = to_quarto(result)
    assert "## Claim support" in qmd and "Cannot assess" in qmd


# ---------------------------------------------------------------- CLI and MCP

async def test_cli_claims_with_judge(manuscript, fake, monkeypatch, capsys):
    for k, v in JUDGE_ENV.items():
        monkeypatch.setenv(k, v)
    canned(fake)
    args = parser().parse_args(["check", str(manuscript), "--to", "", "--quiet", "--claims"])
    await run_check(args, transport=fake.transport())
    out = capsys.readouterr().out
    assert "Level 4: 4 citing sentences: 2 supported, 0 partly supported, 1 not supported, 1 cannot assess." in out
    folder = manuscript.parent / "_starbuck"
    data = json.loads((folder / "draft-references.json").read_text(encoding="utf-8"))
    assert data["claims_run"]["judged_by"] == "test-model"
    evidence = json.loads((folder / "draft-claims.json").read_text(encoding="utf-8"))
    assert set(evidence["texts"]) == {"miller", "quanjer"} and len(evidence["verdicts"]) == 3
    assert len(fake.judge_prompts) == 3 and "Passages:" in fake.judge_prompts[0]
    assert "## Claim support" in (folder / "draft-references.qmd").read_text(encoding="utf-8")


async def test_cli_claims_without_judge_settings(manuscript, fake, monkeypatch, capsys):
    for k in JUDGE_ENV:
        monkeypatch.delenv(k, raising=False)
    args = parser().parse_args(["check", str(manuscript), "--to", "", "--quiet", "--claims"])
    await run_check(args, transport=fake.transport())
    assert "level 4 skipped" in capsys.readouterr().err
    qmd = (manuscript.parent / "_starbuck" / "draft-references.qmd").read_text(encoding="utf-8")
    assert "was not run: STARBUCK\\_JUDGE\\_URL and STARBUCK\\_JUDGE\\_MODEL are not set" in qmd
    assert not fake.judge_prompts


async def test_cli_text_option_must_name_a_file(manuscript, fake, tmp_path):
    args = parser().parse_args(["check", str(manuscript), "--to", "", "--quiet", "--claims",
                                "--text", f"miller={tmp_path / 'missing.txt'}"])
    assert await run_check(args, transport=fake.transport()) == 2


async def test_local_text_file_is_used(manuscript, src, tmp_path):
    full = tmp_path / "miller.txt"
    full.write_text("Methods\n\nWe measured spirometry in 12 laboratories.\n\nResults were comparable "
                    "across laboratories when standard procedures were followed.", encoding="utf-8")
    doc = read_manuscript(manuscript)
    result = await check_document(doc, src)
    p = await prepare(doc, result, src, {"miller": str(full)})
    miller = next(c for c in p["claims"] if c["key"] == "miller")
    assert miller["basis"] == "full text" and miller["source"] == "local file miller.txt"


async def test_mcp_prepare_and_record(manuscript, fake, monkeypatch):
    monkeypatch.setattr(server, "make_sources",
                        lambda: Sources(email="t@example.org", transport=fake.transport(), pacing=False, retry_delay=0))
    page = await server.prepare_claims(str(manuscript), limit=2)
    assert page["total"] == 4 and page["ready"] == 3 and len(page["claims"]) == 2
    rest = await server.prepare_claims(str(manuscript), offset=2, limit=10)
    assert [c["id"] for c in rest["claims"]] == ["c003", "c004"]
    ids = {c["key"] + str(c["line"]): c["id"] for c in page["claims"] + rest["claims"]}
    out = await server.record_claims(str(manuscript), [
        server.ClaimVerdict(id=ids["miller6"], verdict="supported",
                            quote="the acceptability and repeatability of forced expiratory manoeuvres"),
        server.ClaimVerdict(id=ids["quanjer8"], verdict="supported", quote="The equations fit every group"),
    ], formats=[])
    assert out["level4"]["verdicts"] == {"supported": 1, "partly_supported": 0, "not_supported": 0,
                                         "cannot_assess": 3}
    assert out["level4"]["rejected_quotes"] == 1
    assert out["missing_verdicts"] == [ids["quanjer7"]]
    assert [a["id"] for a in out["attention"]] == [ids["quanjer8"]]
    with pytest.raises(Exception, match="Unknown claim ids"):
        await server.record_claims(str(manuscript), [server.ClaimVerdict(id="c999", verdict="supported")])


async def test_europepmc_query_forms(src, fake):
    await src.europepmc_work(pmcid="pmc0000001")
    await src.europepmc_work(doi="10.1183/09031936.00080312")
    queries = [u for u in fake.requests if "/search" in u and "ebi.ac.uk" in u]
    assert "PMCID%3APMC0000001" in queries[0]  # not quoted: Europe PMC finds nothing for PMCID:"..."
    assert "DOI%3A%2210.1183" in queries[1]


# ---------------------------------------------------------------- citation recall, precision, overcitation

def _claim(i, key, line, sentence, verdict):
    return {"id": f"c{i:03d}", "key": key, "line": line, "sentence": sentence, "basis": "abstract",
            "source": "", "verdict": verdict, "quote": "", "reason": "", "judged": verdict != "cannot_assess"}


def test_citation_scores():
    from starbuck.claims import citation_scores
    s1, s2, s3 = "Both say so [@a; @b].", "Only a partial claim [@a].", "Nothing to judge [@c; @d]."
    claims = [_claim(1, "a", 1, s1, "supported"), _claim(2, "b", 1, s1, "not_supported"),
              _claim(3, "a", 2, s2, "partly_supported"), _claim(4, "c", 3, s3, "cannot_assess"),
              _claim(5, "d", 3, s3, "not_supported")]
    recall, precision, over = citation_scores(claims)
    assert recall == {"value": 0.6667, "numerator": 2, "denominator": 3}
    assert precision == {"value": 0.5, "numerator": 2, "denominator": 4}
    assert over == {"c002"}
    # a partly supporting neighbour does not make overcitation
    claims[0]["verdict"] = "partly_supported"
    assert citation_scores(claims)[2] == set()
    assert citation_scores([])[0] == {"value": None, "numerator": 0, "denominator": 0}


async def test_apply_adds_overcitation_and_scores(prepared):
    _, result, p = prepared
    sentence = "Two sources for one sentence [@miller; @quanjer]."
    claims = [_claim(1, "miller", 9, sentence, "supported"), _claim(2, "quanjer", 9, sentence, "not_supported")]
    apply(result, claims, "test-model")
    quanjer = next(r for r in result["references"] if r["key"] == "quanjer")
    assert [f["code"] for f in quanjer["findings"]] == ["claim_not_supported", "claim_overcitation"]
    assert quanjer["findings"][1]["message"] == ("Line 9: the other sources cited in this sentence support it; "
                                                 "this one does not add support.")
    run = result["claims_run"]
    assert run["citation_recall"]["value"] == 1.0 and run["citation_precision"]["numerator"] == 1
    assert run["overcitations"] == 1
    qmd = to_quarto(result)
    assert "Citation recall: 1/1 (100%)" in qmd and "citation precision: 1/2 (50%)" in qmd
    assert "Citation recall is the share" in qmd
    from starbuck.report import to_text
    assert "Citation recall: 1/1 (100%) of sentences" in to_text(result)
