"""Corpus-level table cards (``tables-json/1``) derived from semantic profiles.

``semantic.json`` answers "what does this task do". A corpus of tasks answers a question
no single task can: **what is this table**. The producing statement knows the grain, the
keys, the partition and one sentence per written column; the consuming statements know
which columns anybody actually reads and how. A table card is those two halves published
under one normalized table name, so the reader of a task never has to guess what an input
table's row means -- some other task in the same corpus already proved it.

Three rules keep the card as honest as the contract it is derived from.

1. **One logical table, one card.** A corpus records the same table under several
   qualification levels (``mart.t`` where it is read, ``spark_catalog.mart.t`` where it
   is written). Names are grouped by the dotted-suffix rule the query helper's
   ``_same_table`` uses; the most qualified spelling becomes the primary name and the
   others are published as ``aliases`` rather than dropped.
2. **Only what outlives the script gets a card.** A session-scoped relation (a temporary
   view) and a ``directory:`` write leave nothing behind for another task to read, so
   neither becomes a table -- exactly the exclusion ``produced_tables`` already applies.
3. **Nothing is named that the corpus did not name.** Every table, column, key and task
   on a card was copied from a semantic profile, which in turn copied it from a contract
   document. This module counts, groups and restates in structural Chinese; it never
   invents a business name, a table type or a meaning for a column.

The describe side of WI-2.5 lives here too: ``apply_table_cards`` folds the corpus's
answers back into one task's profile (``inputs[].card``, ``task.downstream_consumers``,
``confidence.metadata_coverage.table_cards``). It is a post-processing step rather than a
parameter of ``build_semantic_profile`` on purpose: a profile built without a corpus must
stay byte-identical to what it was before this module existed, so the three keys appear
only when a corpus was actually supplied.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .markdown_text import cell, expr_span, normalize_inline
from .semantic_profile import (
    REFRESH_SOURCE_TASK_META,
    TASK_PROFILE_ARTIFACT_KIND,
    USAGE_ORDER,
)


DOC_FORMAT = "tables-json/1"
CARD_DOC_FORMAT = "tables-md/1"
INDEX_DOC_FORMAT = "tables-index-md/1"

# A card is only ever published for a table another task could read. The key is carried
# anyway so a later kind (an external table, a view) can be added without a version bump.
TABLE_KIND_PHYSICAL = "physical"

DIRECTORY_TARGET_PREFIX = "directory:"

# P2: which keys of a semantic profile ``build_table_cards`` reads, and so the whole of
# what `scope-lineage tables --incremental` stores per task. It lives here, next to the
# code that reads them, so a builder that starts reading a new key has the list under its
# nose; `tests/core/test_corpus_cache_projection.py` fails until the two agree.
#
# A card restates what each task PROVES about a table -- its grain, its keys, the columns
# it wrote and read -- so it reads the conclusions and never the working. `stages` (how
# the rows got there), `rules` (the JOIN / filter predicates) and `confidence` (the
# profile's own self-assessment) are the working, and between them they are about a third
# of a profile. So is every field's `derivation`, which is why `fields` is narrowed to the
# four keys a card column carries.
PROFILE_FIELDS_READ = {
    "profile": ("artifact_kind", "task_id", "lineage_digest", "produced_tables"),
    "statement": {
        "statement_id": None,
        # A 1.0 profile answers for its own task, so it carries the two keys a 2.0
        # profile keeps above its statements rather than inside them.
        "lineage_digest": None,
        "task": (
            "task_name",
            "stmt_kind",
            "partition",
            "meta",
            "header_comments",
            "target_table",
            "target_table_comment",
            "target_table_domain",
            "target_table_project",
            "target_table_owner",
            "target_declared_columns",
        ),
        "inputs": (
            "table",
            "comment",
            "domain",
            "project",
            "owner",
            "layer",
            "role_in_task",
            "roles",
            "used_columns",
            "declared_columns",
            "read_by_scopes",
        ),
        "output_shape": ("grain", "candidate_keys", "key_confidence"),
        "fields": ("column", "target_comment", "summary", "structural_role"),
    },
}

FINDING_AMBIGUOUS_BARE_NAME = "ambiguous_bare_name"
FINDING_MULTIPLE_PRODUCERS = "multiple_producers"
FINDING_PRODUCER_KEY_CONFLICT = "producer_key_conflict"
FINDING_NEVER_CONSUMED = "never_consumed_in_corpus"
FINDING_NEVER_PRODUCED = "never_produced_in_corpus"

FINDING_KINDS = (
    FINDING_AMBIGUOUS_BARE_NAME,
    FINDING_MULTIPLE_PRODUCERS,
    FINDING_PRODUCER_KEY_CONFLICT,
    FINDING_NEVER_CONSUMED,
    FINDING_NEVER_PRODUCED,
)

TABLE_KEY_ORDER = (
    "table",
    "aliases",
    "comment",
    "domain",
    "project",
    "owner",
    "layer",
    "kind",
    "produced_by",
    "consumed_by",
    "columns",
    "coverage",
    "findings",
)

PRODUCER_KEY_ORDER = (
    "task",
    "statement_id",
    "stmt_kind",
    "partition",
    "grain",
    "candidate_keys",
    "key_confidence",
    "fields",
    "refresh",
    "header_comments",
    "lineage_digest",
)

CONSUMER_KEY_ORDER = (
    "task",
    "statement_id",
    "role_in_task",
    "roles",
    "columns",
    "read_by_scopes",
)

CARD_KEY_ORDER = (
    "produced_by_task",
    "grain_text",
    "candidate_keys",
    "key_confidence",
    "comment",
    "refresh",
)

# Structural words only. "按分组键聚合后的一行" restates the GROUP BY; it does not say the
# row is "a customer" -- that is the business reading, and it is not Core's to give.
GRAIN_BASIS_TEXT = {
    "group_by": "分组聚合后的一行",
    "distinct": "去重后的一行",
    "window_partition": "窗口分组内保留的一行",
    "driving_table_rows": "主表的一行",
    # B10: the producer aggregates without a GROUP BY, so the table it writes holds one
    # row per run of that task -- "一行代表什么" has a complete answer here, not a key list.
    "single_row": "整张输出一行（全表汇总）",
    "unknown": "未知",
}

USAGE_TEXT = {
    "filter": "过滤",
    "partition_filter": "分区过滤",
    "join_key": "连接键",
    "group_by": "分组键",
    "window_partition": "窗口分组",
    "window_order": "窗口排序",
    "output": "输出",
}

ROLE_TEXT = {
    "driving": "主表",
    "merge_source": "MERGE 来源",
    "aggregate_source": "聚合来源",
    "dedup_source": "去重来源",
    "union_branch": "合并分支",
    # B2: an INNER JOIN's partner on the driving path -- it drops driving rows it
    # cannot match, so it is not mere enrichment.
    "filter_partner": "关联筛选",
    "enrich": "关联补充",
    "rowset_only": "仅行集引用",
}

TAG_METADATA_FACT = "元数据事实"
TAG_SQL_FACT = "SQL事实"
TAG_STRUCTURAL_INFERENCE = "结构推断"
TAG_SQL_COMMENT = "SQL注释"

UNKNOWN_TEXT = "未知"

BASIS_UNKNOWN = "unknown"

# What stands in for the walk's own sentence when the contract recorded none.
UNDECIDED_GRAIN_REASON = "结构未记录原因"

# Characters a table name may legally hold that a file name may not.
_UNSAFE_FILENAME_CHARS = '/\\:*?"<>| \t'


@dataclass(frozen=True)
class _Statement:
    """One write statement of one task, with what the task proved about it."""

    task: str
    statement_id: str
    digest: str | None
    profile: dict
    # The table this statement leaves behind, or None (session-scoped, directory, MERGE
    # into a relation the task document does not list as produced).
    target: str | None
    # Relations of the same task that exist only inside the script; an input matching one
    # of these is not a table another task could read.
    session_scoped: tuple[str, ...]


# ------------------------------------------------------------------ name normalization


def same_table(left: str, right: str) -> bool:
    """The corpus-wide identity rule: a dotted suffix of the other name is the same table.

    One corpus records ``dwd.t`` in a hive-style read and ``catalog.dwd.t`` at the
    iceberg writer. Mirrors ``skills/scope-lineage/scripts/query.py::_same_table``; the
    helper is re-implemented here because a packaged module may not import a script.
    """
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def table_groups(names: Iterable[str]) -> dict[str, list[str]]:
    """``primary name -> every spelling seen``, most qualified spelling first."""
    groups, _ambiguous = _group_spellings(names)
    return {_primary_name(group): group for group in groups}


def ambiguous_bare_names(names: Iterable[str]) -> set[str]:
    """The unqualified names more than one qualified table in the corpus could be."""
    _groups, ambiguous = _group_spellings(names)
    return ambiguous


def _group_spellings(names: Iterable[str]) -> tuple[list[list[str]], set[str]]:
    """``(groups, ambiguous bare names)`` -- the suffix rule, with its one stop.

    Merging is transitive **between qualified names**: ``dwd.t`` and ``catalog.dwd.t``
    are one table however many spellings sit between them. An unqualified name is not
    allowed to be the bridge. ``ods.t`` and ``dwd.t`` are two tables, and a script that
    once wrote a bare ``t`` used to merge them into one card -- publishing one table's
    producer as the other's, which is the single worst thing a card can say.

    A bare name is therefore resolved, not assumed: it joins the one qualified group it
    could be, and when several could be it stays its own table and the card says so
    (``ambiguous_bare_name``). Silently picking one would be a guess at which warehouse
    database the author meant, and this module does not guess.
    """
    ordered = sorted({str(name) for name in names})
    groups: list[list[str]] = []
    for name in [item for item in ordered if "." in item]:
        merged = [name]
        for group in list(groups):
            if any(same_table(name, member) for member in group):
                merged.extend(group)
                groups.remove(group)
        groups.append(sorted(set(merged)))
    ambiguous: set[str] = set()
    for name in [item for item in ordered if "." not in item]:
        hosts = [
            group for group in groups if any(same_table(name, item) for item in group)
        ]
        if len(hosts) == 1:
            hosts[0].append(name)
            hosts[0].sort()
            continue
        if hosts:
            ambiguous.add(name)
        groups.append([name])
    return groups, ambiguous


def _primary_name(group: Sequence[str]) -> str:
    """The most qualified spelling; ties break by name so the choice cannot drift."""
    return min(group, key=lambda name: (-len(name), name))


def table_card_filename(table: str) -> str:
    """``<db.table>.md``, with anything a file system would choke on replaced by ``_``."""
    safe = "".join("_" if char in _UNSAFE_FILENAME_CHARS else char for char in str(table))
    return f"{safe}.md"


# ------------------------------------------------------------------ profile flattening


def _statement_records(profiles: Iterable[dict]) -> list[_Statement]:
    records: list[_Statement] = []
    for profile in profiles:
        if profile.get("artifact_kind") == TASK_PROFILE_ARTIFACT_KIND:
            records.extend(_task_statements(profile))
        else:
            records.append(_bare_statement(profile))
    return sorted(records, key=lambda record: (record.task, record.statement_id))


def _task_statements(profile: dict) -> list[_Statement]:
    task = str(profile.get("task_id") or "")
    digest = profile.get("lineage_digest")
    produced = [str(table) for table in profile.get("produced_tables") or []]
    statements = profile.get("statements") or []
    targets = [_target_of(statement) for statement in statements]
    session = tuple(
        sorted({target for target in targets if target and target not in produced})
    )
    return [
        _Statement(
            task=task,
            statement_id=str(statement.get("statement_id") or ""),
            digest=digest,
            profile=statement,
            target=target if target in produced else None,
            session_scoped=session,
        )
        for statement, target in zip(statements, targets)
    ]


def _bare_statement(profile: dict) -> _Statement:
    """A 1.0 statement profile: it is its own task, and has no sibling statements."""
    target = _target_of(profile)
    return _Statement(
        task=str((profile.get("task") or {}).get("task_name") or ""),
        statement_id=str(profile.get("statement_id") or ""),
        digest=profile.get("lineage_digest"),
        profile=profile,
        target=target,
        session_scoped=(),
    )


def _target_of(statement: dict) -> str | None:
    """The written table, or None for a directory write, which no catalog declares."""
    target = str((statement.get("task") or {}).get("target_table") or "")
    if not target or target.startswith(DIRECTORY_TARGET_PREFIX):
        return None
    return target


def _consumed_inputs(record: _Statement) -> list[dict]:
    return [
        item
        for item in record.profile.get("inputs") or []
        if not any(
            same_table(str(item.get("table") or ""), relation)
            for relation in record.session_scoped
        )
    ]


# ----------------------------------------------------------------------------- builder


def build_table_cards(
    profiles: Iterable[dict], *, artifact_root: str | None = None, samples=None
) -> dict:
    """Build the corpus's table cards from one semantic profile per task.

    ``profiles`` holds task profiles (``task_semantic``) and bare statement profiles in
    any order; the result is sorted by table name, so the same corpus always builds the
    same bytes whatever order the caller walked the artifact tree in.

    ``samples`` is a loaded :class:`~scope_lineage.metadata.column_samples.ColumnSamples`
    -- values somebody exported, never values this module read from a database. A6:
    supplying it adds ``columns[].samples``, ``coverage.columns_sampled`` and the
    ``samples_applied`` report; leaving it out builds the document it always built,
    byte for byte.
    """
    records = _statement_records(profiles)
    produced: dict[str, list[_Statement]] = {}
    consumed: dict[str, list[tuple[_Statement, dict]]] = {}
    for record in records:
        if record.target:
            produced.setdefault(record.target, []).append(record)
        for item in _consumed_inputs(record):
            consumed.setdefault(str(item.get("table") or ""), []).append((record, item))
    grouped, ambiguous = _group_spellings([*produced, *consumed])
    groups = {_primary_name(group): group for group in grouped}
    tables = [
        _table_card(
            primary,
            groups[primary],
            produced,
            consumed,
            _bare_name_candidates(primary, groups) if primary in ambiguous else (),
            samples,
        )
        for primary in sorted(groups)
    ]
    document = {"doc_format": DOC_FORMAT, "corpus": _corpus_block(records, artifact_root)}
    if samples is not None:
        document["samples_applied"] = _samples_applied(samples, tables)
    document["tables"] = tables
    return document


def _samples_applied(samples, tables: Sequence[dict]) -> dict:
    """What the supplied file did: which files, how many columns, and what missed.

    ``unmatched`` is read after every card has been built, so it names exactly the
    ``table.column`` keys no table in this corpus ever asked for -- the typo in a
    hand-made export, reported rather than silently dropped.
    """
    return {
        "sources": list(samples.sources),
        "columns_sampled": sum(card["coverage"]["columns_sampled"] for card in tables),
        "unmatched": samples.unmatched(),
    }


def _bare_name_candidates(bare: str, groups: Mapping[str, list[str]]) -> list[str]:
    """The qualified tables an unresolved bare name could have meant, named in the card."""
    return sorted(
        primary
        for primary in groups
        if primary != bare and same_table(bare, primary)
    )


def _corpus_block(records: Sequence[_Statement], artifact_root: str | None) -> dict:
    digests = {
        record.task: record.digest for record in records if record.digest is not None
    }
    return {
        "artifact_root": artifact_root,
        "task_count": len({record.task for record in records}),
        "lineage_digests": {task: digests[task] for task in sorted(digests)},
    }


def _table_card(
    primary: str,
    spellings: Sequence[str],
    produced: dict[str, list[_Statement]],
    consumed: dict[str, list[tuple[_Statement, dict]]],
    bare_name_candidates: Sequence[str] = (),
    samples=None,
) -> dict:
    producers = [record for name in spellings for record in produced.get(name, [])]
    producers.sort(key=lambda record: (record.task, record.statement_id))
    consumers = [pair for name in spellings for pair in consumed.get(name, [])]
    consumers.sort(key=lambda pair: (pair[0].task, pair[0].statement_id))
    produced_by = [_producer_entry(record) for record in producers]
    consumed_by = [_consumer_entry(record, item) for record, item in consumers]
    declared = _declared_columns(producers, consumers)
    columns = _columns(produced_by, consumers, declared)
    _apply_samples(columns, [primary, *spellings], samples)
    comment = _table_comment(producers, consumers)
    card = {
        "table": primary,
        "aliases": [name for name in spellings if name != primary],
        "comment": comment,
        **_table_facts(producers, consumers),
        "kind": TABLE_KIND_PHYSICAL,
        "produced_by": produced_by,
        "consumed_by": consumed_by,
        "columns": columns,
        "coverage": _coverage(
            comment,
            columns,
            produced_by,
            consumed_by,
            len(declared) or None,
            samples is not None,
        ),
        "findings": _findings(produced_by, consumed_by, bare_name_candidates),
    }
    return {key: card[key] for key in TABLE_KEY_ORDER}


def _producer_entry(record: _Statement) -> dict:
    statement = record.profile
    task_block = statement.get("task") or {}
    shape = statement.get("output_shape") or {}
    grain = shape.get("grain") or {}
    entry = {
        "task": record.task,
        "statement_id": record.statement_id,
        "stmt_kind": task_block.get("stmt_kind"),
        "partition": _partition(task_block.get("partition")),
        "grain": {
            "basis": grain.get("basis"),
            "keys": [str(key.get("name")) for key in grain.get("keys") or []],
        },
        "candidate_keys": [str(key) for key in shape.get("candidate_keys") or []],
        "key_confidence": shape.get("key_confidence"),
        "fields": [_producer_field(field) for field in statement.get("fields") or []],
        "refresh": refresh_from_task_meta(task_block.get("meta")),
        "header_comments": [str(item) for item in task_block.get("header_comments") or []],
        "lineage_digest": record.digest,
    }
    return {key: entry[key] for key in PRODUCER_KEY_ORDER}


def _producer_field(field: dict) -> dict:
    return {
        "column": field.get("column"),
        # `target_comment` is the metadata's word for the written column; a field the
        # target's DDL does not describe keeps a null rather than borrowing its source's.
        "comment": field.get("target_comment"),
        "summary": field.get("summary"),
        "structural_role": field.get("structural_role"),
    }


def _partition(partition: dict | None) -> dict:
    partition = partition or {}
    return {
        "columns": [str(column) for column in partition.get("columns") or []],
        "mode": partition.get("mode"),
        "spec": dict(partition.get("spec") or {}) or None,
    }


def refresh_from_task_meta(task_meta: dict | None) -> dict | None:
    """The write's cadence, copied from the task metadata or ``None``.

    Mirrors ``semantic_profile._metric_refresh``: both forms are published side by side
    because the cycle is what a reader wants and the cron is what actually runs, and
    neither is ever derived from a partition column or a table name.
    """
    if not task_meta:
        return None
    cycle = task_meta.get("schedule_cycle")
    cron = task_meta.get("schedule")
    if not cycle and not cron:
        return None
    return {"cycle": cycle, "cron": cron, "source": REFRESH_SOURCE_TASK_META}


def _consumer_entry(record: _Statement, item: dict) -> dict:
    entry = {
        "task": record.task,
        "statement_id": record.statement_id,
        "role_in_task": item.get("role_in_task"),
        "roles": [str(role) for role in item.get("roles") or []],
        "columns": [
            {"name": column.get("name"), "usages": list(column.get("usages") or [])}
            for column in item.get("used_columns") or []
            if column.get("usages")
        ],
        "read_by_scopes": [str(scope) for scope in item.get("read_by_scopes") or []],
    }
    return {key: entry[key] for key in CONSUMER_KEY_ORDER}


# ---------------------------------------------------------------------------- columns


def _declared_columns(
    producers: Sequence[_Statement], consumers: Sequence[tuple[_Statement, dict]]
) -> list[dict]:
    """The table's whole declared width, from the first document that carried it.

    A1: the corpus's own documents only ever describe the columns each task touched, so
    a table read four columns at a time published a four-column card whatever the
    catalog declared. One document's ``declared_columns[]`` answers for the table, and
    the first one asked wins rather than the widest: merging two catalogs' idea of the
    same table would invent a shape no single document ever stated.
    """
    for record in producers:
        declared = (record.profile.get("task") or {}).get("target_declared_columns")
        if declared:
            return [dict(column) for column in declared]
    for _, item in consumers:
        if item.get("declared_columns"):
            return [dict(column) for column in item["declared_columns"]]
    return []


def _columns(
    produced_by: Sequence[dict],
    consumers: Sequence[tuple[_Statement, dict]],
    declared: Sequence[dict] = (),
) -> list[dict]:
    """The union of the declared columns, the written ones and the read ones.

    Order follows the corpus rather than the alphabet: a producer publishes its target
    columns in write order, then the catalog's remaining columns in DDL order, which is
    the order a reader of the table expects to see. A column nobody touched is still a
    column of the table, and it is here with ``used_in_corpus: false`` rather than absent.
    """
    columns: dict[str, dict] = {}
    for producer in produced_by:
        for field in producer["fields"]:
            entry = columns.setdefault(str(field["column"]), _blank_column(field["column"]))
            entry["used_in_corpus"] = True
            _fill(entry, "produced_summary", field.get("summary"))
            _fill(entry, "comment", field.get("comment"))
    for column in declared:
        entry = columns.setdefault(str(column.get("name")), _blank_column(column.get("name")))
        _fill(entry, "type", column.get("type"))
        _fill(entry, "comment", column.get("comment"))
    for _, item in consumers:
        for column in item.get("used_columns") or []:
            entry = columns.setdefault(str(column.get("name")), _blank_column(column.get("name")))
            entry["used_in_corpus"] = True
            _fill(entry, "type", column.get("type"))
            _fill(entry, "comment", column.get("comment"))
            for usage in column.get("usages") or []:
                entry["consumer_usage_counts"][usage] += 1
    _fill_produced_types(columns, produced_by)
    return [_ordered_column(entry) for entry in columns.values()]


def _apply_samples(columns: Sequence[dict], spellings: Sequence[str], samples) -> None:
    """A6: hang the supplied values on the columns they were exported for.

    Applied after the columns are built rather than inside the union, because a samples
    file answers about a column the corpus already knows -- a value for a column no task
    ever touched and no catalog declared would be a column this corpus cannot prove
    exists, and it is reported as unmatched instead.
    """
    if samples is None:
        return
    for column in columns:
        values = samples.values(spellings, column["name"])
        if values:
            column["samples"] = values


def _blank_column(name) -> dict:
    return {
        "name": str(name),
        "type": None,
        "comment": None,
        "produced_summary": None,
        "consumer_usage_counts": Counter(),
        "used_in_corpus": False,
    }


def _fill(entry: dict, key: str, value) -> None:
    """First non-null wins: producers are read before consumers, tasks in name order."""
    if entry.get(key) is None and value is not None:
        entry[key] = value


def _fill_produced_types(columns: dict[str, dict], produced_by: Sequence[dict]) -> None:
    """A written column's declared type, used only where no consumer supplied one."""
    for producer in produced_by:
        for field in producer["fields"]:
            entry = columns.get(str(field["column"]))
            if entry is not None:
                _fill(entry, "type", field.get("type"))


def _ordered_column(entry: dict) -> dict:
    counts = entry["consumer_usage_counts"]
    return {
        "name": entry["name"],
        "type": entry["type"],
        "comment": entry["comment"],
        "produced_summary": entry["produced_summary"],
        "consumer_usage_counts": {
            usage: counts[usage] for usage in USAGE_ORDER if counts.get(usage)
        },
        # A1: whether any task in this corpus wrote or read the column. `false` is the
        # answer the catalog gave and the corpus never contradicted -- not "unused".
        "used_in_corpus": bool(entry["used_in_corpus"]),
    }


# --------------------------------------------------------------- comment and coverage


def _table_comment(
    producers: Sequence[_Statement], consumers: Sequence[tuple[_Statement, dict]]
) -> str | None:
    for record in producers:
        comment = (record.profile.get("task") or {}).get("target_table_comment")
        if comment:
            return str(comment)
    for _, item in consumers:
        if item.get("comment"):
            return str(item["comment"])
    return None


# Each card fact, with the producer's task key and the consumer's input key that answer
# it. A producer describes the table it writes; a consumer describes the table it reads.
# `layer` has no producer spelling -- the task block carries the target's placement, not
# its storage layer -- so only a consumer can answer it.
_CARD_FACTS = (
    ("domain", "target_table_domain", "domain"),
    ("project", "target_table_project", "project"),
    ("owner", "target_table_owner", "owner"),
    ("layer", None, "layer"),
)


def _table_facts(
    producers: Sequence[_Statement], consumers: Sequence[tuple[_Statement, dict]]
) -> dict:
    """Business domain, project, owner and layer, producer first then consumer.

    Same precedence as the comment: whoever writes the table describes it best, and a
    reader of it answers when no producer in this corpus does.
    """
    facts = {}
    for name, task_key, input_key in _CARD_FACTS:
        value = None
        if task_key:
            value = next(
                (
                    str((record.profile.get("task") or {})[task_key])
                    for record in producers
                    if (record.profile.get("task") or {}).get(task_key)
                ),
                None,
            )
        if value is None:
            value = next(
                (str(item[input_key]) for _, item in consumers if item.get(input_key)),
                None,
            )
        facts[name] = value
    return facts


def _coverage(
    comment: str | None,
    columns: Sequence[dict],
    produced_by: Sequence[dict],
    consumed_by: Sequence[dict],
    declared_count: int | None = None,
    sampled: bool = False,
) -> dict:
    commented = sum(1 for column in columns if column["comment"])
    coverage = {
        "column_comment_ratio": round(commented / len(columns), 4) if columns else 0.0,
        "table_comment": comment is not None,
        "producers": len(produced_by),
        "consumers": len(consumed_by),
        # A1: how much of the table this corpus actually exercised. `columns_declared`
        # is null, not zero, when no document declared the table -- "the catalog was
        # never asked" is not "the table has no columns".
        "columns_used": sum(1 for column in columns if column["used_in_corpus"]),
        "columns_declared": declared_count or None,
    }
    # A6: how many columns somebody supplied values for. Absent -- not zero -- when no
    # samples file was given: "nobody was asked" is not "nobody answered".
    if sampled:
        coverage["columns_sampled"] = sum(1 for column in columns if column.get("samples"))
    return coverage


# --------------------------------------------------------------------------- findings


def _findings(
    produced_by: Sequence[dict],
    consumed_by: Sequence[dict],
    bare_name_candidates: Sequence[str] = (),
) -> list[dict]:
    findings = []
    if bare_name_candidates:
        findings.append(
            _finding(
                FINDING_AMBIGUOUS_BARE_NAME,
                f"这个表名没有库名限定，本语料内有 {len(bare_name_candidates)} 张表可能是它："
                + "、".join(bare_name_candidates)
                + "；它们没有被合并成一张卡，请人工确认脚本实际读写的是哪一张。",
                [*produced_by, *consumed_by],
            )
        )
    if len(produced_by) > 1:
        findings.append(
            _finding(
                FINDING_MULTIPLE_PRODUCERS,
                f"{len(produced_by)} 条写语句写同一张表；下游读到的是哪一条的结果取决于调度顺序。",
                produced_by,
            )
        )
        keys = {tuple(item["candidate_keys"]) for item in produced_by}
        if len(keys) > 1:
            findings.append(
                _finding(
                    FINDING_PRODUCER_KEY_CONFLICT,
                    "多个生产语句给出的候选键不一致："
                    + "；".join(
                        f"{item['task']}/{item['statement_id']} → "
                        + ("、".join(item["candidate_keys"]) or "无")
                        for item in produced_by
                    )
                    + "。",
                    produced_by,
                )
            )
    if produced_by and not consumed_by:
        findings.append(
            _finding(
                FINDING_NEVER_CONSUMED,
                "本语料内没有任务读这张表；可能是对外出口，也可能是无人消费的产出。",
                produced_by,
            )
        )
    if consumed_by and not produced_by:
        findings.append(
            _finding(
                FINDING_NEVER_PRODUCED,
                "本语料内没有任务写这张表；它的一行代表什么无法从本语料证明。",
                consumed_by,
            )
        )
    return findings


def _finding(kind: str, text: str, entries: Sequence[dict]) -> dict:
    return {"kind": kind, "text": text, "evidence": [_evidence(entry) for entry in entries]}


def _evidence(entry: Mapping) -> dict:
    """The statement a finding was read off, and -- after a merge -- whose corpus it is.

    A single corpus never carries the key: the document already says which root it was
    walked from. After ``merge_table_cards`` it is the only thing that makes a finding
    actionable, because "these two producers disagree" is a different conversation when
    the two producers belong to two different teams' batches.
    """
    item = {"task": entry["task"], "statement_id": entry["statement_id"]}
    if entry.get("corpus"):
        item["corpus"] = entry["corpus"]
    return item


# --------------------------------------------------------------- cross-corpus merge


#: The merged document's own key: which corpora were folded into it, and how big each
#: was. A document built by ``build_table_cards`` never carries it -- it was not merged
#: from anything -- so one corpus keeps publishing exactly the bytes it always did.
MERGED_FROM_KEY = "merged_from"


@dataclass(frozen=True)
class _Source:
    """One ``tables.json`` being merged: what to stamp its evidence with, and its size."""

    label: str
    task_count: int
    merged_from: list[dict] | None


def merge_table_cards(*card_documents: Mapping) -> dict:
    """Fold several ``tables-json/1`` documents into one, keeping every corpus named.

    One corpus can only prove what its own tasks wrote. The task that proved a table's
    key often sits in another batch entirely, and until the two documents are one the
    reader downstream has to take "this JOIN may fan out" for an answer. Merging is
    therefore not a convenience: it is the only way a card, a ``safe`` verdict or an
    ontology relation gets to stand on evidence from more than one walk.

    Every producer and consumer entry gains a ``corpus``, so a borrowed proof always
    says where to look for the task behind it, and the card's ``coverage`` and
    ``findings`` are re-derived over the merged evidence rather than added up: a table
    nobody read in corpus A is not ``never_consumed_in_corpus`` once corpus B's reader
    is on the same card. Merging one document is the identity -- a document that was
    not merged with anything says nothing about corpora, exactly as it was written.
    """
    documents = [_merge_input(document) for document in card_documents]
    if not documents:
        raise ValueError("merge_table_cards needs at least one tables-json/1 document")
    if len(documents) == 1:
        return dict(documents[0])
    sources = [_source(document, index) for index, document in enumerate(documents)]
    members = [
        (source.label, card)
        for source, document in zip(sources, documents)
        for card in document.get("tables") or []
    ]
    merged_from = _merged_from(sources)
    document = {
        "doc_format": DOC_FORMAT,
        "corpus": _merged_corpus(sources, documents, merged_from),
        MERGED_FROM_KEY: merged_from,
    }
    tables = _merged_tables(members)
    applied = _merged_samples_applied(documents, tables)
    if applied is not None:
        document["samples_applied"] = applied
    document["tables"] = tables
    return document


def _merge_input(document: Mapping) -> dict:
    if not isinstance(document, Mapping) or document.get("doc_format") != DOC_FORMAT:
        raise ValueError(
            f"merge_table_cards expects {DOC_FORMAT} documents; got "
            f"{(document or {}).get('doc_format')!r}"
        )
    return dict(document)


def _source(document: Mapping, index: int) -> _Source:
    """What a source document is called on the evidence it contributes.

    The walked root is the label, because that is the one name the document itself
    carries and the one a reader can walk again. A document written without a root gets
    a positional stand-in rather than an empty string: unattributed evidence is the
    single thing this merge exists to prevent.
    """
    corpus = document.get("corpus") or {}
    label = str(corpus.get("artifact_root") or f"corpus:{index + 1}")
    return _Source(label, int(corpus.get("task_count") or 0), document.get(MERGED_FROM_KEY))


def _merged_from(sources: Sequence[_Source]) -> list[dict]:
    """One flat entry per original corpus, in the order the caller named them.

    A source that was itself merged contributes its own list rather than itself, so
    merging in three steps and merging in one publish the same provenance.
    """
    entries: list[dict] = []
    for source in sources:
        listed = source.merged_from or [
            {"corpus": source.label, "task_count": source.task_count}
        ]
        entries.extend(entry for entry in listed if entry not in entries)
    return entries


def _merged_corpus(
    sources: Sequence[_Source], documents: Sequence[Mapping], merged_from: Sequence[dict]
) -> dict:
    """The merged corpus block: no single root, every task's digest still reachable.

    ``artifact_root`` is null because there is no one tree to walk again -- ``merged_from``
    names them all. The digests are qualified with the corpus they came from, because two
    batches may hold a task of the same name at two different revisions and silently
    keeping one of them would be a lie about what was read.
    """
    digests: dict[str, str] = {}
    for source, document in zip(sources, documents):
        carried = (document.get("corpus") or {}).get("lineage_digests") or {}
        for task, digest in carried.items():
            key = str(task) if source.merged_from else f"{source.label}/{task}"
            digests.setdefault(key, digest)
    return {
        "artifact_root": None,
        "task_count": sum(int(entry["task_count"]) for entry in merged_from),
        "lineage_digests": {key: digests[key] for key in sorted(digests)},
    }


def _merged_samples_applied(
    documents: Sequence[Mapping], tables: Sequence[Mapping]
) -> dict | None:
    """The samples reports folded into one, or None when no document carried one.

    ``columns_sampled`` is counted off the merged cards rather than added up, for the
    same reason ``coverage`` is recomputed: one column with values in two documents is
    one sampled column, and the report may not say otherwise.
    """
    reports = [
        document["samples_applied"]
        for document in documents
        if "samples_applied" in document
    ]
    if not reports:
        return None
    return {
        "sources": _union(report.get("sources") or [] for report in reports),
        "columns_sampled": sum(
            card["coverage"].get("columns_sampled") or 0 for card in tables
        ),
        "unmatched": sorted(_union(report.get("unmatched") or [] for report in reports)),
    }


def _union(lists: Iterable[Sequence]) -> list:
    """Every value, first appearance first -- the one order a merge can defend."""
    found: list = []
    for values in lists:
        found.extend(value for value in values if value not in found)
    return found


def _merged_tables(members: Sequence[tuple[str, Mapping]]) -> list[dict]:
    spellings = [
        name
        for _label, card in members
        for name in [str(card.get("table")), *(card.get("aliases") or [])]
    ]
    grouped, ambiguous = _group_spellings(spellings)
    groups = {_primary_name(group): group for group in grouped}
    return [
        _merged_card(
            primary,
            groups[primary],
            members,
            _bare_name_candidates(primary, groups) if primary in ambiguous else (),
        )
        for primary in sorted(groups)
    ]


def _merged_card(
    primary: str,
    spellings: Sequence[str],
    members: Sequence[tuple[str, Mapping]],
    bare_name_candidates: Sequence[str] = (),
) -> dict:
    group = set(spellings)
    cards = [pair for pair in members if str(pair[1].get("table")) in group]
    produced_by = _merged_entries(cards, "produced_by")
    consumed_by = _merged_entries(cards, "consumed_by")
    columns = _merged_columns(cards)
    comment = _first_fact(cards, "comment")
    card = {
        "table": primary,
        "aliases": [name for name in spellings if name != primary],
        "comment": comment,
        **{name: _first_fact(cards, name) for name in ("domain", "project", "owner", "layer")},
        "kind": str(cards[0][1].get("kind") or TABLE_KIND_PHYSICAL),
        "produced_by": produced_by,
        "consumed_by": consumed_by,
        "columns": columns,
        "coverage": _coverage(
            comment,
            columns,
            produced_by,
            consumed_by,
            _first_coverage(cards, "columns_declared"),
            any("columns_sampled" in (item.get("coverage") or {}) for _label, item in cards),
        ),
        "findings": _findings(produced_by, consumed_by, bare_name_candidates),
    }
    return {key: card[key] for key in TABLE_KEY_ORDER}


def _first_fact(cards: Sequence[tuple[str, Mapping]], key: str):
    """First non-null across the documents, in the order the caller merged them."""
    return next((card[key] for _label, card in cards if card.get(key) is not None), None)


def _first_coverage(cards: Sequence[tuple[str, Mapping]], key: str):
    return next(
        (
            (card.get("coverage") or {})[key]
            for _label, card in cards
            if (card.get("coverage") or {}).get(key) is not None
        ),
        None,
    )


def _merged_entries(cards: Sequence[tuple[str, Mapping]], key: str) -> list[dict]:
    """``produced_by`` / ``consumed_by`` of every document, one entry per statement.

    The identity of an entry is ``(task, statement_id, corpus)``: one task read twice in
    one corpus is one reader, and the same task name in two corpora is two -- they are
    two walks of two trees, and nothing here may assume they are the same code.
    """
    entries: dict[tuple[str, str, str], dict] = {}
    for label, card in cards:
        for entry in card.get(key) or []:
            stamped = _stamped(entry, label)
            entries.setdefault(
                (
                    str(stamped["task"]),
                    str(stamped["statement_id"]),
                    str(stamped["corpus"]),
                ),
                stamped,
            )
    return [entries[identity] for identity in sorted(entries)]


def _stamped(entry: Mapping, label: str) -> dict:
    """The entry with its corpus named, right after the statement it belongs to."""
    if entry.get("corpus"):
        return dict(entry)
    return _insert_after(dict(entry), "statement_id", "corpus", label)


def _merged_columns(cards: Sequence[tuple[str, Mapping]]) -> list[dict]:
    """The union of every document's columns, in the order the first one published.

    The first document's order is the declared order of whichever catalog answered for
    the table; a column only a later document knows about is appended rather than sorted
    in, because no document ever said where it belongs.
    """
    columns: dict[str, dict] = {}
    for _label, card in cards:
        for column in card.get("columns") or []:
            entry = columns.setdefault(str(column["name"]), _blank_column(column["name"]))
            if column.get("used_in_corpus", True):
                entry["used_in_corpus"] = True
            for key in ("type", "comment", "produced_summary"):
                _fill(entry, key, column.get(key))
            for usage, count in (column.get("consumer_usage_counts") or {}).items():
                entry["consumer_usage_counts"][usage] += int(count)
            _merge_samples(entry, column.get("samples"))
    return [_merged_column(entry) for entry in columns.values()]


def _merge_samples(entry: dict, values) -> None:
    """Union the exported values, capped at the widest top-N any document published.

    A merge cannot re-rank by frequency -- a card keeps the values, never the counts --
    so the union keeps first-seen order and stops at the limit the corpora themselves
    ran under, rather than inventing a wider column than either of them published.
    """
    if not values:
        return
    merged = entry.setdefault("samples", [])
    entry["samples_top"] = max(entry.get("samples_top", 0), len(values))
    merged.extend(value for value in values if value not in merged)


def _merged_column(entry: dict) -> dict:
    column = _ordered_column(entry)
    if entry.get("samples"):
        column["samples"] = entry["samples"][: entry["samples_top"]]
    return column


# ------------------------------------------------------------------------ grain wording


def grain_text(producer: dict, *, name_producer: bool = False) -> str:
    """One structural sentence for "what does a row of this table represent".

    WI-2.8 D6. On an input's card the sentence sits in a column where the other answer
    is 「⚠ 本语料内无生产任务」, and a bare 「未知」 there reads as a missing value rather
    than as a finding. ``name_producer`` says the upstream task out loud, with the reason
    its own grain walk stopped, so "no producer" and "a producer that could not tell"
    are two different sentences.
    """
    grain = producer.get("grain") or {}
    basis = str(grain.get("basis") or "unknown")
    if basis == BASIS_UNKNOWN and name_producer:
        parts = [_undecided_grain_text(producer, grain)]
    else:
        parts = [GRAIN_BASIS_TEXT.get(basis, basis)]
    keys = [str(key) for key in grain.get("keys") or []]
    if keys:
        parts.append(f"逻辑键 {'、'.join(keys)}")
    candidate = [str(key) for key in producer.get("candidate_keys") or []]
    parts.append(f"目标表候选键 {'、'.join(candidate)}" if candidate else "目标表无可证明的键")
    parts.append(f"键置信 {producer.get('key_confidence') or UNKNOWN_TEXT}")
    return "；".join(parts)


def _undecided_grain_text(producer: dict, grain: dict) -> str:
    """"生产任务 X 未能判定粒度（<the walk's own reason>）"."""
    evidence = [str(item) for item in grain.get("evidence") or [] if str(item)]
    reason = evidence[0] if evidence else UNDECIDED_GRAIN_REASON
    return f"生产任务 {producer.get('task')} 未能判定粒度（{reason}）"


# -------------------------------------------------------------------- describe support


def apply_table_cards(profile: dict, cards: dict | None) -> dict:
    """Fold a corpus's *narrative* into one task's semantic profile.

    Returns the profile unchanged when no corpus was supplied, so ``describe`` without
    ``--tables`` writes exactly the document it wrote before this module existed.

    Three keys and no inference: ``inputs[].card``, ``task.downstream_consumers`` and the
    card counts under ``confidence.metadata_coverage``. The one *decision* a corpus
    changes -- a JOIN onto a physical table that some other task proved unique (WI-2.8
    D2) -- belongs to ``build_semantic_profile(..., table_cards=...)``, which is also
    where everything derived from the shape can see it.
    """
    if not cards:
        return profile
    index = _card_index(cards)
    if profile.get("artifact_kind") == TASK_PROFILE_ARTIFACT_KIND:
        return {
            key: [_apply_statement(item, index) for item in value]
            if key == "statements"
            else value
            for key, value in profile.items()
        }
    return _apply_statement(profile, index)


def _card_index(cards: dict) -> list[dict]:
    return list(cards.get("tables") or [])


def _lookup(index: Sequence[dict], table: str) -> dict | None:
    for card in index:
        if any(same_table(table, name) for name in [card["table"], *card["aliases"]]):
            return card
    return None


def _apply_statement(profile: dict, index: Sequence[dict]) -> dict:
    inputs = [_apply_input(item, index) for item in profile.get("inputs") or []]
    consumers = _downstream_consumers(profile, index)
    applied = dict(profile)
    applied["inputs"] = inputs
    applied["task"] = _insert_after(
        dict(profile.get("task") or {}), "target_table_owner", "downstream_consumers", consumers
    )
    applied["confidence"] = _with_card_counts(profile.get("confidence"), inputs, consumers)
    return applied


def _apply_input(item: dict, index: Sequence[dict]) -> dict:
    card = _lookup(index, str(item.get("table") or ""))
    producers = (card or {}).get("produced_by") or []
    value = None
    if producers:
        producer = producers[0]
        value = {
            "produced_by_task": producer["task"],
            "grain_text": grain_text(producer, name_producer=True),
            "candidate_keys": list(producer["candidate_keys"]),
            "key_confidence": producer["key_confidence"],
            "comment": card.get("comment"),
            "refresh": producer["refresh"],
        }
        value = {key: value[key] for key in CARD_KEY_ORDER}
    return _insert_after(dict(item), "layer", "card", value)


def _downstream_consumers(profile: dict, index: Sequence[dict]) -> list[dict]:
    """Who reads the table this statement writes -- this statement itself excluded."""
    target = _target_of(profile)
    card = _lookup(index, target) if target else None
    task = str((profile.get("task") or {}).get("task_name") or "")
    statement_id = str(profile.get("statement_id") or "")
    return [
        {
            "task": consumer["task"],
            "role_in_task": consumer["role_in_task"],
            "columns": [column["name"] for column in consumer["columns"]],
        }
        for consumer in (card or {}).get("consumed_by") or []
        if (consumer["task"], consumer["statement_id"]) != (task, statement_id)
    ]


def _with_card_counts(
    confidence: dict | None, inputs: Sequence[dict], consumers: Sequence[dict]
) -> dict:
    confidence = dict(confidence or {})
    coverage = dict(confidence.get("metadata_coverage") or {})
    coverage["table_cards"] = {
        "inputs_with_card": sum(1 for item in inputs if item.get("card")),
        "inputs_total": len(inputs),
        "consumers": len(consumers),
    }
    confidence["metadata_coverage"] = coverage
    return confidence


def _insert_after(entry: dict, anchor: str, key: str, value) -> dict:
    """Place a new key immediately after ``anchor``, or last when there is no anchor."""
    if key in entry or anchor not in entry:
        entry[key] = value
        return entry
    rebuilt: dict = {}
    for name, existing in entry.items():
        rebuilt[name] = existing
        if name == anchor:
            rebuilt[key] = value
    return rebuilt


# --------------------------------------------------------------------------- markdown


def render_table_index_markdown(cards: dict) -> str:
    """``tables.md``: one row per table, so a reader can pick the card worth opening."""
    corpus = cards.get("corpus") or {}
    lines = [
        "---",
        f'doc_format: "{INDEX_DOC_FORMAT}"',
        f"task_count: {corpus.get('task_count')}",
        f"table_count: {len(cards.get('tables') or [])}",
        "---",
        "",
        "# 语料表卡索引",
        "",
        f"共 {corpus.get('task_count')} 个任务、{len(cards.get('tables') or [])} 张表"
        f"（会话内关系与目录写入已排除）。",
        "",
        "| 表 | 生产任务数 | 消费任务数 | 表注释 | 业务域 | 键置信 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for card in cards.get("tables") or []:
        coverage = card["coverage"]
        confidences = sorted(
            {str(item["key_confidence"]) for item in card["produced_by"]}
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(f"[`{card['table']}`](tables/{table_card_filename(card['table'])})"),
                    cell(str(coverage["producers"])),
                    cell(str(coverage["consumers"])),
                    cell("有" if coverage["table_comment"] else "无"),
                    cell(normalize_inline(card["domain"]) if card["domain"] else "—"),
                    cell("、".join(confidences) or "—"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_table_card_markdown(card: dict) -> str:
    """One table's card: six fixed sections, in the reading order of the questions."""
    lines = [
        "---",
        f'doc_format: "{CARD_DOC_FORMAT}"',
        f'table: "{card["table"]}"',
        f"producers: {card['coverage']['producers']}",
        f"consumers: {card['coverage']['consumers']}",
        "---",
        "",
        f"# 表卡 `{card['table']}`",
    ]
    sections = (
        ("1. 这张表是什么", _render_identity(card)),
        ("2. 一行代表什么", _render_grain(card)),
        ("3. 字段", _render_columns(card)),
        ("4. 谁生产", _render_producers(card)),
        ("5. 谁消费", _render_consumers(card)),
        ("6. 治理线索", _render_findings(card)),
    )
    for title, body in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(body)
    lines.append("")
    return "\n".join(lines)


def _tagged(text: str, tag: str, evidence: Sequence[str] = ()) -> str:
    ids = [str(item) for item in evidence if item]
    return f"{text}（{tag}；证据 {', '.join(ids)}）" if ids else f"{text}（{tag}）"


def _render_identity(card: dict) -> list[str]:
    comment = card["comment"]
    lines = [
        _tagged(f"- 表注释：{normalize_inline(comment) if comment else UNKNOWN_TEXT}", TAG_METADATA_FACT),
    ]
    placement = _placement_text(card)
    if placement:
        lines.append(_tagged(f"- 业务归属：{placement}", TAG_METADATA_FACT))
    lines += [
        _tagged(f"- 别名写法：{'、'.join(f'`{name}`' for name in card['aliases']) or '无'}", TAG_SQL_FACT),
        _tagged(
            f"- 语料内：{card['coverage']['producers']} 个生产语句、"
            f"{card['coverage']['consumers']} 个消费语句",
            TAG_SQL_FACT,
        ),
    ]
    if card["coverage"].get("columns_declared"):
        # Absent rather than "用到 4/4" when nothing declared the table: the denominator
        # would then be the corpus's own reading, and the line would prove itself.
        # The denominator is the card's own column list rather than the declared count,
        # because a corpus that reads a column the metadata never declared would
        # otherwise publish "用到 3/2" -- a stale catalog is a real state, and the line
        # has to stay readable in it.
        lines.append(
            _tagged(
                f"- 本语料用到 {card['coverage']['columns_used']}/{len(card['columns'])} 个字段",
                TAG_METADATA_FACT,
            )
        )
    for producer in card["produced_by"]:
        if not producer["header_comments"]:
            continue
        lines.extend(["", f"生产任务 `{producer['task']}` 的语句头注释（{TAG_SQL_COMMENT}）：", ""])
        lines.extend(f"> {normalize_inline(comment)}" for comment in producer["header_comments"])
    return lines


_PLACEMENT_LABELS = (("domain", "业务域"), ("project", "项目"), ("owner", "负责人"), ("layer", "分层"))


def _placement_text(card: dict) -> str:
    """The stated business placement, or "" so the line disappears rather than reading 未知."""
    return "；".join(
        f"{label} {normalize_inline(str(card[key]))}"
        for key, label in _PLACEMENT_LABELS
        if card.get(key)
    )


def _render_grain(card: dict) -> list[str]:
    if not card["produced_by"]:
        return ["- 本语料内没有生产任务，无法证明一行代表什么。（结构推断）"]
    conflict = any(
        finding["kind"] == FINDING_PRODUCER_KEY_CONFLICT for finding in card["findings"]
    )
    lines = []
    for producer in card["produced_by"]:
        marker = "⚠ 口径冲突：" if conflict else ""
        lines.append(
            _tagged(
                f"- {marker}`{producer['task']}` / `{producer['statement_id']}`："
                f"{grain_text(producer)}",
                TAG_STRUCTURAL_INFERENCE,
                [producer["statement_id"]],
            )
        )
    return lines


#: Above this many untouched columns the table stops being readable, so they move below
#: the ones the corpus actually used instead of hiding them among the rows that matter.
UNUSED_COLUMN_TAIL = 20


def _render_columns(card: dict) -> list[str]:
    if not card["columns"]:
        return ["- 无可证明的字段。（SQL事实）"]
    # `.get(..., True)` because a card may have been loaded from a `tables.json` written
    # before `used_in_corpus` existed; an older card simply keeps its old rendering.
    unused = [
        column for column in card["columns"] if not column.get("used_in_corpus", True)
    ]
    lines = [
        f"共 {len(card['columns'])} 列"
        + (f"，用到 {card['coverage']['columns_used']} 列" if unused else "")
        + f"；注释覆盖 {card['coverage']['column_comment_ratio']}（元数据事实）。",
        "",
    ]
    # A6: the 样例值 column appears only when this card has values for some column, so a
    # corpus built without --samples renders the table it always rendered. The decision
    # is taken once per card rather than per sub-table: two column tables of different
    # widths in one section would read as two different documents.
    sampled = any(column.get("samples") for column in card["columns"])
    if len(unused) <= UNUSED_COLUMN_TAIL:
        return lines + _column_table(card["columns"], sampled)
    used = [column for column in card["columns"] if column.get("used_in_corpus", True)]
    lines.extend(_column_table(used, sampled))
    lines.extend(
        [
            "",
            f"本语料没有读写下列 {len(unused)} 个字段，按元数据声明顺序列出（元数据事实）：",
            "",
        ]
    )
    return lines + _column_table(unused, sampled)


def _column_table(columns: Sequence[dict], sampled: bool = False) -> list[str]:
    head = ["列", "类型", "注释"] + (["样例值"] if sampled else [])
    lines = [
        "| " + " | ".join([*head, "生产侧语义（结构推断）", "消费侧用法（SQL事实）"]) + " |",
        "| " + " | ".join(["---"] * (len(head) + 2)) + " |",
    ]
    for column in columns:
        usages = "、".join(
            f"{USAGE_TEXT.get(usage, usage)} ×{count}"
            for usage, count in column["consumer_usage_counts"].items()
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(f"`{column['name']}`"),
                    cell(column["type"] or UNKNOWN_TEXT),
                    cell(normalize_inline(column["comment"]) if column["comment"] else UNKNOWN_TEXT),
                    *([cell(_samples_text(column))] if sampled else []),
                    cell(normalize_inline(column["produced_summary"]) if column["produced_summary"] else "—"),
                    cell(usages or "—"),
                ]
            )
            + " |"
        )
    return lines


def _samples_text(column: Mapping) -> str:
    """The card's sample values, each in the quoted code span a value is rendered in.

    ``'a'``、``'b'``、``'c'``: the quotes say "this is a value, as the export spelled
    it", and the code span survives whatever punctuation the value carries -- the same
    rendering glossary.md gives the literals it read out of the SQL.
    """
    values = column.get("samples") or []
    return "、".join(expr_span(f"'{value}'") for value in values) or "—"


def _corpus_labelled(entries: Sequence[Mapping]) -> bool:
    """P7: a merged card names the corpus of every entry; a built one has none to name."""
    return any(entry.get("corpus") for entry in entries)


def _head(labelled: bool, *names: str) -> list[str]:
    head = (["语料"] if labelled else []) + list(names)
    return [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join(["---"] * len(head)) + " |",
    ]


def _corpus_cell(entry: Mapping, labelled: bool) -> list[str]:
    return [cell(f"`{entry['corpus']}`" if entry.get("corpus") else "—")] if labelled else []


def _render_producers(card: dict) -> list[str]:
    if not card["produced_by"]:
        return ["- 本语料内没有任务写这张表。（SQL事实）"]
    labelled = _corpus_labelled(card["produced_by"])
    lines = _head(labelled, "任务", "语句", "写入方式", "分区", "更新频率")
    for producer in card["produced_by"]:
        partition = producer["partition"]
        columns = "、".join(partition["columns"]) or "无分区"
        refresh = producer["refresh"] or {}
        cadence = refresh.get("cycle") or refresh.get("cron") or UNKNOWN_TEXT
        lines.append(
            "| "
            + " | ".join(
                [
                    *_corpus_cell(producer, labelled),
                    cell(f"`{producer['task']}`"),
                    cell(f"`{producer['statement_id']}`"),
                    cell(str(producer["stmt_kind"] or UNKNOWN_TEXT)),
                    cell(columns + (f"（{partition['mode']}）" if partition["mode"] else "")),
                    cell(str(cadence)),
                ]
            )
            + " |"
        )
    return lines


def _render_consumers(card: dict) -> list[str]:
    if not card["consumed_by"]:
        return ["- 本语料内没有任务读这张表。（SQL事实）"]
    labelled = _corpus_labelled(card["consumed_by"])
    lines = _head(labelled, "任务", "语句", "角色", "用到的列", "怎么用")
    for consumer in card["consumed_by"]:
        role = consumer["role_in_task"]
        used = "、".join(f"`{column['name']}`" for column in consumer["columns"])
        how = "、".join(
            sorted(
                {
                    USAGE_TEXT.get(usage, usage)
                    for column in consumer["columns"]
                    for usage in column["usages"]
                }
            )
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    *_corpus_cell(consumer, labelled),
                    cell(f"`{consumer['task']}`"),
                    cell(f"`{consumer['statement_id']}`"),
                    cell(f"{ROLE_TEXT.get(str(role), UNKNOWN_TEXT)}（{role}）" if role else UNKNOWN_TEXT),
                    cell(used or "—"),
                    cell(how or "—"),
                ]
            )
            + " |"
        )
    return lines


def _render_findings(card: dict) -> list[str]:
    if not card["findings"]:
        return ["- 无。（SQL事实）"]
    return [
        _tagged(
            f"- {finding['kind']}：{normalize_inline(finding['text'])}",
            TAG_SQL_FACT,
            [f"{item['task']}/{item['statement_id']}" for item in finding["evidence"]],
        )
        for finding in card["findings"]
    ]
