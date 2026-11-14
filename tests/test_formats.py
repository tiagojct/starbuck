"""Word, LaTeX and author-year manuscripts."""

import base64
import html
import json
import zipfile

from starbuck.check import check_document
from starbuck.parse import has_citation, read_manuscript

QUANJER_DOI = "10.1183/09031936.00080312"
MILLER_DOI = "10.1183/09031936.05.00034805"
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def run(text):
    return f'<w:r><w:t xml:space="preserve">{html.escape(text)}</w:t></w:r>'


def field(instr, shown, split=False):
    parts = [instr[: len(instr) // 2], instr[len(instr) // 2:]] if split else [instr]
    instrs = "".join(f'<w:r><w:instrText xml:space="preserve">{html.escape(x)}</w:instrText></w:r>' for x in parts)
    return (f'<w:r><w:fldChar w:fldCharType="begin"/></w:r>{instrs}<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'{run(shown)}<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def para(*parts, style="", numbered=False):
    ppr = ""
    if style or numbered:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + \
              ('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>' if numbered else "") + "</w:pPr>"
    return f"<w:p>{ppr}{''.join(parts)}</w:p>"


def docx(path, paragraphs):
    body = f'<?xml version="1.0"?><w:document {NS}><w:body>{"".join(paragraphs)}</w:body></w:document>'
    styles = (f'<?xml version="1.0"?><w:styles {NS}><w:style w:styleId="Titre1"><w:name w:val="heading 1"/>'
              "</w:style></w:styles>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", body)
        z.writestr("word/styles.xml", styles)


def zotero(*items):
    data = {"citationID": "x", "citationItems": [
        {"id": n, "uris": [f"http://zotero.org/users/1/items/{key}"], "itemData": item}
        for n, (key, item) in enumerate(items, 1)]}
    return "ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(data)


QUANJER = {"type": "article-journal", "title": "Multi-ethnic reference values for spirometry for the 3-95-yr age "
           "range: the global lung function 2012 equations", "author": [{"family": "Quanjer", "given": "P"}],
           "issued": {"date-parts": [[2012]]}, "DOI": QUANJER_DOI}
MILLER = {"type": "article-journal", "title": "Standardisation of spirometry", "author": [{"family": "Miller"}],
          "issued": {"date-parts": [[2005]]}, "DOI": MILLER_DOI}


async def test_word_with_zotero_fields(tmp_path, src):
    f = tmp_path / "paper.docx"
    docx(f, [
        para(run("Introduction"), style="Titre1"),
        para(run("Reference equations cover the age range 3 to 95 years"),
             field(zotero(("AAAA1111", QUANJER), ("BBBB2222", MILLER)), "(1,2)", split=True), run(".")),
        para(run("Spirometry has standards"), field(zotero(("BBBB2222", MILLER)), "(2)"), run(".")),
        para(run("Asthma affects 300 million people worldwide and the prevalence keeps rising in cities.")),
    ])
    doc = read_manuscript(f)
    assert doc.style == "fields" and doc.unit == "paragraph"
    assert set(doc.references) == {"AAAA1111", "BBBB2222"}
    assert [(c.key, c.line) for c in doc.citations] == [("AAAA1111", 2), ("BBBB2222", 2), ("BBBB2222", 3)]
    assert "(1,2)" not in doc.citations[0].sentence
    assert [u["line"] for u in doc.uncited_sentences] == [4]
    result = await check_document(doc, src)
    assert result["summary"]["pass"] == 2 and result["unit"] == "paragraph"


def test_word_with_endnote_fields(tmp_path):
    record = ("<EndNote><Cite><Author>Miller</Author><Year>2005</Year><RecNum>12</RecNum><record>"
              "<rec-number>12</rec-number><contributors><authors><author>Miller, M. R.</author>"
              "<author>Hankinson, J.</author></authors></contributors><titles><title>Standardisation of "
              "spirometry</title><secondary-title>Eur Respir J</secondary-title></titles><dates><year>2005</year>"
              f"</dates><electronic-resource-num>{MILLER_DOI}</electronic-resource-num></record></Cite></EndNote>")
    f = tmp_path / "paper.docx"
    docx(f, [para(run("Spirometry needs standards"), field("ADDIN EN.CITE " + record, "[1]"),
                  run("."))])
    doc = read_manuscript(f)
    ref = doc.references["Miller2005-12"]
    assert ref.doi == MILLER_DOI and ref.authors == ["Miller", "Hankinson"] and ref.year == "2005"
    assert doc.citations[0].key == "Miller2005-12"


def b64(data):
    return base64.b64encode(json.dumps(data).encode()).decode()


def mendeley_cite(shown, *items):
    data = {"citationID": "MENDELEY_CITATION_1de18c13", "properties": {"noteIndex": 0}, "isEdited": False,
            "citationItems": [{"id": uid, "itemData": {**item, "id": uid}} for uid, item in items]}
    return (f'<w:sdt><w:sdtPr><w:tag w:val="MENDELEY_CITATION_v3_{b64(data)}"/><w:id w:val="-14"/></w:sdtPr>'
            f"<w:sdtContent>{run(shown)}</w:sdtContent></w:sdt>")


def test_word_with_mendeley_cite(tmp_path):
    f = tmp_path / "paper.docx"
    docx(f, [
        para(run("Reference equations cover the age range 3 to 95 years "),
             mendeley_cite("(Quanjer et al., 2012; Miller, 2005)",
                           ("e219b34e-d397-37b4-818e-80ca578eae74", QUANJER),
                           ("0a1b2c3d-1111-2222-3333-444455556666", MILLER)), run(".")),
        para(run("Spirometry has standards "),
             mendeley_cite("(Miller, 2005)", ("0a1b2c3d-1111-2222-3333-444455556666", MILLER)), run(".")),
    ])
    doc = read_manuscript(f)
    assert doc.style == "fields"
    assert set(doc.references) == {"Quanjer2012-e219", "Miller2005-0a1b"}
    assert doc.references["Quanjer2012-e219"].doi == QUANJER_DOI
    assert [(c.key, c.line) for c in doc.citations] == [("Quanjer2012-e219", 1), ("Miller2005-0a1b", 1),
                                                         ("Miller2005-0a1b", 2)]
    assert "Quanjer et al." not in doc.citations[0].sentence


def citavi(*refs):
    data = {"$id": "1", "$type": "SwissAcademic.Citavi.Citations.WordPlaceholder", "Entries": [
        {"$id": str(10 + n), "Id": f"entry{n}", "ReferenceId": rid, "Reference": ref}
        for n, (rid, ref) in enumerate(refs)], "Tag": "CitaviPlaceholder#550e8400", "WAIVersion": "6.14.0.0"}
    return "ADDIN CitaviPlaceholder{" + b64(data) + "}"


def test_word_with_citavi_fields(tmp_path):
    miller = {"$id": "2", "ReferenceType": "JournalArticle", "Title": "Standardisation of spirometry",
              "Authors": [{"$id": "3", "FirstName": "Martin", "MiddleName": "R.", "LastName": "Miller"},
                          {"$id": "4", "LastName": "Hankinson"}],
              "Year": "2005", "Doi": MILLER_DOI, "PubMedId": "16055882", "Volume": "26", "Number": "2",
              "PageRange": "<sp>\r\n  <n>319</n>\r\n</sp>\r\n<ep>\r\n  <n>338</n>\r\n</ep>\r\n<os>319-338</os>",
              "Periodical": {"$id": "5", "Name": "European Respiratory Journal"}}
    later = {"$id": "6", "ReferenceType": "JournalArticle", "Title": "Another paper on spirometry",
             "Authors": [{"$ref": "3"}], "Year": "2006", "Periodical": {"$ref": "5"}}
    f = tmp_path / "paper.docx"
    sdt = ('<w:sdt><w:sdtPr><w:alias w:val="To edit, see citavi.com/edit"/><w:tag w:val="CitaviPlaceholder#550e8400"/>'
           "</w:sdtPr><w:sdtContent>{}</w:sdtContent></w:sdt>")
    docx(f, [para(run("Spirometry needs standards "),
                  sdt.format(field(citavi(("b213355e-df97-4b43-9e69-8a185817ce57", miller),
                                          ("c0ffee00-df97-4b43-9e69-8a185817ce57", later)),
                                   "(Miller et al. 2005; Miller 2006)", split=True)), run("."))])
    doc = read_manuscript(f)
    assert doc.style == "fields"
    ref = doc.references["Miller2005-b213"]
    assert ref.doi == MILLER_DOI and ref.pmid == "16055882" and ref.authors == ["Miller", "Hankinson"]
    assert ref.year == "2005" and ref.title == "Standardisation of spirometry"
    other = doc.references["Miller2006-c0ff"]
    assert other.authors == ["Miller"] and other.container == "European Respiratory Journal"
    assert [c.key for c in doc.citations] == ["Miller2005-b213", "Miller2006-c0ff"]
    assert "Miller et al." not in doc.citations[0].sentence


def test_word_without_fields_and_a_numbered_word_list(tmp_path):
    f = tmp_path / "plain.docx"
    docx(f, [para(run("Spirometry needs standards [1].")),
             para(run("References"), style="Titre1"),
             para(run(f"Miller MR, Hankinson J. Standardisation of spirometry. Eur Respir J. 2005. doi:{MILLER_DOI}"),
                  numbered=True)])
    doc = read_manuscript(f)
    assert doc.style == "numbered"
    assert doc.references["1"].doi == MILLER_DOI


def test_latex_with_bibtex(tmp_path):
    (tmp_path / "refs.bib").write_text(f"@article{{miller, title={{Standardisation of spirometry}}, "
                                       f"author={{Miller, M.}}, year=2005, doi={{{MILLER_DOI}}}}}\n"
                                       "@article{other, title={Other}, year=2001}\n")
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\usepackage{natbib}\n\\date{2024-03-01}\n\\begin{document}\n"
        "\\section{Introduction}\n"
        "% a comment that cites \\cite{ghost}\n"
        "Spirometry needs standards~\\citep[p.~3]{miller}. As \\citet{miller,other} showed.\n"
        "\\begin{figure}\\caption{Prevalence rose by 30\\% \\cite{fig}}\\end{figure}\n"
        "\\bibliography{refs}\n\\end{document}\n")
    doc = read_manuscript(tmp_path / "paper.tex")
    assert doc.style == "citekey" and doc.date == "2024-03-01"
    assert [(c.key, c.line) for c in doc.citations] == [("miller", 7), ("miller", 7), ("other", 7)]
    assert doc.bibliography[0].endswith("refs.bib")
    assert not doc.missing()


def test_latex_with_thebibliography(tmp_path):
    (tmp_path / "p.tex").write_text(
        "\\begin{document}\nSpirometry needs standards \\cite{mil05}.\n"
        "\\begin{thebibliography}{9}\n\\bibitem{mil05} M.~R. Miller, \\emph{Standardisation of spirometry}, "
        f"Eur Respir J (2005). doi:{MILLER_DOI}\n\\end{{thebibliography}}\n\\end{{document}}\n")
    doc = read_manuscript(tmp_path / "p.tex")
    assert doc.style == "numbered"
    assert doc.references["1"].doi == MILLER_DOI
    assert doc.citations[0].key == "1" and doc.citations[0].line == 2


AUTHOR_YEAR = f"""# Background

Spirometry needs standards (Miller et al., 2005; see Quanjer 2012a, p. 4). Quanjer et al. (2012a) derived
equations for all ages. Later work agreed (Quanjer, 2012b). An uncited claim (Nobody, 2019).

## References

Miller, M. R., Hankinson, J., & Brusasco, V. (2005). Standardisation of spirometry. European Respiratory
  Journal, 26(2), 319-338. https://doi.org/{MILLER_DOI}

Quanjer, P. H., Stanojevic, S., & Cole, T. J. (2012a). Multi-ethnic reference values for spirometry for the
  3-95-yr age range: The global lung function 2012 equations. European Respiratory Journal, 40(6), 1324-1343.

Quanjer, P. H. (2012b). Another paper on lung function. Thorax, 1, 1-2.

van der Berg, J. (2010). Never cited here. Lung, 1, 1.
"""


def test_author_year(tmp_path):
    f = tmp_path / "apa.md"
    f.write_text(AUTHOR_YEAR)
    doc = read_manuscript(f)
    assert doc.style == "authoryear"
    assert list(doc.references) == ["miller2005", "quanjer2012a", "quanjer2012b", "vanderberg2010"]
    assert doc.references["miller2005"].doi == MILLER_DOI
    keys = [c.key for c in doc.citations]
    assert keys.count("quanjer2012a") == 2 and "miller2005" in keys and "quanjer2012b" in keys
    assert doc.missing() == {"Nobody 2019": [4]}
    assert doc.unused() == ["vanderberg2010"]


def test_author_year_sentences_count_as_cited():
    assert has_citation("Asthma affects 300 million people (Smith et al., 2020).")
    assert has_citation("Smith et al. (2020a) found a 20% fall in FEV1.")
    assert not has_citation("Asthma affects 300 million people in 2020.")


def test_word_superscript_citations_and_endnote_data(tmp_path):
    import base64
    sup = '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>{}</w:t></w:r>'
    record = ("<EndNote><Cite><Author>Miller</Author><Year>2005</Year><RecNum>7</RecNum><record><titles><title>"
              "Standardisation of spirometry</title></titles><dates><year>2005</year></dates>"
              f"<electronic-resource-num>{MILLER_DOI}</electronic-resource-num></record></Cite></EndNote>")
    data = base64.b64encode(record.encode()).decode()
    endnote = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> ADDIN EN.CITE </w:instrText></w:r>'
               f'<w:r><w:fldChar w:fldCharType="begin"><w:fldData>{data}</w:fldData></w:fldChar></w:r>'
               '<w:r><w:instrText> ADDIN EN.CITE.DATA </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
               '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run("(1)") +
               '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    f = tmp_path / "sup.docx"
    docx(f, [para(run("Tiago Jacinto"), sup.format("1")),
             para(run("Introduction"), style="Titre1"),
             para(run("Mean BMI was 24 kg/m"), sup.format("2"), run(" in adults with asthma, as reported"),
                  sup.format("1,"), sup.format("2"), run(".")),
             para(run("Spirometry needs standards "), endnote, run("."))])
    doc = read_manuscript(f)
    assert doc.references["Miller2005-7"].doi == MILLER_DOI
    from starbuck.formats import docx_to_markdown
    text = docx_to_markdown(f)[0]
    assert "Jacinto1" in text and "kg/m2 in adults" in text and "reported [1,2]." in text


def test_numbered_list_without_heading_and_bare_numbers(tmp_path):
    f = tmp_path / "erj.md"
    f.write_text("Spirometry needs standards [1]. Equations exist [2, 3].\n\n"
                 "1 Miller MR, Hankinson J. Standardisation of spirometry. Eur Respir J 2005; 26: 319-338.\n\n"
                 "2 Quanjer PH. Multi-ethnic reference values. Eur Respir J 2012; 40: 1324-1343.\n\n"
                 "(3)Graham BL. Standardization of spirometry 2019 update. AJRCCM 2019; 200: e70-e88.\n")
    doc = read_manuscript(f)
    assert doc.style == "numbered"
    assert list(doc.references) == ["1", "2", "3"]
    assert [c.key for c in doc.citations] == ["1", "2", "3"]


def test_abstract_and_labelled_paragraphs_are_not_listed(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Abstract\n\nAsthma affects 300 million people worldwide and the prevalence keeps rising.\n\n"
                 "# Introduction\n\nResults: Higher FGF-23 was associated with lower FEV1 in 203 children here.\n\n"
                 "Asthma affects 300 million people worldwide and the prevalence keeps rising today.\n")
    doc = read_manuscript(f)
    assert [u["line"] for u in doc.uncited_sentences] == [9]


async def test_fix_never_writes_into_a_word_file(tmp_path, src):
    from starbuck.fix import apply_plan, propose
    f = tmp_path / "plain.docx"
    docx(f, [para(run("Spirometry needs standards [1].")), para(run("References"), style="Titre1"),
             para(run("Miller MR, Hankinson J. Standardisation of spirometry. Eur Respir J. 2005;26:319-38."),
                  numbered=True)])
    doc = read_manuscript(f)
    plan = await propose(doc, await check_document(doc, src), src)
    assert plan.changes and apply_plan(doc, plan) == {}
