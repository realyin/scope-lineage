"""The cross checks of a ``table-semantics/1`` document against its packet, and checks 1-4.

Each check returns one result per item it looked at -- ``pass``, ``warn`` or ``fail``
with the path of the item (``columns[2].source_columns[0]``) and, when it is not a pass,
a sentence saying what to change. A document reaches these only once it is legal under
the schema, so every key the schema requires is present. Checks 1-9 hold the document's
form to the packet (``checks``, ``checks_context``); checks 10-13 hold what it means
(``checks_meaning``, ``checks_documented``).
"""

from __future__ import annotations

import re

from .names import bare_column

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
)
MAX_QUESTIONS = 5


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
    """Each ``source_columns`` entry is in that column's lineage (input metadata: warn)."""
    lineage = {
        entry["column"]: {source for producer in entry["producers"] for source in producer["sources"]}
        for entry in packet["lineage"]["columns"]
    }
    known = {f"{item['table']}.{column['name']}" for item in packet["inputs"] for column in item["columns"]}
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


def check_code_values(document: dict, packet: dict) -> list[dict]:
    """A code value not marked ``unconfirmed`` is written in a comment or in the SQL."""
    shared = "\n".join(
        [task["sql"] or "" for task in packet["tasks"]]
        + [line for task in packet["tasks"] for line in task["header_comments"]]
    )
    results = []
    for ci, column in enumerate(document["columns"]):
        text = "\n".join([_column_comments(packet, column["column"]), shared])
        for vi, code in enumerate(column.get("code_values") or []):
            if code.get("unconfirmed"):
                continue
            at = f"columns[{ci}].code_values[{vi}]"
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(code['value'])}(?![A-Za-z0-9_])"
            if code["value"] and re.search(pattern, text):
                results.append(result("code_values", "pass", at))
            else:
                results.append(result("code_values", "fail", at, (
                    f"码值 {code['value']!r} 在注释和 SQL 里都找不到；有依据就写明来源，"
                    "没有就标 unconfirmed: true 并在 questions 里提问")))
    return results


def _column_comments(packet: dict, name: str) -> str:
    """The target column's comment and the comments of the columns it comes from."""
    target = [c["comment"] or "" for c in packet["target"]["columns"] if c["name"] == name]
    return "\n".join(target + [comment for _, comment in source_comments(packet, name)])


def source_comments(packet: dict, name: str) -> list[tuple[str, str]]:
    """``(db.table.column, comment)`` for each commented input column a target column reads."""
    sources = {
        source
        for entry in packet["lineage"]["columns"] if entry["column"] == name
        for producer in entry["producers"] for source in producer["sources"]
    }
    return [
        (f"{item['table']}.{column['name']}", column["comment"])
        for item in packet["inputs"] for column in item["columns"]
        if f"{item['table']}.{column['name']}" in sources and column["comment"]
    ]


# 4 ------------------------------------------------------------------ grain


def check_grain(document: dict, packet: dict) -> list[dict]:
    """Claimed grain columns exist; a ``proven`` grain has a proven key behind it."""
    row = document["summary"]["row"]
    names = {column["name"] for column in packet["target"]["columns"]}
    results = [
        result("grain", "pass", f"summary.row.grain_columns[{index}]") if name in names
        else result("grain", "fail", f"summary.row.grain_columns[{index}]",
                    f"粒度列 {name} 不是目标表的列")
        for index, name in enumerate(row["grain_columns"])
    ]
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
