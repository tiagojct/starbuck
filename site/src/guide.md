---
layout: base.njk
title: Guide
eyebrow: Install, check, correct
lead: Install Starbuck, check a manuscript, read the report and apply the corrections. Each step is one command.
---

## Install

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Install Starbuck:

   ```sh
   uv tool install starbuck
   ```

3. Set a contact address. The services answer faster, and more reliably, to requests that say who sends them:

   ```sh
   export STARBUCK_EMAIL=you@example.org
   ```

4. Check the installation:

   ```sh
   starbuck --version
   ```

For HTML and Word reports, install [Quarto](https://quarto.org). Without Quarto, Starbuck uses Pandoc if it is installed; without either, the report stays a `.qmd` file.

To update: `uv tool upgrade starbuck`.

## Check a manuscript

```sh
starbuck check paper.docx
```

Starbuck writes the report to a folder named `_starbuck` next to the manuscript and prints a summary. Quarto ignores folders that start with an underscore, so the report does not become part of a Quarto project.

More options:

```sh
starbuck check paper.qmd --to html,docx      # HTML and Word reports
starbuck check paper.md --bib refs.bib       # bibliography not named in the YAML header
starbuck check paper.qmd --all-entries       # also check entries that are not cited
starbuck check ch1.qmd ch2.qmd ch3.qmd       # several files, one report each
starbuck check paper.qmd --date 2026-03-01   # date of the manuscript, for retraction dates
starbuck ids 10.1183/09031936.00080312 arXiv:1706.03762
```

## Formats

| Manuscript | Citations | References |
|---|---|---|
| Word (`.docx`) | Zotero, Mendeley, EndNote or Citavi citations | Read from the citations: no file needed |
| Word (`.docx`) | `[1]`, superscript numbers, or (Smith, 2020) | The reference list at the end |
| LaTeX (`.tex`) | `\cite`, `\citep`, `\citet`, `\parencite`, `\textcite`, `\autocite` | `\bibliography{}` or `\addbibresource{}`, or `thebibliography` |
| Markdown, Quarto (`.md`, `.qmd`) | `[@key]`, `@key` | BibTeX, CSL JSON or CSL YAML named in the YAML header |
| Markdown, Quarto | `[1]`, `[2, 5]`, `[3-4]` | A numbered list under References or Sources, or at the end |
| Markdown, Quarto | (Smith et al., 2020), Smith (2020a) | An unnumbered list (APA, Harvard) |

In a Word file, the report gives paragraph numbers instead of line numbers. Superscript numbers on the title page (affiliations) and after units such as kg/m² are not taken for citations.

## Read the report

The report starts with a summary, then the references that need attention. Each one has the reason, the cited and the recorded details side by side, the sentence that cites it, and a suggested action.

| Result | Meaning | What to do |
|---|---|---|
| <span class="v fail">Fail</span> | The identifier does not exist, belongs to a different work, two identifiers disagree, or the work was retracted. | Correct or remove the reference. |
| <span class="v check">Check</span> | A field differs, an expression of concern, a possible match only, a page that is gone, or a work not confirmed. | Look at it. Not confirmed is not wrong: books and reports are often missing from the databases. |
| <span class="v note">Note</span> | A correction, a published version of a preprint, a DOI found by search, a page that refuses programs. | Nothing, in most cases. Adding a found DOI makes the reference checkable. |
| <span class="v pass">Pass</span> | Nothing found. | Nothing. |
| <span class="v none">Not checked</span> | A service did not answer. | Run the check again later. |

The report also lists citations without a reference, references that the text does not cite, and sentences that state a finding without a citation. That last list comes from simple rules and is for a person to read: it never changes a result. See [How it checks](/how-it-checks/#sentences-without-a-citation).

The exit code says the same in one number, for scripts:

| Code | Meaning |
|---|---|
| 0 | No reference failed. |
| 1 | At least one reference failed, or a citation has no reference. |
| 2 | The check could not run (for example, no citations found). |
| 3 | No reference failed, but some checks did not run. |

## Correct the references

`starbuck fix` checks the references, then writes corrected copies and one diff to `_starbuck`. It changes only what a record supports:

- adds a DOI, PMID or ISBN that a search found with a confidence of 0.9 or more, or the DOI that the PubMed record of a cited PMID gives;
- corrects the year or the title when the identifier is right but the field differs;
- replaces a cited preprint with its published version (DOI, year and journal);
- replaces a dead link with its Wayback Machine copy.

It lists everything else (a wrong DOI, a retraction, a wrong author) for you.

1. Read the diff:

   ```sh
   starbuck fix paper.qmd
   ```

2. Apply the changes. Starbuck keeps a `.bak` copy of each file that it changes:

   ```sh
   starbuck fix paper.qmd --in-place
   ```

BibTeX files keep their layout: only the changed fields change. CSL JSON and YAML files are written again. In a Markdown manuscript with a numbered or author-year list, Starbuck adds the identifiers to the entries. Word and LaTeX files are never changed: for these, Starbuck lists the changes, and a `.bib` file of a LaTeX manuscript is changed as usual.

## Claim support (level 4)

Level 4 asks whether each source supports the sentence that cites it. It is optional, because it sends the citing sentences to a language model.

1. Set the model. Any OpenAI-compatible endpoint works: a hosted provider, or a local server such as Ollama.

   ```sh
   export STARBUCK_JUDGE_URL=https://api.example.org/v1
   export STARBUCK_JUDGE_MODEL=model-name
   export STARBUCK_JUDGE_KEY=...        # if the endpoint needs a key
   ```

2. Run the check with `--claims`:

   ```sh
   starbuck check paper.qmd --claims
   starbuck check paper.qmd --claims --zotero                          # full texts from Zotero
   starbuck check paper.qmd --claims --text smith2020=smith2020.txt   # a full text you have
   ```

`--zotero` reads a copy of your Zotero database (`~/Zotero`, or the folder you give), so Zotero can stay open and the library does not change. A second model (`STARBUCK_JUDGE2_MODEL`) makes both judge every sentence; where they differ, the report keeps the less supportive verdict and shows both.

A language model can be wrong. Read the source before you change the text. In Sub-Sub, the model you already use judges, and no settings are needed: see [Starbuck in Sub-Sub](/sub-sub/).

## Settings

| Variable | Purpose |
|---|---|
| `STARBUCK_EMAIL` | Contact address for the services. Without it, Crossref allows one request at a time. |
| `NCBI_API_KEY` | Higher request rate for PubMed. |
| `OPENALEX_API_KEY` | OpenAlex API key. |
| `QUARTO_PATH` | Path to Quarto when it is not on the PATH. |
| `STARBUCK_JUDGE_URL`, `_MODEL`, `_KEY` | Level 4 model. |
| `STARBUCK_JUDGE2_MODEL`, `_URL`, `_KEY` | Optional second judge. URL and key default to the first judge's. |
| `STARBUCK_ZOTERO_DIR` | Zotero data folder for `--zotero`. |
| `STARBUCK_CACHE_DIR`, `STARBUCK_NO_CACHE` | Where the cache is kept; set `STARBUCK_NO_CACHE=1` to turn it off. |

Starbuck keeps the answers of the services in a cache, so a second run asks again only for new or changed references. Answers about retractions and corrections are kept for one day, records for seven. `starbuck cache --clear` empties it.

## Try it on the demo

The repository has a demo manuscript that cites real works, each chosen to show one kind of result: a correct reference, a wrong year, a DOI of another paper, a DOI that does not exist, a retracted paper, a reference without a DOI, an arXiv preprint and a citation without a reference.

```sh
git clone https://github.com/tiagojct/starbuck
starbuck check starbuck/examples/demo.qmd
```
