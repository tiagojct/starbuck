"""Reports: a Quarto document (renders to HTML or Word), JSON, and a short text summary."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from .ids import trim

VERDICT = {"fail": "Fail", "error": "Not checked", "warn": "Check", "note": "Note", "pass": "Pass"}
EXISTS = {"found": "Found", "found_by_search": "Found by search", "possible_match": "Possible match",
          "not_found": "Not found", "not_found_by_search": "Not found by search", "unconfirmed": "Unconfirmed",
          "unidentifiable": "Too little to search", "web_page": "Web page",
          "web_page_unreachable": "Web page unreachable", "error": "Not checked", "not_checked": "Not checked"}
MATCH = {"ok": "Matches", "partial": "Differs in part", "mismatch": "Different work",
         "not_compared": "Nothing to compare", "not_checked": ""}
STATUS = {"ok": "No notices", "retracted": "Retracted", "republished": "Retracted and republished",
          "concern": "Expression of concern", "corrected": "Corrected", "notice": "Is a notice",
          "preprint_published": "Published version exists", "not_checked": ""}
ACTION = {
    "doi_not_found": "Ask the authors for the source. Correct the DOI or remove the reference.",
    "pmid_not_found": "Correct the PMID or remove the reference.",
    "arxiv_not_found": "Correct the arXiv ID or remove the reference.",
    "wrong_work": "Replace the identifier with the one of the cited work, or correct the citation.",
    "id_conflict": "Find out which identifier is wrong and correct it.",
    "retracted": "Remove the citation, or say in the text that the work was retracted and why it is cited.",
    "republished": "Cite the republished version.",
    "concern": "Read the expression of concern and decide whether the citation can stay.",
    "is_notice": "Cite the original work, unless the notice itself is the subject.",
    "title_differs": "Correct the title in the reference list.",
    "author_differs": "Correct the authors in the reference list.",
    "author_order": "Correct the author order in the reference list.",
    "year_differs": "Correct the year in the reference list.",
    "possible_match": "Confirm the work and add its DOI.",
    "not_found": "Check the reference by hand and add an identifier if one exists.",
    "unidentifiable": "Complete the reference so it can be identified.",
    "web_unreachable": "Update the link or cite an archived copy.",
    "service_error": "Run the check again later.",
    "claim_not_supported": "Read the source. Correct the sentence, cite a source that supports it, or remove the claim.",
    "claim_partly_supported": "Read the source and make the sentence match what it shows.",
    "claim_overcitation": "Remove this citation from the sentence unless it supports another part of it.",
}
CLAIM = {"supported": "Supported", "partly_supported": "Partly supported", "not_supported": "Not supported",
         "cannot_assess": "Cannot assess"}
SEVERITY = {"fail": 0, "error": 1, "warn": 2, "note": 3, "pass": 4}


def esc(text: object, strip: bool = True) -> str:
    """Escape text for Pandoc Markdown: no emphasis, links, citations, math or table breaks."""
    s = re.sub(r"\s+", " ", str(text or ""))
    s = s.strip() if strip else s
    return re.sub(r"([\\`*_{}\[\]<>#|@$~^])", r"\\\1", s)


def doi_link(doi: str, text: str | None = None) -> str:
    return f"[{esc(text or 'doi:' + doi)}](https://doi.org/{quote(doi, safe='/:;')})"


MESSAGE_DOI = re.compile(r"(?:doi:)?(10\.\d{4,9}/[^\s\"'<>|\\{}]+)")


def linkify(message: str) -> str:
    """Escape a finding and turn the DOIs in it into links."""
    out, pos = [], 0
    for m in MESSAGE_DOI.finditer(message):
        doi = trim(m.group(1))
        end = m.start(1) + len(doi)
        out.append(esc(message[pos : m.start()], strip=False))
        out.append(doi_link(doi))
        pos = end
    out.append(esc(message[pos:], strip=False))
    return "".join(out).strip()


def ident_links(ref: dict, short: bool = False) -> str:
    out = []
    if ref.get("doi"):
        out.append(doi_link(ref["doi"], "DOI" if short else None))
    if ref.get("pmid"):
        out.append(f"[{'PubMed' if short else 'PMID ' + ref['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{ref['pmid']}/)")
    if ref.get("arxiv"):
        label = "arXiv" if short else f"arXiv:{esc(ref['arxiv'])}"
        out.append(f"[{label}](https://arxiv.org/abs/{quote(ref['arxiv'], safe='/')})")
    if ref.get("isbn"):
        out.append("ISBN" if short else f"ISBN {ref['isbn']}")
    if not out and ref.get("url"):
        out.append(f"[{'Web' if short else 'link'}](<{ref['url'].replace('>', '%3E')}>)")
    return ", ".join(out)


def _ordered(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda r: SEVERITY[r["verdict"]])


def _cited_at(res: dict, limit: int = 2) -> list[str]:
    cites = res.get("cited_in") or []
    lines = [f"> Line {c['line']}: {esc(c['sentence'])}" for c in cites[:limit]]
    if len(cites) > limit:
        lines.append(f"> (cited {len(cites) - limit} more time{'s' if len(cites) - limit > 1 else ''})")
    return lines


def _field_table(res: dict) -> list[str]:
    fields = (res.get("match") or {}).get("fields") or {}
    bad = {k: v for k, v in fields.items() if not v.get("ok")}
    if not bad or not any(v.get("cited") for v in bad.values()):
        return []
    names = {"title": "Title", "first_author": "First author", "year": "Year"}
    rows = ["| | Cited | Record |", "|---|---|---|"]
    for k, v in fields.items():
        rows.append(f"| {names.get(k, k)} | {esc(v.get('cited'))} | {esc(v.get('found'))} |")
    return rows


def _action(res: dict) -> str:
    order = {"fail": 0, "warn": 1, "note": 2}
    for f in sorted(res["findings"], key=lambda f: order[f["level"]]):
        if f["code"] in ACTION:
            return ACTION[f["code"]]
    return ""


def to_quarto(result: dict) -> str:
    doc = Path(result.get("document") or "references")
    s = result["summary"]
    when = result["checked_at"][:10]
    out = [
        "---",
        'title: "Reference check"',
        f'subtitle: "{doc.name.replace(chr(34), "")}"' if result.get("document") else 'subtitle: "References"',
        f'date: "{when}"',
        "lang: en",
        "format:",
        "  html:",
        "    toc: true",
        "    toc-depth: 2",
        "    embed-resources: true",
        "  docx:",
        "    toc: false",
        "---",
        "",
        "## Summary",
        "",
    ]
    style = {"citekey": "citation keys", "numbered": "numbered references"}.get(result.get("style", ""), "")
    where = f" in {esc(doc.name)}" if result.get("document") else ""
    bib = ", ".join(esc(Path(b).name) for b in result.get("bibliography") or [])
    out.append(f"Starbuck {result['starbuck']} checked {s['references_checked']} "
               f"reference{'s' if s['references_checked'] != 1 else ''}{where} on {when}"
               + (f" ({style}" + (f"; bibliography {bib})" if bib else ")") if style else "") + ".")
    out += ["", "| Result | References |", "|---|---:|"]
    for k in ("fail", "error", "warn", "note", "pass"):
        out.append(f"| {VERDICT[k]} | {s.get(k, 0)} |")
    extra = []
    if s.get("missing_entries"):
        extra.append(f"- {s['missing_entries']} cited key{'s have' if s['missing_entries'] > 1 else ' has'} "
                     "no entry in the bibliography (see [Citations without an entry](#citations-without-an-entry)).")
    if s.get("uncited_entries"):
        extra.append(f"- {s['uncited_entries']} bibliography entr{'ies are' if s['uncited_entries'] > 1 else 'y is'} "
                     "not cited in the text" + (" and were not checked." if result.get("style") == "citekey" else "."))
    if n := s.get("uncited_sentences"):
        extra.append(f"- {n} sentence{'s state' if n > 1 else ' states'} a finding without a citation "
                     "(see [Sentences without a citation](#sentences-without-a-citation)).")
    for w in result.get("warnings") or []:
        extra.append(f"- {esc(w)}")
    if extra:
        out += [""] + extra
    run = result.get("claims_run") or {}
    if run.get("run"):
        v, b = run["verdicts"], run["basis"]
        out += ["", f"Level 4 (claim support): {run['citations']} citing sentence"
                f"{'s' if run['citations'] != 1 else ''}, judged by {esc(run['judged_by'])}: "
                + ", ".join(f"{v[k]} {CLAIM[k].lower()}" for k in CLAIM)
                + f". Evidence: {b.get('full text', 0)} full text, {b.get('abstract', 0)} abstract only, "
                f"{b.get('none', 0)} none. {esc(citation_line(run))} See [Claim support](#claim-support)."]
    out.append("")
    out.append("Results: Fail means the reference is wrong or the work was retracted. Check means a person should "
               "look at it. Note is information that needs no change in most cases. Not checked means a service "
               "did not answer.")

    results = _ordered(result["references"])
    attention = [r for r in results if r["verdict"] in ("fail", "error", "warn")]
    out += ["", "## Needs attention", ""]
    if not attention:
        out.append("No reference failed or needs checking.")
    for r in attention:
        out += [f"### {esc(r['key'])}: {VERDICT[r['verdict']]}", "", esc(r["label"]) or "(no citation text)", ""]
        for f in r["findings"]:
            if f["level"] != "note" or r["verdict"] == "error":
                out.append(f"- {linkify(f['message'])}")
        notes = [f for f in r["findings"] if f["level"] == "note" and r["verdict"] != "error"]
        for f in notes:
            out.append(f"- Note: {linkify(f['message'])}")
        table = _field_table(r)
        if table:
            out += [""] + table
        links = ident_links(r["reference"])
        if links:
            out += ["", f"Identifier: {links}"]
        rec = (r.get("match") or {}).get("record") or {}
        if rec and (rec.get("doi") or rec.get("pmid")) and rec.get("doi") != r["reference"].get("doi"):
            out += ["", f"Record found: {ident_links(rec)}"]
        cited = _cited_at(r)
        if cited:
            out += [""] + cited
        if a := _action(r):
            out += ["", f"Suggested action: {a}"]
        out.append("")

    notes = [r for r in results if r["verdict"] == "note"]
    if notes:
        out += ["## Notes", ""]
        for r in notes:
            for f in r["findings"]:
                if f["level"] == "note":
                    out.append(f"- {esc(r['key'])}: {linkify(f['message'])}")
        out.append("")

    if run.get("run"):
        out += _claims_section(result)

    out += ["## All references", "", "| Key | Result | Exists | Metadata | Status | Links |",
            "|---|---|---|---|---|---|"]
    for r in results:
        m = MATCH.get((r.get("match") or {}).get("status", ""), "")
        st = STATUS.get((r.get("status") or {}).get("status", ""), "")
        out.append(f"| {esc(r['key'])} | {VERDICT[r['verdict']]} | {EXISTS.get(r['exists']['status'], '')} | {m} | "
                   f"{st} | {ident_links(r['reference'], short=True)} |")
    out.append("")

    if result.get("missing"):
        out += ["## Citations without an entry", "", "| Key | Lines |", "|---|---|"]
        for m in result["missing"]:
            out.append(f"| {esc(m['key'])} | {', '.join(str(n) for n in m['lines'])} |")
        out.append("")
    if result.get("uncited"):
        out += ["## Entries not cited", "", ", ".join(esc(k) for k in result["uncited"]), ""]
    if result.get("uncited_sentences"):
        out += _uncited_section(result)

    t = result["thresholds"]
    sources = ", ".join("the cited web pages" if x == "web" else x for x in result.get("sources") or []) or "none"
    out += [
        "## How this report was made", "",
        "Starbuck checks three things for each reference. Level 1: the identifier (DOI, PMID, arXiv ID, ISBN) "
        "resolves; a reference without one is searched in Crossref. Level 2: title, first author and year agree "
        "with the record. Level 3: Crossref (including Retraction Watch data), PubMed and OpenAlex show no "
        "retraction, expression of concern or correction, and a cited preprint has no published version.",
        "",
        f"Rules: titles match at a similarity of {t['title_ok']} or more and are a different work below "
        f"{t['title_mismatch']}; for numbered entries, {int(t['contain_ok'] * 100)}% of the record title's words must "
        f"appear in the entry; years may differ by {t['year_tolerance']}; a search result is accepted at "
        f"{t['search_found']} and reported as a possible match from {t['search_possible']}.",
        "",
        f"Services used: {esc(sources)}. Starbuck sends identifiers and reference details (title, authors, year, "
        "or the reference as written) to these services and opens cited web pages; it does not send the "
        "manuscript text.",
        "",
        "Sentences without a citation: sentences of the body text with at least 50 characters, no citation and a "
        "sign of a finding (a number with a unit or a percentage, an effect measure such as OR or HR, or words "
        "such as found, showed, increased, reduced, associated with, risk or prevalence). Headings, tables, "
        "figures, captions, code, the reference list and sections headed Methods or Results are left out. This "
        "list is for a person to read; it does not change any result.",
        "",
        _claims_method(run),
        "",
    ]
    return "\n".join(out)


def _uncited_section(result: dict) -> list[str]:
    rows = result["uncited_sentences"]
    total = result["summary"].get("uncited_sentences", len(rows))
    out = ["## Sentences without a citation", "",
           "These sentences seem to state a finding but cite nothing. Add a citation where the finding comes "
           "from other work. The list comes from simple rules (see the end of the report), so some sentences "
           "need no citation.", ""]
    if total > len(rows):
        out += [f"The first {len(rows)} of {total} are shown.", ""]
    out += ["| Line | Sentence |", "|---|---|"]
    out += [f"| {r['line']} | {esc(r['sentence'])} |" for r in rows]
    out.append("")
    return out


def _claims_section(result: dict) -> list[str]:
    order = {"not_supported": 0, "partly_supported": 1, "cannot_assess": 2, "supported": 3}
    claims = [c for r in result["references"] for c in r.get("claims") or []]
    claims.sort(key=lambda c: (order.get(c["verdict"], 9), c["line"], c["key"]))
    out = ["## Claim support", "",
           "Each row is one citing sentence and one cited source. Read the source before you change the text: "
           "the verdict comes from a language model and can be wrong.", "",
           "| Line | Key | Verdict | Evidence | Sentence | Passage or reason |", "|---|---|---|---|---|---|"]
    for c in claims:
        sentence = c["sentence"] if len(c["sentence"]) <= 300 else c["sentence"][:297] + "..."
        evidence = f"{c['basis']} ({c['source']})" if c.get("source") else c["basis"]
        detail = f"\"{c['quote']}\"" if c.get("quote") else c.get("reason", "")
        if c.get("quote") and c.get("reason"):
            detail += f" {c['reason']}"
        out.append(f"| {c['line']} | {esc(c['key'])} | {CLAIM.get(c['verdict'], esc(c['verdict']))} | {esc(evidence)} | "
                   f"{esc(sentence)} | {esc(detail)} |")
    out.append("")
    return out


def _claims_method(run: dict) -> str:
    if not run.get("run"):
        why = run.get("reason") or "not requested"
        return f"Level 4 (whether each source supports the sentence that cites it) was not run: {esc(why)}."
    return ("Level 4: for each citing sentence, Starbuck took the best text of the cited work (open-access full "
            "text from Europe PMC or a local file, otherwise the abstract from PubMed, Europe PMC, Crossref or "
            f"OpenAlex), ranked its passages against the sentence (BM25) and gave the top passages to "
            f"{esc(run['judged_by'])}. The model had to quote the passage it relied on; a quotation that does not "
            f"appear word for word in the source text (at least {run.get('min_quote', 20)} characters) is "
            f"rejected and the verdict becomes Cannot assess ({run.get('rejected_quotes', 0)} rejected). Level 4 "
            "never makes a reference Fail: Not supported is Check, Partly supported is Note. The citing sentences "
            "were sent to the model's provider."
            " Citation recall is the share of sentences with at least one citation judged Supported or Partly "
            "supported; citation precision is the share of citations judged Supported or Partly supported. Both "
            "count only citations judged Supported, Partly supported or Not supported (Cannot assess is left out); "
            "a sentence is one citing sentence with all its citations. A citation judged Not supported in a "
            "sentence that another of its citations supports is noted as overcitation: it adds no support. These "
            "scores follow the citation recall and precision of ScholarQABench (Asai et al., OpenScholar).")


def _share(r: dict | None, what: str) -> str:
    if not r or not r.get("denominator"):
        return f"no {what} judged"
    return f"{r['numerator']}/{r['denominator']} ({100 * r['value']:.0f}%)"


def citation_line(run: dict) -> str:
    """Citation recall and precision as one sentence (level 4)."""
    if "citation_recall" not in run:
        return ""
    line = (f"Citation recall: {_share(run['citation_recall'], 'sentences')} of sentences have a supporting "
            f"citation; citation precision: {_share(run['citation_precision'], 'citations')} of citations support "
            "their sentence.")
    if run.get("overcitations"):
        n = run["overcitations"]
        line += f" {n} citation{'s add' if n > 1 else ' adds'} no support to a sentence that other sources support."
    return line


def to_text(result: dict, report: str | None = None) -> str:
    """Short plain-text summary for a terminal or an agent."""
    s = result["summary"]
    parts = [f"{s.get(k, 0)} {VERDICT[k].lower()}" for k in ("fail", "error", "warn", "note", "pass") if s.get(k)]
    lines = [f"Starbuck checked {s['references_checked']} references: {', '.join(parts) or 'none'}."]
    for r in _ordered(result["references"]):
        if r["verdict"] in ("fail", "error", "warn"):
            first = next((f for f in r["findings"] if f["level"] != "note"), r["findings"][0] if r["findings"] else None)
            lines.append(f"  {VERDICT[r['verdict']]:<11} {r['key']}: {first['message'] if first else ''}")
    run = result.get("claims_run") or {}
    if run.get("run"):
        v = run["verdicts"]
        lines.append(f"  Level 4: {run['citations']} citing sentences: "
                     + ", ".join(f"{v[k]} {CLAIM[k].lower()}" for k in CLAIM) + ".")
        if cl := citation_line(run):
            lines.append(f"  {cl}")
    if n := s.get("uncited_sentences"):
        lines.append(f"  Sentences without a citation: {n} (listed in the report).")
    if result.get("missing"):
        lines.append("  Cited without an entry: " + ", ".join(m["key"] for m in result["missing"]))
    for w in result.get("warnings") or []:
        lines.append(f"  Warning: {w}")
    if report:
        lines.append(f"Report: {report}")
    return "\n".join(lines)


def write_outputs(result: dict, out_dir: Path, stem: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"json": out_dir / f"{stem}.json", "qmd": out_dir / f"{stem}.qmd"}
    paths["json"].write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["qmd"].write_text(to_quarto(result), encoding="utf-8")
    return paths


def report_stem(document: str | None) -> str:
    base = Path(document).stem if document else "references"
    return f"{base}-references"
