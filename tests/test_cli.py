import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from starbuck.cli import parser, run_check, run_ids

MS = """---
title: Draft
bibliography: refs.json
---

Spirometry needs standards [@miller]. A made-up claim [@ghost].
"""
REFS = [{"id": "miller", "title": "Standardisation of spirometry", "author": [{"family": "Miller"}],
         "issued": {"date-parts": [[2005]]}, "DOI": "10.1183/09031936.05.00034805"},
        {"id": "ghost", "title": "Lung function on Mars", "author": [{"family": "Nobody"}],
         "issued": {"date-parts": [[2024]]}, "DOI": "10.1183/13993003.99999-2024"}]


async def test_check_command(tmp_path, fake, capsys):
    (tmp_path / "refs.json").write_text(json.dumps(REFS), encoding="utf-8")
    ms = tmp_path / "draft.md"
    ms.write_text(MS, encoding="utf-8")
    args = parser().parse_args(["check", str(ms), "--to", "", "--quiet"])
    code = await run_check(args, transport=fake.transport())
    out = capsys.readouterr().out
    assert code == 1
    assert "Starbuck checked 2 references: 1 fail, 1 pass." in out
    assert (tmp_path / "_starbuck" / "draft-references.qmd").exists()
    data = json.loads((tmp_path / "_starbuck" / "draft-references.json").read_text(encoding="utf-8"))
    assert data["summary"]["fail"] == 1


async def test_ids_command(fake, capsys):
    args = parser().parse_args(["ids", "10.1183/09031936.05.00034805", "pmid:99999999", "arXiv:1706.03762"])
    code = await run_ids(args, transport=fake.transport())
    lines = capsys.readouterr().out.strip().splitlines()
    assert code == 1
    assert lines[0].startswith("PASS") and "Standardisation of spirometry" in lines[0]
    assert lines[1].startswith("FAIL") and "PMID 99999999" in lines[1]
    assert lines[2].startswith("PASS") and "Attention Is All You Need" in lines[2]


async def test_no_citations(tmp_path, capsys):
    ms = tmp_path / "plain.md"
    ms.write_text("Nothing cited here.\n", encoding="utf-8")
    code = await run_check(parser().parse_args(["check", str(ms)]))
    assert code == 2 and "no citations found" in capsys.readouterr().err


async def test_mcp_server_over_stdio(tmp_path):
    # No reference needs the network: one entry is uncited, the cited key has no entry.
    (tmp_path / "refs.json").write_text(json.dumps(REFS[:1]), encoding="utf-8")
    ms = tmp_path / "x.md"
    ms.write_text("---\nbibliography: refs.json\n---\n\nClaim [@absent].\n\n"
                  "Asthma affects 300 million people around the world, and the number grows.\n", encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=["-m", "starbuck.server"], env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert set(tools) == {"check_manuscript", "check_references", "prepare_claims", "record_claims"}
        assert tools["check_references"].annotations.read_only_hint is True
        res = await s.call_tool("check_manuscript", {"path": str(ms), "formats": []})
        assert not res.is_error, res.content
        sc = res.structured_content
        data = sc.get("result", sc) if isinstance(sc, dict) else json.loads(res.content[0].text)
        assert data["missing_entries"] == [{"key": "absent", "lines": [5]}]
        assert data["summary"]["references_checked"] == 0
        assert data["uncited_sentences"] == {"count": 1, "first": [
            {"line": 7, "sentence": "Asthma affects 300 million people around the world, and the number grows."}]}
        assert data["reports"]["qmd"].endswith("x-references.qmd")
        bad = await s.call_tool("check_references", {"references": []})
        assert bad.is_error and "at least one" in bad.content[0].text
