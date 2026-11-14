"""`starbuck fix`: corrections to the reference list, as a diff.

Starbuck proposes only the changes that the records support with confidence:

- add a DOI, PMID or ISBN that a search found (confidence at or above the search threshold),
  or the DOI that the PubMed record of a cited PMID gives;
- correct the year or the title when the identifier is right but the field differs;
- replace a cited preprint with its published version (DOI, year and journal);
- replace a dead link with its Wayback Machine copy.

Everything else (a wrong DOI, a retraction, a wrong author) is listed for a person. The
corrected files are written next to the report, with one diff; --in-place changes the
files themselves and keeps a .bak copy of each.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import bibtex
from .check import check_document
from .models import Document, Reference
from .parse import ENTRY_RE, REF_HEADING, ParseError, read_manuscript
from .report import ACTION
from .sources import ServiceError, Sources

FIXES = {"add_identifier": "doi", "year_differs": "year", "title_differs": "title", "preprint_published": "doi",
         "web_unreachable": "url"}  # finding code -> the field whose change answers it
DOI_IN = re.compile(r"doi:(10\.\S+?)(?=[.,;)]?(?:\s|$))")


@dataclass
class Change:
    key: str
    field: str  # doi, pmid, isbn, year, title, container, url
    old: str
    new: str
    reason: str


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    manual: list[dict] = field(default_factory=list)  # {key, verdict, finding, action}


# ---------------------------------------------------------------- what to change

async def propose(doc: Document, result: dict, src: Sources | None) -> Plan:
    plan = Plan()
    for res in result["references"]:
        ref = doc.references.get(res["key"])
        if ref is None:
            continue
        codes = {f["code"]: f for f in res["findings"]}
        rec = (res.get("match") or {}).get("record") or {}
        status = (res.get("match") or {}).get("status")
        exists = (res.get("exists") or {}).get("status")
        before = len(plan.changes)

        def add(fld: str, old: str, new: str, why: str, key: str = ref.key) -> None:
            if new and new != old:
                plan.changes.append(Change(key, fld, old, new, why))

        if "add_identifier" in codes and res.get("suggestion"):
            kind, _, value = res["suggestion"].partition(":")
            if not getattr(ref, kind, ""):
                add(kind, "", value, f"found by {', '.join(res['exists'].get('via') or ['search'])} "
                    f"(confidence {res['exists'].get('confidence')})")
        if ref.pmid and not ref.doi and rec.get("doi") and exists == "found" and status in ("ok", "partial"):
            add("doi", "", rec["doi"], f"the PubMed record of PMID {ref.pmid} gives this DOI")
        if exists == "found" and status == "partial":
            if "year_differs" in codes and rec.get("year"):
                add("year", ref.year, rec["year"][:4], f"the {rec.get('source', 'record')} record gives this year")
            if "title_differs" in codes and rec.get("title") and ref.kind != "numbered":
                add("title", ref.title, rec["title"], f"the {rec.get('source', 'record')} record gives this title")
        if "preprint_published" in codes and src is not None:
            m = DOI_IN.search(codes["preprint_published"]["message"])
            if m:
                try:
                    pub = await src.crossref_work(m.group(1).lower())
                except ServiceError:
                    pub = None
                why = "the cited preprint has a published version"
                add("doi", ref.doi, m.group(1).lower(), why)
                if pub and ref.kind != "numbered":
                    add("year", ref.year, pub.get("year", ""), why)
                    add("container", ref.container, pub.get("container", ""), why)
        if "web_unreachable" in codes and (res.get("suggestion") or "").startswith("https://web.archive.org/"):
            add("url", ref.url, res["suggestion"], "the page is gone; this is its Wayback Machine copy")

        fixed = {c.field for c in plan.changes[before:]}
        handled = {code for code, fld in FIXES.items() if fld in fixed}
        for f in res["findings"]:
            if f["level"] in ("fail", "warn") and f["code"] not in handled:
                plan.manual.append({"key": ref.key, "verdict": res["verdict"], "finding": f["message"],
                                    "action": ACTION.get(f["code"], "")})
    return plan


# ---------------------------------------------------------------- how to change it

BIB_FIELD = {"doi": "doi", "pmid": "pmid", "isbn": "isbn", "year": "year", "title": "title", "url": "url"}
CSL_FIELD = {"doi": "DOI", "pmid": "PMID", "isbn": "ISBN", "title": "title", "url": "URL",
             "container": "container-title"}


def _bib_value(name: str, value: str) -> str:
    if name in ("doi", "url", "pmid", "isbn"):
        return "{" + value + "}"
    return "{" + re.sub(r"(?<!\\)([&%#])", r"\\\1", value) + "}"


def edit_bibtex(text: str, changes: list[Change]) -> tuple[str, list[Change]]:
    entries = {e["key"]: e for e in bibtex.parse(text)[0]}
    edits: list[tuple[int, int, str]] = []
    done = []
    for c in changes:
        e = entries.get(c.key)
        if not e:
            continue
        name = BIB_FIELD.get(c.field) or ("journaltitle" if "journaltitle" in e["fields"] else
                                          "booktitle" if e["type"] in ("inproceedings", "incollection") else "journal")
        if c.field == "year" and "year" not in e["spans"] and "date" in e["spans"]:
            a, b = e["spans"]["date"]
            old = text[a:b]
            edits.append((a, b, re.sub(r"\d{4}", c.new, old, count=1)))
        elif name in e["spans"]:
            a, b = e["spans"][name]
            edits.append((a, b, _bib_value(name, c.new)))
        else:
            start, end = e["span"]
            body = text[start:end - 1]
            cut = start + len(body.rstrip())
            first = re.search(r"\n([ \t]+)\S", body)
            indent = first.group(1) if first else "  "
            comma = "" if text[cut - 1] == "," else ","
            edits.append((cut, cut, f"{comma}\n{indent}{name} = {_bib_value(name, c.new)}"))
        done.append(c)
    for a, b, new in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        text = text[:a] + new + text[b:]
    return text, done


def _csl_set(item: dict, c: Change) -> None:
    if c.field == "year":
        item["issued"] = {"date-parts": [[int(c.new)]]}
    else:
        item[CSL_FIELD[c.field]] = c.new


def edit_csl(text: str, suffix: str, changes: list[Change]) -> tuple[str, list[Change]]:
    data = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    items = data if isinstance(data, list) else (data or {}).get("references" if suffix != ".json" else "items", [])
    by_id = {str(i.get("id") or i.get("citation-key") or ""): i for i in items if isinstance(i, dict)}
    done = []
    for c in changes:
        if c.key in by_id:
            _csl_set(by_id[c.key], c)
            done.append(c)
    if suffix == ".json":
        m = re.search(r"\n([ \t]+)\S", text)
        out = json.dumps(data, indent=m.group(1) if m else 2, ensure_ascii=False)
        return out + ("\n" if text.endswith("\n") else ""), done
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000), done


def edit_numbered(text: str, refs: dict[str, Reference], changes: list[Change]) -> tuple[str, list[Change]]:
    """Numbered references in the manuscript: add identifiers, replace a link or a year."""
    heads = list(REF_HEADING.finditer(text))
    if not heads:
        return text, []
    lines = text[heads[-1].end():].split("\n")
    offset = heads[-1].end()
    where: dict[str, tuple[int, int]] = {}  # number -> (start, end) of the entry
    pos, current = offset, None
    for line in lines:
        m = ENTRY_RE.match(line)
        if m:
            current = m.group(1) or m.group(2)
            where[current] = (pos, pos + len(line))
        elif current and line.strip() and line[:1].isspace():
            where[current] = (where[current][0], pos + len(line))
        elif line.strip():
            current = None
        pos += len(line) + 1
    edits, done = [], []
    for c in changes:
        if c.key not in where:
            continue
        a, b = where[c.key]
        entry = text[a:b]
        if c.field in ("doi", "pmid", "isbn") and not c.old:
            label = {"doi": "doi:", "pmid": "PMID: ", "isbn": "ISBN "}[c.field]
            edits.append((b, b, f" {label}{c.new}"))
        elif c.field in ("url", "doi", "year") and c.old and entry.count(c.old) == 1:
            i = a + entry.index(c.old)
            edits.append((i, i + len(c.old), c.new))
        else:
            continue
        done.append(c)
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    return text, done


def apply_plan(doc: Document, plan: Plan) -> dict[Path, tuple[str, str, list[Change]]]:
    """File -> (old text, new text, changes made). Inline YAML references are not edited."""
    by_file: dict[str, list[Change]] = {}
    for c in plan.changes:
        origin = doc.references[c.key].origin
        if origin:
            by_file.setdefault(origin, []).append(c)
    out = {}
    for name, changes in by_file.items():
        path = Path(name)
        old = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix in (".bib", ".bibtex", ".biblatex"):
            new, done = edit_bibtex(old, changes)
        elif suffix in (".json", ".yaml", ".yml"):
            new, done = edit_csl(old, suffix, changes)
        else:
            new, done = edit_numbered(old, doc.references, changes)
        if done:
            out[path] = (old, new, done)
    return out


def diff(files: dict[Path, tuple[str, str, list[Change]]]) -> str:
    parts = []
    for path, (old, new, _) in files.items():
        parts += difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                      fromfile=f"a/{path.name}", tofile=f"b/{path.name}")
    return "".join(parts)


# ---------------------------------------------------------------- command

def add_fix_parser(sub) -> None:
    f = sub.add_parser("fix", help="propose corrections to the reference list (a diff; --in-place applies them)")
    f.add_argument("manuscript")
    f.add_argument("--bib", action="append", help="bibliography file; repeat for several")
    f.add_argument("--from", dest="from_json", help="use this <name>-references.json instead of checking again")
    f.add_argument("--out", help="folder for the corrected files and the diff (default: _starbuck)")
    f.add_argument("--in-place", action="store_true", help="change the files themselves (a .bak copy is kept)")
    f.add_argument("--all-entries", action="store_true", help="also fix bibliography entries that are not cited")
    f.add_argument("--email")
    f.add_argument("--no-cache", action="store_true")
    f.add_argument("--quiet", action="store_true")


async def run_fix(args: argparse.Namespace, transport=None) -> int:
    from .cli import make_sources

    try:
        doc = read_manuscript(args.manuscript, args.bib or None)
    except ParseError as exc:
        print(f"starbuck: {exc}", file=sys.stderr)
        return 2
    if doc.style == "none":
        print("starbuck: no citations found.", file=sys.stderr)
        return 2
    async with make_sources(args.email, transport, pacing=transport is None,
                            cache=False if args.no_cache else None) as src:
        if args.from_json:
            result = json.loads(Path(args.from_json).expanduser().read_text(encoding="utf-8"))
        else:
            if not args.quiet:
                print(f"Checking the references of {Path(doc.path).name} ...", file=sys.stderr)
            result = await check_document(doc, src, include_uncited=args.all_entries)
        plan = await propose(doc, result, src)
    files = apply_plan(doc, plan)
    made = [c for _, _, done in files.values() for c in done]
    out_dir = Path(args.out).expanduser() if args.out else Path(doc.path).parent / "_starbuck"
    text = diff(files)
    lines = [f"Starbuck proposes {len(made)} change{'s' if len(made) != 1 else ''} "
             f"in {len(files)} file{'s' if len(files) != 1 else ''}."]
    for c in made:
        lines.append(f"  {c.key}: {c.field} {c.old or '(none)'} -> {c.new} ({c.reason})")
    skipped = [c for c in plan.changes if c not in made]
    for c in skipped:
        lines.append(f"  {c.key}: {c.field} -> {c.new} could not be written in the file; change it by hand.")
    if files:
        out_dir.mkdir(parents=True, exist_ok=True)
        patch = out_dir / f"{Path(doc.path).stem}-fix.diff"
        patch.write_text(text, encoding="utf-8")
        for path, (old, new, _) in files.items():
            if args.in_place:
                path.with_name(path.name + ".bak").write_text(old, encoding="utf-8")
                path.write_text(new, encoding="utf-8")
            else:
                (out_dir / f"{path.stem}-fixed{path.suffix}").write_text(new, encoding="utf-8")
        lines.append(f"Diff: {patch}")
        lines.append("Changed in place (a .bak copy of each file is kept)." if args.in_place
                     else f"Corrected copies: {out_dir}. Read the diff, then run again with --in-place.")
    if plan.manual:
        lines.append(f"For a person ({len(plan.manual)}):")
        for m in plan.manual:
            lines.append(f"  {m['key']}: {m['finding']}" + (f" {m['action']}" if m["action"] else ""))
    print("\n".join(lines))
    return 0
