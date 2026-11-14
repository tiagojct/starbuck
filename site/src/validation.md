---
layout: base.njk
title: Validation
eyebrow: How well it checks, and the limits
lead: Two tests. One with errors put into correct references on purpose, run again for each release. One on 300 references from published articles, made for Sub-Sub. The author of Starbuck ran both; neither is an independent audit.
---

## Test 1: injected errors

The validation set has {{ validation.entries }} references in respiratory medicine and health informatics. 50 are correct references, each confirmed in PubMed, Crossref and OpenAlex. The others are correct references with one error put in, or works with a known status: retracted, under an expression of concern, corrected, or a preprint that was published later. Each injected error was confirmed against the live services before the test, and the expected result was written down first.

Latest run: {{ validation.date }}, Starbuck {{ validation.version }}, against the live services.

<div class="figures">
<div><b>{{ validation.strict.k }}/{{ validation.strict.n }}</b><span>errors found with the expected result and reason ({{ validation.strict.pct }}%; 95% CI {{ validation.strict.lo }} to {{ validation.strict.hi }})</span></div>
<div><b>{{ validation.flagged.k }}/{{ validation.flagged.n }}</b><span>errors flagged with any result other than Pass</span></div>
<div><b>{{ validation.specificity.k }}/{{ validation.specificity.n }}</b><span>correct references that passed ({{ validation.specificity.pct }}%; 95% CI {{ validation.specificity.lo }} to {{ validation.specificity.hi }})</span></div>
</div>

| Kind of reference | Entries | Expected result found |
|---|---|---|
{%- for t in validation.types %}
| {{ t.type }} | {{ t.entries }} | {{ t.strict }}/{{ t.of }} |
{%- endfor %}

The kinds: a fabricated DOI (changed digits, confirmed to resolve nowhere); the DOI or PMID of another paper; a DOI and a PMID of two different papers; a year three years off; a wrong first author; the first two authors swapped; a real work without its identifiers; an invented work without identifiers; a web page that is gone.

Each release is also run against a recording of the services' answers, so a change to the code that changes a result shows at once. The set, the scripts and every result are in the repository: [validation/](https://github.com/tiagojct/starbuck/tree/main/validation).

**Limits.** The set is small, so each confidence interval is wide. The author chose the works and built the errors. The works are biomedical and in English, and almost all have a DOI: this is where Starbuck is strongest.

## Test 2: 300 references from published articles

Before Sub-Sub 0.20, Starbuck 0.2.0 was tested on 300 references from open-access articles in biomedicine, the social sciences and the humanities, in English and Portuguese. 90 were altered.

- All 36 invented or recombined references were flagged, or left as not confirmed.
- 30% of the existing references could not be confirmed: 4% in biomedicine, 29% in the social sciences and 67% in the humanities. Books and works in Portuguese were the most often not confirmed. No reference with a DOI was.
- Claim support marked 12 of 15 misattributed citations as not supported. It marked only 5 of 15 distorted claims, and it marked 8 of 30 unaltered pairs as partly or not supported.

The full test is on the [Sub-Sub Tests page]({{ site.subsub }}/tests/).

Since then, version 0.3.0 added searches in PubMed, OpenAlex, DataCite and Open Library for references without an identifier, which is where most of the unconfirmed references were. This test has not been run again yet.

## What this means when you use it

- A Fail is strong evidence. Check it, then correct the reference.
- Not confirmed is not wrong. Outside biomedicine, and for books, reports and works in Portuguese, expect references that Starbuck cannot confirm. Check them in a library catalogue or on the publisher's page.
- Claim support finds citations of the wrong work better than claims that overstate a source. Treat its verdicts as sentences to read again.

## Not measured yet

- Claim support on an independent set. The repository has 100 cases from SciFact and PubMedQA, ready to run against a judge model; no run has been made yet.
- Word and LaTeX input on a large set of real manuscripts.
