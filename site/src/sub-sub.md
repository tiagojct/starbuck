---
layout: base.njk
title: Starbuck in Sub-Sub
eyebrow: How the two work together
lead: Sub-Sub is a research assistant that works from your own Zotero library. Starbuck is its reference checker. Each works without the other; together, the assistant can check a manuscript and the sources it writes itself.
---

## What each one does

<div class="pair">
<div>

**Sub-Sub** reads the papers in your Zotero library, finds the ones you are missing in PubMed, Europe PMC and OpenAlex, and writes notes that say what it read. It keeps the library in order, with a preview of every change. [subsub.tiagojacinto.eu](https://subsub.tiagojacinto.eu)

</div>
<div>

**Starbuck** checks that each cited work exists, matches its citation and still stands, and, when asked, whether it supports the sentence that cites it. It proposes corrections as a diff. This site.

</div>
</div>

## Turn reference checks on in Sub-Sub

Reference checks are off by default in Sub-Sub. To turn them on, do one of these:

- In `subsub init`, answer On to "Reference checks (Starbuck)", or type `subsub init --starbuck on`.
- In the browser view, turn on "Reference checks (Starbuck)" in the panel on the left. Sub-Sub restarts.

Sub-Sub downloads Starbuck with uv the first time. Type `subsub doctor`: the line Starbuck must show ok. Each Sub-Sub version runs one tested Starbuck version, shown in the footer of the Sub-Sub site. You do not install Starbuck yourself.

## What you can do then

| In Sub-Sub | What happens |
|---|---|
| `/verify paper.docx` | Starbuck checks every reference and writes the report in `_starbuck` next to the manuscript. Sub-Sub reports the Fail and Check results as Starbuck states them. |
| `/verify paper.docx claims` | Claim support. Starbuck gives the passages; the model that you use in Sub-Sub judges them and must quote the source; Starbuck checks every quote and number. |
| "Correct the references of paper.qmd" | Starbuck proposes the corrections as a diff. Sub-Sub shows it. The bibliography changes only after you answer Yes. |
| `/lit`, `/compare` | The Researcher checks the sources of its own reports with Starbuck before it gives them to you, and fixes the ones that fail. |
| `/review` | A review of a manuscript includes Starbuck's Fail and Check results. |

## What Sub-Sub adds

- **A model you already have.** Claim support needs a language model. In Sub-Sub, the model you chose for Sub-Sub judges; Starbuck needs no settings of its own.
- **Your approval for writes.** Inside your Sub-Sub folder or vault, a report is written without a question. Elsewhere, Sub-Sub asks first. A change to a bibliography file always needs your Yes.
- **Your library.** Claim support takes the full texts from your Zotero library when it can, so it rests on the full text more often than on the abstract.

## What Starbuck adds to Sub-Sub

An assistant that writes with citations can cite works that do not exist, or cite a real work for a claim it does not make. Starbuck is the check that the program makes, not one that the model is told to make: a reference that does not resolve fails whatever the model says, and a quote that is not in the source is rejected.

## Use Starbuck without Sub-Sub

Everything on this site works without Sub-Sub: the command line, the [GitHub Action and pre-commit hook](/automate/), and the [MCP server](/automate/#from-an-ai-agent-mcp) for other agents. Install it with `uv tool install starbuck`.
