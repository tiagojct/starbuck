---
layout: base.njk
title: Privacy
eyebrow: What leaves your computer
lead: Starbuck runs on your computer. Levels 1 to 3 send details of the references, never the manuscript text. Level 4 sends the citing sentences to the model you choose, and only when you ask for it.
---

## What is sent, and where

| Service | What Starbuck sends | When |
|---|---|---|
| Crossref, DataCite, doi.org, PubMed, Europe PMC, OpenAlex, arXiv, Open Library | Identifiers, and the title, first author and year of references without one, or the reference as written | Every check |
| The cited web pages | A request for the page | References with only a web address |
| Wayback Machine | The address of a page that is gone | When a cited page is gone |
| Unpaywall | The DOI | Level 4, with a contact address set |
| The open-access copies of cited works | A download request | Level 4 |
| Your language model provider | The citing sentences and the passages of their sources | Level 4 only, with `--claims` |

Your contact address (`STARBUCK_EMAIL`) goes to the services that ask for one, so they can write to you when your requests cause a problem. It is optional.

## What stays on your computer

- The manuscript and its text, for levels 1 to 3.
- The report, the JSON and, for level 4, the passages and the model's answers (`<name>-claims.json`), in `_starbuck` next to the manuscript.
- The cache of the services' answers.
- Your Zotero library: with `--zotero`, Starbuck reads a copy of its database and sends nothing from it.

Starbuck collects no usage data and has no account.

## In Sub-Sub

When Starbuck runs in Sub-Sub, the same holds, and level 4 uses the model provider that you chose for Sub-Sub. See the [Sub-Sub privacy page]({{ site.subsub }}/privacy/).
