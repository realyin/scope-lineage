"""The cross checks of a ``table-semantics/1`` document against its packet, and checks 1-4.

Each check returns one result per item it looked at -- ``pass``, ``warn`` or ``fail``
with the path of the item (``columns[2].source_columns[0]``) and, when it is not a pass,
a sentence saying what to change. A document reaches these only once it is legal under
the schema, so every key the schema requires is present. Checks 1-9 hold the document's
form to the packet (``checks``, ``checks_context``); checks 10-13 hold what it means
(``checks_meaning``, ``checks_documented``); check 14 reads the prose alone
(``checks_text``).
"""

from __future__ import annotations

import re

from .names import bare_column, folded_text

CHECKS = (
    "coverage",
    "source_columns",
    "code_values",
    "grain",
    "rules",
    "neighbours",
    "sources",
    "digest",
    "time",
    "fan_out",
    "derived_codes",
    "documented_meaning",
    "header_facts",
    "placeholder",
)
MAX_QUESTIONS = 8


def result(check: str, status: str, at: str, message: str = "") -> dict:
    return {"check": check, "status": status, "at": at, "message": message}


def _plain(expression) -> str:
    return str(expression or "").replace("`", "")


# 1 ------------------------------------------------------------------ coverage


def check_coverage(document: dict, packet: dict) -> list[dict]:
    """``columns`` covers the target table's columns exactly, in table order."""
    expected = [column["name"] for column in packet["target"]["columns"]]
    written = [(index, column["column"]) for index, column in enumerate(document["columns"])]
    results, seen, kept = [], set(), []
    for index, name in written:
        at = f"columns[{index}]"
        if name in seen:
            results.append(result("coverage", "fail", at, f"列 {name} 写了两次；只留一条"))
        elif name not in expected:
            results.append(result("coverage", "fail", at, f"目标表没有列 {name}；删掉这一条"))
        else:
            kept.append((index, name))
        seen.add(name)
    order = [name for name in expected if name in seen]
    for (index, name), wanted in zip(kept, order):
        status = "pass" if name == wanted else "fail"
        message = "" if status == "pass" else (
            f"列 {name} 不在目标表顺序上（这里应是 {wanted}）；按材料包第 5 节的顺序排列"
        )
        results.append(result("coverage", status, f"columns[{index}]", message))
    results += [
        result("coverage", "fail", "columns",
               f"缺少目标表的列 {name}（表内第 {expected.index(name) + 1} 列）；补上这一列")
        for name in expected if name not in seen
    ]
    return results


# 2 ------------------------------------------------------------------ source columns


def check_source_columns(document: dict, packet: dict) -> list[dict]:
    """Each ``source_columns`` entry is in that column's lineage (input metadata: warn).

    A column's lineage is its producers' ``sources`` and ``lookup_keys``: a value read off
    a constant row set (an inline dictionary) has no physical source, and the physical key
    deciding which row is read is the column a writer can name. Only the column's own
    producers count -- another column's lookup key still warns.

    The reference, the lineage sources and the input metadata are all compared as
    ``bare_column`` spells them, whatever case the schema export or the script used.
    """
    lineage = {
        entry["column"]: {
            bare_column(source)
            for producer in entry["producers"]
            for source in [*producer["sources"], *(producer.get("lookup_keys") or [])]
        }
        for entry in packet["lineage"]["columns"]
    }
    known = {
        bare_column(f"{item['table']}.{column['name']}")
        for item in packet["inputs"] for column in item["columns"]
    }
    results = []
    for ci, column in enumerate(document["columns"]):
        for si, reference in enumerate(column.get("source_columns") or []):
            at, name = f"columns[{ci}].source_columns[{si}]", bare_column(reference)
            if name in lineage.get(column["column"], set()):
                results.append(result("source_columns", "pass", at))
            elif name in known:
                results.append(result("source_columns", "warn", at, (
                    f"{name} 不在列 {column['column']} 的血缘来源里，只在输入表元数据中；"
                    "确认它真的参与口径，否则删掉")))
            else:
                results.append(result("source_columns", "fail", at, (
                    f"{name} 既不在列 {column['column']} 的血缘来源里，也不是任何输入表的列；"
                    "改成材料包 4.1 列出的来源列")))
    return results


# 3 ------------------------------------------------------------------ code values


def check_code_values(document: dict, packet: dict, confirmed=None) -> list[dict]:
    """A code value not marked ``unconfirmed`` is written in a comment or in the SQL, or
    the glossary confirms it on the column or on a column it reads, or the owner confirmed
    it for this table and column (``confirmed``, the table's state read from the run's
    confirmations files: :mod:`scope_lineage.semantics.confirmed`).

    In a comment a code ending in a digit may run straight into letters (「1普通2VIP回访」);
    in the SQL it may not, where a hex string or a regex class would match any digit.

    Two kinds of value are held to what the column itself writes (its producers'
    ``literal_outputs``), not to the text:

    - an empty value (``''``, or blanks) is no text to find: it is a code when a producer
      writes ``''`` -- a COALESCE / NVL fallback, a constant, a CASE / IF branch -- and
      not when ``''`` is only compared in a condition;
    - a column every producer of which writes a constant (``constant_only``) holds those
      constants and nothing else, so each of its codes, ``unconfirmed`` or not, must be
      one of them; a column that only writes NULL has no code.

    A packet built before ``literal_outputs`` has no constant column and no producer
    writing ``''``.

    What the owner confirmed is held both ways: each confirmed value must be in the
    column, not ``unconfirmed``, with the confirmed meaning (compared as ``folded_text``).
    The SQL still wins over a confirmation: a confirmed value a constant column never
    writes, or a confirmed ``''`` no producer writes, fails as a confirmation to take back
    to the owner -- the document cannot settle it.
    """
    sql = "\n".join(task["sql"] or "" for task in packet["tasks"])
    headers = [line for task in packet["tasks"] for line in task["header_comments"]]
    results = []
    for ci, column in enumerate(document["columns"]):
        name = column["column"]
        comments = "\n".join([_column_comments(packet, name), *headers])
        confirmed_glossary = confirmed_values(packet, name)
        owner = confirmed.code_meanings(name) if confirmed else {}
        literals, constant = column_literals(packet, name)
        written = set()
        for vi, code in enumerate(column.get("code_values") or []):
            at = f"columns[{ci}].code_values[{vi}]"
            value = str(code["value"])
            written.add(value)
            contradiction = (
                value in owner and _contradicts_sql(value, literals, constant)
            )
            if contradiction:
                results.append(_contradicted(at, name, value, literals, constant))
            elif value in owner:
                results.append(_owner_code(at, code, owner[value]))
            elif constant:
                results.append(_constant_code(at, name, value, literals))
            elif code.get("unconfirmed"):
                continue
            elif not value.strip():
                results.append(result("code_values", "pass", at) if "" in literals else result(
                    "code_values", "fail", at, (
                        f"空串不是列 {name} 会产出的值：材料包 4.1 的步骤里没有回填或产出 ''；"
                        "删掉这个码值，或改成 SQL 真正写出的值")))
            elif value.strip() in confirmed_glossary or (
                re.search(_code_pattern(value, in_comment=True), comments)
                or re.search(_code_pattern(value, in_comment=False), sql)
            ):
                results.append(result("code_values", "pass", at))
            else:
                results.append(result("code_values", "fail", at, (
                    f"码值 {code['value']!r} 在注释和 SQL 里都找不到；有依据就写明来源，"
                    "没有就标 unconfirmed: true 并在 questions 里提问")))
        at = f"columns[{ci}].code_values"
        for value, meaning in owner.items():
            if value in written:
                continue
            if _contradicts_sql(value, literals, constant):
                results.append(_contradicted(at, name, value, literals, constant))
            else:
                results.append(result("code_values", "fail", at, (
                    f"码值 {value!r} 已由 owner 确认（确认文件）为「{meaning}」，列 {name} 的 "
                    "code_values 里没有；照确认补上这个码值并写确认的含义，不要标 unconfirmed")))
    return results


def _contradicts_sql(value: str, literals: set[str], constant: bool) -> bool:
    """Whether the SQL says the column never holds ``value``: a constant column that does
    not write it, or an empty value no producer writes."""
    if constant:
        return value.strip() not in {literal.strip() for literal in literals}
    return not value.strip() and "" not in literals


def _contradicted(at: str, name: str, value: str, literals: set[str], constant: bool) -> dict:
    if constant:
        written = "、".join(repr(literal) for literal in sorted(literals)) or "NULL"
        why = f"列 {name} 恒为常量 {written}，SQL 不会写出它"
    else:
        why = f"材料包 4.1 的步骤里没有回填或产出 ''，列 {name} 不会写出空串"
    return result("code_values", "fail", at, (
        f"码值 {value!r} 已由 owner 确认（确认文件），但{why}：确认与 SQL 矛盾，"
        "交回 owner 重新确认；文档里照 SQL 写，不要自行改确认"))


def _owner_code(at: str, code: dict, meaning: str) -> dict:
    """A code value the owner confirmed: written as confirmed, or a failure that says so."""
    value = code["value"]
    if code.get("unconfirmed"):
        return result("code_values", "fail", at, (
            f"码值 {value!r} 已由 owner 确认（确认文件）为「{meaning}」；照确认写含义，"
            "去掉 unconfirmed，不要标 unconfirmed: true，也不要就它提问"))
    if folded_text(code.get("meaning")) != folded_text(meaning):
        return result("code_values", "fail", at, (
            f"码值 {value!r} 已由 owner 确认（确认文件）为「{meaning}」，这里写成"
            f"「{code.get('meaning')}」；照确认写含义，不要改成别的，也不要标 unconfirmed"))
    return result("code_values", "pass", at)


def column_literals(packet: dict, name: str) -> tuple[set[str], bool]:
    """``(values, constant)``: the literals a target column's producers write, as values
    (``''`` the empty string, NULL left out), and whether every producer writes nothing
    but constants (``constant_only``)."""
    producers = [producer for entry in packet["lineage"]["columns"] if entry["column"] == name
                 for producer in entry["producers"]]
    values = {_unquoted(literal) for producer in producers
              for literal in producer.get("literal_outputs") or [] if literal.upper() != "NULL"}
    constant = bool(producers) and all(producer.get("constant_only") for producer in producers)
    return values, constant


def _unquoted(literal: str) -> str:
    """A literal in SQL spelling as the value it writes: ``'it''s'`` -> ``it's``; ``0`` stays."""
    if len(literal) >= 2 and literal[0] == literal[-1] and literal[0] in "'\"":
        return literal[1:-1].replace(literal[0] * 2, literal[0])
    return literal


def _constant_code(at: str, name: str, value: str, literals: set[str]) -> dict:
    if value.strip() in {literal.strip() for literal in literals}:
        return result("code_values", "pass", at)
    written = "、".join(repr(literal) for literal in sorted(literals)) or "NULL"
    return result("code_values", "fail", at, (
        f"列 {name} 恒为常量 {written}，码值 {value!r} 不会出现；删掉它，或改成 SQL 写出的常量"))


def _code_pattern(value: str, in_comment: bool) -> str:
    """``value`` standing alone: not inside a longer word or number. In a comment a value
    ending in a digit may be followed by letters; a value ending in a letter may not, so
    「A」 still does not match 「ABC」."""
    right = r"(?![0-9_])" if in_comment and value[-1:].isdigit() else r"(?![A-Za-z0-9_])"
    return rf"(?<![A-Za-z0-9_]){re.escape(value)}{right}"


def _column_comments(packet: dict, name: str) -> str:
    """The target column's comment and the comments of the columns it comes from."""
    target = [c["comment"] or "" for c in packet["target"]["columns"] if c["name"] == name]
    return "\n".join(target + [comment for _, comment in source_comments(packet, name)])


def _sources(packet: dict, name: str) -> set[str]:
    """The ``db.table.column`` references a target column reads, over every producer,
    spelt as ``bare_column`` spells them."""
    return {
        bare_column(source)
        for entry in packet["lineage"]["columns"] if entry["column"] == name
        for producer in entry["producers"] for source in producer["sources"]
    }


def _source_columns(packet: dict, name: str) -> list[tuple[str, dict]]:
    """``(db.table.column, column)`` for each input column a target column reads, matched
    whatever case the schema export or the script used."""
    sources = _sources(packet, name)
    return [
        (f"{item['table']}.{column['name']}", column)
        for item in packet["inputs"] for column in item["columns"]
        if bare_column(f"{item['table']}.{column['name']}") in sources
    ]


def source_comments(packet: dict, name: str) -> list[tuple[str, str]]:
    """``(db.table.column, comment)`` for each commented input column a target column reads."""
    return [
        (reference, column["comment"])
        for reference, column in _source_columns(packet, name) if column["comment"]
    ]


def confirmed_values(packet: dict, name: str) -> dict[str, str]:
    """``value -> meaning`` the glossary confirms on a target column or a column it reads.

    The target column's own answer first, then its sources' in packet order; the first
    meaning of a value wins. Empty for a packet built without ``--glossary``.
    """
    target = [c for c in packet["target"]["columns"] if c["name"] == name]
    columns = target + [column for _, column in _source_columns(packet, name)]
    found: dict[str, str] = {}
    for column in columns:
        for item in column.get("confirmed_values") or []:
            found.setdefault(str(item["value"]), str(item["meaning"]))
    return found


# 4 ------------------------------------------------------------------ grain


def check_grain(document: dict, packet: dict, confirmed=None) -> list[dict]:
    """Claimed grain columns exist; a ``proven`` grain has a proven key behind it; a row
    the owner confirmed (``confirmed``, the table's state from the run's confirmations
    files) is written as confirmed.

    A confirmed ``grain_columns`` must be the document's set, a confirmed ``unique`` its
    value, and either one makes ``grain_source: inferred`` a failure: the owner's word is
    ``declared`` (or ``proven`` when the lineage proves the key, judged as before).
    """
    row = document["summary"]["row"]
    names = {column["name"] for column in packet["target"]["columns"]}
    results = [
        result("grain", "pass", f"summary.row.grain_columns[{index}]") if name in names
        else result("grain", "fail", f"summary.row.grain_columns[{index}]",
                    f"粒度列 {name} 不是目标表的列")
        for index, name in enumerate(row["grain_columns"])
    ]
    results += _confirmed_row(row, confirmed.row_fields() if confirmed else {})
    if row["grain_source"] != "proven":
        return results
    proven = [key for key in packet["lineage"]["keys"] if key["proven"]]
    at = "summary.row.grain_source"
    if not proven:
        confidence = "、".join(str(key["key_confidence"]) for key in packet["lineage"]["keys"])
        return [*results, result("grain", "fail", at, (
            f"写了 proven，但材料包里没有语句证明了键（key_confidence：{confidence or '无'}）；"
            "改成 inferred 或 declared，并在 note 里写明不唯一的风险"))]
    if set(row["grain_columns"]) not in [set(key["candidate_keys"]) for key in proven]:
        keys = " / ".join("、".join(key["candidate_keys"]) or "（单行）" for key in proven)
        return [*results, result("grain", "warn", at, (
            f"声称的粒度列 {'、'.join(row['grain_columns'])} 与血缘证明的键 {keys} 不一致"))]
    return [*results, result("grain", "pass", at)]


def _confirmed_row(row: dict, owner: dict) -> list[dict]:
    """The row fields the owner confirmed, held against the document's row."""
    results = []
    told = "已由 owner 确认（确认文件）"
    if isinstance(owner.get("grain_columns"), list):
        wanted, at = owner["grain_columns"], "summary.row.grain_columns"
        if set(row["grain_columns"]) == set(wanted):
            results.append(result("grain", "pass", at))
        else:
            results.append(result("grain", "fail", at, (
                f"行粒度列{told}为 {'、'.join(wanted) or '（无）'}，这里写成 "
                f"{'、'.join(row['grain_columns']) or '（无）'}；照确认写")))
    if "unique" in owner:
        at = "summary.row.unique"
        if row["unique"] == owner["unique"]:
            results.append(result("grain", "pass", at))
        else:
            results.append(result("grain", "fail", at, (
                f"按粒度列是否唯一{told}为 {owner['unique']}，这里写成 {row['unique']}；照确认写")))
    if isinstance(owner.get("grain_columns"), list) or "unique" in owner:
        at = "summary.row.grain_source"
        if row["grain_source"] == "inferred":
            results.append(result("grain", "fail", at, (
                f"行粒度{told}，grain_source 不能写 inferred；写 declared"
                "（血缘证明了同一个键时可写 proven）")))
        else:
            results.append(result("grain", "pass", at))
    return results
