"""starbuck fix: proposals and edits of BibTeX, CSL JSON and numbered lists."""

import json

from starbuck.check import check_document
from starbuck.fix import Change, apply_plan, diff, edit_bibtex, propose
from starbuck.parse import read_manuscript

BIB = """@article{quanjer,
  title = {Multi-ethnic reference values for spirometry for the 3-95-yr age range: the global lung function 2012 equations},
  author = {Quanjer, Philip H. and Stanojevic, Sanja},
  journal = {European Respiratory Journal},
  year = {2009},
  doi = {10.1183/09031936.00080312}
}

@article{miller,
  title = {Standardisation of spirometry},
  author = {Miller, M. R. and Hankinson, J.},
  year = 2005
}

@article{wakefield,
  title = {Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children},
  author = {Wakefield, A. J.},
  year = {1998},
  doi = {10.1016/S0140-6736(97)11096-0}
}

@article{preprint,
  title = {Machine learning for spirometry interpretation},
  author = {Topalovic, Marko},
  year = {2020},
  doi = {10.1101/2020.01.01.000001}
}
"""
TEXT = "---\nbibliography: refs.bib\n---\n\nText [@quanjer; @miller; @wakefield; @preprint].\n"


async def test_fix_proposes_supported_changes_and_lists_the_rest(tmp_path, src, fake):
    import fake_services as fs
    fs.CROSSREF["10.1000/published"] = {"DOI": "10.1000/published", "type": "journal-article",
                                        "title": ["Machine learning for spirometry interpretation"],
                                        "author": [{"family": "Topalovic"}], "issued": {"date-parts": [[2021]]},
                                        "container-title": ["Respiratory Research"]}
    (tmp_path / "refs.bib").write_text(BIB)
    (tmp_path / "paper.qmd").write_text(TEXT)
    try:
        doc = read_manuscript(tmp_path / "paper.qmd")
        result = await check_document(doc, src)
        plan = await propose(doc, result, src)
    finally:
        del fs.CROSSREF["10.1000/published"]
    got = {(c.key, c.field): c.new for c in plan.changes}
    assert got[("quanjer", "year")] == "2012"
    assert got[("miller", "doi")] == "10.1183/09031936.05.00034805"
    assert got[("preprint", "doi")] == "10.1000/published"
    assert got[("preprint", "year")] == "2021"
    assert got[("preprint", "container")] == "Respiratory Research"
    assert [m["key"] for m in plan.manual] == ["wakefield"]  # a retraction is for a person

    files = apply_plan(doc, plan)
    old, new, done = files[tmp_path / "refs.bib"]
    assert len(done) == 5
    assert "year = {2012}," in new and "doi = {10.1183/09031936.05.00034805}" in new
    assert "journal = {Respiratory Research}" in new
    # the edited file reads back, and nothing else changed
    entries = {e["key"]: e["fields"] for e in __import__("starbuck").bibtex.parse(new)[0]}
    assert entries["miller"]["year"] == "2005" and entries["preprint"]["doi"] == "10.1000/published"
    assert new.count("@article") == 4
    patch = diff(files)
    assert patch.startswith("--- a/refs.bib") and "+  year = {2012}," in patch


def test_bibtex_edit_inserts_a_field_after_the_last_one_without_a_comma():
    text = "@book{w,\n\ttitle = {Respiratory physiology},\n\tyear = 2008\n}\n"
    new, done = edit_bibtex(text, [Change("w", "isbn", "", "9780781772068", "x")])
    assert new == "@book{w,\n\ttitle = {Respiratory physiology},\n\tyear = 2008,\n\tisbn = {9780781772068}\n}\n"
    assert done


def test_bibtex_edit_escapes_title_and_uses_date_field():
    text = "@article{a, title = {Old}, date = {2010-05-01}}"
    new, _ = edit_bibtex(text, [Change("a", "title", "Old", "Lungs & air", "x"), Change("a", "year", "2010", "2012", "x")])
    assert new == "@article{a, title = {Lungs \\& air}, date = {2012-05-01}}"


async def test_fix_csl_json_and_numbered(tmp_path, src):
    items = [{"id": "miller", "type": "article-journal", "title": "Standardisation of spirometry",
              "author": [{"family": "Miller"}], "issued": {"date-parts": [[2005]]}}]
    (tmp_path / "refs.json").write_text(json.dumps(items, indent="\t"))
    (tmp_path / "a.md").write_text("---\nbibliography: refs.json\n---\nText [@miller].\n")
    doc = read_manuscript(tmp_path / "a.md")
    plan = await propose(doc, await check_document(doc, src), src)
    files = apply_plan(doc, plan)
    _, new, _ = files[tmp_path / "refs.json"]
    assert json.loads(new)[0]["DOI"] == "10.1183/09031936.05.00034805"
    assert '\n\t{\n\t\t"id": "miller"' in new  # the file's own indentation is kept

    (tmp_path / "b.md").write_text("Text [1].\n\n## References\n\n1. Miller MR, Hankinson J. Standardisation of "
                                   "spirometry. Eur Respir J. 2005;26:319-38.\n")
    doc = read_manuscript(tmp_path / "b.md")
    plan = await propose(doc, await check_document(doc, src), src)
    _, new, done = apply_plan(doc, plan)[tmp_path / "b.md"]
    assert new.endswith("2005;26:319-38. doi:10.1183/09031936.05.00034805\n")
    assert [c.field for c in done] == ["doi"]


async def test_fix_command_writes_copies_and_in_place(tmp_path, fake):
    from starbuck.cli import parser
    from starbuck.fix import run_fix
    (tmp_path / "refs.bib").write_text(BIB.split("@article{wakefield")[0])
    (tmp_path / "paper.qmd").write_text("---\nbibliography: refs.bib\n---\n\nText [@quanjer; @miller].\n")
    args = parser().parse_args(["fix", str(tmp_path / "paper.qmd"), "--quiet"])
    assert await run_fix(args, fake.transport()) == 0
    patch = (tmp_path / "_starbuck" / "paper-fix.diff").read_text().splitlines()
    assert [x for x in patch if x.startswith("+") and not x.startswith("+++")] == [
        "+  year = {2012},", "+  year = 2005,", "+  doi = {10.1183/09031936.05.00034805}"]
    assert "year = {2012}" in (tmp_path / "_starbuck" / "refs-fixed.bib").read_text()
    assert "year = {2009}" in (tmp_path / "refs.bib").read_text()
    args = parser().parse_args(["fix", str(tmp_path / "paper.qmd"), "--quiet", "--in-place"])
    assert await run_fix(args, fake.transport()) == 0
    assert "year = {2012}" in (tmp_path / "refs.bib").read_text()
    assert "year = {2009}" in (tmp_path / "refs.bib.bak").read_text()
