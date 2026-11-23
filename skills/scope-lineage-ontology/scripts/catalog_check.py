#!/usr/bin/env python3
"""List what a built catalog left undone.

``catalog validate`` and the merge coverage report catch what is wrong. They pass a
catalog that left work undone, and a weaker drafter leaves exactly that behind. This
script reads a built ``ontology.json`` (``ontology-json/3``, runbook S10g) and reports
these kinds of omission:

  empty_concept                      a concept with no attribute at all, unless it has no
                                     table of its own in the batch and ``catalog_changes.md``
                                     has ``<concept id> empty skip: …``;
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
  measure_without_unit               a measure attribute with no ``unit``, unless its
                                     ``notes`` carry 「待 owner 确认：单位」 (the material gives
                                     none; listed after the findings for the owner, not counted);
  unit_in_digest                     (with ``--digest``) a measure attribute whose ``notes``
                                     carry that sentence while the digest gives a unit for a
                                     column bound to it -- the unit is in the material, write it;
  metric_incomplete                  a metric with no ``unit`` or ``additivity``, or a sum,
                                     avg, min or max with no ``measure``; no unit is not reported
                                     when the measure has none and its notes carry that sentence;
  code_attribute_without_relation    (cleared by ``<db.table.column> code skip: …`` in
                                     ``catalog_changes.md``) a column named like a code or a key (``*_cd``, ``*_id``,
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
                                     a constraint or a line ``db.table#rN skip: <reason>``;
  measure_repeats_within_grain       (with ``--digest``) an ``additive`` measure attribute bound
                                     to a column whose digest ``joined_in`` names a JOIN whose
                                     keys do not cover that table's grain (a grain column is not
                                     among the keys): rows sharing the key carry the same value,
                                     and adding across rows counts it again. One finding per
                                     attribute, listing each such table, column, JOIN, keys,
                                     grain (and whether it is declared, inferred or proven) and
                                     fan-out status, and the ``sum`` + ``additive`` metrics over
                                     it; an empty grain is not compared. Cleared when the
                                     attribute is no longer ``additive``, when its ``notes`` name
                                     every listed table (by ``db.table`` or the table name), or
                                     by ``<attribute id> repeats skip: <reason>``.

Each finding is something to look at, not proof of an error: fix it (back to S10c / S10d)
or write in ``catalog_changes.md`` why it stays.

Listed after the findings for a person, not counted: measures with no unit whose notes
carry that sentence, and (with ``--digest``) measures with a unit that no column bound to
them has in the digest -- a unit with nothing in the material behind it. The orchestrator
copies both lists into ``RESULT.md``'s pending-confirmation summary for the owner. A measure
none of whose bound columns the digest lists is not compared with it.

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
MEASURED_AGGREGATIONS = ("sum", "avg", "min", "max")
TEXT_SUFFIXES = ("_desc", "_name", "_nm")
# What T5 and T6 tell the drafter to write in a measure's ``notes`` when the digest gives no
# unit (the drafter then writes no ``unit``); the same literal as ``UNIT_LEFT_TO_OWNER`` in
# ``scope_lineage/catalog/soft_checks.py``, which this standard-library script cannot import.
UNIT_LEFT_TO_OWNER = "待 owner 确认：单位"


def _stem(column: str, suffixes: tuple[str, ...]) -> str | None:
    for suffix in suffixes:
        if column.endswith(suffix) and len(column) > len(suffix):
            return column[: -len(suffix)]
    return None


def check(
    ontology: dict,
    digest: dict | None = None,
    changes: str = "",
    look: list[str] | None = None,
    units: dict[str, list[str]] | None = None,
) -> list[str]:
    """The findings; code columns bound as plain attributes that name no concept go to
    ``look``, and the measures whose unit a person has to settle to ``units`` (``left``:
    no unit, left to the owner; ``unsupported``: a unit the digest does not give) -- listed
    for a person, not counted."""
    concepts = {c["id"]: c for c in ontology.get("concepts") or []}
    look = look if look is not None else []
    units = units if units is not None else {}
    findings = _empty_concept_findings(ontology, concepts, changes)
    for representation in ontology.get("representations") or []:
        findings += _representation_findings(ontology, concepts, representation)
    findings += _state_and_measure_findings(ontology, concepts, changes)
    findings += _unit_findings(
        ontology, digest, units.setdefault("left", []), units.setdefault("unsupported", [])
    )
    findings += _code_column_findings(ontology, concepts, changes, look)
    findings += _metric_findings(ontology)
    if digest is not None:
        findings += _rule_findings(ontology, digest, changes)
        findings += _repeat_findings(ontology, digest, changes)
    return findings


def _empty_concept_findings(ontology: dict, concepts: dict, changes: str) -> list[str]:
    """``empty_concept``. A concept with a table of its own takes its attributes from that
    table's columns; one with none (only ever the target of a foreign identifier in this
    batch) may be cleared by ``<concept id> empty skip: <reason>``."""
    tables = {}
    for representation in ontology.get("representations") or []:
        tables.setdefault(representation.get("concept"), []).append(representation["table"])
    skipped = {m.lower() for m in re.findall(r"([\w:.]+)`?\s+empty\s+skip", changes)}
    findings = []
    for concept_id, concept in concepts.items():
        if concept.get("attributes"):
            continue
        if concept_id in tables:
            findings.append(
                f"empty_concept  {concept_id}：没有任何属性（它有自己的表 {'、'.join(tables[concept_id])}，"
                f"从这些表的列建属性）"
            )
        elif concept_id.lower() not in skipped:
            findings.append(
                f"empty_concept  {concept_id}：没有任何属性（本批没有它自己的表；属性确实只在本批以外的表里时，"
                f"在 catalog_changes.md 写一行 `{concept_id} empty skip: <理由>`）"
            )
    return findings


def _metric_findings(ontology: dict) -> list[str]:
    """``metric_incomplete``: a metric with no ``unit`` or ``additivity``, or one that adds
    up, averages or picks an extreme with no ``measure`` to do it over. A metric whose
    measure has no unit and leaves it to the owner has none to copy: no unit is not
    reported for it."""
    attributes = {a["id"]: a for a in _measures(ontology)}
    findings = []
    for metric in ontology.get("metrics") or []:
        measure = attributes.get(metric.get("measure") or "") or {}
        unit_left = bool(measure) and not measure.get("unit") and _left_to_owner(measure)
        missing = [
            key for key in ("measure", "unit", "additivity")
            if not metric.get(key)
            and (key != "measure" or metric.get("aggregation") in MEASURED_AGGREGATIONS)
            and (key != "unit" or not unit_left)
        ]
        if missing:
            findings.append(f"metric_incomplete  {metric['id']}：缺 {'、'.join(missing)}")
    return findings


def _representation_findings(ontology: dict, concepts: dict, representation: dict) -> list[str]:
    """``missing_participant`` and ``attribute_beside_foreign_identifier`` of one table."""
    identifies = {i["id"]: i.get("identifies") for i in ontology.get("identifiers") or []}
    table, own = representation["table"], representation.get("concept")
    bindings = representation.get("bindings") or []
    findings = []
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


def _state_and_measure_findings(ontology: dict, concepts: dict, changes: str) -> list[str]:
    """``state_without_states`` and ``measure_without_unit``."""
    # An attribute is coded when it has a code set of its own or a binding of it lists one
    # (the rule ``catalog validate`` applies).
    bound_codes = {
        b.get("ref") for r in ontology.get("representations") or [] for b in r.get("bindings") or []
        if b.get("code_sets")
    }
    skipped = {m.lower() for m in re.findall(r"([\w:.]+)`?\s+states\s+skip", changes)}
    findings = []
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
            if (
                attribute.get("category") == "measure" and not attribute.get("unit")
                and not _left_to_owner(attribute)
            ):
                findings.append(f"measure_without_unit  {attribute['id']}：度量属性没有 unit")
    return findings


def _left_to_owner(attribute: dict) -> bool:
    """Whether the attribute's ``notes`` carry ``UNIT_LEFT_TO_OWNER``."""
    notes = attribute.get("notes")
    if isinstance(notes, list):
        notes = "；".join(str(note) for note in notes)
    return UNIT_LEFT_TO_OWNER in str(notes or "")


def _measures(ontology: dict) -> list[dict]:
    return [
        a for c in ontology.get("concepts") or [] for a in c.get("attributes") or []
        if a.get("category") == "measure"
    ]


def _bound_columns(ontology: dict) -> dict:
    """``attribute id -> [(db.table, column), ...]``: every column bound to it."""
    found: dict = {}
    for representation in ontology.get("representations") or []:
        for binding in representation.get("bindings") or []:
            if binding.get("ref") and binding.get("column"):
                found.setdefault(binding["ref"], []).append((representation["table"], binding["column"]))
    return found


def _digest_units(digest: dict) -> dict:
    """``(db.table, column) -> unit or ""`` (lower case) for every column the digest lists."""
    found: dict = {}
    for table in digest.get("tables") or []:
        name = str(table.get("table") or "").lower()
        for key, value in table.items():
            if not key.endswith("_columns") or not isinstance(value, list):
                continue
            for column in value:
                if isinstance(column, dict) and column.get("column"):
                    found[(name, str(column["column"]).lower())] = str(column.get("unit") or "").strip()
                elif isinstance(column, str):
                    found.setdefault((name, column.lower()), "")
    return found


def _unit_findings(ontology: dict, digest: dict | None, left: list[str], unsupported: list[str]) -> list[str]:
    """``unit_in_digest`` (with ``--digest``): a measure whose notes leave the unit to the
    owner while the digest gives a unit for a column bound to it. A measure with no unit and
    no such sentence is ``measure_without_unit`` already and is not reported twice.

    Listed, not counted: measures with no unit whose notes leave it to the owner (``left``),
    and, with ``--digest``, measures with a unit that no column bound to them has in the
    digest (``unsupported``). A measure none of whose bound columns the digest lists is not
    compared with it."""
    bound = _bound_columns(ontology)
    units = _digest_units(digest) if digest is not None else {}
    findings = []
    for attribute in _measures(ontology):
        columns = bound.get(attribute["id"]) or []
        listed = [
            (f"{table}.{column}", units[(table.lower(), column.lower())])
            for table, column in columns if (table.lower(), column.lower()) in units
        ]
        given = [(at, unit) for at, unit in listed if unit]
        where = "、".join(f"{table}.{column}" for table, column in columns) or "没有绑定的列"
        if _left_to_owner(attribute) and given:
            findings.append(
                f"unit_in_digest  {attribute['id']}：notes 写着「{UNIT_LEFT_TO_OWNER}」，digest 却给了所绑列的单位 "
                f"{'、'.join(f'{at} [{unit}]' for at, unit in given)}——照 digest 写 unit，去掉这句"
            )
        elif not attribute.get("unit"):
            if _left_to_owner(attribute):
                left.append(f"{attribute['id']}（{where}）")
        elif listed and not given:
            unsupported.append(f"{attribute['id']} [{attribute['unit']}]（{where}）")
    return findings


def _code_column_findings(ontology: dict, concepts: dict, changes: str, look: list[str]) -> list[str]:
    """``code_attribute_without_relation``; the code columns naming no concept go to ``look``.
    A column may be cleared by ``<db.table.column> code skip: <reason>``. What the finding asks
    for depends on the table's own concept: an event lists the other concept as a participant
    (participation relations are derived, never handwritten); anything else gets a relation."""
    skipped = {m.lower() for m in re.findall(r"([\w.]+)`?\s+code\s+skip", changes)}
    names = _concept_stems(concepts, ontology.get("identifiers") or [])
    attributes = {a["id"]: a for c in concepts.values() for a in c.get("attributes") or []}
    findings = []
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
                if at.lower() in skipped:
                    continue
                if (concepts.get(own) or {}).get("kind") == "event":
                    action = (f"{own} 是事件：目录起草者把 {target} 列进它的 participants（没有标识符就先建），"
                              f"片段作者把这一列改绑 foreign_identifier（参与关系自动派生，不手写）")
                else:
                    action = (f"目录起草者在 relations 里建 {own} 与 {target} 的关系（没有标识符就先建），"
                              f"片段作者把这一列改绑 foreign_identifier")
                findings.append(
                    f"code_attribute_without_relation  {at} 绑成属性 {binding.get('ref')}（无码值集），"
                    f"列名词干指向 {target}。{action}；确实只是本概念自己的编号、或材料证明不了它指向 {target}，"
                    f"就在 catalog_changes.md 写一行 `{at} code skip: <理由>`"
                )
            else:
                look.append(f"{at}（{binding.get('ref')}）")
    return findings


def _rule_findings(ontology: dict, digest: dict, changes: str) -> list[str]:
    """``unabsorbed_rule``: a digest rule no constraint carries and no skip line names."""
    carried = {ref.lower() for c in ontology.get("constraints") or [] for ref in c.get("rules") or []}
    named = {m.lower() for m in re.findall(r"([\w.]+#r\d+)`?\s+skip", changes)}
    findings = []
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


GRAIN_SOURCE_TEXT = {"declared": "声明", "inferred": "推断", "proven": "证实"}


def _digest_joins(digest: dict) -> dict:
    """``(db.table, column) -> (joined_in, grain columns, grain source)`` (names lower case)
    for every digest column that carries ``joined_in``."""
    found: dict = {}
    for table in digest.get("tables") or []:
        name = str(table.get("table") or "").lower()
        grain = table.get("grain") if isinstance(table.get("grain"), dict) else {}
        columns = [str(column).lower() for column in grain.get("columns") or []]
        for key, value in table.items():
            if not key.endswith("_columns") or not isinstance(value, list):
                continue
            for column in value:
                if isinstance(column, dict) and column.get("column") and column.get("joined_in"):
                    found[(name, str(column["column"]).lower())] = (
                        column["joined_in"], columns, str(grain.get("source") or ""),
                    )
    return found


def _repeat_findings(ontology: dict, digest: dict, changes: str) -> list[str]:
    """``measure_repeats_within_grain``: an ``additive`` measure whose value, on some table,
    is joined in by keys that leave a grain column out (module docstring)."""
    skipped = {m.lower() for m in re.findall(r"([\w:.]+)`?\s+repeats\s+skip", changes)}
    joins = _digest_joins(digest)
    bound = _bound_columns(ontology)
    findings = []
    for attribute in _measures(ontology):
        if attribute.get("additivity") != "additive" or attribute["id"].lower() in skipped:
            continue
        places = []
        for table, column in bound.get(attribute["id"]) or []:
            fact = joins.get((table.lower(), column.lower()))
            if fact is None or not fact[1]:
                continue
            hops, grain, source = fact
            open_hops = [
                hop for hop in hops
                if not set(grain) <= {str(key).lower() for key in hop.get("keys") or []}
            ]
            if open_hops:
                places.append((table, column, open_hops, grain, source))
        if not places or _notes_name_all(attribute, [table for table, *_ in places]):
            continue
        metrics = [
            metric["id"] for metric in ontology.get("metrics") or []
            if metric.get("measure") == attribute["id"] and metric.get("aggregation") == "sum"
            and metric.get("additivity") == "additive"
        ]
        said = "；".join(
            f"{table}.{column} 经 " + "、".join(
                f"{hop.get('rule')} 按 {'、'.join(hop.get('keys') or [])} 连接带入（fan-out {hop.get('fan_out')}）"
                for hop in hops
            ) + f"，键没盖住行粒度（{'、'.join(grain)}，粒度{GRAIN_SOURCE_TEXT.get(source, source or '来源未说明')}）"
            for table, column, hops, grain, source in places
        )
        uses = ("；以它为度量的 sum + additive 指标：" + "、".join(f"{m}（sum）" for m in metrics)) if metrics else ""
        findings.append(
            f"measure_repeats_within_grain  {attribute['id']}：{said}——同键的多行带同一个值{uses}。"
            "读 SQL 确认：重复的，在属性（和这些指标）的 notes 为每张列出的表写「在 <库.表> 里同 <键> 的多行带同一个值，"
            "按 <键> 每组取一行后再加」（additivity 不为此改）；"
            f"不重复的，在 catalog_changes.md 写一行 `{attribute['id']} repeats skip: <理由>`"
        )
    return findings


def _notes_name_all(attribute: dict, tables: list[str]) -> bool:
    """Whether the attribute's ``notes`` name every table, by ``db.table`` or its table name."""
    notes = attribute.get("notes")
    if isinstance(notes, list):
        notes = "；".join(str(note) for note in notes)
    text = str(notes or "").lower()
    return all(table.lower().rpartition(".")[2] in text for table in tables)


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
    units: dict[str, list[str]] = {}
    findings = check(ontology, digest, changes, look, units)
    for finding in findings:
        print(finding)
    if units["left"]:
        print(f"供人看（不计入）：{len(units['left'])} 个度量属性没有单位（材料没给，notes 写着「{UNIT_LEFT_TO_OWNER}」）——"
              "编排者抄进 RESULT.md 的「待确认汇总」交 owner，不用返工")
        for item in units["left"]:
            print(f"  {item}")
    if units["unsupported"]:
        print(f"供人看（不计入）：{len(units['unsupported'])} 个度量属性有 unit，digest 里所绑的列却都没有单位（单位没有材料依据）——"
              "编排者抄进 RESULT.md 的「待确认汇总」交 owner")
        for item in units["unsupported"]:
            print(f"  {item}")
    if look:
        print(f"供人看（不计入）：{len(look)} 个编码列绑成属性、无码值集、列名不指向已有概念——"
              "若其实指向一个还没建的对象，按 S10g 返工建概念；否则不用处理")
        for item in look:
            print(f"  {item}")
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
