---
layout: base.njk
title: How it checks
eyebrow: The rules, the sources and the limits
lead: Every report ends with the rules it applied. This page gives the same rules, with the reasons for them.
---

## Level 1: does the work exist?

| Identifier | Looked up in |
|---|---|
| DOI | Crossref, then DataCite, then the DOI system itself |
| PMID | PubMed |
| PMCID | Europe PMC, which gives the PMID and the DOI |
| arXiv ID | arXiv |
| ISBN | Open Library |

A DOI that is registered but has no metadata in Crossref or DataCite gets a Note: it exists, but it cannot be compared with the citation. An ISBN that Open Library does not know is unconfirmed, not wrong: its coverage is incomplete.

A reference without an identifier is searched for. Crossref first, then PubMed, OpenAlex and DataCite, and Open Library for books and reports. The best record must agree with the citation at 0.9 or more (title similarity, with penalties for a different year or first author) to count as found; from 0.75 it is a possible match, which is a Check. For a numbered entry without a title field, Starbuck takes the longest part of the entry that is not the author list or the journal details as the title.

A reference with only a web page is opened. A page that answers is a Note: its content is not checked. A page that is gone is a Check, with the Wayback Machine copy when there is one. A server that refuses programs (HTTP 401, 403 or 429) is a Note, because the page is not shown to be gone.

## Level 2: does the citation match the record?

| Field | Rule |
|---|---|
| Title | Similarity of 0.9 or more is the same title; below 0.6 is a different work. Case, accents, punctuation and prefixes such as "RETRACTED:" are ignored. A title cited in its original language matches the record's original-language title. |
| First author | Family names compared without accents; "da Silva" matches "Silva". A cited first author who is listed later in the record is an author-order Check. |
| Year | May differ by one year (online first and print). |
| Numbered entries | 80% of the words of the record's title must be in the entry; the year nearest to the record's year is compared, so a title such as "1990-2019" does not count. |

A DOI that resolves to a different work is a Fail: the reference points somewhere else. When a DOI and a PMID point to different works, that is a Fail too; when both records have the same title, it is a Check, because one work can have two DOIs.

## Level 3: does the work still stand?

Starbuck asks Crossref (which includes the Retraction Watch database), PubMed (publication types and linked notices) and OpenAlex.

| Found | Result |
|---|---|
| Retraction, in Crossref or PubMed | Fail |
| Retraction flagged only by OpenAlex | Check: OpenAlex marks some works as retracted with no notice elsewhere |
| Retracted and republished | Check: cite the republished version |
| Expression of concern | Check |
| Correction, erratum | Note |
| The cited item is itself a notice | Check: cite the original work |
| A cited preprint has a published version | Note |

When the manuscript has a date (`date:` in the YAML header, `\date{}` in LaTeX, or `--date`), the report says whether a retraction or an expression of concern came before that date. A retraction before the date was public when the work was cited.

## Level 4: does the source support the sentence?

Level 4 is optional. For each sentence that cites a source, Starbuck takes the best text of that source, in this order: a local file, the Zotero library, open-access full text from Europe PMC, the arXiv PDF, an open-access PDF that Unpaywall knows, and the abstract (PubMed, Europe PMC, Crossref or OpenAlex). The reference list at the end of a full text is cut off, so that its titles do not match the sentence.

The text is split into passages, and the five that best match the sentence (BM25) go to a language model. The model answers Supported, Partly supported, Not supported or Cannot assess, and quotes the passage it relies on. Then Starbuck checks the answer:

- The quote must appear word for word in the source, with at least 20 characters. A quote that is not there is rejected, and the verdict becomes Cannot assess.
- Each number of the sentence (a percentage, a decimal, or an integer of 10 or more that is not a year) must be in the source. When the full text lacks one, Supported becomes Partly supported. With the abstract only, the report names the number and the verdict stays: an abstract leaves out most numbers.
- With two judges, both answer every sentence. Where they differ, the less supportive verdict is kept.

Level 4 never makes a reference Fail: Not supported is a Check and Partly supported is a Note. The report gives citation recall (the share of citing sentences with at least one supporting citation) and citation precision (the share of citations that support their sentence), following ScholarQABench.

## Sentences without a citation

The report lists sentences of the body text that seem to state a finding and cite nothing: at least 50 characters, no citation, and a number with a unit or a percentage, an effect measure (OR, HR, RR, CI) or a claim word such as found, showed, increased, reduced, associated with, risk or prevalence.

Left out: headings, tables, figures and captions, code, the reference list; the abstract and the sections headed Methods, Results or Conclusions; the back matter (ethics, funding, abbreviations, declarations); paragraphs that start with a label such as "Results:"; and sentences that start with "We" or "In this study". The authors' own work needs no citation.

The rules are simple and in English. The list is for a person to read, and it never changes a result.

## What Starbuck does not check

- Whether a reference is the best one, or whether an important one is missing.
- The content of a web page.
- Page numbers, volume, issue and journal name (only title, first author and year are compared).
- Whether a source supports the sentence, unless you ask for level 4. Even then, a language model judges, and it can be wrong.

## Sources

Crossref, DataCite, the DOI system, PubMed, Europe PMC, OpenAlex, arXiv, Open Library, the Wayback Machine and, for level 4, Unpaywall. Starbuck asks politely: a few requests at a time per service, the pace that PubMed and arXiv ask for, retries after a busy answer, and a User-Agent with your contact address when you give one.
