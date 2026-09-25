"""Cross checks 10-11: row multiplication and derived codes.

Checks 1-9 hold a document's form to the packet; a page can pass all of them and still
tell a reader the wrong thing. These two read what the lineage already knows about the
rows and the values:

- 10 ``fan_out`` -- a JOIN whose right side the profile did not prove unique on the join
  keys can repeat a row per match; the reader has to be told, by name;
- 11 ``derived_codes`` -- a CASE / IF with literal outputs defines the column's values,
  so each must be listed, and one that sounds like a single state (成功, 正常 ...) while
  gathering several source values needs a warning.

A packet written before these facts existed has none of them, and nothing is checked.
"""

from __future__ import annotations

import re

from .checks import _plain, result

# 10 ------------------------------------------------------------------ fan out

_NO_EFFECT = re.compile(
    r"无影响|不影响(?:行数|粒度|记录数)?|不会(?:导致|造成|使)?(?:行数|记录)?(?:放大|膨胀|重复|增加|变多)"
    r"|不放大|行数不变"
)
_LEFT_WORDS = re.compile(r"left\s*(?:outer\s*)?join|左关联|左连接|左联", re.IGNORECASE)
_SENTENCES = re.compile(r"[。；;\n]")


def check_fan_out(document: dict, packet: dict) -> list[dict]:
    """Every right side not proven unique on its join keys is named in the note or a risk.

    Joins onto one right side (the same table joined under several aliases) are one item:
    naming the table once tells the reader. A sentence calling such a LEFT join harmless to
    the row count warns once, wherever it stands.
    """
    summary = document["summary"]
    said = _sentences("summary.row.note", summary["row"].get("note"))
    everywhere = list(said)
    for index, watch in enumerate(summary["watch"]):
        found = _sentences(f"summary.watch[{index}]", watch["text"])
        everywhere += found
        said += found if watch["kind"] == "risk" else []
    groups: dict[tuple, list[dict]] = {}
    for rule in packet["lineage"]["rules"]:
        verdict = rule.get("fan_out") if rule["kind"] == "join" else None
        if verdict and verdict.get("status") != "safe":
            key = tuple(rule.get("right_tables") or [rule.get("right")])
            groups.setdefault(key, []).append(rule)
    results = [_named(rules, said) for rules in groups.values()]
    left = [r for rules in groups.values() for r in rules if "LEFT" in str(r.get("join_type")).upper()]
    return results + _harmless_left(left, everywhere)


def _sentences(at: str, text) -> list[tuple[str, str]]:
    return [(at, part) for part in _SENTENCES.split(str(text or "")) if part.strip()]


def _label(rules: list[dict]) -> str:
    return "、".join(rules[0].get("right_tables") or [rules[0].get("right") or "?"])


def _named(rules: list[dict], said: list) -> dict:
    names = list(dict.fromkeys(name for rule in rules for name in join_names(rule)))
    at = "summary.row.note"
    if any(_mentions(text, names) for _, text in said):
        return result("fan_out", "pass", at)
    first = rules[0]
    joins = "、".join(dict.fromkeys(str(rule.get("join_type") or "JOIN") for rule in rules))
    where = (f"ON {_plain(first['expression'])}，{first['task']}，材料包 {first['id']}"
             if len(rules) == 1 else f"{len(rules)} 处，材料包 {'、'.join(r['id'] for r in rules)}")
    return result("fan_out", "fail", at, (
        f"关联 {_label(rules)}（{joins}，{where}）的右侧没有被证明按关联键唯一"
        f"（{first['fan_out'].get('reason')}），一条记录可能匹配多条、让行数放大；在 "
        "summary.row.note 或一条 kind 为 risk 的 summary.watch 里点名它"
        f"（{'、'.join(names)} 任一），写明会不会放大行数、为什么"))


def _harmless_left(left: list[dict], everywhere: list) -> list[dict]:
    """One warning per place that calls an unproven LEFT join harmless to the row count."""
    if not left:
        return []
    results, warned = [], set()
    for where, text in everywhere:
        named = [rule for rule in left if _mentions(text, join_names(rule))]
        if where in warned or not _NO_EFFECT.search(text):
            continue
        if named or _LEFT_WORDS.search(text):
            warned.add(where)
            label = "、".join(dict.fromkeys(_label([rule]) for rule in named or left))
            results.append(result("fan_out", "warn", where, (
                f"把左关联写成了不影响行数，但 {label} 的右侧没有被证明按关联键唯一："
                "LEFT JOIN 只保证左侧记录不丢，右侧一对多时照样放大行数；改写这句话，"
                "写明右侧什么情况下会有多条")))
    return results


def join_names(rule: dict) -> list[str]:
    """What a writer may call a JOIN's right side: its tables (whole and bare), its aliases."""
    names = []
    for table in rule.get("right_tables") or []:
        names += [table, table.rsplit(".", 1)[-1]]
    right = str(rule.get("right") or "")
    names += [right] if right and ":" not in right else []
    names += list(rule.get("right_aliases") or [])
    return list(dict.fromkeys(name for name in names if name))


def _mentions(text: str, names: list[str]) -> bool:
    return any(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text, re.IGNORECASE)
        for name in names
    )


# 11 ------------------------------------------------------------------ derived codes

# A meaning that names a single good state; "没有成功…" and an aside "（有效期外）" do not.
_SUCCESS_LIKE = re.compile(r"(?<!没有)(?<![不未非无没])(?:成功|正常|通过|有效)")
_ASIDE = re.compile(r"（[^）]*）|\([^)]*\)")


def success_like(meaning: str) -> bool:
    return bool(_SUCCESS_LIKE.search(_ASIDE.sub("", meaning)))


def check_derived_codes(document: dict, packet: dict) -> list[dict]:
    """A CASE / IF column lists each literal it returns; a merged success value is watched."""
    outputs = _case_outputs(packet)
    watched = {ref for watch in document["summary"]["watch"] for ref in watch.get("refs") or []}
    results = []
    for ci, column in enumerate(document["columns"]):
        for output in outputs.get(column["column"], {}).values():
            results += _derived_code(ci, column, output, watched)
    return results


def _case_outputs(packet: dict) -> dict[str, dict[str, dict]]:
    """``column -> value -> output``, one output per value over every producer."""
    merged: dict[str, dict[str, dict]] = {}
    for entry in packet["lineage"]["columns"]:
        for producer in entry["producers"]:
            for output in producer.get("case_outputs") or []:
                values = merged.setdefault(entry["column"], {})
                seen = values.setdefault(output["value"], {**output, "when": []})
                seen["when"] += [w for w in output["when"] if w not in seen["when"]]
                seen["catch_all"] = seen["catch_all"] or output["catch_all"]
                if seen["source_values"] is not None and output["source_values"] is not None:
                    seen["source_values"] = list(dict.fromkeys(
                        seen["source_values"] + output["source_values"]))
                else:
                    seen["source_values"] = None
    return merged


def _derived_code(ci: int, column: dict, output: dict, watched: set) -> list[dict]:
    name, value = column["column"], output["value"]
    when = "；".join("其余值（ELSE）" if w == "ELSE" else _plain(w) for w in output["when"])
    codes = {str(code["value"]).strip().strip("'\""): code for code in column.get("code_values") or []}
    code = codes.get(value)
    if code is None:
        return [result("derived_codes", "fail", f"columns[{ci}].code_values", (
            f"列 {name} 由 CASE/IF 派生，会输出 {value!r}（条件：{when}），但 code_values 里"
            "没有这个值；补上它和它的含义（依据分支条件与注释），拿不准含义就标 "
            "unconfirmed: true 并在 questions 里提问"))]
    passed = result("derived_codes", "pass", f"columns[{ci}].code_values")
    many = output["catch_all"] or len(output["source_values"] or []) > 1
    if not (many and success_like(code["meaning"])):
        return [passed]
    if column.get("watch") or f"column:{name}" in watched:
        return [passed]
    return [passed, result("derived_codes", "warn", f"columns[{ci}].watch", (
        f"码值 {value!r} 写成「{code['meaning']}」，但它由多个来源值归并而来（{when}）；"
        f"在列 {name} 的 watch 里写明哪些来源值被算作「{code['meaning']}」，"
        "免得读者以为它只对应一种状态"))]
