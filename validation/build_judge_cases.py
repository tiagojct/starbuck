"""Build judge_cases.jsonl: an independent test set for the level 4 judge, from SciFact and PubMedQA.

    uv run python validation/build_judge_cases.py            download (or reuse the cache) and write
    uv run python validation/build_judge_cases.py --cache DIR

Sources (the files are checked against the SHA-256 below; a changed file stops the build):
- SciFact (Wadden et al., 2020): claims_dev.jsonl and corpus.jsonl from the release tarball.
  Claims and labels CC BY 4.0; abstracts (S2ORC) ODC-By 1.0.
- PubMedQA (Jin et al., 2019): ori_pqal.json (PQA-L, 1,000 expert-labelled questions), MIT.
- ScholarQABench (Asai et al., OpenScholar): scifact_test.jsonl and pubmed_test.jsonl, only to mark
  the cases that ScholarQABench also uses (ODC-BY).

Selection (seed SEED, fixed):
- SciFact dev claims that cite exactly one abstract and have one label: 20 SUPPORT, 20 CONTRADICT,
  20 NOINFO. The source text is that abstract (title kept apart).
- PubMedQA PQA-L: 15 yes, 15 no, 10 maybe. The source text is the abstract without its conclusion
  (CONTEXTS), as in PubMedQA. A PubMedQA item is a question, not a claim, so the citing sentence is
  made by one fixed template (TEMPLATE) that states the answer "yes"; the expected verdict then
  follows the label.

Labels to Starbuck's verdicts, strict and lenient (lenient also accepts cannot_assess where the
source does not settle the claim):
  SciFact SUPPORT -> supported; CONTRADICT -> not_supported;
          NOINFO -> not_supported (strict), not_supported or cannot_assess (lenient)
  PubMedQA yes -> supported; no -> not_supported;
           maybe -> partly_supported (strict), partly_supported or cannot_assess (lenient)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import tarfile
from pathlib import Path

import httpx

HERE = Path(__file__).parent
SEED = 20261005
N_SCIFACT = {"SUPPORT": 20, "CONTRADICT": 20, "NOINFO": 20}
N_PUBMEDQA = {"yes": 15, "no": 15, "maybe": 10}
TEMPLATE = 'This study found that the answer to the question "{question}" is yes.'
STRICT = {("scifact", "SUPPORT"): "supported", ("scifact", "CONTRADICT"): "not_supported",
          ("scifact", "NOINFO"): "not_supported", ("pubmedqa", "yes"): "supported",
          ("pubmedqa", "no"): "not_supported", ("pubmedqa", "maybe"): "partly_supported"}
LENIENT = {("scifact", "NOINFO"): ["not_supported", "cannot_assess"],
           ("pubmedqa", "maybe"): ["partly_supported", "cannot_assess"]}

SQAB = "https://raw.githubusercontent.com/AkariAsai/ScholarQABench/95e6fc52b0a8a0ce0a74956029991e3bb00c38b9"
FILES = {
    "scifact_data.tar.gz": ("https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz",
                            "11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be"),
    "ori_pqal.json": ("https://raw.githubusercontent.com/pubmedqa/pubmedqa/"
                      "1cbae8e92f72f20c8d3747cbb3bf5bc53554d997/data/ori_pqal.json",
                      "8b3276be8942ebbd77f3ddcda12c1749bf0e490045a736fd8438ee40cf37a41d"),
    "sqab_scifact_test.jsonl": (f"{SQAB}/data/single_paper_tasks/scifact_test.jsonl",
                                "f2ef58b77295453385d5528a146af9a0839bd9cc57c9e7f6b06ca9df45d08d5d"),
    "sqab_pubmed_test.jsonl": (f"{SQAB}/data/single_paper_tasks/pubmed_test.jsonl",
                               "1cce262d881ae1802766d6bda7447d7f80bddc535f23a5976a99f8a23f422e46"),
}
ORIGIN = {
    "scifact": "SciFact dev set, https://github.com/allenai/scifact (claims CC BY 4.0; abstracts from S2ORC, "
               "ODC-By 1.0)",
    "pubmedqa": "PubMedQA PQA-L, https://github.com/pubmedqa/pubmedqa (MIT)",
}


def fetch(cache: Path) -> dict[str, bytes]:
    """The source files, from the cache or downloaded; each one checked against its SHA-256."""
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, (url, sha) in FILES.items():
        path = cache / name
        if not path.exists():
            print(f"Downloading {url}", file=sys.stderr)
            r = httpx.get(url, follow_redirects=True, timeout=300)
            r.raise_for_status()
            path.write_bytes(r.content)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit(f"{name} differs from the file this set was built from (SHA-256). Stopped.")
        out[name] = data
    return out


def scifact_cases(tarball: bytes, sqab_claims: set[str], rng: random.Random) -> list[dict]:
    with tarfile.open(fileobj=io.BytesIO(tarball)) as tar:
        dev = [json.loads(line) for line in tar.extractfile("data/claims_dev.jsonl").read().splitlines()]
        corpus = {d["doc_id"]: d for line in tar.extractfile("data/corpus.jsonl").read().splitlines()
                  if (d := json.loads(line))}
    pools: dict[str, list[tuple[dict, int]]] = {k: [] for k in N_SCIFACT}
    for c in dev:
        labels = {e["label"] for ev in c["evidence"].values() for e in ev}
        docs = [int(d) for d in c["evidence"]] or c["cited_doc_ids"]
        if len(docs) != 1 or len(labels) > 1:
            continue  # one cited abstract and one label only
        pools[labels.pop() if labels else "NOINFO"].append((c, docs[0]))
    out = []
    for label, n in N_SCIFACT.items():
        for c, doc_id in sorted(rng.sample(pools[label], n), key=lambda x: x[0]["id"]):
            doc = corpus[doc_id]
            out.append({"id": f"sf{c['id']}-{doc_id}", "dataset": "scifact", "dataset_id": str(c["id"]),
                        "doc_id": str(doc_id), "sentence": c["claim"], "source_title": doc["title"],
                        "source_text": " ".join(s.strip() for s in doc["abstract"]),
                        "label": label, "expected": STRICT[("scifact", label)],
                        "expected_lenient": LENIENT.get(("scifact", label), [STRICT[("scifact", label)]]),
                        "in_scholarqabench": c["claim"] in sqab_claims, "origin": ORIGIN["scifact"]})
    return out


def pubmedqa_cases(pqal: dict, sqab_questions: set[str], rng: random.Random) -> list[dict]:
    pools: dict[str, list[str]] = {k: [] for k in N_PUBMEDQA}
    for pmid in sorted(pqal):
        pools[pqal[pmid]["final_decision"]].append(pmid)
    out = []
    for label, n in N_PUBMEDQA.items():
        for pmid in sorted(rng.sample(pools[label], n)):
            item = pqal[pmid]
            out.append({"id": f"pq{pmid}", "dataset": "pubmedqa", "dataset_id": pmid, "doc_id": pmid,
                        "sentence": TEMPLATE.format(question=item["QUESTION"].strip()),
                        "question": item["QUESTION"], "source_title": f"PubMed {pmid}",
                        "source_text": " ".join(c.strip() for c in item["CONTEXTS"]),
                        "label": label, "expected": STRICT[("pubmedqa", label)],
                        "expected_lenient": LENIENT.get(("pubmedqa", label), [STRICT[("pubmedqa", label)]]),
                        "in_scholarqabench": item["QUESTION"] in sqab_questions, "origin": ORIGIN["pubmedqa"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default=str(HERE / ".cache"), help="folder for the downloaded files")
    ap.add_argument("--out", default=str(HERE / "judge_cases.jsonl"))
    args = ap.parse_args()
    files = fetch(Path(args.cache))
    sqab_sf = {json.loads(line)["input"] for line in files["sqab_scifact_test.jsonl"].splitlines()}
    sqab_pq = {json.loads(line)["input"] for line in files["sqab_pubmed_test.jsonl"].splitlines()}
    rng = random.Random(SEED)
    cases = scifact_cases(files["scifact_data.tar.gz"], sqab_sf, rng)
    cases += pubmedqa_cases(json.loads(files["ori_pqal.json"]), sqab_pq, rng)
    Path(args.out).write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    print(f"{len(cases)} cases written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
