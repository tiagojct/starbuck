"""Level 4 judge on an independent set: SciFact and PubMedQA cases (judge_cases.jsonl).

    export STARBUCK_JUDGE_URL=... STARBUCK_JUDGE_MODEL=... [STARBUCK_JUDGE_KEY=...]
    uv run python validation/judge_external.py                live
    uv run python validation/judge_external.py --record       live, and save the judge's answers
    uv run python validation/judge_external.py --replay validation/recordings/<date>-judge-<model>.json.gz

Only Starbuck's judge and quote check run: each case gives the citing sentence and the cited
abstract, so retrieval is bypassed. The abstract is split and ranked as Starbuck does with an
abstract (evidence.chunk, rank), then claims.judge and claims.validate run unchanged.

Scores: agreement with the expected verdict, strict and lenient (see build_judge_cases.py for
the label mapping), with 95% Wilson intervals; a confusion matrix of dataset label by verdict;
the quote rejection rate (rejected quotes / cases the judge answered). Writes
results/<date>-judge-<model>[-replay].md and .csv. Recordings keep the judge's answers and no key.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import httpx

from run import Recorder, Replayer, pct  # validation/run.py

from starbuck import __version__
from starbuck.claims import VERDICTS, judge, judge_settings, validate
from starbuck.evidence import ABSTRACT, ABSTRACT_WORDS, TOP_K, chunk, query_text, rank

HERE = Path(__file__).parent
CASES = HERE / "judge_cases.jsonl"


def load(path: Path = CASES) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prepared(cases: list[dict]) -> dict:
    """The structure claims.prepare would return, built from the cases (no retrieval)."""
    claims, texts = [], {}
    for n, c in enumerate(cases, 1):
        source = f"{c['dataset']} {c['doc_id']}"
        texts[c["id"]] = {"basis": ABSTRACT, "source": source, "text": c["source_text"]}
        claims.append({"id": c["id"], "key": c["id"], "line": n, "sentence": c["sentence"], "status": "ready",
                       "reason": "", "basis": ABSTRACT, "source": source, "label": c["source_title"],
                       "passages": rank(query_text(c["sentence"]), chunk(c["source_text"], "Abstract",
                                                                          ABSTRACT_WORDS), TOP_K)})
    return {"starbuck": __version__, "document": CASES.name, "claims": claims, "texts": texts}


async def run(cases: list[dict], settings: dict, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Judge every case; one row per case with the verdict and whether it agrees."""
    p = prepared(cases)
    final = {c["id"]: c for c in validate(p, await judge(p["claims"], settings, transport))}
    rows = []
    for c in cases:
        v = final[c["id"]]
        rows.append({"id": c["id"], "dataset": c["dataset"], "label": c["label"], "expected": c["expected"],
                     "expected_lenient": " ".join(c["expected_lenient"]), "verdict": v["verdict"],
                     "agree_strict": v["verdict"] == c["expected"],
                     "agree_lenient": v["verdict"] in c["expected_lenient"],
                     "answered": v.get("judged", False) and not v.get("reason", "").startswith("The judge did not"),
                     "rejected": bool(v.get("rejected")), "rejected_verdict": v.get("rejected_verdict", ""),
                     "in_scholarqabench": c.get("in_scholarqabench", False),
                     "quote": v.get("quote", ""), "reason": v.get("reason", "")})
    return rows


def summary(rows: list[dict]) -> dict:
    def agree(rs: list[dict]) -> dict:
        return {"n": len(rs), "strict": sum(r["agree_strict"] for r in rs),
                "lenient": sum(r["agree_lenient"] for r in rs)}

    labels = list(dict.fromkeys((r["dataset"], r["label"]) for r in rows))
    answered = [r for r in rows if r["answered"]]
    return {
        "overall": agree(rows),
        "datasets": {d: agree([r for r in rows if r["dataset"] == d]) for d in dict.fromkeys(r["dataset"] for r in rows)},
        "confusion": {f"{d} {lab}": {v: sum(r["dataset"] == d and r["label"] == lab and r["verdict"] == v for r in rows)
                                     for v in VERDICTS} for d, lab in labels},
        "answered": len(answered), "rejected": sum(r["rejected"] for r in answered),
        "false_supported": sum(r["verdict"] == "supported" and r["expected"] != "supported" for r in rows),
    }


def report(rows: list[dict], s: dict, meta: dict) -> str:
    o = s["overall"]
    out = [f"# Starbuck level 4 judge, independent set: {meta['date']}", "",
           f"Judge: {meta['model']}; Starbuck {meta['starbuck']}; mode: {meta['mode']}; cases: {len(rows)} "
           f"({CASES.name}, SHA-256 {meta['cases_sha256'][:12]}).", "",
           f"- Agreement, strict: {pct(o['strict'], o['n'])}",
           f"- Agreement, lenient (cannot_assess accepted for SciFact NOINFO and PubMedQA maybe): "
           f"{pct(o['lenient'], o['n'])}"]
    for d, a in s["datasets"].items():
        out.append(f"- {d}: strict {pct(a['strict'], a['n'])}; lenient {pct(a['lenient'], a['n'])}")
    out += [f"- Quotes rejected: {pct(s['rejected'], s['answered'])} of the cases the judge answered",
            f"- Supported where the label expects another verdict: {s['false_supported']}", "",
            "## Confusion matrix", "", "| Dataset label | " + " | ".join(VERDICTS) + " |",
            "|---|" + "---|" * len(VERDICTS)]
    for lab, counts in s["confusion"].items():
        out.append(f"| {lab} | " + " | ".join(str(counts[v]) for v in VERDICTS) + " |")
    out += ["", "## Cases that differ (strict)", "", "| Case | Label | Expected | Verdict | Reason |", "|---|---|---|---|---|"]
    for r in rows:
        if not r["agree_strict"]:
            out.append(f"| {r['id']} | {r['dataset']} {r['label']} | {r['expected']} | {r['verdict']} | "
                       f"{r['reason'].replace('|', '/')} |")
    return "\n".join(out) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", action="store_true", help="save the judge's answers to recordings/")
    ap.add_argument("--replay", help="answer from this recording, without the network")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--limit", type=int, default=0, help="only the first N cases (a trial run)")
    args = ap.parse_args()
    path = Path(args.cases)
    if not path.exists():
        print(f"{path} not found: run validation/build_judge_cases.py first.", file=sys.stderr)
        return 2
    cases = load(path)[: args.limit or None]
    recording = json.loads(gzip.decompress(Path(args.replay).read_bytes())) if args.replay else None
    settings = (recording or {}).get("judge") or judge_settings()
    if not settings:
        print("Set STARBUCK_JUDGE_URL and STARBUCK_JUDGE_MODEL, or use --replay.", file=sys.stderr)
        return 2
    transport: httpx.AsyncBaseTransport | None = None
    if recording:
        transport = Replayer(recording["responses"])
    elif args.record:
        transport = Recorder()
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rows = await run(cases, {"key": "", **settings}, transport)

    model = re.sub(r"[^A-Za-z0-9._-]+", "_", settings["model"])
    today = dt.date.today().isoformat()
    stem = f"{today}-judge-{model}" + ("-replay" if args.replay else "")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.record:
        (HERE / "recordings").mkdir(exist_ok=True)
        data = json.dumps({"recorded": started, "starbuck": __version__, "cases_sha256": sha,
                           "judge": {"url": settings["url"], "model": settings["model"]},  # never the key
                           "responses": dict(sorted(transport.saved.items()))}, indent=1, ensure_ascii=False)
        (HERE / "recordings" / f"{today}-judge-{model}.json.gz").write_bytes(gzip.compress(data.encode(), mtime=0))
    if args.replay and transport.missing:
        print(f"{len(transport.missing)} requests were not in the recording.", file=sys.stderr)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    with open(out / f"{stem}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    meta = {"date": started, "model": settings["model"], "starbuck": __version__, "cases_sha256": sha,
            "mode": f"replay of {Path(args.replay).name}" if args.replay else "live"}
    text = report(rows, summary(rows), meta)
    (out / f"{stem}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
