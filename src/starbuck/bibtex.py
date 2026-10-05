"""A small BibTeX / BibLaTeX reader: entries, fields, @string macros and LaTeX accents.

It reads what reference managers export (Zotero, Better BibTeX, Mendeley, JabRef).
It does not try to be a full BibTeX implementation; an entry it cannot read is
reported and skipped, never guessed.
"""

from __future__ import annotations

import re
import unicodedata

ENTRY_START = re.compile(r"^[ \t]*@([A-Za-z]+)[ \t]*([{(])", re.MULTILINE)
MONTHS = {m: str(i) for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
           ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328",
           "r": "\u030a", "d": "\u0323", "b": "\u0331"}
SYMBOLS = {r"\ss": "ß", r"\o": "ø", r"\O": "Ø", r"\ae": "æ", r"\AE": "Æ", r"\oe": "œ", r"\OE": "Œ",
           r"\aa": "å", r"\AA": "Å", r"\l": "ł", r"\L": "Ł", r"\i": "ı", r"\j": "ȷ"}
ESCAPED = {r"\&": "&", r"\%": "%", r"\_": "_", r"\$": "$", r"\#": "#", r"\{": "{", r"\}": "}"}


class BibError(ValueError):
    pass


def latex_to_text(value: str) -> str:
    s = value
    for k, v in ESCAPED.items():
        s = s.replace(k, v)
    # \'{\i} and \'\i: drop the dotless-i command first so the accent lands on a plain i
    s = re.sub(r"\\i(?![A-Za-z])", "i", s)
    s = re.sub(r"\\j(?![A-Za-z])", "j", s)
    s = re.sub(r"\\([uvHcdbkr])(?:\s*\{(\w)\}|\s+(\w))",
               lambda m: (m.group(2) or m.group(3)) + ACCENTS[m.group(1)], s)
    s = re.sub(r"\\(['`^\"~=.])\s*(?:\{(\w)\}|(\w))",
               lambda m: (m.group(2) or m.group(3)) + ACCENTS[m.group(1)], s)
    for k in sorted(SYMBOLS, key=len, reverse=True):
        s = re.sub(re.escape(k) + r"(?![A-Za-z])\s?", SYMBOLS[k], s)
    s = s.replace("---", "\u2014").replace("--", "\u2013").replace("~", " ")
    s = re.sub(r"\\[A-Za-z]+\*?\s*(?=\{)", "", s)  # \emph{x} -> {x}
    s = re.sub(r"\\[A-Za-z]+\*?", "", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\s+", " ", s).strip()
    return unicodedata.normalize("NFC", s)


def _balanced(text: str, i: int, open_: str, close: str) -> int:
    """Index just after the bracket that closes text[i] (which must be open_)."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise BibError("unbalanced brackets")


def _value(text: str, i: int, close: str, macros: dict[str, str]) -> tuple[str, int]:
    parts: list[str] = []
    n = len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            raise BibError("value runs to the end of the file")
        c = text[i]
        if c == "{":
            end = _balanced(text, i, "{", "}")
            parts.append(text[i + 1 : end - 1])
            i = end
        elif c == '"':
            j = i + 1
            depth = 0
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                elif text[j] == '"' and depth == 0:
                    break
                j += 1
            if j >= n:
                raise BibError("unclosed quote")
            parts.append(text[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[^\s,#}\)]+", text[i:])
            if not m:
                raise BibError(f"unexpected {c!r}")
            word = m.group(0)
            parts.append(macros.get(word.lower(), MONTHS.get(word.lower()[:3], word)) if not word.isdigit()
                         else word)
            i += len(word)
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "#":
            i += 1
            continue
        return "".join(parts), i


def parse(text: str) -> tuple[list[dict], list[str]]:
    """Return (entries, problems). An entry is {"type", "key", "fields"} with lower-case field names."""
    entries: list[dict] = []
    problems: list[str] = []
    macros: dict[str, str] = {}
    done = 0  # end of the last entry read, so text inside an entry is never taken for a new one
    for m in ENTRY_START.finditer(text):
        if m.start() < done:
            continue
        kind = m.group(1).lower()
        open_ = m.group(2)
        close = "}" if open_ == "{" else ")"
        start = m.end() - 1
        line = text.count("\n", 0, m.start()) + 1
        try:
            end = _balanced(text, start, open_, close)
        except BibError:
            problems.append(f"line {line}: @{kind} entry is not closed; skipped")
            continue
        done = end
        if kind in ("comment", "preamble"):
            continue
        body = text[start + 1 : end - 1]
        try:
            if kind == "string":
                name, _, rest = body.partition("=")
                value, _ = _value(rest + close, 0, close, macros)
                macros[name.strip().lower()] = value
                continue
            key, sep, rest = body.partition(",")
            key = key.strip()
            if not sep or not key or re.search(r"\s", key):
                problems.append(f"line {line}: @{kind} entry without a readable key; skipped")
                continue
            fields: dict[str, str] = {}
            i = 0
            rest = rest + close
            while True:
                while i < len(rest) and (rest[i].isspace() or rest[i] == ","):
                    i += 1
                if i >= len(rest) or rest[i] == close:
                    break
                fm = re.match(r"([A-Za-z][\w\-:.+]*)\s*=", rest[i:])
                if not fm:
                    raise BibError(f"cannot read a field near {rest[i:i + 20]!r}")
                i += fm.end()
                value, i = _value(rest, i, close, macros)
                fields[fm.group(1).lower()] = value
            entries.append({"type": kind, "key": key, "fields": fields, "line": line})
        except BibError as exc:
            problems.append(f"line {line}: @{kind} entry {body.split(',', 1)[0].strip()!r} skipped ({exc})")
    return entries, problems


def split_names(value: str) -> list[str]:
    """Split an author field on ' and ' outside braces."""
    names, depth, cur, i = [], 0, [], 0
    while i < len(value):
        c = value[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        m = re.match(r"\s+and\s+", value[i:], re.IGNORECASE) if depth == 0 else None
        if m:
            names.append("".join(cur))
            cur = []
            i += m.end()
            continue
        cur.append(c)
        i += 1
    names.append("".join(cur))
    return [n.strip() for n in names if n.strip()]


def family_name(name: str) -> str:
    n = name.strip()
    if n.startswith("{") and n.endswith("}") and _balanced(n, 0, "{", "}") == len(n):
        return latex_to_text(n)  # group author, e.g. {Global Initiative for Asthma}
    depth = 0
    for i, c in enumerate(n):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "," and depth == 0:
            return latex_to_text(n[:i])
    words, depth, cur = [], 0, []
    for c in n:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c.isspace() and depth == 0:
            if cur:
                words.append("".join(cur))
                cur = []
            continue
        cur.append(c)
    if cur:
        words.append("".join(cur))
    return latex_to_text(words[-1]) if words else ""


def authors(fields: dict[str, str]) -> list[str]:
    raw = fields.get("author") or fields.get("editor") or ""
    return [f for name in split_names(raw) if name.lower() != "others" and (f := family_name(name))]
