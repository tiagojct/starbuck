"""Check the level 4 cases in claims.csv against the saved abstracts.

    uv run python validation/check_claims.py

Every passage must appear word for word in the abstract of its source
(evidence/abstracts.json), every source must be an entry of truth.csv, and a
case labelled not_addressed has no passage. The labels are drafts until a
person has reviewed them (status column).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
LABELS = {"supported", "partly_supported", "contradicted", "not_addressed"}


def main() -> int:
    abstracts = json.loads((HERE / "evidence" / "abstracts.json").read_text())["abstracts"]
    with open(HERE / "truth.csv", newline="") as f:
        keys = {r["key"] for r in csv.DictReader(f)}
    with open(HERE / "claims.csv", newline="") as f:
        claims = list(csv.DictReader(f))
    problems = []
    for c in claims:
        if c["expected"] not in LABELS:
            problems.append(f"{c['id']}: unknown label {c['expected']!r}")
        if c["key"] not in keys:
            problems.append(f"{c['id']}: {c['key']} is not in truth.csv")
        if c["key"] not in abstracts:
            problems.append(f"{c['id']}: no saved abstract for {c['key']}")
            continue
        if c["expected"] == "not_addressed":
            if c["passage"]:
                problems.append(f"{c['id']}: not_addressed has a passage")
        elif not c["passage"] or c["passage"] not in abstracts[c["key"]]["text"]:
            problems.append(f"{c['id']}: passage not found word for word in the abstract of {c['key']}")
    counts = {label: sum(c["expected"] == label for c in claims) for label in sorted(LABELS)}
    drafts = sum(c["status"] == "draft" for c in claims)
    print(f"{len(claims)} cases: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"; {drafts} still drafts.")
    for p in problems:
        print(f"  - {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
