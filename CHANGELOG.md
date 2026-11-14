# Changes

Starbuck follows semantic versions. Before 1.0, a change in the second number (0.4) can add commands, options and result codes; the meaning of Fail, Check, Note and Pass does not change.

## 0.4.1 (2026-11-14)

- Word: citations inserted with Mendeley Cite (the current Mendeley add-in) and Citavi are read, with their records, like those of Zotero, Mendeley Desktop and EndNote. Paragraphs inside content controls are read.
- Validation: result and recording files carry the Starbuck version, so two runs on the same day do not replace each other. Level 4 judge results with Claude Sonnet 5.5: 48 of 60 SciFact cases and 25 of 40 PubMedQA cases with the expected verdict.

## 0.4.0 (2026-11-14)

Word, LaTeX and author-year manuscripts.

- Word (`.docx`): the citation fields of Zotero, Mendeley Desktop and EndNote give the cited records, so no bibliography file is needed. Without fields, the text is read: numbered, superscript and author-year citations, and the numbers of Word lists in the reference list. The report gives paragraph numbers.
- LaTeX (`.tex`): `\cite` and its natbib and biblatex forms, the `\bibliography` and `\addbibresource` files, and `thebibliography`.
- Author-year citations (APA, Harvard) with an unnumbered reference list.
- Numbered reference lists without a heading, and entries numbered `(1)` or `1 Name`.
- Sentences without a citation: the abstract, labelled paragraphs ("Results:"), conclusions, back matter, figure sections and sentences about the authors' own study are left out.
- `starbuck fix` never writes into a Word or LaTeX file.

## 0.3.0 (2026-11-14)

- References without an identifier are searched in PubMed, OpenAlex, DataCite and Open Library after Crossref. A PMCID is looked up in Europe PMC. A dead link gets its Wayback Machine copy.
- `starbuck fix` and the MCP tool `fix_references`: corrections that the records support, as a diff; `--in-place` applies them and keeps a `.bak` copy.
- Level 4: full texts from the Zotero library (`--zotero`), arXiv PDFs and open-access PDFs found through Unpaywall; a check of the numbers of the citing sentence; an optional second judge.
- A cache of the services' answers; several manuscripts in one run; `--if-cited`; retraction dates against the manuscript date; a GitHub Action and a pre-commit hook.
- A retraction that only OpenAlex reports is a Check; a DOI and a PMID with the same title are a Check; a web page that refuses programs is a Note.
- Fixes: DOIs with angle brackets (SICI), first authors and years in numbered entries, titles in their original language, unreadable service answers, BibTeX month macros, judges that refuse a temperature setting.
- Validation: 65 of 65 injected errors found with the expected result, 50 of 50 correct references passed.

## 0.2.0 (2026-10-05)

First public version: levels 1 to 4 for Markdown and Quarto manuscripts, a Quarto report in HTML or Word, a JSON result, and the MCP server used by Sub-Sub.
