"""Level 4 validation: run Starbuck's claim check on claims.csv and score it.

    export STARBUCK_JUDGE_URL=... STARBUCK_JUDGE_MODEL=... [STARBUCK_JUDGE_KEY=...]
    uv run python validation/run_claims.py                 live (services and judge)
    uv run python validation/run_claims.py --record        live, and save every answer
    uv run python validation/run_claims.py --replay validation/recordings/<date>-claims-<model>.json.gz
    uv run python validation/run_claims.py --evidence-only  no judge: which text each case gets

claims.csv labels map to Starbuck's verdicts: supported -> supported,
partly_supported -> partly_supported, contradicted and not_addressed ->
not_supported. A cannot_assess verdict counts as a miss and is also reported on
its own. Writes results/<date>-claims-<model>[-replay].md and .csv. The judge key
is never written to a recording.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import gzip
import json
import re
import sys
from pathlib import Path

import httpx

from run import Recorder, Replayer, pct  # validation/run.py

from starbuck.check import check_document
from starbuck.claims import VERDICTS, judge, judge_settings, prepare, validate
from starbuck.cli import make_sources
from starbuck.evidence import quote_in
from starbuck.parse import read_manuscript

HERE = Path(__file__).parent
EXPECT = {"supported": "supported", "partly_supported": "partly_supported", "contradicted": "not_supported",
          "not_addressed": "not_supported"}


def write_manuscript(cases: list[dict]) -> Path:
    """One paragraph per case: the sentence, then the citation."""
    path = HERE / "claims.qmd"
    body = [f"{c['sentence'].rstrip('.')} [@{c['key']}]." for c in cases]
    path.write_text('---\ntitle: "Starbuck level 4 cases"\nbibliography: references.bib\n---\n\n'
                    + "\n\n".join(body) + "\n", encoding="utf-8")
    return path


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--replay")
    ap.add_argument("--evidence-only", action="store_true", help="no judge; report the evidence each case gets")
    args = ap.parse_args()
    with open(HERE / "claims.csv", newline="") as f:
        cases = list(csv.DictReader(f))
    doc = read_manuscript(write_manuscript(cases))
    recording = json.loads(gzip.decompress(Path(args.replay).read_bytes())) if args.replay else None
    settings = (recording or {}).get("judge") or judge_settings()
    if not settings and not args.evidence_only:
        print("Set STARBUCK_JUDGE_URL and STARBUCK_JUDGE_MODEL, or use --evidence-only.", file=sys.stderr)
        return 2
    transport: httpx.AsyncBaseTransport | None = None
    if recording:
        transport = Replayer(recording["responses"])
    elif args.record:
        transport = Recorder()
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    async with make_sources(transport=transport, pacing=not args.replay) as src:
        result = await check_document(doc, src)
        prepared = await prepare(doc, result, src)
    # One sentence per paragraph, in the order of claims.csv.
    if len(prepared["claims"]) != len(cases) or any(c["key"] != k["key"] for c, k in zip(prepared["claims"], cases)):
        print("The prepared claims do not line up with claims.csv.", file=sys.stderr)
        return 2
    rows = []
    for case, claim in zip(cases, prepared["claims"]):
        text = (prepared["texts"].get(case["key"]) or {}).get("text", "")
        rows.append({"id": case["id"], "key": case["key"], "expected": case["expected"],
                     "basis": claim["basis"], "source": claim["source"],
                     "gold_passage_in_text": bool(case["passage"]) and quote_in(case["passage"], text),
                     "gold_passage_in_top": bool(case["passage"]) and any(
                         quote_in(case["passage"], p["text"]) for p in claim["passages"]),
                     "claim_id": claim["id"]})
    if args.evidence_only:
        for r in rows:
            print(f"{r['id']} {r['key']:15} {r['expected']:17} {r['basis']:10} {r['source']:28} "
                  f"gold in text {r['gold_passage_in_text']!s:5} in top {r['gold_passage_in_top']}")
        return 0

    verdicts = await judge(prepared["claims"], {"key": "", **settings}, transport)
    final = {c["id"]: c for c in validate(prepared, verdicts)}
    for r in rows:
        c = final[r["claim_id"]]
        r.update(verdict=c["verdict"], rejected=bool(c.get("rejected")), quote=c.get("quote", ""),
                 reason=c.get("reason", ""), agree=c["verdict"] == EXPECT[r["expected"]])

    model = re.sub(r"[^A-Za-z0-9._-]+", "_", settings["model"])
    today = dt.date.today().isoformat()
    stem = f"{today}-claims-{model}" + ("-replay" if args.replay else "")
    if args.record:
        (HERE / "recordings").mkdir(exist_ok=True)
        data = json.dumps({"recorded": started, "starbuck": result["starbuck"],
                           "judge": {"url": settings["url"], "model": settings["model"]},
                           "responses": dict(sorted(transport.saved.items()))}, indent=1, ensure_ascii=False)
        (HERE / "recordings" / f"{today}-claims-{model}.json.gz").write_bytes(gzip.compress(data.encode(), mtime=0))
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    with open(out / f"{stem}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    lines = [f"# Starbuck level 4 validation: {started}", "",
             f"Judge: {settings['model']}; Starbuck {result['starbuck']}; "
             f"mode: {'replay' if args.replay else 'live'}; cases: {len(rows)}.", "",
             f"- Agreement with the expected verdict: {pct(sum(r['agree'] for r in rows), len(rows))}",
             f"- Cannot assess: {sum(r['verdict'] == 'cannot_assess' for r in rows)}, of which quotes rejected: "
             f"{sum(r['rejected'] for r in rows)}",
             f"- Evidence: {sum(r['basis'] == 'full text' for r in rows)} full text, "
             f"{sum(r['basis'] == 'abstract' for r in rows)} abstract", "",
             "| Expected (claims.csv) | " + " | ".join(VERDICTS) + " |", "|---|" + "---|" * len(VERDICTS)]
    for lab in EXPECT:
        lines.append(f"| {lab} | " + " | ".join(str(sum(r["expected"] == lab and r["verdict"] == v for r in rows))
                                              for v in VERDICTS) + " |")
    lines += ["", "| Case | Key | Expected | Verdict | Basis | Reason |", "|---|---|---|---|---|---|"]
    for r in rows:
        if not r["agree"]:
            lines.append(f"| {r['id']} | {r['key']} | {r['expected']} | {r['verdict']} | {r['basis']} | "
                         f"{r['reason'].replace('|', '/')} |")
    text = "\n".join(lines) + "\n"
    (out / f"{stem}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
