# Starbuck validation set

Test data for Starbuck and the validation data for the paper on the screening
tool. This folder is not part of the package.

## Contents

| File | Contents |
|---|---|
| `sources.csv` | The hand-picked works: key, group, PMID, DOI. The only input written by hand. |
| `build.py` | Checks every source and every injected error against the live services, then writes the files below. Writes nothing when a check fails. |
| `references.bib`, `manuscript.qmd` | The validation manuscript: one citation per entry. |
| `truth.csv` | key, error_type, expected_verdict, expected_code. |
| `injections.csv` | What was changed in each entry and how the change was confirmed. |
| `evidence/build.json` | The Crossref, PubMed and OpenAlex records the build used, with the build time. |
| `run.py` | Runs Starbuck and scores it against `truth.csv`. |
| `recordings/<date>.json.gz` | Every service answer of one run, to repeat it without the network. |
| `results/` | Starbuck's JSON and the scores (Markdown and CSV) of each run. |
| `claims.csv`, `check_claims.py`, `evidence/abstracts.json` | Level 4 cases (claim support). |
| `run_claims.py`, `claims.qmd` | Runs level 4 on the cases (`claims.qmd` is written from `claims.csv`) and scores it. |
| `build_judge_cases.py`, `judge_cases.jsonl` | Independent level 4 judge set from SciFact and PubMedQA (see below). |
| `judge_external.py` | Runs Starbuck's judge and quote check on `judge_cases.jsonl` and scores it. |

## Sources

- 50 clean base references (respiratory medicine and health informatics).
  Each one passed these checks: the PubMed record gives the DOI; the DOI is
  in Crossref and registered at doi.org; a PubMed search for the DOI gives the
  same PMID; title and first author agree between PubMed and Crossref; no
  update notice in Crossref, no linked notice in PubMed (CommentsCorrections),
  not retracted in OpenAlex.
- 5 retracted works: a retraction notice in Crossref (Retraction Watch),
  "Retracted Publication" or a linked retraction in PubMed, retracted in
  OpenAlex.
- 4 works with an expression of concern and no retraction in any source.
- 12 corrected works: a correction, erratum or addendum in Crossref or PubMed,
  and no stronger notice. Six of them have the erratum only in PubMed.
- 5 medRxiv preprints with a published version that Crossref links.

Excluded on purpose: reporting guidelines published in several journals
(TRIPOD 2015, PRISMA 2020, CONSORT-AI), group authors, book chapters.

## Injected errors

Each injected entry copies one clean base reference and changes one thing. A
base reference is the target of at most one injection.

| Error type | Entries | Change | Expected |
|---|---|---|---|
| fabricated_doi | 4 | last digits of the DOI changed; confirmed absent from Crossref, DataCite, doi.org and PubMed | fail, doi_not_found |
| doi_of_other_paper | 4 | DOI of another source | fail, wrong_work |
| pmid_of_other_paper | 4 | PMID of another source, no DOI | fail, wrong_work |
| doi_pmid_disagree | 4 | own DOI, PMID of another source | fail, id_conflict |
| wrong_year | 4 | year 3 years off; more than 1 year from every source's year | warn, year_differs |
| wrong_first_author | 4 | first author replaced by a name not among the record's authors | warn, author_differs |
| author_order | 4 | first two authors swapped | warn, author_order |
| no_identifier_real | 4 | DOI and PMID removed | note, add_identifier |
| no_identifier_invented | 4 | invented reference (authors named after Melville's harpooners); no similar title in Crossref or PubMed | warn, not_found |
| dead_web_page | 3 | web page that answers 404, or a `.invalid` domain | warn, web_unreachable |

Retracted, concern, corrected and preprint entries are cited correctly; the
expected results are fail retracted, warn concern, note corrected and note
preprint_published.

## Use

```sh
export STARBUCK_EMAIL=you@example.org
uv run python validation/build.py                 # rebuild (only when sources.csv or the plan changes)
uv run python validation/run.py --record          # live run, saves the service answers
uv run python validation/run.py --replay validation/recordings/2026-10-04.json.gz
uv run python validation/check_claims.py
```

A replay sends no requests; a request that is not in the recording counts as a
service failure and the entry as not checked. Recordings leave out the contact
address and API keys, and keep only the status of web pages.

## Scores

Strict: the expected verdict and the expected finding code. Flagged: any
result other than Pass. Specificity: clean entries with Pass. Entries that
could not be checked are counted apart. 95% Wilson intervals.

## Level 4 cases

`claims.csv`: 20 citing sentences on 5 sources, 5 per label (supported,
partly_supported, contradicted, not_addressed). Each passage is quoted word for
word from the PubMed abstract in `evidence/abstracts.json`; `check_claims.py`
confirms this. The labels are drafts (status `draft`) until a person reviews
them.

`run_claims.py` needs a judge model (`STARBUCK_JUDGE_URL`, `STARBUCK_JUDGE_MODEL`,
`STARBUCK_JUDGE_KEY`); `--evidence-only` runs without one and shows which text
each case gets. Labels map to Starbuck's verdicts as follows: contradicted and
not_addressed both expect not_supported. `--record` saves the service and model
answers (without the key) so a run can be replayed.

The cases and their draft labels were written by the assistant that also
wrote Starbuck's judge prompt. Results on them show that level 4 works as
designed; they are not an independent accuracy estimate.

## Independent judge set (SciFact and PubMedQA)

`judge_cases.jsonl` has 100 cases that Starbuck's author did not write or
label: 60 from the SciFact dev set (20 SUPPORT, 20 CONTRADICT, 20 NOINFO) and 40
from PubMedQA PQA-L (15 yes, 15 no, 10 maybe), drawn with a fixed seed and
stratified by label. ScholarQABench (OpenScholar) uses both datasets; each case
says whether ScholarQABench's own file has it (`in_scholarqabench`: 40 SciFact
and 29 PubMedQA cases). Every case keeps its dataset, its identifier (SciFact
claim id and corpus doc_id; PubMedQA PMID), the label and the source.

`build_judge_cases.py` downloads the source files, checks each against a
SHA-256, and writes the set again byte for byte:

- SciFact: claims with one cited abstract and one label. The citing sentence
  is the claim; the source text is the cited abstract.
- PubMedQA: the source text is the abstract without its conclusion
  (`CONTEXTS`). A PubMedQA item is a question, so the citing sentence comes from
  one fixed template: `This study found that the answer to the question "..."
  is yes.` The sentence reads less naturally than a real citing sentence.

| Dataset label | Strict | Lenient |
|---|---|---|
| SciFact SUPPORT | supported | supported |
| SciFact CONTRADICT | not_supported | not_supported |
| SciFact NOINFO | not_supported | not_supported or cannot_assess |
| PubMedQA yes | supported | supported |
| PubMedQA no | not_supported | not_supported |
| PubMedQA maybe | partly_supported | partly_supported or cannot_assess |

`judge_external.py` bypasses retrieval: it splits and ranks each abstract as
Starbuck does with an abstract (80-word passages, best 5 by BM25), then runs
`claims.judge` and `claims.validate` unchanged against `STARBUCK_JUDGE_URL`,
`STARBUCK_JUDGE_MODEL` and `STARBUCK_JUDGE_KEY`. It reports agreement (strict
and lenient, 95% Wilson intervals), a confusion matrix, the quote rejection
rate and the number of false "supported" verdicts, in
`results/<date>-judge-<model>.md` and `.csv`. `--record` saves the judge's
answers (not the key); `--replay` repeats a run without the network.

```sh
uv run python validation/build_judge_cases.py     # only to rebuild judge_cases.jsonl
uv run python validation/judge_external.py --record
uv run python validation/judge_external.py --replay validation/recordings/<date>-judge-<model>.json.gz
```

No run against a real model has been made yet.

### Licences

All three allow the cases to be copied with attribution, so `judge_cases.jsonl`
is in the repository. The licences, quoted from the sources on 2026-10-05:

SciFact, `LICENSE.md` at https://github.com/allenai/scifact (commit
68b98a56d93e0f9da0d2aab4e6c3294699a0f72e):

> ## Claims
>
> All claims and evidence annotations -- in the files `claims_*.jsonl` -- are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
>
> ## Abstracts
>
> The abstracts in the corpus -- in the file `corpus.jsonl` -- are part of the Semantic Scholar [S2ORC dataset](https://github.com/allenai/s2orc) and are licensed under [ODC-By 1.0](https://opendatacommons.org/licenses/by/1-0/).

PubMedQA, `LICENSE` at https://github.com/pubmedqa/pubmedqa (commit
1cbae8e92f72f20c8d3747cbb3bf5bc53554d997). The repository has one licence,
which covers `data/ori_pqal.json`; its README names no separate data licence:

> MIT License
>
> Copyright (c) 2019 pubmedqa
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

ScholarQABench, `README.md` at https://github.com/AkariAsai/ScholarQABench
(commit 95e6fc52b0a8a0ce0a74956029991e3bb00c38b9), used here only to mark the
shared cases:

> The aggregate test cases, sample system answers under `data/src_answers` and other files under data directory are released under [ODC-BY](https://opendatacommons.org/licenses/by/1.0/) license.
> By downloading this data you acknowledge that you have read and agreed to all the terms in this license.
> For constituent datasets, also go through the individual licensing requirements, as applicable.

Not verified: the copyright of the abstract texts themselves rests with their
publishers; the dataset licences above are the licences their authors give.

Citations: Wadden D, et al. Fact or Fiction: Verifying Scientific Claims.
EMNLP 2020. Jin Q, et al. PubMedQA: A Dataset for Biomedical Research Question
Answering. EMNLP-IJCNLP 2019. Asai A, et al. OpenScholar: Synthesizing
Scientific Literature with Retrieval-augmented LMs. arXiv:2411.14199.
