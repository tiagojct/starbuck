"""validation/judge_external.py with a fake judge (no network). The cases are made up for the test."""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "validation"))

import judge_external  # noqa: E402
from run import Recorder, Replayer  # noqa: E402

TEXT = ("Background text about inhaled steroids in adults with asthma. In 400 adults, inhaled steroids reduced "
        "severe exacerbations by 40% over one year. Adverse events were rare and mild in both groups of the trial.")


def case(i, dataset, label, sentence, expected, lenient=None):
    return {"id": f"t{i}", "dataset": dataset, "dataset_id": str(i), "doc_id": str(100 + i), "sentence": sentence,
            "source_title": "A made-up trial", "source_text": TEXT, "label": label, "expected": expected,
            "expected_lenient": lenient or [expected], "in_scholarqabench": False, "origin": "test"}


CASES = [
    case(1, "scifact", "SUPPORT", "Inhaled steroids reduce severe exacerbations in adults.", "supported"),
    case(2, "scifact", "CONTRADICT", "Inhaled steroids increase severe exacerbations.", "not_supported"),
    case(3, "scifact", "NOINFO", "Inhaled steroids change bone density.", "not_supported",
         ["not_supported", "cannot_assess"]),
    case(4, "pubmedqa", "maybe", "This study found that the answer to the question \"Do steroids help?\" is yes.",
         "partly_supported", ["partly_supported", "cannot_assess"]),
]
ANSWERS = {
    "reduce severe": {"verdict": "supported", "quote": "inhaled steroids reduced severe exacerbations by 40%"},
    "increase severe": {"verdict": "supported", "quote": "a passage that is not in the abstract at all"},
    "bone density": {"verdict": "cannot_assess", "quote": ""},
    "Do steroids help": {"verdict": "supported", "quote": "inhaled steroids reduced severe exacerbations"},
}
SETTINGS = {"url": "https://judge.test/v1/chat/completions", "model": "fake-model", "key": "secret-key"}


def fake_judge(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        prompt = json.loads(request.content)["messages"][1]["content"]
        answer = next(a for k, a in ANSWERS.items() if k in prompt)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})
    return httpx.MockTransport(handler)


async def test_external_judge_scores():
    seen: list[httpx.Request] = []
    rows = await judge_external.run(CASES, SETTINGS, fake_judge(seen))
    assert len(seen) == 4 and seen[0].headers["Authorization"] == "Bearer secret-key"
    assert "Passages:" in json.loads(seen[0].content)["messages"][1]["content"]
    by = {r["id"]: r for r in rows}
    assert by["t1"]["verdict"] == "supported" and by["t1"]["agree_strict"]
    assert by["t2"]["verdict"] == "cannot_assess" and by["t2"]["rejected"]  # quote not in the source
    assert by["t3"]["agree_lenient"] and not by["t3"]["agree_strict"]
    assert by["t4"]["verdict"] == "supported" and not by["t4"]["agree_lenient"]
    s = judge_external.summary(rows)
    assert s["overall"] == {"n": 4, "strict": 1, "lenient": 2}
    assert s["confusion"]["scifact NOINFO"]["cannot_assess"] == 1
    assert s["answered"] == 4 and s["rejected"] == 1 and s["false_supported"] == 1
    text = judge_external.report(rows, s, {"date": "2026-10-05", "model": "fake-model", "starbuck": "x",
                                           "mode": "test", "cases_sha256": "0" * 64})
    assert "Agreement, strict: 1/4 = 25.0%" in text and "| scifact NOINFO | 0 | 0 | 0 | 1 |" in text


async def test_recording_keeps_answers_not_the_key():
    recorder = Recorder()
    recorder.inner = fake_judge([])
    rows = await judge_external.run(CASES, SETTINGS, recorder)
    saved = json.dumps(recorder.saved)
    assert "secret-key" not in saved and "reduced severe exacerbations" in saved
    replayed = await judge_external.run(CASES, SETTINGS, Replayer(json.loads(saved)))
    assert [r["verdict"] for r in replayed] == [r["verdict"] for r in rows]


def test_case_file_shape():
    path = judge_external.CASES
    cases = judge_external.load(path)
    assert len(cases) == 100 and len({c["id"] for c in cases}) == 100
    for c in cases:
        assert c["sentence"] and c["source_text"] and c["origin"]
        assert c["expected"] in c["expected_lenient"]
