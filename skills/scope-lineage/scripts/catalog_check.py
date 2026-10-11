#!/usr/bin/env python3
"""List what a built catalog left undone.

``catalog validate`` and the merge coverage report catch what is wrong. They pass a
catalog that left work undone, and a weaker drafter leaves exactly that behind. This
script reads a built ``ontology.json`` (``ontology-json/3``, runbook S10g) and reports
three kinds of omission:

  empty_concept                      a concept with no attribute at all;
  missing_participant                an event whose table points at another concept
                                     through a foreign identifier, while that concept is not
                                     among the event's participants;
  attribute_beside_foreign_identifier
                                     a name or description column (``*_desc``, ``*_name``,
                                     ``*_nm``) bound as an attribute of the table's own
                                     concept, while a code column with the same stem in the
                                     same table is a foreign identifier of another concept --
                                     it is probably that concept's attribute.

Each finding is something to look at, not proof of an error: fix it (back to S10c / S10d)
or write in ``catalog_changes.md`` why it stays.

  catalog_check.py ONTOLOGY_JSON

Exit 0 with no findings, 1 with findings (both print ``N finding(s)`` last), 2 when the
file is missing or not ``ontology-json``. Read-only; standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CODE_SUFFIXES = ("_cd", "_code", "_id", "_no", "_key")
TEXT_SUFFIXES = ("_desc", "_name", "_nm")


def _stem(column: str, suffixes: tuple[str, ...]) -> str | None:
    for suffix in suffixes:
        if column.endswith(suffix) and len(column) > len(suffix):
            return column[: -len(suffix)]
    return None


def check(ontology: dict) -> list[str]:
    identifies = {i["id"]: i.get("identifies") for i in ontology.get("identifiers") or []}
    concepts = {c["id"]: c for c in ontology.get("concepts") or []}
    findings = []

    for concept_id, concept in concepts.items():
        if not concept.get("attributes"):
            findings.append(f"empty_concept  {concept_id}：没有任何属性")

    for representation in ontology.get("representations") or []:
        table, own = representation["table"], representation.get("concept")
        bindings = representation.get("bindings") or []
        pointers = {}  # column -> concept it points at
        for binding in bindings:
            if binding.get("to") == "foreign_identifier":
                target = identifies.get(binding.get("ref"))
                if target and target != own:
                    pointers[binding["column"]] = target

        event = concepts.get(own) or {}
        if event.get("kind") == "event":
            participants = {p.get("concept") for p in event.get("participants") or []}
            for column, target in pointers.items():
                if target not in participants:
                    findings.append(
                        f"missing_participant  {own}：{table}.{column} 指向 {target}，它不在参与者里"
                    )

        code_stems = {}
        for column, target in pointers.items():
            stem = _stem(column, CODE_SUFFIXES)
            if stem:
                code_stems[stem] = (column, target)
        for binding in bindings:
            if binding.get("to") != "attribute":
                continue
            stem = _stem(binding["column"], TEXT_SUFFIXES)
            if stem in code_stems:
                code_column, target = code_stems[stem]
                findings.append(
                    f"attribute_beside_foreign_identifier  {table}.{binding['column']} 绑成 {binding.get('ref')}，"
                    f"但同表 {code_column} 指向 {target}：可能是 {target} 的属性"
                )
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：catalog_check.py ONTOLOGY_JSON", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 2
    ontology = json.loads(path.read_text(encoding="utf-8"))
    if not str(ontology.get("doc_format", "")).startswith("ontology-json/"):
        print(f"{path} 不是 ontology-json（doc_format={ontology.get('doc_format')}）", file=sys.stderr)
        return 2
    findings = check(ontology)
    for finding in findings:
        print(finding)
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
