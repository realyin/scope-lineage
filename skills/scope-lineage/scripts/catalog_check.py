#!/usr/bin/env python3
"""List what a built catalog left undone.

``catalog validate`` and the merge coverage report catch what is wrong. They pass a
catalog that left work undone, and a weaker drafter leaves exactly that behind. This
script reads a built ``ontology.json`` (``ontology-json/3``, runbook S10g) and reports
these kinds of omission:

  empty_concept                      a concept with no attribute at all;
  missing_participant                an event whose table points at another concept
                                     through a foreign identifier, while that concept is not
                                     among the event's participants;
  attribute_beside_foreign_identifier
                                     a name or description column (``*_desc``, ``*_name``,
                                     ``*_nm``) bound as an attribute of the table's own
                                     concept, while a code column with the same stem in the
                                     same table is a foreign identifier of another concept --
                                     it is probably that concept's attribute;
  state_without_states               an entity with a state attribute that has a code set (its
                                     own or a binding's) and no ``states`` (one state machine, an
                                     object; events and roles carry none), unless
                                     ``catalog_changes.md`` has ``<concept id> states skip: …``;
  measure_without_unit               a measure attribute with no ``unit``;
  code_attribute_without_relation    a column named like a code or a key (``*_cd``, ``*_id``,
                                     ``*_no``, ``*_code``) bound as a plain attribute, not as an
                                     identifier or a foreign identifier, whose attribute has no
                                     code set, and whose stem names another concept (a concept
                                     id's last word or an identifier column's stem) -- it wants a
                                     relation. Such columns naming no concept are listed after
                                     the findings for a look and do not count;
  unabsorbed_rule                    (with ``--digest``) a filter, dedup or derive rule of a
                                     table in ``digest.json`` that no constraint names in its
                                     ``rules`` (``db.table#rN``) and that ``catalog_changes.md``
                                     (``--changes``) does not name either -- each such rule wants
                                     a constraint or a line ``db.table#rN skip: <reason>``.

Each finding is something to look at, not proof of an error: fix it (back to S10c / S10d)
or write in ``catalog_changes.md`` why it stays.

  catalog_check.py ONTOLOGY_JSON [--digest DIGEST_JSON] [--changes CATALOG_CHANGES_MD]

Exit 0 with no findings, 1 with findings (both print ``N finding(s)`` last), 2 when a
file is missing or not what it should be (``ontology-json`` / ``catalog-digest``).
Read-only; standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CODE_SUFFIXES = ("_cd", "_code", "_id", "_no", "_key")
POINTER_SUFFIXES = ("_cd", "_id", "_no", "_code")
RULE_KINDS = ("filter", "dedup", "derive")
TEXT_SUFFIXES = ("_desc", "_name", "_nm")


def _stem(column: str, suffixes: tuple[str, ...]) -> str | None:
    for suffix in suffixes:
        if column.endswith(suffix) and len(column) > len(suffix):
            return column[: -len(suffix)]
    return None


def check(
    ontology: dict, digest: dict | None = None, changes: str = "", look: list[str] | None = None
) -> list[str]:
    """The findings; code columns bound as plain attributes that name no concept go to
    ``look`` (listed for a person, not counted)."""
    identifies = {i["id"]: i.get("identifies") for i in ontology.get("identifiers") or []}
    concepts = {c["id"]: c for c in ontology.get("concepts") or []}
    findings = []
    look = look if look is not None else []

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

    # An attribute is coded when it has a code set of its own or a binding of it lists one
    # (the rule ``catalog validate`` applies).
    bound_codes = {
        b.get("ref") for r in ontology.get("representations") or [] for b in r.get("bindings") or []
        if b.get("code_sets")
    }
    skipped = {m.lower() for m in re.findall(r"([\w:.]+)`?\s+states\s+skip", changes)}
    for concept_id, concept in concepts.items():
        # ``states`` is one state machine (an object) and only an entity carries it.
        coded = [
            a["id"] for a in concept.get("attributes") or []
            if a.get("category") == "state" and (a.get("code_set") or a["id"] in bound_codes)
        ]
        if (
            concept.get("kind") == "entity" and coded and not concept.get("states")
            and concept_id.lower() not in skipped
        ):
            findings.append(
                f"state_without_states  {concept_id}：状态属性 {'、'.join(coded)} 有码值集，概念没有 states"
                f"（挑描述生命周期的那一个写 states；都不是生命周期状态时，在 catalog_changes.md 写一行 "
                f"`{concept_id} states skip: <理由>`）"
            )
        for attribute in concept.get("attributes") or []:
            if attribute.get("category") == "measure" and not attribute.get("unit"):
                findings.append(f"measure_without_unit  {attribute['id']}：度量属性没有 unit")

    names = _concept_stems(concepts, ontology.get("identifiers") or [])
    attributes = {a["id"]: a for c in concepts.values() for a in c.get("attributes") or []}
    for representation in ontology.get("representations") or []:
        own = representation.get("concept")
        for binding in representation.get("bindings") or []:
            column = binding.get("column", "")
            if binding.get("to") != "attribute" or not column.endswith(POINTER_SUFFIXES):
                continue
            if (attributes.get(binding.get("ref")) or {}).get("code_set"):
                continue  # a coded value with its code set, not a pointer
            at = f"{representation['table']}.{column}"
            target = names.get(_stem(column, POINTER_SUFFIXES) or "")
            if target and target != own:
                findings.append(
                    f"code_attribute_without_relation  {at} 绑成属性 {binding.get('ref')}（无码值集），"
                    f"列名词干指向 {target}：应建关系并绑成 foreign_identifier；确实只是本概念自己的编号就在 "
                    f"catalog_changes.md 写理由"
                )
            else:
                look.append(f"{at}（{binding.get('ref')}）")

    if digest is not None:
        carried = {ref.lower() for c in ontology.get("constraints") or [] for ref in c.get("rules") or []}
        named = {m.lower() for m in re.findall(r"([\w.]+#r\d+)`?\s+skip", changes)}
        for table in digest.get("tables") or []:
            for rule in table.get("rules") or []:
                if rule.get("kind") not in RULE_KINDS:
                    continue
                ref = f"{table['table']}#{rule['id']}"
                if ref.lower() not in carried and ref.lower() not in named:
                    findings.append(
                        f"unabsorbed_rule  {ref} {rule['kind']}：{rule.get('text', '')} —— 没有约束的 rules 引用它，"
                        f"catalog_changes.md 也没写 skip 理由"
                    )
    return findings


def _concept_stems(concepts: dict, identifiers: list[dict]) -> dict:
    """``stem -> concept`` a code column's name may point at: the last word of each concept id
    (``concept:queue`` -> ``queue``) and the stem of each identifier spelling's column
    (``cust_id`` -> ``cust``)."""
    stems = {concept_id.rsplit(".", 1)[-1].split(":")[-1]: concept_id for concept_id in concepts}
    for identifier in identifiers:
        columns = [str(s.get("column") or "") for s in identifier.get("spellings") or []]
        columns.append(str(identifier.get("id") or "").split(":", 1)[-1])
        for column in columns:
            stem = _stem(column, POINTER_SUFFIXES)
            if stem and identifier.get("identifies"):
                stems.setdefault(stem, identifier["identifies"])
    return stems


def _load(path: Path, prefix: str) -> dict | None:
    if not path.is_file():
        print(f"文件不存在：{path}", file=sys.stderr)
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not str(data.get("doc_format", "")).startswith(prefix + "/"):
        found = data.get("doc_format") if isinstance(data, dict) else None
        print(f"{path} 不是 {prefix}（doc_format={found}）", file=sys.stderr)
        return None
    return data


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="catalog_check.py", usage="catalog_check.py ONTOLOGY_JSON "
                                     "[--digest DIGEST_JSON] [--changes CATALOG_CHANGES_MD]")
    parser.add_argument("ontology")
    parser.add_argument("--digest", help="digest/digest.json (catalog-digest/1)")
    parser.add_argument("--changes", help="catalog_changes.md, where a rule left out is named with its reason")
    args = parser.parse_args(argv[1:])
    ontology = _load(Path(args.ontology), "ontology-json")
    if ontology is None:
        return 2
    digest = None
    if args.digest:
        digest = _load(Path(args.digest), "catalog-digest")
        if digest is None:
            return 2
    changes = ""
    if args.changes:
        if not Path(args.changes).is_file():
            print(f"文件不存在：{args.changes}", file=sys.stderr)
            return 2
        changes = Path(args.changes).read_text(encoding="utf-8")
    look: list[str] = []
    findings = check(ontology, digest, changes, look)
    for finding in findings:
        print(finding)
    if look:
        print(f"供人看（不计入）：{len(look)} 个编码列绑成属性、无码值集、列名不指向已有概念——"
              "若其实指向一个还没建的对象，按 S10g 返工建概念；否则不用处理")
        for item in look:
            print(f"  {item}")
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
