"""``domain-profile evidence``: what a parsed corpus says about its own conventions.

A ``domain-profile/1`` file is drafted from this evidence by a model and checked against
it by :mod:`.profile_check`. The tool reports observations only and decides nothing a
corpus cannot show:

* **table-name suffixes** -- per suffix of the corpus tables (the last name segment's
  part after its last ``_``), how each statement reads those tables' partitions and how
  the corpus writes them. A suffix whose partitioned reads are ranges is suggested
  ``incremental``; one read a single partition at a time is only ever *pending*, with a
  lean, because reads alone cannot tell a daily full snapshot from a daily increment;
  the tool never suggests ``full``;
* **qualifier material** -- the comments of the columns the corpus uses and of its
  tables, numeric columns first;
* **concept material** -- table comments, key-column comments and table-name words,
  cut the way the concept layer's vote cuts them;
* **built-in words** -- what the package already knows, so a draft does not repeat it.

Lineage documents and a metadata lookup come in as plain data (``cli_domain_profile``
loads them); no domain profile is read, and nothing here names a business.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..redaction import redact
from ..render.concepts import builtin_concept_words, table_name_words
from ..render.semantic_profile import build_semantic_profile
from ..render.value_lookups import partitioned_tables
from . import packet_facts as facts
from .checks_documented import QUALIFIER_TERMS
from .names import bare_table, strip_leading_keyword

EVIDENCE_FORMAT = "domain-profile-evidence/1"

READ_KINDS = ("equality", "multi_equality", "range", "unconditioned", "unpartitioned")
_PARTITION_READS = ("equality", "multi_equality", "range")
OBSERVATIONS = ("range_reads", "single_partition_reads", "mixed", "too_few")
SUGGEST_INCREMENTAL = "incremental"
SUGGEST_PENDING = "pending"
LEAN_FULL = "full"

#: The thresholds, written into every evidence file as they are (USAGE「观察结论」「建议」).
SUFFIX_RULES = {
    "min_tables_with_partition_reads": 3,
    "min_partition_reads": 5,
    "dominance_at_least": 0.9,
    "min_metadata_coverage": 0.8,
    "lean_full_min_writes": 1,
    "lean_full_max_window_writes": 0,
    "lean_full_max_unconditioned_reads": 0.1,
}
#: How many entries of each material part ``evidence.md`` lists. Qualifier material is the
#: larger part (every used column's comment), and a model reads it whole far more cheaply
#: than it recovers a qualifier it never saw, so its limit is the higher one.
MARKDOWN_LIMITS = {"qualifier": 1200, "concept": 400}
_SHAPES_PER_READ = 3
_EXAMPLES = 3
_KEY_USAGES = frozenset({"group_by", "join_key"})
_NUMERIC = re.compile(
    r"^(tinyint|smallint|int|integer|bigint|long|float|double|real|decimal|numeric|number)\b")
_SUFFIX = re.compile(r"[a-z0-9]+")

Metadata = Callable[[str], "dict | None"]


def suffix_of(table: str) -> str | None:
    """The part of a table's last name segment after its last ``_``, when that is letters
    and digits only; ``None`` for a name without ``_``."""
    name = bare_table(table).rsplit(".", 1)[-1]
    if "_" not in name:
        return None
    tail = name.rsplit("_", 1)[-1]
    return tail if _SUFFIX.fullmatch(tail) else None


# ------------------------------------------------------------------ rules


def observe(reads: dict, tables_with_partition_reads: int) -> str:
    """``range_reads`` / ``single_partition_reads`` / ``mixed`` / ``too_few``.

    The denominator is the partitioned reads (``equality`` + ``multi_equality`` +
    ``range``); ``multi_equality`` is in it and in neither numerator.
    """
    rules = SUFFIX_RULES
    partitioned = sum(reads.get(kind, 0) for kind in _PARTITION_READS)
    if (tables_with_partition_reads < rules["min_tables_with_partition_reads"]
            or partitioned < rules["min_partition_reads"]):
        return "too_few"
    if reads.get("range", 0) >= rules["dominance_at_least"] * partitioned:
        return "range_reads"
    if reads.get("equality", 0) >= rules["dominance_at_least"] * partitioned:
        return "single_partition_reads"
    return "mixed"


def suggest(observation: str, reads: dict, writes: dict) -> tuple[str | None, str | None, str | None]:
    """``(suggestion, lean, pending_reason)``; the suggestion is never ``full``.

    Ranges are ``incremental``. A single-partition reading is ``pending``, leaning ``full``
    only when the corpus writes the tables, never through a business-date window, and
    reads them without a partition condition at most 10% of the time (the share of the
    partitioned tables' reads); otherwise the reason names each condition that failed.
    """
    if observation == "range_reads":
        return SUGGEST_INCREMENTAL, None, None
    if observation != "single_partition_reads":
        return None, None, None
    rules = SUFFIX_RULES
    failed = []
    if writes.get("statements", 0) < rules["lean_full_min_writes"]:
        failed.append("语料里没有写入这类表的语句")
    if writes.get("window_filtered", 0) > rules["lean_full_max_window_writes"]:
        failed.append(
            f"写入这类表的语句里有 {writes['window_filtered']} 条按窗口型业务日期筛选上游")
    total = sum(reads.get(kind, 0) for kind in READ_KINDS if kind != "unpartitioned")
    unconditioned = reads.get("unconditioned", 0)
    if total and unconditioned > rules["lean_full_max_unconditioned_reads"] * total:
        failed.append(f"不带分区条件的读取占 {unconditioned}/{total}，超过 10%")
    if failed:
        return SUGGEST_PENDING, None, "；".join(failed)
    return SUGGEST_PENDING, LEAN_FULL, _LEAN_FULL_REASON


_LEAN_FULL_REASON = (
    "带分区条件的读取几乎都只取一个分区，写入一侧没有反证；但单分区读既可能是全量快照，"
    "也可能是每天取当天那一批增量，沿分区传递的增量链路在 SQL 里和全量链路没有区别，需要人确认"
)


# ------------------------------------------------------------------ evidence


class _Tally:
    """Everything one walk over the corpus counts."""

    def __init__(self) -> None:
        self.tables: set[str] = set()
        self.reads: dict[str, Counter] = defaultdict(Counter)
        self.read_tables: dict[str, set[str]] = defaultdict(set)
        self.partition_read_tables: dict[str, set[str]] = defaultdict(set)
        self.shapes: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        self.writes: dict[str, Counter] = defaultdict(Counter)
        self.written_tables: dict[str, set[str]] = defaultdict(set)
        # (table, column) -> usage set; key columns of writing statements
        self.used: dict[tuple[str, str], dict] = {}
        self.keys: set[tuple[str, str]] = set()
        self.lineage_table_comments: dict[str, str] = {}


def build_evidence(
    documents: Iterable[tuple[dict, list]], metadata: Metadata, *, inputs: dict,
) -> dict:
    """The ``domain-profile-evidence/1`` document of a corpus.

    ``documents`` are ``(lineage document, diagnostics)`` pairs; ``metadata`` answers
    ``db.table`` with the schema's facts (columns, partition columns, comment) or None.
    ``inputs`` (paths, digest, tool version) is recorded as given.
    """
    documents = list(documents)
    cache: dict[str, dict | None] = {}

    def meta(table: str) -> dict | None:
        if table not in cache:
            cache[table] = metadata(table)
        return cache[table]

    flags = partitioned_tables(document for document, _ in documents)
    tally = _Tally()
    for document, diagnostics in documents:
        _walk(document, diagnostics, meta, flags, tally)
    found = sum(1 for table in tally.tables if meta(table))
    covered = not tally.tables or found >= SUFFIX_RULES["min_metadata_coverage"] * len(tally.tables)
    notes = [] if covered else [_LOW_COVERAGE.format(found=found, tables=len(tally.tables))]
    read = sorted(tally.reads, key=str)
    return {
        "doc_format": EVIDENCE_FORMAT,
        "inputs": inputs,
        "suffix_rules": dict(SUFFIX_RULES),
        "coverage": {"tables": len(tally.tables), "found": found},
        "suffixes": [_suffix_entry(name, tally, covered) for name in read],
        "write_only_suffixes": [
            _write_only_entry(name, tally) for name in sorted(set(tally.writes) - set(read))
        ],
        "qualifier_material": {
            "columns": _column_material(tally, meta),
            "tables": _table_material(tally, meta),
        },
        "concept_material": {
            "table_tokens": _token_material(tally.tables),
            "table_comments": _table_material(tally, meta),
            "key_comments": _column_material(tally, meta, keys_only=True),
        },
        "builtin": {
            "qualifier_terms": list(QUALIFIER_TERMS),
            "concept_words": builtin_concept_words(),
        },
        "notes": notes,
    }


_LOW_COVERAGE = (
    "语料表 {tables} 张，元数据里查到 {found} 张，不到 80%：分区列认不全，读法统计不可靠，"
    "所以所有后缀都不给建议"
)


def _walk(document: dict, diagnostics: list, meta: Metadata, flags: dict, tally: _Tally) -> None:
    profile = build_semantic_profile(document, diagnostics)
    task = str(profile.get("task_id") or document.get("task_id") or "")
    for statement in profile.get("statements") or [profile]:
        rules = facts.statement_rules(task, statement)
        facts.mark_partition_filters(rules, meta)
        window = False
        for item in statement.get("inputs") or []:
            table = bare_table(item.get("table"))
            if not table:
                continue
            tally.tables.add(table)
            if item.get("comment"):
                tally.lineage_table_comments.setdefault(table, str(item["comment"]))
            window |= _count_read(table, item, rules, meta, flags, tally)
        _count_write(statement, window, tally)


def _count_read(table, item, rules, meta, flags, tally) -> bool:
    """Count one statement's read of one table; whether a business-date window filters it."""
    found = meta(table) or {}
    partition_columns = list(found.get("partition_columns") or [])
    used = [c for c in item.get("used_columns") or [] if c.get("usages")]
    declared = found.get("columns") or item.get("declared_columns") or item.get("used_columns") or []
    columns = facts.time_columns(declared, [str(c.get("name")) for c in used], partition_columns)
    read = facts.read_facts(table, rules, columns)
    kind = read["partition_read"]
    if kind == "none":
        partitioned = bool(partition_columns or found.get("partitioned")) if found else bool(
            flags.get(table))
        kind = "unconditioned" if partitioned else "unpartitioned"
    name = suffix_of(table)
    if name is not None:
        tally.reads[name][kind] += 1
        tally.read_tables[name].add(table)
        if kind in _PARTITION_READS:
            tally.partition_read_tables[name].add(table)
            names = set(partition_columns) | {
                c["name"] for c in columns if c["partition"]}
            shape = " AND ".join(mask_expression(text, names) for text in read["partition_filters"])
            tally.shapes[name][kind][shape] += 1
    for column in used:
        key = (table, str(column.get("name")))
        entry = tally.used.setdefault(key, {"type": None, "comment": None})
        entry["type"] = entry["type"] or column.get("type")
        entry["comment"] = entry["comment"] or column.get("comment")
        if _KEY_USAGES & set(column.get("usages") or []):
            tally.keys.add(key)
    return any(d.get("shape") == facts.DATE_WINDOW for d in read["date_filters"])


def _count_write(statement: dict, window: bool, tally: _Tally) -> None:
    task = statement.get("task") or {}
    target = bare_table(task.get("target_table"))
    if not target:
        return
    tally.tables.add(target)
    if task.get("target_table_comment"):
        tally.lineage_table_comments.setdefault(target, str(task["target_table_comment"]))
    name = suffix_of(target)
    if name is None:
        return
    writes = tally.writes[name]
    writes["statements"] += 1
    writes["window_filtered"] += int(window)
    mode = str((task.get("partition") or {}).get("mode") or "")
    if mode in ("static", "dynamic"):
        writes[mode] += 1
    tally.written_tables[name].add(target)


def _writes(counter: Counter) -> dict:
    return {key: counter.get(key, 0) for key in ("statements", "window_filtered", "static", "dynamic")}


def _suffix_entry(name: str, tally: _Tally, covered: bool) -> dict:
    reads = {kind: tally.reads[name].get(kind, 0) for kind in READ_KINDS}
    writes = _writes(tally.writes.get(name, Counter()))
    tables_with = len(tally.partition_read_tables[name])
    observation = observe(reads, tables_with)
    suggestion, lean, reason = suggest(observation, reads, writes) if covered else (None, None, None)
    return {
        "suffix": name,
        "tables": len(tally.read_tables[name]),
        "tables_with_partition_reads": tables_with,
        "examples": sorted(tally.read_tables[name])[:_EXAMPLES],
        "reads": reads,
        "read_shapes": {
            kind: [shape for shape, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                   ][:_SHAPES_PER_READ]
            for kind, counts in sorted(tally.shapes[name].items())
        },
        "writes": writes,
        "written_tables": len(tally.written_tables.get(name, ())),
        "observation": observation,
        "suggestion": suggestion,
        "lean": lean,
        "pending_reason": reason,
    }


def _write_only_entry(name: str, tally: _Tally) -> dict:
    return {
        "suffix": name,
        "written_tables": len(tally.written_tables[name]),
        "examples": sorted(tally.written_tables[name])[:_EXAMPLES],
        "writes": _writes(tally.writes[name]),
    }


# ------------------------------------------------------------------ material


def _clean(text) -> str | None:
    text = str(text or "").strip()
    return redact(text) if text else None


def _schema_column(found: dict | None, column: str) -> dict:
    for item in (found or {}).get("columns") or []:
        if str(item.get("name")).lower() == column.lower():
            return item
    return {}


def _column_material(tally: _Tally, meta: Metadata, *, keys_only: bool = False) -> list[dict]:
    """One entry per distinct comment: how many columns carry it, one of them as its source,
    where the comment came from, and (qualifier material) whether any is numeric."""
    grouped: dict[str, dict] = {}
    for (table, column) in sorted(tally.keys if keys_only else tally.used):
        used = tally.used.get((table, column)) or {}
        schema = _schema_column(meta(table), column)
        comment, origin = _clean(schema.get("comment")), "schema"
        if comment is None:
            comment, origin = _clean(used.get("comment")), "lineage"
        if comment is None:
            continue
        kind = str(schema.get("type") or used.get("type") or "").lower()
        entry = grouped.setdefault(comment, {
            "comment": comment, "count": 0, "source": f"{table}.{column}", "from": origin,
            **({} if keys_only else {"numeric": False}),
        })
        entry["count"] += 1
        if not keys_only:
            entry["numeric"] = entry["numeric"] or bool(_NUMERIC.match(kind))
    if keys_only:
        return sorted(grouped.values(), key=lambda e: (-e["count"], e["comment"]))
    return sorted(grouped.values(), key=lambda e: (not e["numeric"], -e["count"], e["comment"]))


def _table_material(tally: _Tally, meta: Metadata) -> list[dict]:
    grouped: dict[str, dict] = {}
    for table in sorted(tally.tables):
        comment, origin = _clean((meta(table) or {}).get("comment")), "schema"
        if comment is None:
            comment, origin = _clean(tally.lineage_table_comments.get(table)), "lineage"
        if comment is None:
            continue
        entry = grouped.setdefault(
            comment, {"comment": comment, "count": 0, "source": table, "from": origin})
        entry["count"] += 1
    return sorted(grouped.values(), key=lambda e: (-e["count"], e["comment"]))


def _token_material(tables: Iterable[str]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for table in sorted(tables):
        for token in dict.fromkeys(table_name_words(table)):
            entry = grouped.setdefault(token, {"token": token, "count": 0, "source": table})
            entry["count"] += 1
    return sorted(grouped.values(), key=lambda e: (-e["count"], e["token"]))


def material_texts(evidence: dict) -> dict[str, list[str]]:
    """The texts each kind of word is judged against, as the reading command reads them:
    ``qualifier`` (column and table comments, check 12); ``votes`` (table-name words and
    table comments -- the concept layer votes a kind on a member's table name and table
    comment only); ``names`` (table and key-column comments -- where name candidates, which
    measure suffixes and filter words demote, come from)."""
    qualifier = evidence.get("qualifier_material") or {}
    concept = evidence.get("concept_material") or {}

    def comments(*parts: str) -> list[str]:
        return [e["comment"] for part in parts for e in concept.get(part) or []]

    return {
        "qualifier": [e["comment"] for part in ("columns", "tables")
                      for e in qualifier.get(part) or []],
        "votes": [e["token"] for e in concept.get("table_tokens") or []] + comments("table_comments"),
        "names": comments("table_comments", "key_comments"),
    }


# ------------------------------------------------------------------ read shapes

_PARTITION_MARK, _COLUMN_MARK, _CONSTANT_MARK = "zzpartitionzz", "zzcolumnzz", "zzconstantzz"
_PARAMETER = re.compile(r"\$\{[^}]*\}")


def mask_expression(text: str, partition_columns: Iterable[str]) -> str:
    """A partition condition with everything but its operators, keywords and function names
    masked: a partition column is 「分区列」, any other column 「列」, a constant 「常量」."""
    partitions = {str(name).lower() for name in partition_columns}
    source = _PARAMETER.sub("0", strip_leading_keyword(str(text or "")))
    try:
        tree = sqlglot.parse_one(source, read="spark")
    except (SqlglotError, ValueError, RecursionError):
        return "（无法解析）"

    def mask(node):
        if isinstance(node, exp.Column):
            mark = _PARTITION_MARK if node.name.lower() in partitions else _COLUMN_MARK
            return exp.var(mark)
        if isinstance(node, (exp.Literal, exp.Null, exp.Boolean, exp.Placeholder, exp.Parameter)):
            return exp.var(_CONSTANT_MARK)
        return node

    rendered = tree.transform(mask).sql("spark")
    return (rendered.replace(_PARTITION_MARK, "分区列").replace(_COLUMN_MARK, "列")
            .replace(_CONSTANT_MARK, "常量"))


# ------------------------------------------------------------------ summary and markdown


def suffix_counts(evidence: dict) -> dict[str, int]:
    entries = list(evidence.get("suffixes") or [])
    incremental = sum(1 for e in entries if e.get("suggestion") == SUGGEST_INCREMENTAL)
    pending = sum(1 for e in entries if e.get("suggestion") == SUGGEST_PENDING)
    total = len(entries) + len(evidence.get("write_only_suffixes") or [])
    return {"total": total, "incremental": incremental, "pending": pending,
            "none": total - incremental - pending}


def _parts(evidence: dict) -> dict[str, list[tuple[str, dict]]]:
    """The two material parts, each as ``(list name, entry)`` pairs in listing order."""
    qualifier = evidence.get("qualifier_material") or {}
    concept = evidence.get("concept_material") or {}
    return {
        "qualifier": [(name, e) for name in ("columns", "tables") for e in qualifier.get(name) or []],
        "concept": [(name, e) for name in ("table_tokens", "table_comments", "key_comments")
                    for e in concept.get(name) or []],
    }


def _kept(part: str, entries: list[tuple[str, dict]]) -> set[int]:
    """The positions ``evidence.md`` keeps of one part, at most its limit: numeric columns'
    comments first (qualifiers are mostly written on measure columns), then the most frequent."""
    order = sorted(
        range(len(entries)),
        key=lambda i: (not entries[i][1].get("numeric"), -entries[i][1].get("count", 0), i),
    )
    return set(order[:MARKDOWN_LIMITS[part]])


def truncated_count(evidence: dict) -> int:
    return sum(
        max(0, len(entries) - MARKDOWN_LIMITS[part]) for part, entries in _parts(evidence).items()
    )


def evidence_summary(evidence: dict) -> str:
    coverage = evidence.get("coverage") or {}
    tables, found = coverage.get("tables", 0), coverage.get("found", 0)
    share = round(100 * found / tables) if tables else 100
    counts = suffix_counts(evidence)
    parts = _parts(evidence)
    return (
        f"Evidence for {tables} corpus table(s), {found} found in metadata ({share}%): "
        f"{counts['total']} suffix(es) -- {counts['incremental']} incremental, "
        f"{counts['pending']} pending, {counts['none']} without suggestion; "
        f"qualifier material {len(parts['qualifier'])} entries, "
        f"concept material {len(parts['concept'])} entries "
        f"(truncated {truncated_count(evidence)})"
    )


_SUGGESTION_WORDS = {SUGGEST_INCREMENTAL: "`incremental`", None: "无"}


def _suggestion_text(entry: dict) -> str:
    if entry.get("suggestion") == SUGGEST_PENDING:
        return "待确认（倾向全量）" if entry.get("lean") == LEAN_FULL else "待确认（无倾向）"
    return _SUGGESTION_WORDS.get(entry.get("suggestion"), "无")


def render_evidence_markdown(evidence: dict) -> str:
    """``evidence.md``: the same evidence for a model to read, the material parts cut at
    :data:`MARKDOWN_LIMITS` entries each with the number left out."""
    lines = ["# 领域配置证据", ""]
    for note in evidence.get("notes") or []:
        lines += [f"> **注意**：{note}", ""]
    lines += _intro(evidence)
    lines += _suffix_lines(evidence)
    lines += _material_lines(evidence)
    lines += _builtin_lines(evidence)
    return "\n".join(lines).rstrip() + "\n"


def _intro(evidence: dict) -> list[str]:
    inputs = evidence.get("inputs") or {}
    return [
        evidence_summary(evidence), "",
        f"- lineage：`{inputs.get('lineage')}`；元数据：`{inputs.get('schema')}`；"
        f"工具版本 {inputs.get('tool_version')}",
        "- 工具只报观察，不替你下结论；证据不足以下定论的地方，一律留给人。", "",
    ]


_READ_HEAD = "| 后缀 | 表 | 带分区条件的表 | equality | multi_equality | range | unconditioned | unpartitioned | 写入（语句/窗口筛选/静态/动态） | 观察 | 建议 |"


def _suffix_lines(evidence: dict) -> list[str]:
    entries = list(evidence.get("suffixes") or [])
    small = [e for e in entries if e["observation"] == "too_few"
             and not any(e["reads"][k] for k in _PARTITION_READS)]
    shown = [e for e in entries if e not in small]
    lines = [
        "## 一、表名后缀", "",
        "读法以「一条语句读一张表」为单位。单分区读既可能是全量快照，也可能是每天取当天那一批增量；"
        "沿分区传递的增量链路在 SQL 里和全量链路没有区别，所以工具从不直接建议 `full`。", "",
        _READ_HEAD, "|" + " --- |" * 11,
    ]
    for e in shown:
        r, w = e["reads"], e["writes"]
        lines.append(
            f"| `{e['suffix']}` | {e['tables']} | {e['tables_with_partition_reads']} | "
            f"{r['equality']} | {r['multi_equality']} | {r['range']} | {r['unconditioned']} | "
            f"{r['unpartitioned']} | {w['statements']}/{w['window_filtered']}/{w['static']}/"
            f"{w['dynamic']} | {e['observation']} | {_suggestion_text(e)} |")
    lines.append("")
    for e in shown:
        lines += _suffix_detail(e)
    if small:
        names = "、".join(f"`{e['suffix']}`" for e in small)
        lines += [f"另有 {len(small)} 个后缀不够门槛、也没有带分区条件的读取（多半是表名里的普通单词）："
                  f"{names}。", ""]
    write_only = list(evidence.get("write_only_suffixes") or [])
    if write_only:
        lines += ["### 只写不读的后缀", "", "| 后缀 | 写入的表 | 写入（语句/窗口筛选/静态/动态） | 例子 |",
                  "| --- | --- | --- | --- |"]
        for e in write_only:
            w = e["writes"]
            lines.append(f"| `{e['suffix']}` | {e['written_tables']} | {w['statements']}/"
                         f"{w['window_filtered']}/{w['static']}/{w['dynamic']} | "
                         f"{', '.join(e['examples'])} |")
        lines.append("")
    return lines


def _suffix_detail(entry: dict) -> list[str]:
    lines = [f"### `{entry['suffix']}`", "", f"- 建议：{_suggestion_text(entry)}"]
    if entry.get("pending_reason"):
        lines.append(f"- 理由：{entry['pending_reason']}")
    lines.append(f"- 例子：{', '.join(entry['examples'])}")
    for kind, shapes in entry["read_shapes"].items():
        lines.append(f"- {kind} 的典型写法：" + "；".join(f"`{s}`" for s in shapes))
    return lines + [""]


_PART_TITLES = {
    "qualifier": ("## 二、修饰词材料", {"columns": "被用到的列的注释（数值列在前）", "tables": "表注释"}),
    "concept": ("## 三、概念词材料", {"table_tokens": "表名词元", "table_comments": "表注释",
                                     "key_comments": "键列注释"}),
}


def _material_lines(evidence: dict) -> list[str]:
    lines: list[str] = []
    for part, entries in _parts(evidence).items():
        title, names = _PART_TITLES[part]
        kept = _kept(part, entries)
        lines += [title, ""]
        for name, heading in names.items():
            rows = [e for i, (owner, e) in enumerate(entries) if owner == name and i in kept]
            lines += [f"### {heading}", ""]
            lines += [_material_row(name, e) for e in rows] or ["（无）"]
            lines.append("")
        left = len(entries) - len(kept)
        if left:
            lines += [f"另有 {left} 条未列出，见 evidence.json", ""]
    return lines


def _material_row(name: str, entry: dict) -> str:
    if name == "table_tokens":
        return f"- `{entry['token']}` ×{entry['count']}（{entry['source']}）"
    numeric = "，数值" if entry.get("numeric") else ""
    return (f"- 「{entry['comment']}」 ×{entry['count']}（{entry['source']}，"
            f"{entry['from']}{numeric}）")


def _builtin_lines(evidence: dict) -> list[str]:
    builtin = evidence.get("builtin") or {}
    lines = ["## 四、已内置的通用词（不用重复写）", "",
             "- `qualifier_terms`：" + "、".join(builtin.get("qualifier_terms") or [])]
    for kind, words in (builtin.get("concept_words") or {}).items():
        lines.append(f"- `concept_words.{kind}`：" + "、".join(words))
    return lines + [""]
