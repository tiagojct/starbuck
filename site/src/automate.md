---
layout: base.njk
title: Automate
eyebrow: Agents, GitHub, commits
lead: "Starbuck can check references where the text is written: from an AI agent, in a GitHub repository, or before each commit."
---

## From an AI agent (MCP)

`starbuck-mcp` is an MCP server. Any MCP client can use it: Claude, an IDE agent, or a research agent that must check the sources it writes.

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

| Tool | What it does |
|---|---|
| `check_manuscript` | Checks a manuscript and writes the report. |
| `check_references` | Checks references given directly: an identifier, citation details, or both. For the sources of a text the agent wrote. |
| `prepare_claims` | Level 4, step 1: each citing sentence with the best passages of its source. |
| `record_claims` | Level 4, step 2: takes the agent's verdicts, checks the quotes and adds them to the report. |
| `fix_references` | Proposes corrections and returns the diff. With `in_place`, changes the bibliography and keeps a copy. |

Inside an agent, the agent's own model judges claim support, so no `STARBUCK_JUDGE_*` settings are needed. The server tells the agent to report results as Starbuck states them, never to turn a Check into a Fail or a Pass into "verified".

[Sub-Sub](/sub-sub/) uses this server, with approval gates around the tools that write files.

## GitHub Action

Check the references of a manuscript on each push and pull request:

```yaml
on: [push, pull_request]
jobs:
  references:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: tiagojct/starbuck@v{{ release.version }}
        with:
          manuscripts: paper.qmd
          email: ${{ "{{" }} vars.STARBUCK_EMAIL {{ "}}" }}
```

| Input | Purpose |
|---|---|
| `manuscripts` | Files to check, separated by spaces. |
| `args` | More options for `starbuck check`, for example `--all-entries`. |
| `email` | Contact address for the services. |
| `fail-on-check` | `true` also fails the job on a Check, not only on a Fail. |
| `version` | Another Starbuck version. |

The job fails when a reference fails. The job summary shows the result, and the HTML reports are in the artifact `starbuck-reports`.

## pre-commit

Check each changed manuscript before a commit:

```yaml
repos:
  - repo: https://github.com/tiagojct/starbuck
    rev: v{{ release.version }}
    hooks:
      - id: starbuck
```

The hook checks each changed Markdown or Quarto file that has citations, skips the files without citations, and stops the commit when a reference fails. It writes no rendered report.

## In scripts

`starbuck check` returns an exit code (0 no Fail, 1 a Fail, 2 could not run, 3 some checks did not run), and writes `<name>-references.json` with every result, finding and record. `starbuck ids` checks identifiers directly:

```sh
starbuck ids 10.1183/09031936.00080312 pmid:22743675 --json
```
