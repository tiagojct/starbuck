import json
from pathlib import Path

from starbuck import bibtex
from starbuck.parse import read_manuscript, references_from_identifiers

BIB = r"""
@string{erj = "European Respiratory Journal"}
% a comment line with @misc{not, an entry}
@article{quanjer2012,
  title = {Multi-ethnic reference values for spirometry for the 3--95-yr age range: the global lung function 2012 equations},
  author = {Quanjer, Philip H. and Stanojevic, Sanja and Cole, Tim J. and others},
  journal = erj,
  year = 2012,
  doi = {10.1183/09031936.00080312},
  abstract = {Text that mentions
@article{fake, title={not an entry}} inside a field}
}
@book{west2008,
  title = "Respiratory physiology: {T}he essentials",
  author = {West, John B.},
  year = {2008},
  isbn = {978-0-7817-7206-8}
}
@misc{gina,
  author = {{Global Initiative for Asthma}},
  title = {Global Strategy for Asthma Management and Prevention},
  year = {2024},
  url = {https://ginasthma.org/reports/}
}
@article{fonseca2019,
  author = {Fons{\^e}ca, Jo{\~a}o and M{\"u}ller, Anna},
  title = {Decision support in lung function},
  date = {2019-05-01},
  journaltitle = {Respiratory Medicine}
}
@online{vaswani2017,
  author = {Vaswani, Ashish},
  title = {Attention Is All You Need},
  eprint = {1706.03762}, eprinttype = {arxiv}, year = {2017}
}
@article{broken,
  title = {Missing brace
"""

MANUSCRIPT = """---
title: Test
bibliography: refs.bib
---

Spirometry reference values differ by ethnicity [@quanjer2012]. West explains it well
[see @west2008, p. 12; @gina]. As @fonseca2019 showed, decision support helps. Write to
me at someone@example.org, see @fig-one, and follow @tiagojct.

```python
x = "[@quanjer2012]"  # code is not a citation
```

Transformers changed everything [@vaswani2017; @missing2020].
"""


def test_bibtex_entries():
    entries, problems = bibtex.parse(BIB)
    keys = [e["key"] for e in entries]
    assert keys == ["quanjer2012", "west2008", "gina", "fonseca2019", "vaswani2017"]
    assert any("broken" in p or "not closed" in p for p in problems)
    q = entries[0]["fields"]
    assert q["journal"] == "European Respiratory Journal"
    assert q["year"] == "2012"
    assert bibtex.authors(q) == ["Quanjer", "Stanojevic", "Cole"]
    assert bibtex.authors(entries[2]["fields"]) == ["Global Initiative for Asthma"]
    assert bibtex.authors(entries[3]["fields"]) == ["Fonsêca", "Müller"]
    assert bibtex.latex_to_text(q["title"]).startswith("Multi-ethnic reference values for spirometry for the 3–95")


def test_manuscript_with_bibtex(tmp_path: Path):
    (tmp_path / "refs.bib").write_text(BIB, encoding="utf-8")
    ms = tmp_path / "paper.qmd"
    ms.write_text(MANUSCRIPT, encoding="utf-8")
    doc = read_manuscript(ms)
    assert doc.style == "citekey"
    assert doc.cited_keys() == ["quanjer2012", "west2008", "gina", "fonseca2019", "vaswani2017", "missing2020"]
    assert doc.missing() == {"missing2020": [14]}
    assert doc.unused() == []
    first = doc.citing("quanjer2012")
    assert len(first) == 1 and first[0].line == 6
    assert first[0].sentence == "Spirometry reference values differ by ethnicity [@quanjer2012]."
    assert doc.citing("fonseca2019")[0].sentence.startswith("As @fonseca2019 showed")
    refs = doc.references
    assert refs["quanjer2012"].doi == "10.1183/09031936.00080312"
    assert refs["west2008"].isbn == "9780781772068"
    assert refs["vaswani2017"].arxiv == "1706.03762"
    assert refs["fonseca2019"].year == "2019"
    assert refs["fonseca2019"].container == "Respiratory Medicine"
    assert refs["gina"].url == "https://ginasthma.org/reports/"
    assert any("broken" in w or "not closed" in w for w in doc.warnings)


def test_csl_json_and_unused(tmp_path: Path):
    items = [
        {"id": "miller2005", "type": "article-journal", "title": "Standardisation of spirometry",
         "author": [{"family": "Miller", "given": "M R"}], "issued": {"date-parts": [[2005]]},
         "DOI": "10.1183/09031936.05.00034805", "PMID": "16055882"},
        {"id": "unused", "title": "Never cited", "issued": {"date-parts": [[2000]]}},
    ]
    (tmp_path / "refs.json").write_text(json.dumps(items), encoding="utf-8")
    ms = tmp_path / "paper.md"
    ms.write_text("Spirometry needs standards [@miller2005].\n", encoding="utf-8")
    doc = read_manuscript(ms, [tmp_path / "refs.json"])
    assert doc.references["miller2005"].pmid == "16055882"
    assert doc.references["miller2005"].authors == ["Miller"]
    assert doc.unused() == ["unused"]


def test_numbered_sources(tmp_path: Path):
    ms = tmp_path / "report.md"
    ms.write_text("""# Report

Spirometry needs standards [1]. Reference values differ [2, 3]. See also [4-5] and
a [link](https://example.org) and [6](https://x.org).

## Sources

1. Miller MR et al. Standardisation of spirometry. Eur Respir J 2005. https://doi.org/10.1183/09031936.05.00034805
2. [2] is not how this list is written
3. Quanjer PH. Multi-ethnic reference values for spirometry. 2012. PMID: 22743675
   (continued on the next line)
4. https://arxiv.org/abs/1706.03762
5. Global Initiative for Asthma. GINA report 2024. https://ginasthma.org/reports/
""", encoding="utf-8")
    doc = read_manuscript(ms)
    assert doc.style == "numbered"
    assert doc.cited_keys() == ["1", "2", "3", "4", "5"]
    r = doc.references
    assert r["1"].doi == "10.1183/09031936.05.00034805" and r["1"].year == "2005"
    assert r["3"].pmid == "22743675" and r["3"].raw.endswith("(continued on the next line)")
    assert r["4"].arxiv == "1706.03762"
    assert r["5"].url == "https://ginasthma.org/reports/"
    assert doc.missing() == {}


def test_no_bibliography_warns(tmp_path: Path):
    ms = tmp_path / "x.md"
    ms.write_text("Claim [@a2020].\n", encoding="utf-8")
    doc = read_manuscript(ms)
    assert doc.style == "citekey" and doc.missing() == {"a2020": [1]}
    assert "names no bibliography" in doc.warnings[0]


def test_given_references():
    refs = references_from_identifiers([
        {"identifier": "10.1183/09031936.00080312", "title": "Multi-ethnic reference values", "first_author": "Quanjer"},
        {"raw": "Miller MR. Standardisation of spirometry. Eur Respir J 2005"},
    ])
    assert refs[0].doi == "10.1183/09031936.00080312" and refs[0].authors == ["Quanjer"]
    assert refs[1].year == "2005" and not refs[1].doi


UNCITED = """---
title: "COPD has a prevalence of 10% in adults"
bibliography: refs.json
---

# Introduction

Chronic obstructive pulmonary disease is the leading cause of death in many countries. Smoking
increased the risk of COPD by 30% in a large cohort [@miller]. Spirometry is a simple test.
Is it true that air pollution increased the incidence of asthma in children by 20%?
Short claim: risk rose 20%.

- Exposure to biomass smoke was associated with airflow obstruction in rural women.
- A narrative citation such as @miller found that procedures differ between laboratories.

| Table row with a prevalence of 12% in the population of interest | x |
|---|---|

![Prevalence was 12% among the 300 participants of the study](fig.png)

Figure 1: Prevalence was 12% among the 300 participants of the study shown here.

```
Code that showed a 50% increase in risk of everything here and elsewhere.
```

<!-- A comment that found a 50% increase in risk of everything here and elsewhere. -->

# Methods

We recruited 300 participants and found that 20% had airflow obstruction at baseline.

## Results

Mean FEV1 decreased by 40 mL per year over the follow-up period of the study.

# Discussion

Our results agree with earlier work [1] and a footnote[^1]. Other cohorts reported a decline of 60 mL/year
in smokers.

[^1]: A footnote that reported a decline of 60 mL/year in smokers from other cohorts.

# References

1. Someone. A study that found a 50% reduction in mortality among all participants. 2020.
"""


def test_uncited_sentences(tmp_path):
    (tmp_path / "refs.json").write_text(json.dumps(
        [{"id": "miller", "title": "Standardisation of spirometry", "issued": {"date-parts": [[2005]]}}]))
    ms = tmp_path / "u.md"
    ms.write_text(UNCITED, encoding="utf-8")
    doc = read_manuscript(ms)
    assert doc.uncited_sentences == [
        {"line": 8, "sentence": "Chronic obstructive pulmonary disease is the leading cause of death in many countries."},
        {"line": 13, "sentence": "Exposure to biomass smoke was associated with airflow obstruction in rural women."},
        {"line": 39, "sentence": "Other cohorts reported a decline of 60 mL/year in smokers."},
    ]


def test_uncited_sentences_refs_div_and_bold_heading(tmp_path):
    ms = tmp_path / "n.md"
    ms.write_text("Rates of asthma increased by 20% in two decades in most countries studied [1].\n\n"
                  "Asthma prevalence in adults is about 4.3% worldwide, by most estimates.\n\n"
                  "**References**\n\n1. A survey that found a prevalence of 4.3% in adults worldwide. 2012.\n",
                  encoding="utf-8")
    doc = read_manuscript(ms)
    assert doc.style == "numbered"
    assert [s["line"] for s in doc.uncited_sentences] == [3]
    ms.write_text("::: {#refs}\nA reference that found a prevalence of 4.3% in adults worldwide in 2012.\n:::\n",
                  encoding="utf-8")
    assert read_manuscript(ms).uncited_sentences == []
