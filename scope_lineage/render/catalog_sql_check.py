"""``catalog check-sql``: what the catalog says about a query an agent wrote.

An agent reads the catalog (``search``, ``context``) and then writes SQL. ``check_sql``
compares that SQL, handed over as the plain facts ``scope.query_facts`` extracts, with the
built ``ontology-json/3`` document, and lists what does not agree. Every rule fires only on
what the two together settle; where they cannot tell, it says nothing or says ``info``:

- ``table_not_in_catalog`` (info): a physical table with no representation, so nothing about
  it can be checked.
- ``unknown_column`` (error): a column a table does not have. The document records a table's
  columns only as its bindings, and a catalog may bind some of a table's columns and not the
  others; the only statement of how many columns the table has is the table card count
  ``evidence.representations[t].declared_columns`` (``build --tables``). So a column is called
  absent only when that count is present and equals the number of bound columns. Otherwise an
  unbound column is ``column_unchecked`` (info).
- ``join_not_recorded`` (warning): judged once per JOIN between two reads (or per WHERE
  across two aliases), over all its equality pairs. One pair that shares an identifier (both
  ``identifier`` / ``foreign_identifier`` bindings of the same ref) or appears in a JOIN the
  corpus evidence recorded carries the join, and the other pairs (a date, an environment) only
  narrow it. When none does, one finding lists every pair asked and the pairs the catalog
  records between the two tables. A JOIN with a pair whose side reaches no single physical
  column, or a column the catalog does not bind, is not judged.
- ``missing_partition_filter`` (warning): a read of a table whose bindings carry
  ``time_role: partition``, or the validity window of a zipper (``valid_from`` /
  ``valid_to``), with no WHERE or JOIN ON predicate on any column of that group anywhere in
  the statement that reaches this read.
- ``fan_out_unaggregated`` (warning): a SUM or COUNT (not DISTINCT, not windowed, not
  ``COUNT(*)``) whose columns all belong to one table A read directly in a SELECT, and another
  table B read directly in the same SELECT and joined to A (not SEMI / ANTI) whose recorded
  grain is not covered by the join columns plus the columns of B a predicate pins (a zipper's
  window pins its start), nor by the GROUP BY. Only B decides; A's own grain does not matter.
  A B reduced in a subquery first is not a direct read, and a B with no recorded grain is not
  judged.
- ``code_value_unknown`` (warning): a column whose binding or attribute has listed code values
  compared with ``=`` or ``IN`` to a literal that is not one of them. Code sets whose values
  live in a lookup table, and columns that store meanings or keys (``holds``), are not judged.

Nothing here reads a file or the SQL text; the command composes the two halves.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_joins import (
    backed_pairs,
    grain_columns,
    pair_backed,
    pin_window,
    time_groups,
    uncovered,
)
from .catalog_view import CatalogView

__all__ = ["CHECK_FORMAT", "RULES", "check_sql", "render_check_sql_text"]

CHECK_FORMAT = "catalog-sql-check/1"
# rule id -> severity, in the order findings are listed
RULES = {
    "unknown_column": "error",
    "join_not_recorded": "warning",
    "missing_partition_filter": "warning",
    "fan_out_unaggregated": "warning",
    "code_value_unknown": "warning",
    "table_not_in_catalog": "info",
    "column_unchecked": "info",
}
SEVERITY_TEXT = {"error": "错误", "warning": "警告", "info": "提示"}
_PREDICATE_CLAUSES = ("where", "join")


def check_sql(document: Mapping, statements: Iterable[Mapping]) -> dict:
    """``{doc_format, tables, findings}`` for the query statements' facts."""
    view = CatalogView(document)
    statements = list(statements)
    findings: list[dict] = []
    tables: dict[str, dict] = {}
    for statement in statements:
        number = statement["statement"]
        for read in statement["reads"]:
            entry = tables.setdefault(read["table"], _table_entry(view, read["table"]))
            if number not in entry["statements"]:
                entry["statements"].append(number)
        found: list[dict] = []
        found += _missing_tables(view, statement)
        found += _columns(view, statement)
        found += _joins(view, statement)
        found += _partition_filters(view, statement)
        found += _fan_out(view, statement)
        found += _code_values(view, statement)
        order = list(RULES)
        found.sort(key=lambda f: order.index(f["rule"]))
        findings += [{"rule": f["rule"], "severity": RULES[f["rule"]], "statement": number,
                      **{k: v for k, v in f.items() if k != "rule"}} for f in found]
    return {
        "doc_format": CHECK_FORMAT,
        "statements": [s["statement"] for s in statements],
        "tables": list(tables.values()),
        "findings": findings,
    }


def _table_entry(view: CatalogView, table: str) -> dict:
    rep = view.representation(table)
    if rep is None:
        return {"table": table, "in_catalog": False, "concept": None,
                "columns_complete": None, "statements": []}
    return {
        "table": rep["table"],
        "in_catalog": True,
        "concept": rep["concept"],
        "columns_complete": _complete(view, rep),
        "statements": [],
    }


def _bound(rep: Mapping) -> dict[str, Mapping]:
    return {str(b["column"]).casefold(): b for b in rep["bindings"]}


def _complete(view: CatalogView, rep: Mapping) -> bool:
    """Whether the bindings are every column the table has, by its table card's count."""
    declared = view.rep_evidence(rep["table"]).get("declared_columns")
    return isinstance(declared, int) and declared == len(_bound(rep))


def _all_refs(statement: Mapping):
    for scope in statement["scopes"]:
        for ref in scope["refs"]:
            yield scope, ref


def _single_target(ref: Mapping) -> Optional[Mapping]:
    targets = ref.get("targets") or []
    return targets[0] if len(targets) == 1 else None


# ------------------------------------------------------- tables and columns


def _missing_tables(view: CatalogView, statement: Mapping) -> list[dict]:
    seen: dict[str, dict] = {}
    for read in statement["reads"]:
        if view.representation(read["table"]) is None and read["table"] not in seen:
            seen[read["table"]] = {
                "rule": "table_not_in_catalog",
                "table": read["table"],
                "alias": read["alias"],
                "message": f"目录里没有表 {read['table']} 的表示，它的列、关联和码值都无法核对。",
            }
    return list(seen.values())


def _columns(view: CatalogView, statement: Mapping) -> list[dict]:
    found: dict[tuple, dict] = {}
    for _scope, ref in _all_refs(statement):
        for target in ref["targets"]:
            rep = view.representation(target["table"])
            if rep is None:
                continue
            key = (rep["table"], target["column"].casefold())
            if key in found or key[1] in _bound(rep):
                continue
            columns = [b["column"] for b in rep["bindings"]]
            if _complete(view, rep):
                found[key] = {
                    "rule": "unknown_column",
                    "table": rep["table"],
                    "column": target["column"],
                    "alias": ref["alias"],
                    "message": (
                        f"表 {rep['table']} 没有列 {target['column']}：目录按表卡记录了它的全部 "
                        f"{len(columns)} 列。"
                    ),
                    "catalog": {"columns": columns},
                }
            else:
                declared = view.rep_evidence(rep["table"]).get("declared_columns")
                total = f"元数据声明 {declared} 列" if declared is not None else "没有表卡说明共有几列"
                found[key] = {
                    "rule": "column_unchecked",
                    "table": rep["table"],
                    "column": target["column"],
                    "alias": ref["alias"],
                    "message": (
                        f"目录没有绑定 {rep['table']}.{target['column']}，但目录只绑定了这张表的 "
                        f"{len(columns)} 列（{total}），无法判断这一列是否存在。"
                    ),
                    "catalog": {"columns": columns},
                }
    return list(found.values())


# -------------------------------------------------------------------- joins


def _joins(view: CatalogView, statement: Mapping) -> list[dict]:
    """One judgement per JOIN between two reads (or per WHERE across two aliases)."""
    found: dict[tuple, dict] = {}
    for scope in statement["scopes"]:
        for join in scope["joins"]:
            groups: dict[frozenset, list] = {}
            for pair in join["pairs"]:
                key = frozenset((pair["left"]["alias"], pair["right"]["alias"]))
                groups.setdefault(key, []).append(pair)
            for pairs in groups.values():
                finding = _join_finding(view, pairs)
                if finding is not None:
                    key = tuple(sorted(
                        f"{p['left']['table']}.{p['left']['column']}={p['right']['table']}."
                        f"{p['right']['column']}".casefold()
                        for p in finding["pairs"]
                    ))
                    found.setdefault(key, finding)
    return list(found.values())


def _placed(view: CatalogView, pair: Mapping, first_alias: str) -> Optional[list[tuple]]:
    """``[(rep, binding, ref), (rep, binding, ref)]`` with ``first_alias`` first, or None
    when a side is not one bound catalog column."""
    refs = [pair["left"], pair["right"]]
    if refs[0]["alias"] != first_alias:
        refs.reverse()
    sides = []
    for ref in refs:
        target = _single_target(ref)
        rep = view.representation(target["table"]) if target else None
        binding = _bound(rep).get(target["column"].casefold()) if rep else None
        if binding is None:
            return None
        sides.append((rep, binding, ref))
    return sides


def _pair_recorded(view: CatalogView, sides: list[tuple]) -> bool:
    (rep_a, bind_a, _), (rep_b, bind_b, _) = sides
    return pair_backed(view, rep_a, bind_a, rep_b, bind_b)


def _join_finding(view: CatalogView, pairs: list[Mapping]) -> Optional[dict]:
    """A finding when no equality of one JOIN is backed by the catalog.

    One backed pair carries the join; the others only narrow it (a date, an environment).
    A pair whose side is not one bound catalog column might be the real key, so the JOIN
    is then not judged.
    """
    first_alias = pairs[0]["left"]["alias"]
    placed = []
    for pair in pairs:
        sides = _placed(view, pair, first_alias)
        if sides is None:
            return None
        placed.append(sides)
    if any(_pair_recorded(view, sides) for sides in placed):
        return None
    (rep_a, bind_a, ref_a), (rep_b, _bind_b, ref_b) = placed[0]
    asked = [
        {
            "left": {"table": ra["table"], "column": ba["column"], "alias": fa["alias"]},
            "right": {"table": rb["table"], "column": bb["column"], "alias": fb["alias"]},
        }
        for (ra, ba, fa), (rb, bb, fb) in placed
    ]
    recorded = backed_pairs(view, rep_a, rep_b)
    asked_text = "；".join(
        f"{p['left']['table']}.{p['left']['column']} = {p['right']['table']}.{p['right']['column']}"
        for p in asked
    )
    shown = "；".join(f"{p['left']} = {p['right']}" for p in recorded) or "无"
    return {
        "rule": "join_not_recorded",
        "table": rep_a["table"],
        "column": bind_a["column"],
        "alias": ref_a["alias"],
        "left": {"table": rep_a["table"], "alias": ref_a["alias"]},
        "right": {"table": rep_b["table"], "alias": ref_b["alias"]},
        "pairs": asked,
        "message": (
            f"{rep_a['table']}（别名 {ref_a['alias']}）与 {rep_b['table']}（别名 "
            f"{ref_b['alias']}）的关联在目录里没有依据：关联条件 {asked_text} 中没有一对是同一个"
            f"标识，语料中也没有见过。目录记录的关联：{shown}。"
        ),
        "catalog": {"recorded": recorded},
    }


# -------------------------------------------------------- partition filters


def _predicated(statement: Mapping) -> tuple[set, set]:
    """``(read, column)`` pairs a WHERE / JOIN ON predicate reaches, and ``(scope, column)``
    for bare names that could belong to any source of their scope."""
    reached, bare = set(), set()
    for scope, ref in _all_refs(statement):
        if ref["clause"] not in _PREDICATE_CLAUSES:
            continue
        if ref["ambiguous"]:
            bare.add((scope["id"], ref["column"].casefold()))
        for target in ref["targets"]:
            reached.add((target["read"], target["column"].casefold()))
    return reached, bare


def _partition_filters(view: CatalogView, statement: Mapping) -> list[dict]:
    reached, bare = _predicated(statement)
    found = []
    for read in statement["reads"]:
        rep = view.representation(read["table"])
        if rep is None:
            continue
        for name, columns in time_groups(rep):
            if any(
                (read["read"], c["column"].casefold()) in reached
                or (read["scope"], c["column"].casefold()) in bare
                for c in columns
            ):
                continue
            names = "、".join(c["column"] for c in columns)
            what, rows = ("分区列", "所有分区") if name == "partition" else ("拉链有效期列", "所有版本")
            found.append({
                "rule": "missing_partition_filter",
                "table": rep["table"],
                "alias": read["alias"],
                "column": columns[0]["column"],
                "message": (
                    f"读 {rep['table']}（别名 {read['alias']}）时没有按{what} {names} 过滤，"
                    f"会把{rows}的行一起读进来。"
                ),
                "catalog": {"columns": columns},
            })
    return found


# ------------------------------------------------------------------ fan-out


def _direct(scope: Mapping, ref: Mapping) -> Optional[str]:
    """The table alias ``ref`` reads directly in ``scope``, else None."""
    target = _single_target(ref)
    if target and not ref["ambiguous"] and target["read"] == f"{scope['id']}:{ref['alias']}":
        return ref["alias"]
    return None


def _fan_out(view: CatalogView, statement: Mapping) -> list[dict]:
    found: dict[tuple, dict] = {}
    for scope in statement["scopes"]:
        for finding in _scope_fan_out(view, scope):
            key = (
                finding["table"], finding["column"], finding["function"],
                finding["catalog"]["many_side"]["table"],
            )
            found.setdefault(key, finding)
    return list(found.values())


def _join_columns(scope: Mapping) -> dict[str, dict[str, set]]:
    """``alias -> {other alias: the other side's join columns}`` between tables read
    directly in the scope, over every JOIN that can repeat rows (not SEMI / ANTI)."""
    joined: dict[str, dict[str, set]] = {}
    for join in scope["joins"]:
        if "SEMI" in join["kind"] or "ANTI" in join["kind"]:
            continue
        for pair in join["pairs"]:
            a, b = _direct(scope, pair["left"]), _direct(scope, pair["right"])
            if not a or not b or a == b:
                continue
            joined.setdefault(a, {}).setdefault(b, set()).add(pair["right"]["column"].casefold())
            joined.setdefault(b, {}).setdefault(a, set()).add(pair["left"]["column"].casefold())
    return joined


def _scope_fan_out(view: CatalogView, scope: Mapping) -> list[dict]:
    """A SUM / COUNT over one side is inflated by every other side the join leaves
    non-unique: only the other side's grain decides, never the summed side's own."""
    joined = _join_columns(scope)
    found = []
    for aggregate in scope["aggregates"]:
        if aggregate["distinct"] or not aggregate["columns"]:
            continue
        owners = {_direct(scope, ref) for ref in aggregate["columns"]}
        if len(owners) != 1 or None in owners:
            continue
        summed = owners.pop()
        for other, columns in joined.get(summed, {}).items():
            rep = view.representation(scope["sources"][other]["table"])
            grain = grain_columns(rep) if rep else None
            if grain is None or _other_side_unique(scope, other, rep, grain, columns):
                continue
            found.append(_fan_out_finding(scope, aggregate, summed, other, rep, grain, columns))
    return found


def _other_side_unique(scope: Mapping, alias: str, rep: Mapping, grain: list, joined: set) -> bool:
    """Whether at most one row of ``alias`` meets each row of the summed side: its grain is
    covered by the join columns and the columns a predicate pins, or it is grouped by it."""
    grouped = {r["column"] for r in scope["group_by"] if _direct(scope, r) == alias}
    if not uncovered(grain, grouped):
        return True
    pinned = {
        r["column"].casefold()
        for r in scope["refs"]
        if r["clause"] in _PREDICATE_CLAUSES and _direct(scope, r) == alias
    }
    return not uncovered(grain, joined | pin_window(rep, pinned))


def _fan_out_finding(
    scope: Mapping, aggregate: Mapping, summed: str, other: str, rep: Mapping, grain: list,
    joined: set,
) -> dict:
    table = scope["sources"][summed]["table"]
    column = aggregate["columns"][0]["column"]
    join_columns = [b["column"] for b in rep["bindings"] if b["column"].casefold() in joined]
    return {
        "rule": "fan_out_unaggregated",
        "table": table,
        "column": column,
        "alias": summed,
        "function": aggregate["function"],
        "message": (
            f"{aggregate['function']}({summed}.{column}) 会重复计数：{rep['table']}（别名 "
            f"{other}）的粒度是 {'、'.join(grain)}，按 {'、'.join(join_columns) or '这些列'} 关联"
            f"时一行 {table} 会对上多行。先在子查询里把 {other} 聚合到关联列、用谓词钉住它其余"
            "的粒度列，或改用 DISTINCT。"
        ),
        "catalog": {
            "many_side": {
                "table": rep["table"],
                "alias": other,
                "grain": list(grain),
                "join_columns": join_columns,
            },
        },
    }


# -------------------------------------------------------------- code values


def _listed_values(view: CatalogView, binding: Mapping) -> Optional[list[dict]]:
    """The values the catalog lists for a column, or None when it cannot list them all."""
    if binding.get("holds") and list(binding["holds"]) != ["code"]:
        return None
    code_sets = view.translating(binding)
    ref = binding.get("ref")
    if not code_sets and ref in view.attributes:
        code_sets = view.attribute_code_sets(view.attributes[ref][0])
    if any(code_set.get("lookup") for code_set in code_sets):
        return None
    values = [
        {"value": str(v["value"]), "meaning": v.get("meaning"), "code_set": code_set["id"]}
        for code_set in code_sets
        for v in code_set.get("values") or []
    ]
    known = {v["value"] for v in values}
    for value, meaning in (binding.get("code_map") or {}).items():
        if str(value) not in known:
            values.append({"value": str(value), "meaning": meaning, "code_set": None})
    return values or None


def _same_value(literal: str, value: str) -> bool:
    if literal == value:
        return True
    try:
        return float(literal) == float(value)
    except ValueError:
        return False


def _code_values(view: CatalogView, statement: Mapping) -> list[dict]:
    found: dict[tuple, dict] = {}
    for scope in statement["scopes"]:
        for comparison in scope["comparisons"]:
            for target in comparison["ref"]["targets"]:
                rep = view.representation(target["table"])
                binding = _bound(rep).get(target["column"].casefold()) if rep else None
                values = _listed_values(view, binding) if binding else None
                if not values:
                    continue
                for literal in comparison["values"]:
                    if any(_same_value(literal, v["value"]) for v in values):
                        continue
                    key = (rep["table"], binding["column"], literal)
                    shown = "、".join(f"{v['value']}={v['meaning']}" for v in values)
                    found.setdefault(key, {
                        "rule": "code_value_unknown",
                        "table": rep["table"],
                        "column": binding["column"],
                        "alias": comparison["ref"]["alias"],
                        "value": literal,
                        "message": (
                            f"{rep['table']}.{binding['column']} 与 '{literal}' 比较，但目录列出的"
                            f"取值里没有它。可用的值：{shown}。"
                        ),
                        "catalog": {"values": values},
                    })
    return list(found.values())


# --------------------------------------------------------------------- text


def render_check_sql_text(result: Mapping) -> str:
    """The findings as short Markdown, one block a statement."""
    lines: list[str] = []
    for table in result["tables"]:
        if not table["in_catalog"]:
            state = "不在目录里"
        elif table["columns_complete"]:
            state = "目录记录了全部列"
        else:
            state = "目录只记录了部分列"
        lines.append(f"- 表 {table['table']}：{state}")
    if lines:
        lines = ["# 读到的表", *lines, ""]
    if not result["findings"]:
        lines.append("没有发现问题。")
        return "\n".join(lines) + "\n"
    for number in result["statements"]:
        mine = [f for f in result["findings"] if f["statement"] == number]
        if not mine:
            continue
        lines.append(f"# 第 {number} 条语句")
        for finding in mine:
            label = SEVERITY_TEXT[finding["severity"]]
            lines.append(f"- {label} [{finding['rule']}] {finding['message']}")
        lines.append("")
    counts = {s: sum(1 for f in result["findings"] if f["severity"] == s) for s in SEVERITY_TEXT}
    lines.append("合计：" + "，".join(f"{SEVERITY_TEXT[s]} {n}" for s, n in counts.items()))
    return "\n".join(lines) + "\n"
