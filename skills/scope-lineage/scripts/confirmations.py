#!/usr/bin/env python3
"""Turn answered 待确认清单 items into the two files the tools read back.

A business profile's third piece is a list of questions; the answers arrive as prose in
the same file, on each item's `- 答案：` line. Left there they are a document nobody's
tooling reads, and the next profile asks the same questions again. This script closes the
loop: it reads `business_profile.md`, keeps the items that have an answer, and routes each
one by its `- 回写目标：` line into the file that owns that kind of answer.

  术语:<词>          -> glossary.overrides.json   terms
  值域:<列>=<值>     -> glossary.overrides.json   values
  字段注释:<表.列>   -> metadata-patch.json       columns
  表注释:<表>        -> metadata-patch.json       tables

Then re-run `scope-lineage glossary --overrides …` and
`scope-lineage describe --glossary … --metadata-patch …`, and the confirmed items come
back as facts instead of questions.

  apply <business_profile.md> --by <name> [--overrides PATH] [--patch PATH]
        [--date YYYY-MM-DD] [--dry-run]

Merging never overwrites: a key another round already answered is kept and counted, so
two reviewers' files can be applied in any order without one erasing the other. An item
with no answer is skipped and counted -- an unanswered question is not an empty answer.
Stdlib only, Python 3.9+. Exit 0 on success, 2 on usage/IO errors.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path


# `Q12.（优先）为什么…` -- the number and the optional priority marker are not the question.
_QUESTION_RE = re.compile(r"^\s*Q(\d+)[.．、]\s*(.*)$")
# `- 回写目标：术语:逾期` -- the field name, then either colon, then the value.
_FIELD_RE = re.compile(r"^\s*[-*]\s*([^:：]+)[:：]\s*(.*)$")

_QUESTION = "question"
_EVIDENCE = "证据"
_TARGET = "回写目标"
_ANSWER = "答案"

# What the template writes before anybody has answered. Anything in this set is "no
# answer yet", not an answer that happens to be short.
_UNANSWERED = frozenset({"", "（待填）", "(待填)", "待填", "—", "-", "待确认", "{答案}"})

_TERM = "术语"
_VALUE = "值域"
_COLUMN_COMMENT = "字段注释"
_TABLE_COMMENT = "表注释"
_TARGET_KINDS = (_TERM, _VALUE, _COLUMN_COMMENT, _TABLE_COMMENT)

PATCH_DOC_FORMAT = "metadata-patch/1"

_DEFAULT_OVERRIDES = "glossary.overrides.json"
_DEFAULT_PATCH = "metadata-patch.json"


# --------------------------------------------------------------------- parsing


def parse_items(text: str) -> list[dict]:
    """Every `Q<n>.` block in the profile, as ``{number, question, 证据, 回写目标, 答案}``.

    Blocks are delimited by the next `Q<n>.` or by a line that is neither blank nor a
    list item -- a heading, a table row, the start of the appendix. The five-line format
    is what the prompt writes; a sixth line (`- 答案：`) is what the business owner adds,
    and its absence is simply an unanswered item.
    """
    items: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        question = _QUESTION_RE.match(line)
        if question:
            current = {"number": int(question.group(1)), _QUESTION: question.group(2).strip()}
            items.append(current)
            continue
        if current is None:
            continue
        if not line.strip():
            continue
        field = _FIELD_RE.match(line)
        if field is None:
            current = None
            continue
        current[field.group(1).strip()] = field.group(2).strip()
    return items


def answer_of(item: dict) -> str | None:
    """The answer somebody wrote, or ``None`` while the placeholder is still there."""
    answer = _clean(item.get(_ANSWER, ""))
    return None if answer in _UNANSWERED else answer


def target_of(item: dict) -> tuple | None:
    """``(kind, subject)`` from the 回写目标 line, or ``None`` when it is not one target.

    The template's own placeholder lists all four kinds separated by `|`; a block that
    still carries it was never filled in, and guessing which kind was meant would write
    an answer into the wrong file.
    """
    raw = _clean(item.get(_TARGET, ""))
    if not raw or "|" in raw or "｜" in raw:
        return None
    for kind in _TARGET_KINDS:
        for separator in (":", "："):
            prefix = kind + separator
            if raw.startswith(prefix):
                subject = _clean(raw[len(prefix):])
                return (kind, subject) if subject else None
    return None


def _clean(value: str) -> str:
    """Strip the decorations a markdown author adds: backticks, braces, whitespace."""
    text = str(value).strip().strip("`").strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()
    return text.strip("`").strip()


# ------------------------------------------------------------------- write-back


def build_write_backs(items: list[dict], *, by: str, date: str) -> dict:
    """Route every answered item into one of the four buckets; count what was skipped."""
    result = {
        "terms": {},
        "values": {},
        "columns": {},
        "tables": {},
        "skipped_unanswered": 0,
        "skipped_no_target": 0,
    }
    stamp = {"confirmed_by": by, "date": date}
    for item in items:
        answer = answer_of(item)
        if answer is None:
            result["skipped_unanswered"] += 1
            continue
        target = target_of(item)
        if target is None:
            result["skipped_no_target"] += 1
            continue
        kind, subject = target
        if kind == _TERM:
            result["terms"][subject] = {"meaning": answer, **stamp}
        elif kind == _VALUE:
            result["values"][subject] = {"meaning": answer, **stamp}
        elif kind == _COLUMN_COMMENT:
            result["columns"][subject] = {"comment": answer, **stamp}
        else:
            result["tables"][subject] = {"table_name_cn": answer, **stamp}
    return result


def merge_overrides(existing: dict, write_backs: dict) -> tuple:
    """``glossary.overrides.json``, with entries somebody already wrote left alone."""
    document = {
        "terms": dict((existing.get("terms") or {})),
        "values": dict((existing.get("values") or {})),
    }
    added, kept = 0, 0
    for group in ("terms", "values"):
        for key, payload in write_backs[group].items():
            if key in document[group]:
                kept += 1
                continue
            document[group][key] = payload
            added += 1
    return document, added, kept


def merge_patch(existing: dict, write_backs: dict) -> tuple:
    """``metadata-patch.json``, same rule: an existing key is never overwritten."""
    document = {
        "doc_format": PATCH_DOC_FORMAT,
        "tables": dict((existing.get("tables") or {})),
        "columns": dict((existing.get("columns") or {})),
    }
    added, kept = 0, 0
    for group in ("tables", "columns"):
        for key, payload in write_backs[group].items():
            if key in document[group]:
                kept += 1
                continue
            document[group][key] = payload
            added += 1
    return document, added, kept


# -------------------------------------------------------------------- commands


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"cannot read {path}: {error}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(document, dict):
        print(f"{path}: expected a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return document


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def cmd_apply(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="confirmations.py apply")
    parser.add_argument("profile", help="business_profile.md with answers filled in")
    parser.add_argument("--by", required=True, help="Who confirmed these answers")
    parser.add_argument("--date", help="Confirmation date (default: today)")
    parser.add_argument(
        "--overrides",
        help=f"glossary overrides file to merge into (default: <profile dir>/{_DEFAULT_OVERRIDES})",
    )
    parser.add_argument(
        "--patch",
        help=f"metadata patch file to merge into (default: <profile dir>/{_DEFAULT_PATCH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print both documents and write nothing",
    )
    args = parser.parse_args(argv)

    profile = Path(args.profile)
    if not profile.is_file():
        print(f"path does not exist: {profile}", file=sys.stderr)
        return 2
    date = args.date or datetime.date.today().isoformat()
    items = parse_items(profile.read_text(encoding="utf-8"))
    write_backs = build_write_backs(items, by=args.by, date=date)

    overrides_path = Path(args.overrides or profile.parent / _DEFAULT_OVERRIDES)
    patch_path = Path(args.patch or profile.parent / _DEFAULT_PATCH)
    overrides, terms_added, terms_kept = merge_overrides(
        _read_json(overrides_path), write_backs
    )
    patch, patch_added, patch_kept = merge_patch(_read_json(patch_path), write_backs)

    if args.dry_run:
        print(f"--- {overrides_path} (dry run)")
        print(json.dumps(overrides, ensure_ascii=False, indent=2))
        print(f"--- {patch_path} (dry run)")
        print(json.dumps(patch, ensure_ascii=False, indent=2))
    else:
        _write_if_any(overrides_path, overrides, ("terms", "values"))
        _write_if_any(patch_path, patch, ("tables", "columns"))
    print(
        f"{len(items)} question(s): "
        f"terms={len(write_backs['terms'])}, values={len(write_backs['values'])}, "
        f"columns={len(write_backs['columns'])}, tables={len(write_backs['tables'])}, "
        f"written={terms_added + patch_added}, kept_existing={terms_kept + patch_kept}, "
        f"unanswered={write_backs['skipped_unanswered']}, "
        f"no_target={write_backs['skipped_no_target']}"
    )
    return 0


def _write_if_any(path: Path, document: dict, groups: tuple) -> None:
    """An empty document is not written: an empty file reads as "everything was cleared"."""
    if any(document.get(group) for group in groups):
        _write_json(path, document)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"apply": cmd_apply}
    if not argv or argv[0] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
