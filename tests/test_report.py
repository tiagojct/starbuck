import shutil
from pathlib import Path

import pytest

from starbuck.check import check_document
from starbuck.parse import read_manuscript
from starbuck.render import render
from starbuck.report import esc, to_quarto, to_text, write_outputs

MS = """---
title: Draft
bibliography: refs.json
---

Spirometry needs standards [@miller]. Reference values exist [@quanjer].
A retracted paper is still cited here [@wakefield]. And a made-up one [@ghost2024; @nokey].
"""
REFS = """[
 {"id": "miller", "title": "Standardisation of spirometry", "author": [{"family": "Miller"}],
  "issued": {"date-parts": [[2005]]}, "DOI": "10.1183/09031936.05.00034805"},
 {"id": "quanjer", "title": "Multi-ethnic reference values for spirometry for the 3-95-yr age range",
  "author": [{"family": "Quanjer"}], "issued": {"date-parts": [[2012]]}, "DOI": "10.1183/09031936.00080312"},
 {"id": "wakefield", "title": "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children",
  "author": [{"family": "Wakefield"}], "issued": {"date-parts": [[1998]]}, "DOI": "10.1016/S0140-6736(97)11096-0"},
 {"id": "ghost2024", "title": "Spirometry | on the *Moon* with @astronauts and $x$",
  "author": [{"family": "Nobody"}], "issued": {"date-parts": [[2024]]}, "DOI": "10.1183/13993003.99999-2024"}
]"""


@pytest.fixture
async def result(tmp_path, src):
    (tmp_path / "refs.json").write_text(REFS, encoding="utf-8")
    ms = tmp_path / "draft.qmd"
    ms.write_text(MS, encoding="utf-8")
    return await check_document(read_manuscript(ms), src)


def test_escape():
    assert esc("a | b *c* @d $e$ [f]") == r"a \| b \*c\* \@d \$e\$ \[f\]"


async def test_quarto_report(result):
    q = to_quarto(result)
    assert q.startswith("---\ntitle: \"Reference check\"\nsubtitle: \"draft.qmd\"")
    assert "embed-resources: true" in q and "docx:" in q
    assert "## Needs attention" in q and "## All references" in q and "## How this report was made" in q
    # failures come first, with the reason and an action
    attention = q.split("## Needs attention", 1)[1].split("## All references", 1)[0]
    assert "### miller" not in attention and "### quanjer" not in attention
    assert attention.index("### wakefield: Fail") < attention.index("### ghost2024: Fail")
    assert "Retracted (2010-02-06" in attention
    assert "Suggested action: Remove the citation" in attention
    assert "> Line 7: A retracted paper is still cited here \\[\\@wakefield\\]." in attention
    # the made-up title is escaped, so it cannot break the table or become a citation
    assert r"Spirometry \| on the \*Moon\* with \@astronauts and \$x\$" in q
    assert "| nokey | 7 |" in q
    assert "[doi:10.1016/s0140-6736(97)11096-0](https://doi.org/10.1016/s0140-6736%2897%2911096-0)" in q


async def test_text_summary(result):
    t = to_text(result, "/tmp/r.html")
    assert t.splitlines()[0] == "Starbuck checked 4 references: 2 fail, 2 pass."
    assert "Cited without an entry: nokey" in t and t.endswith("Report: /tmp/r.html")


@pytest.mark.skipif(not (shutil.which("quarto") or shutil.which("pandoc")), reason="needs Quarto or Pandoc")
async def test_render_html_and_docx(result, tmp_path: Path):
    paths = write_outputs(result, tmp_path / "_starbuck", "draft-references")
    out = render(paths["qmd"], ["html", "docx"])
    html = out["html"].read_text(encoding="utf-8")
    assert "Reference check" in html and "wakefield: Fail" in html
    assert "@astronauts" in html and "<em>Moon</em>" not in html
    assert out["docx"].stat().st_size > 5000
    assert paths["json"].exists()


def test_linkify_keeps_doi_parentheses():
    from starbuck.report import linkify
    msg = "Retracted (2010-02-06, notice doi:10.1016/s0140-6736(10)60175-4; reported by Retraction Watch)."
    assert linkify(msg) == ("Retracted (2010-02-06, notice "
                            "[doi:10.1016/s0140-6736(10)60175-4](https://doi.org/10.1016/s0140-6736%2810%2960175-4)"
                            "; reported by Retraction Watch).")


async def test_uncited_sentences_in_report(tmp_path, src):
    (tmp_path / "refs.json").write_text(REFS, encoding="utf-8")
    ms = tmp_path / "u.qmd"
    lines = [f"Study {i} found that the risk rose by {i}% in the adults who were followed." for i in range(55)]
    ms.write_text("---\nbibliography: refs.json\n---\n\nSpirometry needs standards [@miller].\n\n"
                  + "\n\n".join(lines) + "\n", encoding="utf-8")
    result = await check_document(read_manuscript(ms), src)
    assert result["summary"]["uncited_sentences"] == 55 and len(result["uncited_sentences"]) == 50
    assert result["uncited_sentences"][0] == {"line": 7, "sentence": lines[0]}
    qmd = to_quarto(result)
    assert "- 55 sentences state a finding without a citation" in qmd
    assert "## Sentences without a citation" in qmd and "The first 50 of 55 are shown." in qmd
    assert "Sentences without a citation: 55" in to_text(result)
