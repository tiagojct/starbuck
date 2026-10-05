# Starbuck

Reference-integrity checks for manuscripts. Starbuck reads a Markdown or Quarto
manuscript with its bibliography and checks each cited reference against public
scholarly records. It writes a Quarto report that renders to HTML or Word.

> *"I will have no man in my boat," said Starbuck, "who is not afraid of a whale."*
> Herman Melville, *Moby-Dick*, chapter 26

## What it checks

| Level | Question | Sources |
|---|---|---|
| 1. Exists | Does the DOI, PMID, arXiv ID or ISBN resolve? Without an identifier, can the work be found? | Crossref, DataCite, doi.org, PubMed, arXiv, Open Library, Crossref search |
| 2. Matches | Do the cited title, first author and year agree with the record? | The record from level 1 |
| 3. Stands | Is the work retracted, under an expression of concern or corrected? Is it a notice itself? Was a cited preprint published? | Crossref (with Retraction Watch data), PubMed, OpenAlex, arXiv |
| 4. Supports (optional) | Does the source support the sentence that cites it? | Europe PMC open-access full text or the abstract (PubMed, Europe PMC, Crossref, OpenAlex); a language model judges |

Each reference gets one result:

| Result | Meaning |
|---|---|
| Fail | The identifier does not exist, belongs to a different work, two identifiers disagree, or the work was retracted. |
| Check | A person should look: a field differs, an expression of concern, a possible match only, an unreachable web page. |
| Note | Information that needs no change in most cases: a correction, a published version of a preprint, a DOI found by search. |
| Pass | Nothing found. |
| Not checked | A service did not answer. Run the check again later. |

The report also lists citations without a bibliography entry, entries that
the text does not cite, and sentences that state a finding without a citation.
A sentence is listed when it has at least 50 characters, cites nothing, and
has a number with a unit or a percentage, an effect measure (OR, HR, RR, CI)
or a claim word such as found, showed, increased, reduced, associated with,
risk or prevalence. Headings, tables, figures, captions, code, the reference
list and sections headed Methods or Results are left out: the authors' own
methods and data need no citation. The rules are simple and English only, so
the list is for a person to read; it never makes a reference Fail or Check.
The JSON keeps the first 50 sentences under `uncited_sentences` (the key
`uncited` lists the bibliography entries that are not cited).

Level 4 adds a verdict for each citing sentence: Supported, Partly supported,
Not supported or Cannot assess. Level 4 never makes a reference Fail: Not
supported is Check and Partly supported is Note, so a person decides. See
[Level 4](#level-4-claim-support).

## Install

Starbuck needs Python 3.11 or later and [uv](https://docs.astral.sh/uv/).
For HTML and Word reports, install [Quarto](https://quarto.org). If Quarto is
not installed, Starbuck uses Pandoc when it is available.

1. Install Starbuck:

   ```sh
   uv tool install starbuck
   ```

2. Set a contact address. The services give faster, more reliable access to
   requests that identify their sender:

   ```sh
   export STARBUCK_EMAIL=you@example.org
   ```

3. Check the installation:

   ```sh
   starbuck --version
   ```

## Use

Check a manuscript. The bibliography comes from the `bibliography:` field in the
YAML header:

```sh
starbuck check paper.qmd
```

Starbuck writes the report to a folder named `_starbuck` next to the manuscript.
Quarto ignores folders that start with an underscore, so the report does not
become part of a Quarto project.

More options:

```sh
starbuck check paper.qmd --to html,docx      # HTML and Word
starbuck check paper.md --bib refs.bib       # bibliography not in the YAML header
starbuck check paper.qmd --all-entries       # also check entries that are not cited
starbuck check paper.qmd --out reports/      # another report folder
starbuck ids 10.1183/09031936.00080312 arXiv:1706.03762
starbuck check paper.qmd --claims            # also level 4 (see below)
```

To check a Word manuscript, convert it to Markdown first:

```sh
quarto pandoc paper.docx -o paper.md
```

### Input

Starbuck reads two citation styles:

- Citation keys: Pandoc citations such as `[@key]`, `[see @key, p. 3; @other]`
  and `@key` in running text. The bibliography can be BibTeX or BibLaTeX
  (`.bib`), CSL JSON (`.json`) or CSL YAML (`.yaml`), or `references:` in the
  YAML header.
- Numbered references: `[1]`, `[2, 5]`, `[3-4]` in the text, with a numbered list
  under a heading such as References or Sources. AI research agents often write
  this format.

### Output

| File | Contents |
|---|---|
| `<name>-references.qmd` | The report. Edit it or render it again with Quarto. |
| `<name>-references.html` | The report as one self-contained web page. |
| `<name>-references.docx` | The report for Word, with `--to docx`. |
| `<name>-references.json` | Every result, finding and record, for other tools. |
| `<name>-claims.json` | Level 4 only: passages, source texts and the model's answers. |

The report starts with a summary, then the references that need attention, each
with the reason, the cited and the recorded metadata side by side, the sentence
that cites it, and a suggested action. A section at the end states the rules and
the services used.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | No reference failed. |
| 1 | At least one reference failed, or a cited key has no entry. |
| 2 | The check could not run (for example, no citations found). |
| 3 | No reference failed, but some checks did not run. |

## Level 4: claim support

For each sentence that cites a source, Starbuck takes the best text of that
source: a local text file you give, open-access full text from Europe PMC, or
otherwise the abstract. It ranks the passages of that text against the
sentence (BM25) and gives the best five to a language model. The model answers
Supported, Partly supported, Not supported or Cannot assess, and quotes the
passage it relies on. Starbuck then checks that the quotation appears word for
word in the source text. A quotation that is not there is rejected, and the
verdict becomes Cannot assess. The report states for each verdict whether it
rests on the full text or on the abstract only.

The report also gives two scores over the judged citations (Cannot assess is
left out). Citation recall: the share of citing sentences with at least one
citation judged Supported or Partly supported. Citation precision: the share
of citations judged Supported or Partly supported. A citation judged Not
supported in a sentence that another of its sources supports gets a Note
(overcitation): it adds no support. The idea comes from ScholarQABench
(OpenScholar).

1. Set the model. Any OpenAI-compatible endpoint works (a hosted provider, or a
   local server such as Ollama):

   ```sh
   export STARBUCK_JUDGE_URL=https://api.example.org/v1
   export STARBUCK_JUDGE_MODEL=model-name
   export STARBUCK_JUDGE_KEY=...        # if the endpoint needs a key
   ```

2. Run the check with `--claims`:

   ```sh
   starbuck check paper.qmd --claims
   starbuck check paper.qmd --claims --text smith2020=smith2020.txt   # full text you have
   ```

Without `--claims`, or without the model settings, level 4 does not run and the
report says so. Level 4 sends the citing sentences and the source passages to
the model's provider. The file `<name>-claims.json` in `_starbuck` keeps the
passages, the source texts and the model's answers.

A language model can be wrong. Read the source before you change the text.

## Settings

| Variable | Purpose |
|---|---|
| `STARBUCK_EMAIL` | Contact address for the services. `ZOTERO_CONTACT_EMAIL` also works. |
| `NCBI_API_KEY` | Higher request rate for PubMed. |
| `OPENALEX_API_KEY` | OpenAlex API key. |
| `QUARTO_PATH` | Path to Quarto when it is not on the PATH. |
| `STARBUCK_JUDGE_URL`, `STARBUCK_JUDGE_MODEL`, `STARBUCK_JUDGE_KEY` | Level 4 model (OpenAI-compatible endpoint). |

## Use from an agent (MCP)

`starbuck-mcp` is an MCP server with four tools:

- `check_manuscript`: checks a manuscript and writes the report.
- `check_references`: checks references given directly (an identifier, citation
  details, or both). An agent can use it to check the sources of a text it wrote.
- `prepare_claims`: level 4, step 1. Checks the references and returns each
  citing sentence with the best passages of its source. A local full text can
  be given per citation key.
- `record_claims`: level 4, step 2. Takes the agent's verdicts, checks the
  quoted passages and adds level 4 to the report.

Inside an agent, the agent's own model judges, so no `STARBUCK_JUDGE_*`
settings are needed.

In [Sub-Sub](https://github.com/tiagojct/subsub), turn on reference checks in
`subsub init` or with the switch in the web view; Sub-Sub then runs Starbuck as
its `verify` server.

Example configuration for an MCP client:

```json
{
  "mcpServers": {
    "starbuck": {
      "command": "uvx",
      "args": ["--from", "starbuck", "starbuck-mcp"],
      "env": { "STARBUCK_EMAIL": "you@example.org" }
    }
  }
}
```

## Privacy

Starbuck sends identifiers and reference details (title, authors, year, or the
reference as written) to the services listed above, and it opens cited web
pages. Levels 1 to 3 do not send the manuscript text. Level 4 (only with
`--claims`) sends the citing sentences and source passages to the model you
set. Starbuck collects no usage data.

## Demo

`examples/demo.qmd` cites real works, each set up to show one kind of result:
a correct reference, a wrong year, a DOI that belongs to another paper, a DOI
that does not exist, a retracted paper, a reference without a DOI, an arXiv
preprint and a citation without an entry.

```sh
starbuck check examples/demo.qmd --to html,docx
```

## Development

```sh
uv sync
uv run pytest -q
```

The tests use canned service responses and do not need the network.

## License

[MIT](LICENSE) © Tiago Jacinto
