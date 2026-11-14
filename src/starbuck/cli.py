"""The `starbuck` command.

    starbuck check paper.qmd                  check a manuscript, write the report
    starbuck check paper.qmd --to html,docx   also render Word
    starbuck check paper.md --bib refs.bib    bibliography not named in the YAML header
    starbuck check paper.qmd --claims         also level 4 (needs STARBUCK_JUDGE_URL and _MODEL)
    starbuck check a.qmd b.qmd --if-cited     several files; skip files without citations
    starbuck fix paper.qmd                    propose corrections to the bibliography (a diff)
    starbuck ids 10.1183/09031936.00080312 arXiv:1706.03762
    starbuck cache --clear                    empty the cache of service answers

Exit codes: 0 nothing failed; 1 at least one reference failed or a cited key has
no entry; 2 the check could not run; 3 nothing failed, but some checks did not
run because a service did not answer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

import httpx

from . import __version__
from .cache import DiskCache
from .check import check_document, check_given
from .claims import apply, combine, judge, judge_settings, not_run, prepare, validate
from .parse import ParseError, iso_date, read_manuscript, references_from_identifiers
from .render import RenderError, render
from .report import report_stem, to_text, write_outputs
from .fix import add_fix_parser, run_fix
from .sources import Sources
from .zotero import ZoteroLibrary


def settings(env: dict[str, str] | None = None) -> dict[str, str | None]:
    e = os.environ if env is None else env
    return {
        "email": e.get("STARBUCK_EMAIL") or e.get("ZOTERO_CONTACT_EMAIL") or None,
        "ncbi_api_key": e.get("NCBI_API_KEY") or None,
        "openalex_api_key": e.get("OPENALEX_API_KEY") or None,
    }


def make_sources(email: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 pacing: bool = True, cache: bool | None = None) -> Sources:
    """The service clients. The disk cache is on for real runs and off when a transport is given
    (tests, validation recordings and replays), unless `cache` says otherwise."""
    s = settings()
    use_cache = (transport is None and not os.environ.get("STARBUCK_NO_CACHE")) if cache is None else cache
    disk = None
    if use_cache:
        try:
            disk = DiskCache()
        except (OSError, sqlite3.Error) as exc:
            print(f"starbuck: the cache cannot be used ({exc}); every answer is asked again.", file=sys.stderr)
    return Sources(email=email or s["email"], ncbi_api_key=s["ncbi_api_key"],
                   openalex_api_key=s["openalex_api_key"], transport=transport, pacing=pacing,
                   retry_delay=1.5 if pacing else 0.0, cache=disk)


def exit_code(result: dict) -> int:
    s = result["summary"]
    if s.get("fail") or s.get("missing_entries"):
        return 1
    if s.get("error"):
        return 3
    return 0


PRIORITY = [0, 3, 1, 2]  # for several manuscripts: the exit code of the worst one


async def run_check(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None = None) -> int:
    codes = []
    for manuscript in args.manuscript:
        if len(args.manuscript) > 1 and not args.quiet:
            print(f"== {manuscript}", file=sys.stderr)
        codes.append(await check_one(manuscript, args, transport))
    return max(codes, key=PRIORITY.index)


async def check_one(manuscript: str, args: argparse.Namespace,
                    transport: httpx.AsyncBaseTransport | None = None) -> int:
    try:
        doc = read_manuscript(manuscript, args.bib or None)
    except ParseError as exc:
        print(f"starbuck: {exc}", file=sys.stderr)
        return 2
    if args.date:
        doc.date = iso_date(args.date)
    if doc.style == "none" and args.if_cited:
        if not args.quiet:
            print(f"starbuck: {manuscript}: no citations; skipped.", file=sys.stderr)
        return 0
    if doc.style == "none":
        print("starbuck: no citations found. Starbuck reads [@key] citations with a bibliography, or numbered "
              "[1] citations with a numbered list under a References or Sources heading.", file=sys.stderr)
        return 2
    n = len([k for k in doc.cited_keys() if k in doc.references]) if doc.style == "citekey" and not args.all_entries \
        else len(doc.references)
    if not args.quiet:
        print(f"Checking {n} reference{'s' if n != 1 else ''} in {Path(doc.path).name} ...", file=sys.stderr)

    def progress(done: int, total: int) -> None:
        if not args.quiet and sys.stderr.isatty():
            print(f"\r  {done}/{total}", end="" if done < total else "\n", file=sys.stderr, flush=True)

    texts = {}
    for item in args.text or []:
        key, _, path = item.partition("=")
        if not key or not path or not Path(path).expanduser().is_file():
            print(f"starbuck: --text needs KEY=FILE with an existing file: {item}", file=sys.stderr)
            return 2
        texts[key] = path
    settings = judge_settings() if args.claims else None
    second = judge_settings(prefix="STARBUCK_JUDGE2") if settings else None
    zotero = None
    if args.claims and args.zotero is not None:
        try:
            zotero = ZoteroLibrary(args.zotero or None)
        except (OSError, sqlite3.Error) as exc:
            print(f"starbuck: Zotero library not used: {exc}", file=sys.stderr)
    prepared = None
    async with make_sources(args.email, transport, pacing=transport is None,
                            cache=False if args.no_cache else None) as src:
        result = await check_document(doc, src, include_uncited=args.all_entries, progress=progress)
        if not args.claims:
            not_run(result, "not requested (starbuck check --claims)")
        elif not settings:
            not_run(result, "STARBUCK_JUDGE_URL and STARBUCK_JUDGE_MODEL are not set")
            print("starbuck: level 4 skipped: set STARBUCK_JUDGE_URL and STARBUCK_JUDGE_MODEL "
                  "(and STARBUCK_JUDGE_KEY if the endpoint needs one).", file=sys.stderr)
        else:
            if not args.quiet:
                print(f"Level 4: preparing {len(doc.citations)} citations ...", file=sys.stderr)
            prepared = await prepare(doc, result, src, texts, zotero)
    if prepared is not None:
        if not args.quiet:
            ready = sum(c["status"] == "ready" for c in prepared["claims"])
            print(f"Level 4: {ready} citing sentences to {settings['model']} ...", file=sys.stderr)
        verdicts = await judge(prepared["claims"], settings, transport)
        final, judged_by = validate(prepared, verdicts), settings["model"]
        if second:
            if not args.quiet:
                print(f"Level 4: the same sentences to {second['model']} ...", file=sys.stderr)
            verdicts2 = await judge(prepared["claims"], second, transport)
            final = combine(final, validate(prepared, verdicts2))
            judged_by = f"{settings['model']} and {second['model']}"
            verdicts = {"first": verdicts, "second": verdicts2}
        apply(result, final, judged_by)
    out_dir = Path(args.out).expanduser() if args.out else Path(doc.path).parent / "_starbuck"
    paths = write_outputs(result, out_dir, report_stem(doc.path))
    if prepared is not None:
        # The evidence behind every level 4 verdict: passages shown, source texts, raw answers.
        claims_file = out_dir / f"{Path(doc.path).stem}-claims.json"
        claims_file.write_text(json.dumps({**prepared, "verdicts": verdicts}, indent=1, ensure_ascii=False),
                               encoding="utf-8")
    formats = [f.strip() for f in (args.to or "").split(",") if f.strip()]
    shown = paths["qmd"]
    try:
        rendered = render(paths["qmd"], formats)
        shown = rendered.get(formats[0], shown) if formats else shown
    except RenderError as exc:
        print(f"starbuck: {exc}", file=sys.stderr)
    print(to_text(result, str(shown)))
    return exit_code(result)


async def run_ids(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None = None) -> int:
    refs = references_from_identifiers([{"identifier": i} for i in args.identifiers])
    async with make_sources(args.email, transport, pacing=transport is None,
                            cache=False if args.no_cache else None) as src:
        result = await check_given(refs, src)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for r in result["references"]:
            msgs = "; ".join(f["message"] for f in r["findings"]) or "ok"
            rec = (r.get("match") or {}).get("record") or {}
            title = f" {rec.get('title')}" if rec.get("title") else ""
            print(f"{r['verdict'].upper():<6} {r['reference'].get('raw', r['key'])}:{title} [{msgs}]")
    s = result["summary"]
    return 1 if s.get("fail") else 3 if s.get("error") else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="starbuck", description="Reference-integrity checks for manuscripts.")
    p.add_argument("--version", action="version", version=f"starbuck {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="check the references of a Markdown or Quarto manuscript")
    c.add_argument("manuscript", nargs="+", help="Markdown or Quarto files; several are checked one by one")
    c.add_argument("--bib", action="append", help="bibliography file (.bib, .json, .yaml); repeat for several")
    c.add_argument("--out", help="folder for the report (default: _starbuck next to the manuscript)")
    c.add_argument("--to", default="html", help="formats to render: html, docx or html,docx; empty for none")
    c.add_argument("--all-entries", action="store_true", help="also check bibliography entries that are not cited")
    c.add_argument("--email", help="contact address for the services' polite pools (or STARBUCK_EMAIL)")
    c.add_argument("--claims", action="store_true",
                   help="level 4: does each source support the sentence that cites it? Sends the citing "
                        "sentences to the model at STARBUCK_JUDGE_URL")
    c.add_argument("--text", action="append", metavar="KEY=FILE",
                   help="level 4: full text of a cited work as a local text file; repeat for several")
    c.add_argument("--zotero", nargs="?", const="", metavar="DIR",
                   help="level 4: take full texts from the local Zotero library (default ~/Zotero or "
                        "STARBUCK_ZOTERO_DIR); the library is read, never changed")
    c.add_argument("--date", help="manuscript date (YYYY-MM-DD) for notices; default: date: in the YAML header")
    c.add_argument("--if-cited", action="store_true",
                   help="skip files without citations (exit 0), for pre-commit hooks")
    c.add_argument("--no-cache", action="store_true", help="ask every service again; do not use the cache")
    c.add_argument("--quiet", action="store_true")
    i = sub.add_parser("ids", help="check identifiers directly (DOI, PMID, arXiv ID, ISBN)")
    i.add_argument("identifiers", nargs="+")
    i.add_argument("--json", action="store_true")
    i.add_argument("--email")
    i.add_argument("--no-cache", action="store_true")
    k = sub.add_parser("cache", help="show or empty the cache of service answers")
    k.add_argument("--clear", action="store_true", help="delete every kept answer")
    add_fix_parser(sub)
    return p


def run_cache(args: argparse.Namespace) -> int:
    disk = DiskCache()
    if args.clear:
        print(f"Removed {disk.clear()} answers from {disk.path}.")
    else:
        n = disk.db.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
        print(f"{disk.path}: {n} answers. Set STARBUCK_CACHE_DIR to move it, STARBUCK_NO_CACHE=1 to turn it off.")
    disk.close()
    return 0


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        if args.command == "cache":
            code = run_cache(args)
        elif args.command == "fix":
            code = asyncio.run(run_fix(args))
        else:
            code = asyncio.run(run_check(args) if args.command == "check" else run_ids(args))
    except KeyboardInterrupt:
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
