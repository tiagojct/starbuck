"""Render the Quarto report to HTML or Word.

Quarto is used when it is installed (QUARTO_PATH or `quarto` on PATH); Pandoc
is the fallback. Rendering happens in a temporary folder, so a surrounding
Quarto project (its _quarto.yml, output-dir or filters) never changes the report.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

FORMATS = {"html": ".html", "docx": ".docx"}


class RenderError(RuntimeError):
    pass


def engine() -> tuple[str, str] | None:
    """("quarto" | "pandoc", executable path), or None when neither is installed."""
    q = os.environ.get("QUARTO_PATH") or shutil.which("quarto")
    if q and Path(q).exists():
        return "quarto", q
    p = shutil.which("pandoc")
    if p:
        return "pandoc", p
    return None


def render(qmd: Path, formats: list[str], timeout: int = 180) -> dict[str, Path]:
    """Render qmd to each format; outputs are written next to the .qmd."""
    wanted = [f for f in formats if f in FORMATS]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise RenderError(f"Unknown format(s): {', '.join(unknown)}. Use html and/or docx.")
    if not wanted:
        return {}
    found = engine()
    if not found:
        raise RenderError("Neither Quarto nor Pandoc is installed; the report stays as a .qmd file. "
                          "Install Quarto from https://quarto.org to get HTML and Word reports.")
    kind, exe = found
    out: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="starbuck-") as tmp:
        src = Path(tmp) / qmd.name
        shutil.copyfile(qmd, src)
        for fmt in wanted:
            target = src.with_suffix(FORMATS[fmt])
            if kind == "quarto":
                cmd = [exe, "render", src.name, "--to", fmt]
            else:
                cmd = [exe, "-f", "markdown", "-s", *(["--toc"] if fmt == "html" else []), "-o", target.name, src.name]
            try:
                res = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise RenderError(f"{kind} did not finish within {timeout} s") from exc
            if res.returncode != 0 or not target.exists():
                raise RenderError(f"{kind} could not render {fmt}: {(res.stderr or res.stdout).strip()[-800:]}")
            final = qmd.with_suffix(FORMATS[fmt])
            shutil.move(str(target), final)
            out[fmt] = final
    return out
