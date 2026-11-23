"""Check 14 ``placeholder``: a format placeholder left in a document's prose.

A writer's own script can leave ``%s`` or ``{name}`` in a sentence it meant to fill in.
This check is where that is found, not where it comes from. It reads the free text a
reader sees -- the summary's sentences, ``steps``, the rules' text and the columns'
explanations -- and never ``rules[].sql`` or ``columns[].derivation``, where such
characters are code. Inside a field, what is quoted as code or as a value (backticks,
single or double quotes) and a ``${param}`` are skipped, and so is a ``{A}`` written as a
set after ``∈``, ``in`` or ``属于``. A WARN per placeholder, since prose may legitimately
hold these characters; a document with none gets one ``pass`` for the whole document.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

CHECK = "placeholder"

# Spans whose characters are code or a quoted value, blanked before matching.
_QUOTED = re.compile(r"`[^`]*`|'[^']*'|\"[^\"]*\"")
_PLACEHOLDER = re.compile(
    r"%\([A-Za-z_][A-Za-z0-9_]*\)[sd]"           # %(name)s
    r"|(?<![0-9A-Za-z%])%[sd](?![A-Za-z0-9])"   # %s, %d
    r"|\{\{|\}\}"                                # {{ and }}
    r"|\{\}"                                     # {}
    r"|(?<!\$)\{[A-Za-z_][A-Za-z0-9_]*\}"        # {name}, not ${name}
)
# A one-member set written as one: ``状态 ∈ {A}``.
_SET_BEFORE = re.compile(r"(?:∈|\bin|属于)\s*$")


def _fields(document: dict) -> Iterator[tuple[str, str]]:
    """``(path, text)`` of every free-text field the check reads."""
    summary = document.get("summary") or {}
    for key in ("what",):
        yield f"summary.{key}", summary.get(key)
    for part, keys in (("row", ("text", "note", "watch")),
                       ("refresh", ("cycle", "how_to_read", "watch"))):
        for key in keys:
            yield f"summary.{part}.{key}", (summary.get(part) or {}).get(key)
    for part, keys in (("scope", ("text", "watch")), ("upstream", ("provides", "watch")),
                       ("watch", ("text",)), ("questions", ("text", "answer"))):
        for index, item in enumerate(summary.get(part) or []):
            for key in keys:
                yield f"summary.{part}[{index}].{key}", item.get(key)
    for part in ("good_for", "not_for"):
        for index, text in enumerate(summary.get(part) or []):
            yield f"summary.{part}[{index}]", text
    for index, text in enumerate(document.get("steps") or []):
        yield f"steps[{index}]", text
    for index, rule in enumerate(document.get("rules") or []):
        for key in ("text", "watch"):
            yield f"rules[{index}].{key}", rule.get(key)
    for index, column in enumerate(document.get("columns") or []):
        for key in ("meaning", "null_meaning", "watch", "unit"):
            yield f"columns[{index}].{key}", column.get(key)
        for number, branch in enumerate(column.get("branches") or []):
            for key in ("branch", "text"):
                yield f"columns[{index}].branches[{number}].{key}", branch.get(key)


def placeholders(text: str) -> list[str]:
    """The placeholders ``text`` holds, in order, quoted code and one-member sets aside."""
    plain = _QUOTED.sub(lambda match: " " * len(match.group(0)), text)
    found = []
    for match in _PLACEHOLDER.finditer(plain):
        token = match.group(0)
        if token.startswith("{") and token not in ("{{", "{}") and _SET_BEFORE.search(
            plain[: match.start()]
        ):
            continue
        found.append(token)
    return found


def check_placeholder(document: dict, _packet: dict) -> list[dict]:
    """One WARN per placeholder in a free-text field, or one ``pass`` when there is none."""
    results = [
        {"check": CHECK, "status": "warn", "at": at,
         "message": f"像是没替换的占位符 {token}：换成它要说的话（来自写作时用的脚本）"}
        for at, text in _fields(document) if isinstance(text, str)
        for token in placeholders(text)
    ]
    return results or [{"check": CHECK, "status": "pass", "at": "document", "message": ""}]
