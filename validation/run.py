"""Run Starbuck on the validation set and score it against truth.csv.

    uv run python validation/run.py                  live services
    uv run python validation/run.py --record         live, and save every service answer
    uv run python validation/run.py --replay validation/recordings/2026-10-04.json.gz
                                                     no network: the saved answers only

Writes results/<date>[-replay]-starbuck.json (Starbuck's own result) and
results/<date>[-replay]-scores.md and .csv.

Scoring
- An entry with an injected error is detected when Starbuck's verdict is the
  expected verdict and the expected finding code is among its findings
  (strict), or when the verdict is anything other than Pass (flagged).
- A clean entry is a true negative when the verdict is Pass.
- Entries that Starbuck could not check (a service did not answer) are counted
  apart and left out of sensitivity and specificity.
- 95% confidence intervals are Wilson score intervals.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from starbuck.check import check_document
from starbuck.cli import make_sources
from starbuck.parse import read_manuscript

HERE = Path(__file__).parent
PRIVATE_PARAMS = {"mailto", "email", "api_key", "tool"}  # never written to a recording
API_HOSTS = {"api.crossref.org", "api.datacite.org", "doi.org", "eutils.ncbi.nlm.nih.gov", "api.openalex.org",
             "export.arxiv.org", "openlibrary.org", "www.ebi.ac.uk"}


def request_key(request: httpx.Request) -> str:
    u = urlsplit(str(request.url))
    query = urlencode(sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k not in PRIVATE_PARAMS))
    key = f"{request.method} {urlunsplit((u.scheme, u.netloc, u.path, query, ''))}"
    if request.method != "GET":  # several POSTs to one URL (the level 4 judge): tell them apart by body
        key += " " + hashlib.sha256(request.content).hexdigest()[:16]
    return key


class Recorder(httpx.AsyncBaseTransport):
    """Passes requests to the network and keeps the answers."""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.saved: dict[str, dict] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = request_key(request)
        try:
            response = await self.inner.handle_async_request(request)
        except httpx.HTTPError as exc:
            self.saved[key] = {"error": type(exc).__name__}
            raise
        body = await response.aread()
        # Web pages: only the status matters to Starbuck, so the page itself is not kept.
        # Service answers and every non-GET answer (the level 4 judge) are kept whole.
        api = urlsplit(str(request.url)).netloc in API_HOSTS or request.method != "GET"
        text = body.decode("utf-8", "replace") if api else ""
        # Some services echo the request (Europe PMC returns the email parameter): remove private values.
        for k, v in parse_qsl(urlsplit(str(request.url)).query):
            if k in PRIVATE_PARAMS and len(v) > 3:
                text = text.replace(v, "")
        self.saved[key] = {"status": response.status_code,
                           "content_type": response.headers.get("content-type", ""),
                           "headers": {k: v for k, v in response.headers.items() if k.lower() == "location"},
                           "body": text}
        headers = [(k, v) for k, v in response.headers.items() if k.lower() not in ("content-encoding", "content-length",
                                                                                  "transfer-encoding")]
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()


class Replayer(httpx.AsyncBaseTransport):
    """Answers from a recording; a request that is not in it is an error."""

    def __init__(self, saved: dict[str, dict]) -> None:
        self.saved = saved
        self.missing: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = request_key(request)
        r = self.saved.get(key)
        if r is None:
            self.missing.append(key)
            raise httpx.ConnectError(f"not in recording: {key}", request=request)
        if "error" in r:
            raise getattr(httpx, r["error"], httpx.ConnectError)("recorded error", request=request)
        headers = {"content-type": r["content_type"], **r.get("headers", {})}
        return httpx.Response(r["status"], headers=headers, content=r["body"].encode(), request=request)


def wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959964
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.1f}% ({100 * lo:.1f} to {100 * hi:.1f})"


def score(results: list[dict], truth: list[dict]) -> tuple[list[dict], dict]:
    by_key = {r["key"]: r for r in results}
    rows = []
    for t in truth:
        r = by_key.get(t["key"])
        verdict = r["verdict"] if r else "missing"
        codes = [f["code"] for f in r["findings"]] if r else []
        rows.append({**t, "verdict": verdict, "codes": " ".join(codes),
                     "strict": verdict == t["expected_verdict"] and (not t["expected_code"] or t["expected_code"] in codes),
                     "flagged": verdict not in ("pass", "error", "missing"),
                     "not_checked": verdict in ("error", "missing")})
    per_type = {}
    for et in dict.fromkeys(r["error_type"] for r in rows):
        rs = [r for r in rows if r["error_type"] == et and not r["not_checked"]]
        per_type[et] = {"n": len([r for r in rows if r["error_type"] == et]), "checked": len(rs),
                        "strict": sum(r["strict"] for r in rs), "flagged": sum(r["flagged"] for r in rs)}
    errs = [r for r in rows if r["error_type"] != "none" and not r["not_checked"]]
    clean = [r for r in rows if r["error_type"] == "none" and not r["not_checked"]]
    overall = {"errors": len(errs), "strict": sum(r["strict"] for r in errs), "flagged": sum(r["flagged"] for r in errs),
               "clean": len(clean), "true_negative": sum(r["verdict"] == "pass" for r in clean),
               "not_checked": sum(r["not_checked"] for r in rows), "per_type": per_type}
    return rows, overall


def report(rows: list[dict], overall: dict, meta: dict) -> str:
    out = [f"# Starbuck validation: {meta['date']}", "",
           f"Starbuck {meta['starbuck']}; mode: {meta['mode']}; entries: {len(rows)}; "
           f"not checked: {overall['not_checked']}.", "",
           "## Overall", "",
           f"- Sensitivity, strict (expected verdict and code): {pct(overall['strict'], overall['errors'])}",
           f"- Sensitivity, flagged (any result other than Pass): {pct(overall['flagged'], overall['errors'])}",
           f"- Specificity (clean entries with Pass): {pct(overall['true_negative'], overall['clean'])}", "",
           "## Per error type", "",
           "| Error type | Entries | Checked | Strict | Flagged |", "|---|---|---|---|---|"]
    for et, s in overall["per_type"].items():
        if et != "none":
            out.append(f"| {et} | {s['n']} | {s['checked']} | {pct(s['strict'], s['checked'])} | "
                       f"{pct(s['flagged'], s['checked'])} |")
    s = overall["per_type"].get("none")
    if s:
        out.append(f"| none (clean): Pass | {s['n']} | {s['checked']} | {pct(s['strict'], s['checked'])} | |")
    out += ["", "## Entries that differ from the truth table", "",
            "| Key | Error type | Expected | Starbuck | Codes |", "|---|---|---|---|---|"]
    for r in rows:
        if not r["strict"]:
            out.append(f"| {r['key']} | {r['error_type']} | {r['expected_verdict']} {r['expected_code']} | "
                       f"{r['verdict']} | {r['codes']} |")
    return "\n".join(out) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", action="store_true", help="save every service answer to recordings/<date>.json.gz")
    ap.add_argument("--replay", help="answer from this recording, without the network")
    args = ap.parse_args()
    today = dt.date.today().isoformat()
    doc = read_manuscript(HERE / "manuscript.qmd")
    with open(HERE / "truth.csv", newline="") as f:
        truth = list(csv.DictReader(f))

    transport: httpx.AsyncBaseTransport | None = None
    if args.replay:
        recording = json.loads(gzip.decompress(Path(args.replay).read_bytes()))
        transport = Replayer(recording["responses"])
        mode = f"replay of {Path(args.replay).name} (recorded {recording['recorded']})"
    elif args.record:
        transport = Recorder()
        mode = "live, recorded"
    else:
        mode = "live"
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    # make_sources turns pacing off whenever a transport is given (that is what the tests want);
    # a live recorded run must keep it, so the pacing flag is set from the mode instead.
    async with make_sources(transport=transport, pacing=not args.replay) as src:
        result = await check_document(doc, src)

    out = HERE / "results"
    out.mkdir(exist_ok=True)
    stem = today + ("-replay" if args.replay else "")
    if args.record:
        (HERE / "recordings").mkdir(exist_ok=True)
        rec_path = HERE / "recordings" / f"{today}.json.gz"
        data = json.dumps({"recorded": started, "starbuck": result["starbuck"],
                           "responses": dict(sorted(transport.saved.items()))}, indent=1, ensure_ascii=False)
        rec_path.write_bytes(gzip.compress(data.encode(), mtime=0))
        print(f"Recording: {rec_path}", file=sys.stderr)
    if args.replay and transport.missing:
        print(f"{len(transport.missing)} requests were not in the recording, for example {transport.missing[0]}",
              file=sys.stderr)
    # no local paths in the results
    result["document"] = "validation/manuscript.qmd"
    result["bibliography"] = [f"validation/{Path(b).name}" for b in result.get("bibliography") or []]
    (out / f"{stem}-starbuck.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    rows, overall = score(result["references"], truth)
    meta = {"date": started, "starbuck": result["starbuck"], "mode": mode}
    text = report(rows, overall, meta)
    (out / f"{stem}-scores.md").write_text(text)
    with open(out / f"{stem}-scores.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
