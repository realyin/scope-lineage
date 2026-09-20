"""Build the deterministic semantic profile (``semantic-json/1``) from one contract document.

This is a derived VIEW of the versioned contract, a sibling of ``mapping_markdown``: it
consumes contract document dicts only (never scope-internal dataclasses), so a document
read back from disk and one produced in memory profile identically. Every value in the
profile is either copied from the contract, counted from it, or restated in Chinese by
``semantic_text`` using structural words only. Nothing here names a business concept,
guesses from a column name, or fills a missing comment with a plausible one -- a fact the
contract does not carry is published as ``null``.

It implements rules R1-R8 of dev-notes/plans/task-semantic-description-plan.md: the
``task`` / ``inputs`` / ``rules`` / ``fields`` / ``confidence`` blocks (R1, R4, R5, R7,
R8), the ``output_shape`` block (R2 shape, R3 grain / candidate keys / per-JOIN fan-out
risk) and the ``stages`` block (per-scope actions, including the R6 window intents).

R7's driving role and R1's summary sentence are answered by a walk of their own
(``_driving_branches``, B2), not by R3's grain walk: a ``LATERAL VIEW`` makes the row
*count* unprovable while leaving the row *source* plain, and reading the source off the
grain's stop published a statement's real main table as ``enrich``. Where that same stop
is a row-multiplying step whose upstream grain is decided, B3 publishes the row shape it
implies as ``grain.candidate``, at ``confidence: hypothesis`` and beside -- never
instead of -- the ``unknown`` verdict.

**Two deliberate departures from the plan text, both in the conservative direction.**

1. *Fan-out safety compares the other way round.* The plan writes "right-side GROUP BY
   keys ⊇ join keys → safe". That is inverted: grouping by ``(a, b)`` and joining on
   ``a`` alone leaves many right rows per left row -- the classic fan-out -- while
   grouping by ``a`` and joining on ``(a, b)`` provably cannot fan out, because the
   extra key can only filter. This module therefore grants ``safe`` when the right
   side's proven unique key set is a **subset** of the join keys, for both the GROUP BY
   form and the ``row_number() = 1`` form. A wrongly granted ``safe`` is the one failure
   the plan explicitly asks to avoid, so the provable direction wins over the wording.

2. *A JOIN's extra ON condition does not publish join-key fields.* When the condition
   tests a generated column (``status.row_num = 1``), the contract answers with that
   column's own physical inputs -- the window's partition and order columns. Listing
   them under ``rules[].fields`` would state that ``event_time`` is a join key, which it
   is not. They are published under ``rules[].extra_condition_fields`` instead, each
   flagged ``via_generated_column``, so the fact survives without the false claim.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Mapping, Sequence

from . import glossary_values, semantic_text
from .diagnostics_view import all_warnings, fact_gaps_for, warnings_for
from .mapping_markdown import lineage_document_digest
from .sequences import unique_ordered


DOC_FORMAT = "semantic-json/1"

SUPPORTED_SCHEMA_VERSION = "1.0"
TASK_SCHEMA_VERSION = "2.0"
TASK_ARTIFACT_KIND = "task_lineage"
TASK_PROFILE_ARTIFACT_KIND = "task_semantic"

# The statement profile's top-level keys, in order. `statement_id` is omitted when the
# source document has none (an AST handed in directly has no script position).
STATEMENT_PROFILE_KEYS = (
    "doc_format",
    "schema_version",
    "statement_id",
    "lineage_digest",
    "task",
    "inputs",
    "output_shape",
    "stages",
    "rules",
    "fields",
    "confidence",
)

TASK_PROFILE_KEYS = (
    "doc_format",
    "artifact_kind",
    "task_id",
    "lineage_digest",
    "produced_tables",
    "warning_counts",
    "statements",
)

# WI-1f: re-exported so a consumer reading the profile has the join-type vocabulary in
# the module that publishes it, without importing the wording module.
JOIN_NULL_SEMANTICS = semantic_text.JOIN_NULL_SEMANTICS

TAG_SQL_FACT = "SQL事实"
TAG_SQL_AND_METADATA_FACT = "SQL事实+元数据事实"
TAG_STRUCTURAL_INFERENCE = "结构推断"
# WI-2.2. A comment is the author's own words about the SQL, which is neither a fact the
# SQL states nor an inference this view drew: it gets a label of its own so a reader can
# tell "the author wrote this" from "the statement does this".
TAG_SQL_COMMENT = "SQL注释"

# WI-2.2: where `metric_spec.refresh` came from. One value today, named rather than
# implied, because a cadence read off a schedule string and a cadence a person typed are
# not the same evidence and the card has to be able to say which it holds.
REFRESH_SOURCE_TASK_META = "task_meta"

# R7, most specific first: a table with several roles reports the first of these.
# B2 adds `filter_partner` between the two: an INNER JOIN's right side on the driving
# path is more than enrichment (an unmatched driving row is dropped by it) and less than
# driving (the rows are not counted from it), and calling it `enrich` told a reader the
# one thing about it that is false.
ROLE_PRIORITY = (
    "driving",
    "merge_source",
    "aggregate_source",
    "dedup_source",
    "union_branch",
    "filter_partner",
    "enrich",
    "rowset_only",
)

# R2's vocabulary. `unknown` is a real answer, not a failure: a MERGE has no ordinary
# ROOT projection, and a document without a ROOT scope proves nothing about its shape.
SHAPE_AGGREGATED = "aggregated"
SHAPE_DEDUPLICATED = "deduplicated"
SHAPE_UNION_MERGE = "union_merge"
SHAPE_ENRICHED = "enriched_projection"
SHAPE_FILTERED = "filtered_projection"
SHAPE_UNKNOWN = "unknown"

OUTPUT_SHAPES = (
    SHAPE_AGGREGATED,
    SHAPE_DEDUPLICATED,
    SHAPE_UNION_MERGE,
    SHAPE_ENRICHED,
    SHAPE_FILTERED,
    SHAPE_UNKNOWN,
)

# The two shapes whose row count follows one driving table rather than a key set.
_PROJECTION_SHAPES = (SHAPE_ENRICHED, SHAPE_FILTERED)

# P3: the two shapes that fold the rows they read, and the word R1's sentence uses for
# the fold. Every other shape passes its rows through and says only where they came from.
_ROW_FOLD_VERBS = {SHAPE_AGGREGATED: "汇总", SHAPE_DEDUPLICATED: "去重"}

# How many grain keys R1's opening clause names before it counts the rest instead.
_SUMMARY_KEY_LIMIT = 3

# The two paths a metric card reads, and the order it reads them in. The grain path
# decides which rows are counted; the argument path is where the counted value was read
# from, which for a metric fed by a joined-in scope is a different place with different
# filters on it. A scope on both is published once, as grain. WI-2.1c item 5 gives the
# same two names to the JOINs a fan-out verdict is asked about, for the same reason: a
# join that duplicates the rows a metric's *argument* comes from inflates that number
# without touching the output's row count.
METRIC_PATH_GRAIN = "grain"
METRIC_PATH_ARGUMENT = "argument"

METRIC_PATHS = (METRIC_PATH_GRAIN, METRIC_PATH_ARGUMENT)

# The third path a fan-out verdict is asked about, and the one a metric card does not
# read. Once a metric is anchored to its own aggregating scope, the grain path starts at
# that anchor and follows driving inputs only -- so a JOIN sitting *under* the
# aggregation on a non-driving branch (a lookup the anchor joins in, and the joins
# inside it) was judged by nobody, although duplicating its rows inflates every number
# the anchor aggregates. The anchor path is that scope's whole input subtree, minus what
# the other two paths already walked. It is not a metric-card vocabulary: the card's
# conditions are still read along ``METRIC_PATHS`` alone, because a condition on a
# non-driving branch is not a condition on the counted rows.
METRIC_PATH_ANCHOR = "anchor"

FAN_OUT_PATHS = (METRIC_PATH_GRAIN, METRIC_PATH_ARGUMENT, METRIC_PATH_ANCHOR)

# R6, for the window functions whose intent does not depend on a downstream `= 1`.
WINDOW_INTENT_BY_FUNCTION = {
    "first_value": "pick_first_in_group",
    "last_value": "pick_last_in_group",
    "lag": "adjacent_row_offset",
    "lead": "adjacent_row_offset",
    "sum": "running_aggregate",
    "count": "running_aggregate",
    "avg": "running_aggregate",
    "min": "running_aggregate",
    "max": "running_aggregate",
}

_ROOT = "ROOT"

_ACTION_KEY_ORDER = (
    "type",
    "intent",
    "column",
    "text",
    "expression",
    "fields",
    "sql_comments",
    "consumed_by",
    "evidence",
    "tag",
)

# A scope's actions are listed in the order SQL applies them, not in logic_block_id
# order: a reader asking "what does this stage do" follows the rows, and the rows are
# joined, filtered, grouped, having-filtered, windowed, deduplicated, merged, exploded,
# and only then labelled by a CASE over the result.
ACTION_TYPE_ORDER = (
    "join",
    "filter",
    "aggregate",
    "having",
    "window",
    "distinct",
    "union",
    "lateral_view",
    "derive",
    "case_when",
)

# WI-1g item B. The output transform that makes a column a plain expression derivation.
# DIRECT / CONSTANT / CONDITIONAL / AGGREGATE / WINDOW / UNION all have an action of
# their own already, so only this one was invisible in the stage view.
_DERIVE_TRANSFORM = "EXPRESSION"

_ACTION_TYPE_RANK = {name: index for index, name in enumerate(ACTION_TYPE_ORDER)}

_STAGE_KEY_ORDER = (
    "scope_id",
    "name",
    "kind",
    "role",
    "direct_inputs",
    "direct_source_tables",
    "upstream_physical_tables",
    "actions",
    "outputs",
    "output_count",
    "pattern_signature",
)

# Column usage vocabulary, in the order a column's usages are listed.
USAGE_ORDER = (
    "filter",
    "partition_filter",
    "join_key",
    "group_by",
    "window_partition",
    "window_order",
    "output",
)

# Keys a table-level metadata blob may use for its comment, most specific first. Nothing
# else is read as one. `table_name_cn` leads because a business metadata export puts the
# table's readable name there and a longer description in `table_desc`; a reader scanning a
# table of inputs wants the name.
TABLE_COMMENT_KEYS = ("table_name_cn", "table_desc", "comment", "table_comment")

# WI-2.6. What a comment says about itself: a fact the warehouse's metadata carried, or
# an answer a human confirmed and wrote back through a `metadata-patch/1` file. The two
# spellings are the contract's, restated here rather than imported -- a derived view
# reads the published document, never the loader that wrote it.
COMMENT_SOURCE_METADATA = "metadata"
COMMENT_SOURCE_PATCH = "patch"
TABLE_PATCH_MARKER = "patch_applied"

# The other table-level facts this view republishes, each with the keys it may arrive
# under. They are metadata facts, copied and never inferred.
TABLE_FACT_KEYS = {
    "domain": ("domain",),
    "project": ("project",),
    "owner": ("owner",),
    "layer": ("table_label_layer",),
}

_DIRECTORY_TARGET_PREFIX = "directory:"

# WHERE and HAVING are separate logic types in the contract; both carry a
# `filter_predicate_detail`, and `predicate_type` inside it says which one it is.
_PREDICATE_LOGIC_TYPES = ("filter", "having")

_TEMPORAL_TYPE_PREFIXES = ("timestamp", "date", "datetime")

# R3's grain vocabulary. The walk answers with exactly one of these, and ``unknown`` is
# a real answer whose reason says which layer could not be crossed.
BASIS_GROUP_BY = "group_by"
BASIS_DISTINCT = "distinct"
BASIS_WINDOW_PARTITION = "window_partition"
BASIS_DRIVING_TABLE_ROWS = "driving_table_rows"
# B10. An aggregate over an empty grouping set -- `SELECT COUNT(1) FROM t` -- returns
# exactly one row for the whole relation. Published as `group_by` with no keys it read
# as "could not decide", which is the opposite of what it is: the strongest uniqueness
# statement this view can make. A UNION ALL of such aggregates is not one row, and the
# union blocker that already stops the walk keeps it out.
BASIS_SINGLE_ROW = "single_row"
BASIS_UNKNOWN = "unknown"

# B3. The candidate's own basis and confidence, deliberately outside `GRAIN_BASES`: a
# candidate never becomes `grain.basis`, which stays `unknown`, and `hypothesis` is
# weaker than every other `confidence` this view publishes -- it is the row shape the
# structure *suggests* after a row-multiplying step, not one it proves.
BASIS_CANDIDATE = "candidate"
CONFIDENCE_HYPOTHESIS = "hypothesis"

GRAIN_BASES = (
    BASIS_GROUP_BY,
    BASIS_DISTINCT,
    BASIS_WINDOW_PARTITION,
    BASIS_DRIVING_TABLE_ROWS,
    BASIS_SINGLE_ROW,
    BASIS_UNKNOWN,
)

# The three bases whose key set is proven unique by the operation itself. `single_row`
# is not one of them: it is unique with an *empty* key set, which every rule that walks
# a key list has to answer separately rather than by looping over nothing.
_PROVEN_BASES = (BASIS_GROUP_BY, BASIS_DISTINCT, BASIS_WINDOW_PARTITION)

# B9. The two right-hand sides that pin a column to one value for a whole scope: a
# scalar literal, and the `${...}` a scheduler substitutes (one value per run). An `IN`
# list, a `BETWEEN`, a `<>`, a `LIKE` and a comparison with another column all leave the
# column free to vary, and `semantic_text.equality_conjunct` already tells them apart.
_PINNING_VALUE_KINDS = (
    semantic_text.VALUE_KIND_LITERAL,
    semantic_text.VALUE_KIND_PARAMETER,
)

# A logical key that *is* a column reference, rather than an expression that reads one.
# `GROUP BY CASE WHEN dt = '20260815' THEN ... END` reads a pinned column without being
# pinned by it, so only a bare reference can be dropped from a key set.
_BARE_COLUMN = re.compile(r"[`\"]?\w+[`\"]?(?:\.[`\"]?\w+[`\"]?){0,2}")

# How many scopes the grain walk may cross. A contract this deep is pathological; the
# limit exists so a malformed document cannot make the walk run away, and it is reported
# as an honest ``unknown`` rather than raising.
GRAIN_DEPTH_LIMIT = 32

# How many pierced columns a fan-out sentence names before it just counts them. The note
# is an aside on a verdict decided elsewhere (WI-2.1d item 1), so it stays short enough
# to read past: one logical key over a twelve-branch UNION pierces to twelve columns.
_PHYSICAL_NOTE_LIMIT = 4

# How far the published key set can be trusted, beside the keys themselves.
KEY_CONFIDENCE_PROVEN = "proven"
# The keys are proven unique and the *target* is not: at least one of them never reaches
# a target column, so the columns that were written cannot identify a row. WI-1e treats
# this as a governance finding rather than as a weaker "candidate".
KEY_CONFIDENCE_PROVEN_UNEXPOSED = "proven_unexposed"
KEY_CONFIDENCE_CANDIDATE = "candidate"
KEY_CONFIDENCE_NONE = "none"

KEY_CONFIDENCES = (
    KEY_CONFIDENCE_PROVEN,
    KEY_CONFIDENCE_PROVEN_UNEXPOSED,
    KEY_CONFIDENCE_CANDIDATE,
    KEY_CONFIDENCE_NONE,
)

# WI-2.8 D2. A fan-out verdict a table card decided rather than this statement. One
# statement can never prove a physical table unique, so the verdict stopped at "unknown"
# even while the same document's `inputs[].card` said another task had produced that very
# table one row per these very columns. `basis` names where the fact came from, and it
# appears only on a risk a card actually re-decided.
FAN_OUT_BASIS_TABLE_CARD = "table_card"

# The card confidences that may re-decide a JOIN. `proven_unexposed` is deliberately
# absent: its key list is the exposed SUBSET of a proven key set, which identifies
# nothing on its own.
_CARD_KEY_CONFIDENCES = (KEY_CONFIDENCE_PROVEN, KEY_CONFIDENCE_CANDIDATE)

# The mapping-chain step types that carry a value unchanged. Anything else -- a CASE, a
# COALESCE, a cast, an aggregate -- may map two distinct keys onto one value, so a key
# that crosses one is no longer a key of the target.
_PASS_THROUGH_STEP_TYPES = ("direct_projection", "union")

# The contract's sentinel for a bare column several inputs could own.
_AMBIGUOUS = "AMBIGUOUS"


# B2. How the summary counts explodes. Chinese writes the first few as words, and "1 次
# LATERAL VIEW 展开" in a sentence otherwise made of words reads like a defect.
_EXPANSION_COUNTS = {1: "一次", 2: "两次", 3: "三次"}


_SCOPE_ROLE_LABELS = (
    ("aggregate", "聚合"),
    ("dedup", "去重"),
    ("window", "窗口"),
    ("union", "合并"),
    ("join", "关联"),
    ("filter", "过滤"),
)


def build_semantic_profile(
    lineage_document: dict,
    diagnostics_document: dict | None = None,
    *,
    table_cards: Mapping | None = None,
) -> dict:
    """Build the semantic profile of one statement document or one task document.

    A 1.0 statement document profiles to a single statement profile; a 2.0 task document
    profiles to a task profile holding one statement profile per write statement, in
    ``statement_sequence`` order.

    ``table_cards`` is an optional corpus (``tables-json/1``). One question needs it:
    a JOIN onto a physical table can only end at 「物理表无主键事实」 from inside one
    statement, and a card may carry another task's proof that the table is written one
    row per the columns this ON clause names (WI-2.8 D2). It is a parameter of the build
    rather than a post-processing step because everything else the build derives from
    the shape -- a field's ``candidate_key`` role, the inferred-item counts -- has to see
    the same answer. Without it the profile is byte for byte what it was before cards
    existed.
    """
    version = lineage_document.get("schema_version")
    if (
        version == TASK_SCHEMA_VERSION
        and lineage_document.get("artifact_kind") == TASK_ARTIFACT_KIND
    ):
        return _build_task_profile(lineage_document, diagnostics_document, table_cards)
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"semantic profile builder supports schema_version "
            f"{SUPPORTED_SCHEMA_VERSION!r} statement documents and "
            f"{TASK_SCHEMA_VERSION!r} task documents; document declares {version!r}"
        )
    # A bare statement document has no task metadata to read: `task_meta` is a 2.0
    # top-level fact, and the statement it wraps cannot supply one.
    return _build_statement_profile(
        lineage_document, diagnostics_document, table_cards=table_cards
    )


# --------------------------------------------------------------------- task document


def _build_task_profile(
    task_document: dict,
    diagnostics_document: dict | None,
    table_cards: Mapping | None = None,
) -> dict:
    statement_lineage = task_document.get("statement_lineage") or {}
    ordered_ids = [
        str(statement.get("statement_id") or "")
        for statement in task_document.get("statement_sequence") or []
        if statement.get("statement_id") in statement_lineage
    ]
    # Entries no statement_sequence row points at still profile, after the ordered ones.
    seen = set(ordered_ids)
    ordered_ids.extend(sid for sid in statement_lineage if sid not in seen)

    profile = {
        "doc_format": DOC_FORMAT,
        "artifact_kind": TASK_PROFILE_ARTIFACT_KIND,
        "task_id": task_document.get("task_id"),
        "lineage_digest": lineage_document_digest(task_document),
        "produced_tables": _produced_tables(task_document),
        # WI-1f: the script's warnings live in two places (top level for script-scoped
        # ones, `statement_diagnostics` for the rest), so the wrapper carries the union
        # as one count -- a reader asking "does this task have warnings at all" must not
        # have to add up N statement profiles.
        "warning_counts": (
            _counted(
                warning.get("type") for warning in all_warnings(diagnostics_document)
            )
            if diagnostics_document is not None
            else None
        ),
        "statements": [
            _build_statement_profile(
                statement_lineage[sid],
                diagnostics_document,
                # WI-2.2: task metadata is a fact of the script, not of one statement,
                # so it is handed down rather than looked up per statement.
                task_meta=task_document.get("task_meta"),
                table_cards=table_cards,
            )
            for sid in ordered_ids
        ],
    }
    return {key: profile[key] for key in TASK_PROFILE_KEYS}


def _produced_tables(task_document: dict) -> list[str]:
    """Tables the script leaves behind: no session-scoped relations, no directory writes."""
    session_scoped = {
        str(statement.get("target_table"))
        for statement in task_document.get("statement_sequence") or []
        if statement.get("is_session_scoped_relation")
    }
    return [
        table
        for table in (task_document.get("final_table_states") or {})
        if table not in session_scoped
        and not str(table).startswith(_DIRECTORY_TARGET_PREFIX)
    ]


# ---------------------------------------------------------------- statement document


def _build_statement_profile(
    document: dict,
    diagnostics: dict | None,
    task_meta: dict | None = None,
    table_cards: Mapping | None = None,
) -> dict:
    rules = _build_rules(document)
    # WI-2.1c item 5: the metric cards are what know where a metric's *argument* was
    # read from, so the fields are built first and hand their argument paths to the
    # shape block rather than the walk being repeated there.
    context = _field_context(document, rules, task_meta)
    fields = _build_fields(document, rules, context)
    output_shape = _build_output_shape(
        document,
        context["metric_argument_scopes"],
        table_cards,
        context["metric_anchor_scopes"],
    )
    stages = _build_stages(document)
    # R5's last two roles need R3's result, so they are applied once the shape is known
    # rather than guessed from the column name inside `_structural_role`.
    _apply_key_roles(fields, output_shape)
    # WI-2.4: what this statement itself proves about each field's values. A corpus
    # glossary replaces these entries wholesale through `glossary.apply_glossary`; on
    # its own the profile still answers "which constants does this column take here",
    # with every `meaning` null because one statement cannot know one.
    values = glossary_values.aggregate_values(
        glossary_values.statement_observations(document, rules, fields)
    )
    glossary_values.apply_value_domains(fields, values, document.get("target_table"))
    profile = {
        "doc_format": DOC_FORMAT,
        "schema_version": document.get("schema_version"),
        "statement_id": document.get("statement_id"),
        "lineage_digest": lineage_document_digest(document),
        "task": _build_task_block(document, task_meta, rules, output_shape),
        "inputs": _build_inputs(document),
        "output_shape": output_shape,
        "stages": stages,
        "rules": rules,
        "fields": fields,
        "confidence": _build_confidence(
            document, diagnostics, fields, output_shape, stages, rules, values
        ),
    }
    keys = [
        key
        for key in STATEMENT_PROFILE_KEYS
        if key != "statement_id" or "statement_id" in document
    ]
    return {key: profile[key] for key in keys}


# --------------------------------------------------------------------- shared lookups


def _scopes(document: dict) -> dict:
    return document.get("scopes") or {}


def _profile_steps(document: dict) -> list[dict]:
    return (document.get("scope_profile") or {}).get("steps") or []


def _scope_order(document: dict) -> list[str]:
    """Scope ids in topological order: scope_profile's order, then the rest sorted.

    ``scope_profile`` folds union-branch scopes away, so the remainder is appended by
    name -- stable, and never silently dropped.
    """
    ordered = [
        str(step.get("scope_id"))
        for step in _profile_steps(document)
        if step.get("scope_id") in _scopes(document)
    ]
    seen = set(ordered)
    ordered.extend(sorted(sid for sid in _scopes(document) if sid not in seen))
    return ordered


def _scope_blocks(document: dict, scope_id: str) -> list[dict]:
    """One scope's logic blocks, in ``logic_block_id`` order."""
    blocks = (_scopes(document).get(scope_id) or {}).get("logic_blocks") or []
    return sorted(blocks, key=lambda block: str(block.get("logic_block_id")))


def _blocks_of_type(document: dict, scope_id: str, logic_type: str) -> list[dict]:
    return [
        block
        for block in _scope_blocks(document, scope_id)
        if str(block.get("logic_type")) == logic_type
    ]


def _block_ids(blocks: Iterable[dict]) -> list[str]:
    return [str(block.get("logic_block_id")) for block in blocks]


def _scope_of_logic_block(logic_block_id: str) -> str:
    """``logic:<scope_id>:<type>:<nnn>`` -> ``<scope_id>`` (a scope id may hold colons)."""
    parts = str(logic_block_id).split(":")
    return ":".join(parts[1:-2]) if len(parts) > 3 else ""


def _logic_blocks(document: dict) -> list[tuple[str, dict]]:
    """Every logic block as ``(scope_id, block)``, in scope order then block id."""
    blocks: list[tuple[str, dict]] = []
    for scope_id in _scope_order(document):
        scope_blocks = (_scopes(document).get(scope_id) or {}).get("logic_blocks") or []
        for block in sorted(
            scope_blocks, key=lambda item: str(item.get("logic_block_id"))
        ):
            blocks.append((scope_id, block))
    return blocks


def _input_metadata(document: dict) -> dict:
    return (document.get("related_metadata") or {}).get("input_tables") or {}


def _output_metadata(document: dict) -> dict:
    target = str(document.get("target_table") or "")
    return ((document.get("related_metadata") or {}).get("output_tables") or {}).get(
        target
    ) or {}


def _column_detail(metadata_item: dict, column: str) -> dict:
    for detail in metadata_item.get("column_details") or []:
        if str(detail.get("name")) == str(column):
            return detail
    return {}


def _input_column_comment(document: dict, table: str, column: str) -> str | None:
    detail = _column_detail(_input_metadata(document).get(str(table)) or {}, column)
    return detail.get("comment")


def _table_metadata_value(metadata_item: dict, keys: Iterable[str]) -> str | None:
    table_metadata = metadata_item.get("table_metadata") or {}
    for key in keys:
        value = table_metadata.get(key)
        if value:
            return str(value)
    return None


def _table_comment(metadata_item: dict) -> str | None:
    """The table-level comment, when the metadata blob carries one under a known key."""
    return _table_metadata_value(metadata_item, TABLE_COMMENT_KEYS)


def _comment_source(comment, patched: bool) -> str | None:
    """WI-2.6: where a comment came from -- ``None`` when there is no comment to source.

    A key that said ``"metadata"`` for a table nobody ever commented would answer a
    question the document cannot answer; absence is the honest reading.
    """
    if not comment:
        return None
    return COMMENT_SOURCE_PATCH if patched else COMMENT_SOURCE_METADATA


def _table_comment_is_patched(metadata_item: dict) -> bool:
    return bool((metadata_item.get("table_metadata") or {}).get(TABLE_PATCH_MARKER))


def _table_facts(metadata_item: dict) -> dict:
    """Business domain, project, owner and layer -- ``None`` for each the metadata omits.

    Always all four keys: a missing key would read as "this view does not carry the fact",
    and the question a reader asks is whether the *metadata* knew it.
    """
    return {
        name: _table_metadata_value(metadata_item, keys)
        for name, keys in TABLE_FACT_KEYS.items()
    }


def _physical_fields(resolution: dict | None) -> list[tuple[str, str]]:
    pairs = []
    for field in (resolution or {}).get("physical_source_fields") or []:
        table, column = field.get("table"), field.get("field")
        if table and column:
            pairs.append((str(table), str(column)))
    return pairs


def _dedupe(items: Iterable) -> list:
    """Order-preserving dedupe that also accepts dict items (rendered key pairs)."""
    return unique_ordered(
        items, lambda item: repr(item) if isinstance(item, dict) else item
    )


# --------------------------------------------------------------------- task block (R1)


def _build_task_block(
    document: dict,
    task_meta: dict | None,
    rules: Sequence[dict],
    output_shape: Mapping,
) -> dict:
    output_metadata = _output_metadata(document)
    target_facts = _table_facts(output_metadata)
    mode = document.get("target_partition_mode")
    return {
        "task_name": document.get("task_id"),
        "target_table": document.get("target_table"),
        "target_table_comment": _table_comment(output_metadata),
        # The target's own business placement, as the metadata states it. `null` means the
        # metadata did not say, never that the table belongs to no domain or project.
        "target_table_domain": target_facts["domain"],
        "target_table_project": target_facts["project"],
        "target_table_owner": target_facts["owner"],
        "stmt_kind": document.get("stmt_kind"),
        "partition": {
            "columns": list(document.get("target_partition_columns") or []),
            "mode": None if mode in (None, "none") else mode,
            "spec": document.get("target_partition_spec") or None,
        },
        # WI-2.9 item A. Which day (or days) this instance reads, as its own filters
        # write it. Empty means no filter pins a day-shaped constant -- a parameterised
        # statement, or one with no date filter at all -- never "it reads every day".
        "instance_dates": _instance_dates(document, rules),
        # B2, see `_driving_branches`: which physical table every output row comes from.
        "driving_tables": _driving_branches(document),
        "structural_summary": _structural_summary(document, output_shape),
        # A1: the target's whole declared width, so a corpus can publish the columns this
        # write leaves untouched. Empty when no metadata described the target table.
        "target_declared_columns": _declared_columns(output_metadata),
        "target_metadata_source": output_metadata.get("metadata_source"),
        # WI-2.2. The author's header block, verbatim and in order. It is the one place
        # in this document where a line is neither copied from a structural fact nor
        # inferred from one -- it is a quotation, and the markdown renders it as one.
        "header_comments": list(document.get("statement_comments") or []),
        # The task JSON's metadata, or null when the input was a bare `.sql` file. Null
        # means "nothing supplied it", never "this task has no owner or schedule".
        "meta": dict(task_meta) if task_meta else None,
    }


def _instance_dates(document: dict, rules: Sequence[dict]) -> list[str]:
    """Every day this statement's equality filters pin a column to, deduped and sorted.

    Read from the same comparisons the governance findings read, so the 取数日 line and
    the ``hardcoded_date_literal`` information item can never name different days. The
    constant's *shape* is the whole test: quotes are stripped, and a value written any
    other way is not a day however date-like its column is.
    """
    return sorted(
        {
            str(item["value"]).strip().strip("'\"")
            for item in _literal_comparisons(document, rules)
            if item["value_kind"] == semantic_text.VALUE_KIND_LITERAL
            and semantic_text.looks_like_date_literal(item["value"])
        }
    )


def _output_comments(document: dict) -> dict[tuple[str, str], list[str]]:
    """``(scope_id, name-or-mapping-output-field) -> comments`` for every commented output.

    Keyed twice on purpose. A chain step names its output the way `_mapping_output_field`
    does -- the target column for a ROOT output that binds one, and ``<scope>.<name>``
    otherwise -- while a caller holding a chain header has the plain output name. One
    index answers both rather than each caller re-deriving the other spelling.
    """
    index: dict[tuple[str, str], list[str]] = {}
    for scope_id, scope in _scopes(document).items():
        for output in scope.get("outputs") or []:
            comments = [str(item) for item in output.get("comments") or []]
            if not comments:
                continue
            name = str(output.get("name") or "")
            targets = output.get("target_columns") or []
            index[(scope_id, name)] = comments
            index[(scope_id, str(targets[0]) if targets else f"{scope_id}.{name}")] = comments
    return index


def _structural_summary(document: dict, output_shape: Mapping) -> str:
    """R1: one template sentence built from counts, structural words and table names.

    ``output_shape`` is R2's and R3's answer for this statement, which P3's opening
    clause reads: an aggregated statement's sentence names the keys it folds by before
    the table it folded. It is passed in rather than re-derived so the sentence and the
    ``output_shape`` block can never tell different stories.
    """
    steps = _profile_steps(document)
    root = next((step for step in steps if step.get("scope_id") == "ROOT"), None)
    if root is None:
        return _structural_summary_without_profile(document)
    direct_tables = list(root.get("direct_source_tables") or [])
    parts = [_root_read_clause(document, direct_tables, output_shape)]
    derived = [
        item for item in root.get("direct_inputs") or [] if item not in direct_tables
    ]
    if derived:
        parts.append(f"关联 {len(derived)} 个上游（{_derived_role_counts(steps, derived)}）")
    logic = root.get("logic") or {}
    if logic.get("filters"):
        parts.append(f"过滤 {len(logic['filters'])} 处")
    if logic.get("case_when"):
        parts.append(f"CASE WHEN 派生 {len(logic['case_when'])} 个字段")
    if logic.get("distinct"):
        parts.append("DISTINCT 去重")
    parts.append(f"输出 {root.get('output_columns')} 列")
    return "；".join(parts) + "。"


def _root_read_clause(
    document: dict, direct_tables: Sequence[str], output_shape: Mapping
) -> str:
    """How ROOT reaches its rows: the driving path first, then what it only reads.

    B2. The sentence used to open with what ROOT reads *directly*, which is the joined
    dimension whenever the FROM item is a subquery -- so the one table the reader must
    not mistake for the main one was the first one named. It now opens with the row
    source and demotes the rest, and falls back to the old wording only where no driving
    path resolves (an unprovable FROM item, or a document whose ROOT reads nothing).

    P3: an aggregated or deduplicated statement says what it did to those rows first --
    a reader who is told 「行来自 <table>」 about a GROUP BY would otherwise read it as
    one output row per source row -- and every other shape keeps the B2 sentence.
    """
    branches = _driving_branches(document)
    if branches:
        named = "、".join(
            f"{branch['table']}{_driving_path_note(branch)}" for branch in branches
        )
        driving = {branch["table"] for branch in branches}
        rest = [item for item in direct_tables if item not in driving]
        prefix = _row_shape_prefix(output_shape)
        lead = f"{prefix}，行来自 {named}" if prefix else f"行来源 {named}"
        return f"{lead}；补充 {'、'.join(rest)}" if rest else lead
    table, path, _ = _driving_source(document)
    if table and path:
        clause = f"ROOT 经 {path[0]} 读取 {table}"
        rest = [item for item in direct_tables if item != table]
        return f"{clause}，直接读取 {'、'.join(rest)}" if rest else clause
    if direct_tables:
        return f"ROOT 直接读取 {'、'.join(direct_tables)}"
    return "ROOT 不直接读取物理表"


def _driving_path_note(branch: dict) -> str:
    """The scopes the rows travelled up through, and how often they were exploded.

    Written in data-flow order -- the sentence has just named the table, so it reads on
    from there -- while ``driving_tables[].via_scopes`` keeps the descent order
    ``grain.via_scopes`` uses. Same list, each spelled the way its sentence is read.
    """
    via = list(reversed(branch["via_scopes"]))
    expansions = len(branch["lateral_view_scopes"])
    if not via and not expansions:
        return ""
    counted = _EXPANSION_COUNTS.get(expansions, f"{expansions} 次")
    # A table ROOT reads directly and explodes in place has no scope path to name, and
    # dropping the note with the path would hide the one row-multiplying step there is.
    parts = [f"经 {' → '.join(via)}" if via else ""]
    parts.append(f"{counted} LATERAL VIEW 展开" if expansions else "")
    return "（" + " ".join(item for item in parts if item) + "）"


def _row_shape_prefix(output_shape: Mapping) -> str:
    """P3: what the statement did to the rows, said before where they came from.

    Only the two shapes that fold rows say anything: 「按 <keys> 汇总」 and 「按 <keys>
    去重」, with B10's empty grouping set written as 「全表汇总」 because there are no
    keys to name and 「按 汇总」 would read as a missing list. A fold whose keys the walk
    could not resolve keeps the bare verb -- the fold is proven, the key list is not.
    """
    verb = _ROW_FOLD_VERBS.get(str(output_shape.get("shape")))
    if not verb:
        return ""
    grain = output_shape.get("grain") or {}
    if str(grain.get("basis")) == BASIS_SINGLE_ROW:
        return f"全表{verb}"
    keys = _summary_key_names(grain.get("keys") or [])
    return f"按 {keys} {verb}" if keys else verb


def _summary_key_names(keys: Sequence[dict]) -> str:
    """The grain's keys as one short span, truncated rather than allowed to run away.

    A ten-key GROUP BY spelled out in full buries the rest of the sentence, and the
    sentence's job is to say *that* the rows are folded and roughly by what;
    ``output_shape.grain.keys`` carries the whole list for a reader who needs it.
    """
    names = _dedupe(
        str(key.get("name") or key.get("expression") or key.get("scope_id"))
        for key in keys
    )
    if len(names) <= _SUMMARY_KEY_LIMIT:
        return "、".join(names)
    return "、".join(names[:_SUMMARY_KEY_LIMIT]) + f" 等 {len(names)} 列"


def _structural_summary_without_profile(document: dict) -> str:
    tables = list(document.get("source_tables") or [])
    outputs = len(document.get("end_to_end_lineage") or [])
    read = f"ROOT 读取 {'、'.join(tables)}" if tables else "ROOT 无物理来源表"
    return f"{read}；输出 {outputs} 列。（文档未携带 scope_profile）"


def _derived_role_counts(steps: Sequence[dict], derived: Sequence[str]) -> str:
    roles = Counter(
        str(step.get("role"))
        for step in steps
        if step.get("scope_id") in set(derived)
    )
    parts = [
        f"{roles[role]} 个{label}"
        for role, label in _SCOPE_ROLE_LABELS
        if roles.get(role)
    ]
    named = sum(roles[role] for role, _ in _SCOPE_ROLE_LABELS if roles.get(role))
    if len(derived) > named:
        parts.append(f"{len(derived) - named} 个其他")
    return "、".join(parts) if parts else "角色未知"


# --------------------------------------------------------------------- inputs (R7, R8)


def _build_inputs(document: dict) -> list[dict]:
    roles = _input_roles(document)
    usages = _column_usages(document)
    readers = _read_by_scopes(document)
    metadata = _input_metadata(document)
    # P3: the driving path, as a per-input flag. It is not a role -- an aggregated ROOT's
    # row source is still `aggregate_source`, which is the more specific thing to call it
    # -- so the two facts are published side by side instead of one overwriting the other.
    driving = {branch["table"] for branch in _driving_branches(document)}
    inputs = []
    for table in sorted(document.get("source_tables") or []):
        item = metadata.get(table) or {}
        table_roles = roles.get(table, [])
        comment = _table_comment(item)
        entry = {
            "table": table,
            "comment": comment,
            **_table_facts(item),
            "role_in_task": table_roles[0] if table_roles else None,
            "roles": table_roles,
            "used_columns": _used_columns(item, table, usages),
            "metadata_complete": item.get("metadata_complete"),
            "read_by_scopes": readers.get(table, []),
        }
        inputs.append(_with_optional_facts(entry, item, comment, table in driving))
    return inputs


def _with_optional_facts(entry: dict, item: dict, comment, driving: bool) -> dict:
    """The input facts published only when there is one, each beside what it qualifies.

    An absent key here is 「nothing said so」 and never a negative answer, which is why
    none of them is published as ``null`` or ``false``.
    """
    if "table_column_count" in item:
        # placed next to the other metadata facts, only when the schema knew the table
        entry = _insert_before(
            entry, "read_by_scopes", "table_column_count", item["table_column_count"]
        )
    if item.get("declared_columns"):
        # A1: the table's whole declared width, so a corpus reading these profiles
        # can publish the columns this task never touched instead of dropping them.
        entry = _insert_before(
            entry, "metadata_complete", "declared_columns", _declared_columns(item)
        )
    if driving:
        # P3, beside the role rather than inside it: a table off the path is not
        # 「not driving」 -- it is one this walk had nothing to say about.
        entry = _insert_before(entry, "roles", "driving", True)
    source = _comment_source(comment, _table_comment_is_patched(item))
    if source is not None:
        # WI-2.6: right behind the comment it describes, so the two are read together.
        entry = _insert_before(entry, "domain", "comment_source", source)
    return entry


def _insert_before(entry: dict, anchor: str, key: str, value) -> dict:
    rebuilt = {}
    for name, existing in entry.items():
        if name == anchor:
            rebuilt[key] = value
        rebuilt[name] = existing
    return rebuilt


def _used_columns(
    metadata_item: dict, table: str, usages: dict[tuple[str, str], list[str]]
) -> list[dict]:
    """The columns this statement reads from one table, with their observed usages.

    The declared order is the contract's own ``column_details`` order; a column proven to
    be read by a logic block but absent from the metadata (a schema-less parse) follows,
    sorted, rather than being dropped.
    """
    details = metadata_item.get("column_details") or []
    names = [str(detail.get("name")) for detail in details if detail.get("name") != "*"]
    observed = sorted(
        column for (owner, column) in usages if owner == table and column not in names
    )
    columns = []
    for name in [*names, *observed]:
        detail = _column_detail(metadata_item, name)
        columns.append(
            {
                "name": name,
                "type": detail.get("type"),
                "comment": detail.get("comment"),
                "usages": _ordered_usages(usages.get((table, name), [])),
            }
        )
    return columns


def _declared_columns(metadata_item: dict) -> list[dict]:
    """The contract's ``declared_columns[]``, copied key for key and in DDL order.

    Copied rather than referenced so a caller that edits a profile cannot reach back into
    the document it was built from, and left exactly as the contract wrote it so the two
    always answer "what is this table" with the same list.
    """
    return [
        {
            "name": str(detail.get("name")),
            "type": detail.get("type"),
            "comment": detail.get("comment"),
            "used": bool(detail.get("used")),
        }
        for detail in metadata_item.get("declared_columns") or []
    ]


def _ordered_usages(usages: Iterable[str]) -> list[str]:
    found = set(usages)
    return [usage for usage in USAGE_ORDER if usage in found]


def _read_by_scopes(document: dict) -> dict[str, list[str]]:
    readers: dict[str, list[str]] = {}
    for scope_id in _scope_order(document):
        scope = _scopes(document).get(scope_id) or {}
        for table in scope.get("depends_on") or []:
            readers.setdefault(str(table), []).append(scope_id)
    return readers


def _column_usages(document: dict) -> dict[tuple[str, str], list[str]]:
    """Every ``(table, column) -> [usage]`` the logic blocks and end-to-end layer prove."""
    usages: dict[tuple[str, str], list[str]] = {}

    def record(pairs: Iterable[tuple[str, str]], usage: str) -> None:
        for pair in pairs:
            bucket = usages.setdefault(pair, [])
            if usage not in bucket:
                bucket.append(usage)

    for _, block in _logic_blocks(document):
        logic_type = str(block.get("logic_type"))
        if logic_type in _PREDICATE_LOGIC_TYPES:
            _record_filter_usages(block, record)
        elif logic_type == "join":
            _record_join_usages(block, record)
        elif logic_type == "group_by":
            _record_group_by_usages(block, record)
        elif logic_type == "window":
            _record_window_usages(block, record)
    for entry in document.get("end_to_end_lineage") or []:
        record(
            (
                (str(source.get("table")), str(source.get("column")))
                for source in entry.get("physical_sources") or []
                if source.get("table") and source.get("column")
            ),
            "output",
        )
    return usages


def _record_filter_usages(block: dict, record) -> None:
    detail = block.get("filter_predicate_detail") or {}
    # `is_partition_filter` is a block-level verdict in the contract (the whole predicate
    # references partition columns only); this view reports it as the contract states it
    # and never upgrades an individual conjunct, which would mean re-deriving the
    # partition-name rule that lives in the parser, not here.
    partition = bool(detail.get("is_partition_filter"))
    conjuncts = detail.get("conjuncts") or []
    resolutions = [item.get("expression_resolution") for item in conjuncts] or [
        detail.get("expression_resolution")
    ]
    for resolution in resolutions:
        record(_physical_fields(resolution), "filter")
        if partition:
            record(_physical_fields(resolution), "partition_filter")


def _record_join_usages(block: dict, record) -> None:
    detail = block.get("join_relation_detail") or {}
    for pair in detail.get("join_key_pairs") or []:
        for side in ("left_fields", "right_fields"):
            record(
                (
                    (str(field.get("table")), str(field.get("field")))
                    for field in pair.get(side) or []
                    if field.get("table") and field.get("field")
                ),
                "join_key",
            )
    # A JOIN's extra ON condition is NOT recorded as a filter usage. When it tests a
    # derived column (`status.row_num = 1`), the contract publishes that column's own
    # physical inputs as `physical_fields` -- the window's partition and order columns.
    # Calling those a filter usage would state that a column is filtered when it is not;
    # the condition itself is published verbatim as `rules[].extra_conditions`.


def _record_group_by_usages(block: dict, record) -> None:
    detail = block.get("aggregation_detail") or {}
    for item in detail.get("group_by_items") or []:
        record(_physical_fields(item.get("expression_resolution")), "group_by")


def _record_window_usages(block: dict, record) -> None:
    specification = block.get("window_specification") or {}
    for item in specification.get("partition_by") or []:
        record(_physical_fields(item.get("expression_resolution")), "window_partition")
    for item in specification.get("order_by") or []:
        record(_physical_fields(item.get("expression_resolution")), "window_order")


def _input_roles(document: dict) -> dict[str, list[str]]:
    """R7: the role each physical input table plays, most specific first."""
    tables = set(document.get("source_tables") or [])
    found: dict[str, set[str]] = {}

    def add(table: str, role: str) -> None:
        if table in tables:
            found.setdefault(table, set()).add(role)

    left_inputs, right_inputs, joined = _join_sides(document)
    for table in _merge_source_tables(document):
        add(table, "merge_source")
    for step in _profile_steps(document):
        _add_step_roles(step, left_inputs, right_inputs, add)
    for scope in _scopes(document).values():
        alignment = scope.get("union_branch_alignment") or {}
        for branch in alignment.get("branches") or []:
            for table in branch.get("source_tables") or []:
                add(str(table), "union_branch")
    for table in joined:
        if "driving" not in found.get(table, set()):
            add(table, "enrich")
    # R7 follows R3: a table ROOT reads through a row-preserving scope drives the
    # statement exactly as a directly read one does, and keeps its other roles.
    driving, path, _ = _driving_source(document)
    if driving and path and _classify_shape(document)[0] in _PROJECTION_SHAPES:
        add(driving, "driving")
    for table in _upstream_driving_tables(document):
        add(table, "driving")
    _apply_driving_path(document, found, joined, add)
    for table, item in _input_metadata(document).items():
        if item.get("column_details") == []:
            add(str(table), "rowset_only")
    return {
        table: [role for role in ROLE_PRIORITY if role in roles]
        for table, roles in sorted(found.items())
    }


def _apply_driving_path(document: dict, found: dict, joined: set, add) -> None:
    """B2: let the driving path decide ``driving``, and name the partners it passes.

    The path is the authority where it resolves. A table it excludes loses the
    ``driving`` an earlier rule granted off ROOT's own FROM list and falls back to
    ``enrich`` when a JOIN reaches it -- a RIGHT JOIN's left side is exactly that
    table, and the earlier rule, which only asks whether an input is a JOIN's right
    side, called it the main table.

    Only where the shape counts its rows from a table: P3 publishes the path for an
    aggregated or deduplicated ROOT too, and there the rows are counted by a key set, so
    ``aggregate_source`` / ``dedup_source`` stay the most specific thing to call those
    inputs. ``inputs[].driving`` carries the path fact for them instead.
    """
    if _classify_shape(document)[0] not in _ROW_COUNT_SHAPES:
        return
    branches = _driving_branches(document)
    if not branches:
        return
    driving = {branch["table"] for branch in branches}
    for table, roles in found.items():
        if table not in driving and "driving" in roles:
            roles.discard("driving")
            if table in joined:
                roles.add("enrich")
    for table in sorted(driving):
        add(table, "driving")
    for table in _filter_partner_tables(document, branches):
        add(table, "filter_partner")


def _upstream_driving_tables(document: dict) -> list[str]:
    """WI-2.1c item 4: the tables that drive the statement one or more scopes down.

    A physical table that is a non-ROOT scope's own FROM item drives that scope's rows,
    by exactly the rule ``_scope_from_item`` already applies -- an input that is only
    ever a JOIN's right side is not one. Whether the *statement's* rows follow it is the
    second half: they do when that scope sits on ROOT's driving path, and they do when
    the columns that scope outputs are what ROOT groups by.

    The corpus case this exists for had every GROUP BY key coming from one table, and
    the profile labelled that table ``enrich`` because ROOT did not read it directly --
    a reader looking for "the main table" was pointed at a lookup instead.
    """
    if str(document.get("stmt_kind")) == "MERGE":
        # A MERGE has no ROOT projection whose rows a FROM item could drive: its ROOT is
        # the USING relation, and R7 already names those tables `merge_source`.
        return []
    qualifying = [
        scope_id
        for scope_id in _dedupe(
            [
                *_aggregation_path(document, _ROOT, {"aggregation_paths": {}}),
                *_root_group_by_scopes(document),
            ]
        )
        if scope_id != _ROOT
    ]
    tables = set(document.get("source_tables") or [])
    found = []
    for scope_id in qualifying:
        item, _ = _scope_from_item(document, scope_id)
        if item in tables:
            found.append(str(item))
    return _dedupe(found)


def _root_group_by_scopes(document: dict) -> list[str]:
    """The scopes whose output columns ROOT's GROUP BY items were expanded from.

    Read off the contract's own resolution (``source_scope_id`` / ``scope_output_trace``)
    and the item's scope-level ``source_fields``; anything this document does not declare
    as a scope is dropped rather than treated as one.
    """
    scopes = set(_scopes(document))
    found: list[str] = []
    for block in _blocks_of_type(document, _ROOT, "group_by"):
        for item in (block.get("aggregation_detail") or {}).get("group_by_items") or []:
            resolution = item.get("expression_resolution") or {}
            found.extend(
                [
                    str(resolution.get("source_scope_id") or ""),
                    *[
                        str(trace.get("to_scope_id") or "")
                        for trace in resolution.get("scope_output_trace") or []
                    ],
                    *[
                        str(ref.get("scope") or "")
                        for ref in item.get("source_fields") or []
                    ],
                ]
            )
    return _dedupe(item for item in found if item in scopes)


def _add_step_roles(
    step: dict, left_inputs: set, right_inputs: set, add
) -> None:
    """The roles one ``scope_profile`` step proves for the tables it reads directly."""
    role = str(step.get("role"))
    for table in [str(item) for item in step.get("direct_source_tables") or []]:
        if role == "aggregate":
            add(table, "aggregate_source")
        elif role == "dedup":
            add(table, "dedup_source")
        # A table ROOT reads directly drives the statement unless ROOT aggregates or
        # dedups it, or it only ever appears on the right of a JOIN (then it is
        # enrichment). A self join keeps it driving: it is a left input too.
        if step.get("scope_id") == _ROOT and role not in ("aggregate", "dedup"):
            if table not in right_inputs or table in left_inputs:
                add(table, "driving")


def _merge_source_tables(document: dict) -> list[str]:
    """R7: the physical tables a MERGE reads through its USING relation.

    A MERGE's ROOT is the USING source itself -- it carries no JOIN block and often no
    direct physical input, so none of the projection roles fire and the source table
    would be left role-less. The boundary fact the contract already publishes (ROOT's
    ``physical_source_tables``) is exactly the set of tables the merge reads.

    The statement's own target table is never a merge source. Where a JOIN reads it, the
    contract says so in ``join_relation_detail.target_self_reference``; that reference is
    the write target being consulted, not an input the MERGE draws rows from. It keeps
    whatever other role the statement proves for it (a carry-forward self join is still
    ``enrich``) -- it just never becomes a ``merge_source``.
    """
    if str(document.get("stmt_kind")) != "MERGE":
        return []
    root = next(
        (step for step in _profile_steps(document) if step.get("scope_id") == _ROOT), {}
    )
    excluded = {str(document.get("target_table") or "")} | _self_referenced_tables(document)
    return [
        str(table)
        for table in root.get("physical_source_tables") or []
        if str(table) not in excluded
    ]


def _self_referenced_tables(document: dict) -> set[str]:
    return {
        str((block.get("join_relation_detail") or {}).get("target_self_reference", {}).get("table"))
        for _, block in _logic_blocks(document)
        if (block.get("join_relation_detail") or {}).get("target_self_reference")
    }


def _join_sides(document: dict) -> tuple[set[str], set[str], set[str]]:
    """Physical tables appearing on a JOIN's left side, right side, and either.

    A side is read both from the input id (a directly joined table) and from the key
    pairs the contract has already pierced to physical fields, so a table joined through
    a filter-only subquery still counts as joined -- the pierce is the contract's, not a
    guess made here.

    A JOIN whose condition the parser could not split into key pairs (``COALESCE(a, b) =
    c`` reports ``missing_join_key_pairs``) still proves participation: the contract
    pierces the condition itself to physical fields. Those tables join the ``joined``
    set but neither side, because the condition does not say which side each field came
    from -- enough for the ``enrich`` role, not enough to revoke ``driving``.
    """
    tables = set(document.get("source_tables") or [])
    left: set[str] = set()
    right: set[str] = set()
    condition_only: set[str] = set()
    for _, block in _logic_blocks(document):
        if block.get("logic_type") != "join":
            continue
        detail = block.get("join_relation_detail") or {}
        for side, bucket in (("left", left), ("right", right)):
            candidate = str(detail.get(f"{side}_input") or "")
            if candidate in tables:
                bucket.add(candidate)
            for pair in detail.get("join_key_pairs") or []:
                for field in pair.get(f"{side}_fields") or []:
                    if str(field.get("table")) in tables:
                        bucket.add(str(field.get("table")))
        for condition in detail.get("condition_filters") or []:
            condition_only |= {
                str(field.get("table"))
                for field in condition.get("physical_fields") or []
                if str(field.get("table")) in tables
            }
    return left, right, left | right | condition_only


# ------------------------------------------------------------ driving path (B2, R7)

# The contract's `input_edges[].position` vocabulary, which is what "the FROM item"
# means without re-deriving it: the parser already recorded which input was written in
# FROM, which was joined on, and which arrived through a LATERAL VIEW.
_EDGE_FROM = "from"
_EDGE_JOIN = "join"
_EDGE_LATERAL_VIEW = "lateral_view"

# The two join types that move the driving side off the FROM item. A RIGHT JOIN makes
# the whole left relation optional, so the rows are the right side's; a FULL JOIN keeps
# both sides' unmatched rows, so the rows follow both, exactly as a UNION's do. Every
# other type leaves the FROM item driving.
_JOIN_SWAPS_DRIVING = "RIGHT_OUTER"
_JOIN_DRIVES_BOTH = "FULL_OUTER"

# The join types whose right side can drop a driving row. An OUTER join cannot (the
# unmatched left row survives with nulls) and a CROSS join has no condition to fail.
_FILTERING_JOIN_TYPES = ("INNER", "LEFT_SEMI", "LEFT_ANTI", "SEMI", "ANTI")

# The shapes whose row *count* follows a table at all. P3: the path itself is walked for
# every shape -- a GROUP BY still has a row source, and the reader asking 「这张表的行从
# 哪来」 wants it -- but only these shapes let reaching a table *count* rows. An
# aggregated or deduplicated ROOT counts by its key set (R7 already names those inputs
# `aggregate_source` / `dedup_source`, and overwriting that with `driving` would lose the
# more specific fact), and a MERGE writes through branch semantics this view does not
# model. So this tuple gates the two row-count readings of the path -- the `driving`
# role and B3's row-shape hypothesis -- and nothing else.
_ROW_COUNT_SHAPES = (SHAPE_ENRICHED, SHAPE_FILTERED, SHAPE_UNION_MERGE)


def _driving_branches(document: dict) -> list[dict]:
    """B2: every physical table ROOT's rows come from, with the path walked to reach it.

    R3's grain walk answers a different question and stops early: an explode or a UNION
    ends it with ``unknown``, and the driving role and R1's summary sentence were read
    off that same stop -- so a statement whose FROM item was an exploded subquery chain
    published every input as ``enrich`` and opened its summary with the dimension table
    that happened to be joined on. Row *count* is undecidable there; row *source* is
    not, and this walk answers only the second question.

    Each branch is ``{table, via_scopes, lateral_view_scopes}``, the two scope lists in
    descent order (ROOT first, the table's own scope last), so they read like
    ``grain.via_scopes``. One table appears once, keeping the left-most path to it.

    P3: every shape is walked. An aggregated or deduplicated ROOT counts its rows by a
    key set rather than by a table, and it still *reads* those rows from somewhere -- the
    FROM item its GROUP BY sits on -- so the descent is the same one, and it is only the
    row-count readings of the answer that ``_ROW_COUNT_SHAPES`` still holds back. A MERGE
    answers too: its ROOT is the USING relation, whose FROM item is the source side.
    """
    found: dict[str, dict] = {}
    for branch in _walk_driving(document, _ROOT, [], [], []):
        found.setdefault(branch["table"], branch)
    return list(found.values())


def _walk_driving(
    document: dict, item: str, crossed: list, lateral: list, seen: list
) -> list[dict]:
    """The descent itself, one branch per driving table, left to right."""
    if item in set(document.get("source_tables") or []):
        return [
            {
                "table": item,
                "via_scopes": list(crossed),
                "lateral_view_scopes": list(lateral),
            }
        ]
    if item not in _scopes(document) or item in seen or len(seen) >= GRAIN_DEPTH_LIMIT:
        return []
    below = list(crossed) if item == _ROOT else [*crossed, item]
    # A LATERAL VIEW multiplies the driving table's rows instead of replacing them, so
    # the walk crosses it and remembers that it did -- B3 reads exactly this list.
    expanded = [*lateral, item] if _lateral_view_inputs(document, item) else list(lateral)
    return [
        branch
        for following in _driving_inputs_of(document, item)
        for branch in _walk_driving(document, following, below, expanded, [*seen, item])
    ]


def _driving_inputs_of(document: dict, scope_id: str) -> list[str]:
    """The inputs whose rows this scope's rows follow, left to right.

    A UNION answers with every branch, because its row count is their sum. Everything
    else answers with its FROM item, moved to the right side by a RIGHT JOIN and joined
    by a FULL one. A scope the contract gave no ``input_edges`` (a UNION's own parent,
    which reads nothing but the union) falls back to the dependency-level rule.
    """
    scope = _scopes(document).get(scope_id) or {}
    branches = (scope.get("union_branch_alignment") or {}).get("branches") or []
    if branches:
        return [str(branch.get("branch_id")) for branch in branches]
    edges = scope.get("input_edges") or []
    driving = [
        str(edge.get("source_id"))
        for edge in edges
        if str(edge.get("position")) == _EDGE_FROM
    ]
    for edge in edges:
        if str(edge.get("position")) != _EDGE_JOIN:
            continue
        kind = str(edge.get("join_type") or "").upper()
        if kind == _JOIN_SWAPS_DRIVING:
            driving = [str(edge.get("source_id"))]
        elif kind == _JOIN_DRIVES_BOTH:
            driving = _dedupe([*driving, str(edge.get("source_id"))])
    if driving:
        return driving
    item, _reason = _scope_from_item(document, scope_id)
    return [item] if item else []


def _lateral_view_inputs(document: dict, scope_id: str) -> list[str]:
    """The UDTF scopes this scope reads through a LATERAL VIEW, in edge order."""
    return [
        str(edge.get("source_id"))
        for edge in (_scopes(document).get(scope_id) or {}).get("input_edges") or []
        if str(edge.get("position")) == _EDGE_LATERAL_VIEW
    ]


def _filter_partner_tables(document: dict, branches: Sequence[dict]) -> list[str]:
    """B2: the tables an INNER-family JOIN *on the driving path* can drop rows by.

    Only the partner's own driving table is named. A partner subquery that left-joins a
    lookup of its own does not make that lookup a filter on this statement's rows, and
    listing every table under the partner would say it does.
    """
    tables = set(document.get("source_tables") or [])
    scopes = _dedupe([_ROOT, *[item for branch in branches for item in branch["via_scopes"]]])
    found: list[str] = []
    for scope_id in scopes:
        for edge in (_scopes(document).get(scope_id) or {}).get("input_edges") or []:
            if str(edge.get("position")) != _EDGE_JOIN:
                continue
            if str(edge.get("join_type") or "").upper() not in _FILTERING_JOIN_TYPES:
                continue
            found.extend(
                branch["table"]
                for branch in _walk_driving(document, str(edge.get("source_id")), [], [], [])
            )
    return [item for item in _dedupe(found) if item in tables]


# --------------------------------------------------------------------- rules


def _build_rules(document: dict) -> list[dict]:
    """A flat, stably numbered list of the statement's conditions and branch logic."""
    rules: list[dict] = []
    for scope_id, block in _logic_blocks(document):
        logic_type = str(block.get("logic_type"))
        if logic_type in _PREDICATE_LOGIC_TYPES:
            rules.extend(_filter_rules(document, scope_id, block))
        elif logic_type == "join":
            rules.append(_join_rule(document, scope_id, block))
        elif logic_type == "case_when":
            rules.append(_case_rule(document, scope_id, block))
    for index, rule in enumerate(rules, start=1):
        rule["rule_id"] = f"rule:{index:03d}"
    return [_ordered_rule(rule) for rule in rules]


_RULE_KEY_ORDER = (
    "rule_id",
    "kind",
    "scope_id",
    "expression",
    "is_partition_filter",
    "join_type",
    "null_semantics",
    "left_input",
    "right_input",
    "key_pairs",
    "physical_key_pairs",
    "extra_conditions",
    "extra_condition_fields",
    "branches",
    "else",
    # WI-2.12: filled in by `apply_glossary`, so it sits beside the fields whose codes it
    # explains rather than at the end of the rule.
    "value_meanings",
    "fields",
    "scope_fields",
    "sql_comments",
    "evidence",
    "tag",
)


def _ordered_rule(rule: dict) -> dict:
    return {key: rule[key] for key in _RULE_KEY_ORDER if key in rule}


def _filter_rules(document: dict, scope_id: str, block: dict) -> list[dict]:
    detail = block.get("filter_predicate_detail") or {}
    kind = "having" if detail.get("predicate_type") == "having" else "filter"
    evidence = str(block.get("logic_block_id"))
    partition = bool(detail.get("is_partition_filter"))
    conjuncts = detail.get("conjuncts") or [
        {
            "expression": detail.get("expression") or block.get("raw_expression"),
            "expression_resolution": detail.get("expression_resolution"),
        }
    ]
    rules = []
    for conjunct in conjuncts:
        pairs = _physical_fields(conjunct.get("expression_resolution"))
        rules.append(
            {
                "kind": kind,
                "scope_id": scope_id,
                "expression": conjunct.get("expression"),
                "is_partition_filter": partition,
                "fields": _rule_fields(document, pairs),
                "scope_fields": _scope_fields(document, conjunct.get("fields")),
                # WI-2.2. A WHERE split into conjuncts has one comment list for the whole
                # block, so every conjunct carries it: the author wrote the note about the
                # predicate, and the split is this view's doing, not theirs.
                **_rule_comments(block),
                "evidence": evidence,
                "tag": TAG_SQL_FACT,
            }
        )
    return rules


def _join_rule(document: dict, scope_id: str, block: dict) -> dict:
    """One JOIN condition. ``fields`` are the key-pair endpoints and nothing else.

    See the module docstring, departure 2: an extra ON condition over a generated column
    pierces to the columns that *built* that column, which are not join keys. They are
    published separately under ``extra_condition_fields``.
    """
    detail = block.get("join_relation_detail") or {}
    pairs: list[dict] = []
    physical_pairs: list[dict] = []
    physical: list[tuple[str, str]] = []
    for pair in detail.get("join_key_pairs") or []:
        rendered, pierced, fields = _join_key_pair(pair)
        pairs.extend(rendered)
        physical_pairs.extend(pierced)
        physical.extend(fields)
    return {
        "kind": "join_condition",
        "scope_id": scope_id,
        "expression": detail.get("condition_expression"),
        "join_type": detail.get("join_type"),
        # WI-1f: what this join does to the rows it cannot match. It is a fact of the
        # join type, so it is published beside `join_type` rather than folded into a
        # sentence the JSON does not otherwise carry.
        "null_semantics": semantic_text.join_null_semantics(detail.get("join_type")),
        "left_input": detail.get("left_input"),
        "right_input": detail.get("right_input"),
        "key_pairs": _dedupe(pairs),
        "physical_key_pairs": _dedupe(physical_pairs),
        "extra_conditions": [
            condition.get("expression") for condition in detail.get("condition_filters") or []
        ],
        "extra_condition_fields": _extra_condition_fields(document, detail),
        "fields": _rule_fields(document, physical),
        "scope_fields": _scope_fields(document, detail.get("condition_fields")),
        **_rule_comments(block),
        "evidence": str(block.get("logic_block_id")),
        "tag": TAG_SQL_FACT,
    }


def _rule_comments(block: dict) -> dict:
    """``{"sql_comments": [...]}`` when the block carries comments, ``{}`` otherwise."""
    comments = [str(item) for item in block.get("comments") or []]
    return {"sql_comments": comments} if comments else {}


def _extra_condition_fields(document: dict, detail: dict) -> list[dict]:
    pairs = [
        (str(field.get("table")), str(field.get("field")))
        for condition in detail.get("condition_filters") or []
        for field in condition.get("physical_fields") or []
        if field.get("table") and field.get("field")
    ]
    key_endpoints = {
        (str(field.get("table")), str(field.get("field")))
        for pair in detail.get("join_key_pairs") or []
        for side in ("left_fields", "right_fields")
        for field in pair.get(side) or []
    }
    return [
        {**item, "via_generated_column": True}
        for item in _rule_fields(
            document, [pair for pair in pairs if pair not in key_endpoints]
        )
    ]


def _join_condition_physical_fields(document: dict, detail: dict) -> list[dict]:
    """The key-pair endpoints of one JOIN, deduped by ``(table, column)``."""
    pairs: list[tuple[str, str]] = []
    for pair in detail.get("join_key_pairs") or []:
        pairs.extend(_join_key_pair(pair)[2])
    return _rule_fields(document, pairs)


def _join_key_pair(pair: dict) -> tuple[list[dict], list[dict], list[tuple[str, str]]]:
    """One key pair as ``(scope-level pairs, physical pairs, physical endpoints)``.

    WI-1g item A2. The physical rendering is a cross product of both sides' pierced
    fields, so one logical key pair written over a 12-branch UNION comes back as twelve
    "keys" the SQL never wrote, and a two-key join over it as twenty. The scope-level
    pair -- ``qualifier.column`` on each side, exactly what the ON clause says -- is the
    key the reader is looking for, so it leads; the cross product stays available under
    ``physical_key_pairs`` and the endpoints under ``fields``.

    Two scopes reading the same table pierce to the same physical field, so a pierced
    pair that degenerates to ``t.c = t.c`` is dropped exactly as the mapping document
    drops it.
    """
    physical: list[dict] = []
    fields: list[tuple[str, str]] = []
    for left in pair.get("left_fields") or []:
        for right in pair.get("right_fields") or []:
            left_text = f"{left.get('table')}.{left.get('field')}"
            right_text = f"{right.get('table')}.{right.get('field')}"
            fields.append((str(left.get("table")), str(left.get("field"))))
            fields.append((str(right.get("table")), str(right.get("field"))))
            if left_text != right_text:
                physical.append({"left": left_text, "right": right_text})
    scoped = _scope_key_pair(pair)
    return ([scoped] if scoped else list(physical)), physical, fields


def _scope_key_pair(pair: dict) -> dict | None:
    """``{left, right}`` as the ON clause writes the pair, or None when it has no refs."""
    left_ref = pair.get("left") or {}
    right_ref = pair.get("right") or {}
    if not left_ref.get("column") or not right_ref.get("column"):
        return None
    return {
        "left": f"{left_ref.get('qualifier') or left_ref.get('scope')}"
        f".{left_ref.get('column')}",
        "right": f"{right_ref.get('qualifier') or right_ref.get('scope')}"
        f".{right_ref.get('column')}",
    }


def _case_rule(document: dict, scope_id: str, block: dict) -> dict:
    # raw_expression, never display_expression: the display form lower-cases string
    # literals, so `'HIGH'` would be published as `'high'`.
    expression = block.get("raw_expression")
    split = semantic_text.split_case_branches(expression)
    branches, otherwise = split if split is not None else (None, None)
    pairs = [
        (str(usage.get("source_id")), str(name))
        for usage in block.get("field_usage") or []
        if usage.get("source_type") == "physical_table"
        for name in usage.get("used_fields") or []
    ]
    return {
        "kind": "case_branch",
        "scope_id": scope_id,
        "expression": expression,
        "branches": branches,
        "else": otherwise,
        "fields": _rule_fields(document, pairs),
        "scope_fields": _scope_fields(document, block.get("fields")),
        **_rule_comments(block),
        "evidence": str(block.get("logic_block_id")),
        "tag": TAG_SQL_FACT,
    }


def _rule_fields(document: dict, pairs: Sequence[tuple[str, str]]) -> list[dict]:
    return [
        {
            "table": table,
            "column": column,
            "comment": _input_column_comment(document, table, column),
        }
        for table, column in _dedupe(pairs)
    ]


def _scope_fields(document: dict, refs: Sequence[dict] | None) -> list[dict]:
    """Scope-level references that do not pierce to a physical field.

    They keep a ``scope`` key rather than a ``table`` key on purpose: a CTE id is not a
    table, and publishing it under ``table`` would fabricate one.
    """
    tables = set(document.get("source_tables") or [])
    return _dedupe(
        {"scope": str(ref.get("scope")), "column": str(ref.get("column"))}
        for ref in refs or []
        if ref.get("scope") not in tables
    )


# --------------------------------------------------------------------- fields (R4, R5)


_FIELD_KEY_ORDER = (
    "column",
    "column_label",
    # WI-B: published only where a positional write renamed the column -- see
    # `_sql_alias`. It sits beside the name it disagrees with, not among the SQL facts.
    "sql_alias",
    "summary",
    "target_comment",
    "target_comment_source",
    # WI-2.12: the corpus term's confirmed meaning, published only where the target table
    # has no comment of its own. It is a term, never a comment, and never impersonates one.
    "term_meaning",
    "sql_comments",
    "type",
    "transform",
    "structural_role",
    "nullable_by_join",
    "metric_spec",
    "value_domain",
    "sources",
    "generated_sources",
    "derivation",
    "expression",
    "trace_complete",
    "trace_incomplete_reasons",
    "ambiguous",
    "mapping_chain_id",
    "tag",
)


def _e2e_sort_key(entry: dict, index: int):
    ordinal = entry.get("target_column_ordinal")
    if ordinal is None:
        ordinal = entry.get("output_ordinal")
    if ordinal is None:
        ordinal = index
    return (ordinal, index)


def _field_context(
    document: dict, rules: Sequence[dict] = (), task_meta: dict | None = None
) -> dict:
    """The per-document lookups every field reads, resolved once.

    A 100-field task walks thousands of chain steps, so nothing in here is recomputed
    per field. ``metric_argument_scopes`` is the one entry written *into*: each metric
    card records the scopes its argument was read from, and the shape block asks those
    scopes for their fan-out verdicts (WI-2.1c item 5).
    """
    return {
        "group_by_keys": _group_by_keys_by_scope(document),
        "udf_blocks": _udf_logic_block_ids(document),
        "column_types": _column_types(document),
        "nullable_inputs": _nullable_join_inputs(document),
        "union_branches": _union_branch_index(document),
        # WI-2.1: the metric card reads the statement's conditions and the WI-1e
        # exposure map, both of which are per-document and walked once.
        "rules": list(rules),
        "exposed": _exposed_target_columns(document),
        "aggregation_paths": {},
        "metric_argument_scopes": [],
        # WI-9 legacy a: the input subtree of every scope a metric anchors to, for the
        # same reason and written into the same way.
        "metric_anchor_scopes": [],
        # WI-2.2: the two per-document comment lookups, resolved once like everything
        # else here -- a 100-field task would otherwise rebuild the index per field.
        "output_comments": _output_comments(document),
        "task_meta": dict(task_meta) if task_meta else None,
    }


def _build_fields(
    document: dict, rules: Sequence[dict] = (), context: dict | None = None
) -> list[dict]:
    entries = document.get("end_to_end_lineage") or []
    ordered = sorted(enumerate(entries), key=lambda pair: _e2e_sort_key(pair[1], pair[0]))
    chains = _chain_matcher(document)
    context = _field_context(document, rules) if context is None else context
    return [_build_field(document, entry, chains(entry), context) for _, entry in ordered]


def _column_types(document: dict) -> dict[str, str]:
    """``column name -> declared type``, for the MIN/MAX reading (WI-1f item 5).

    Keyed by the bare column name because that is what a restated call prints, and a
    name two input tables type differently is dropped rather than resolved: an
    ambiguous type proves nothing, and "最晚时间" on a decimal would be a fabrication.
    """
    declared: dict[str, set[str]] = {}
    for item in _input_metadata(document).values():
        for detail in item.get("column_details") or []:
            name, kind = detail.get("name"), detail.get("type")
            if name and kind:
                declared.setdefault(str(name), set()).add(str(kind))
    return {name: next(iter(kinds)) for name, kinds in declared.items() if len(kinds) == 1}


def _union_branch_index(document: dict) -> dict[str, dict]:
    """``branch scope id -> {index, label}`` for every UNION this statement carries.

    WI-1g item D1 needs to know which derivation steps happen inside a branch and which
    branch that is; the label is the branch's own ``source_tables``, and a branch whose
    sources the contract could not name falls back to its scope id rather than to a
    number alone.
    """
    index: dict[str, dict] = {}
    for scope in _scopes(document).values():
        branches = (scope.get("union_branch_alignment") or {}).get("branches") or []
        for position, branch in enumerate(branches, start=1):
            branch_id = str(branch.get("branch_id") or "")
            if not branch_id:
                continue
            tables = [str(table) for table in branch.get("source_tables") or []]
            index[branch_id] = {
                "index": position,
                "label": "、".join(tables) or branch_id,
            }
    return index


def _group_by_keys_by_scope(document: dict) -> dict[str, list[str]]:
    return {
        scope_id: _group_by_keys(document, scope_id) for scope_id in _scopes(document)
    }


def _udf_logic_block_ids(document: dict) -> set:
    return {
        str(block.get("logic_block_id"))
        for _, block in _logic_blocks(document)
        if (block.get("expression_features") or {}).get("has_udf")
    }


def _chain_matcher(document: dict):
    """Match each end-to-end entry to its mapping chain by output position, once each."""
    remaining = list(document.get("field_mapping_chains") or [])

    def match(entry: dict) -> dict | None:
        position = entry.get("output_ordinal")
        candidates = [
            chain for chain in remaining if chain.get("target_position") == position
        ]
        for chain in candidates:
            if chain.get("target_field") in (
                entry.get("parsed_column"),
                entry.get("column"),
            ):
                remaining.remove(chain)
                return chain
        if candidates:
            remaining.remove(candidates[0])
            return candidates[0]
        return None

    return match


def _build_field(document: dict, entry: dict, chain: dict | None, context: dict) -> dict:
    detail = _column_detail(_output_metadata(document), entry.get("column"))
    comment = detail.get("comment")
    derivation = _derivation(chain, context)
    # WI-2.1 fix: the chain rule below only proves a *pass-through* value nullable, so an
    # aggregate over a joined-in column came back false. The argument rule proves the
    # other half, and the field flag follows whichever of the two fires.
    nullable_argument = _nullable_argument(document, entry, chain, context)
    nullable = bool(nullable_argument) or _nullable_by_join(
        entry, chain, context["nullable_inputs"]
    )
    # WI-2.2. Two different questions, so two different reads of the same key: the
    # chain-wide list is everything the author wrote anywhere along the derivation, while
    # the alias comment is what they wrote beside THIS column's name -- only the second
    # earns a place in the one-sentence summary.
    sql_comments = _chain_sql_comments(chain, context)
    alias_comments = _alias_comments(chain, entry, context)
    field = {
        "column": entry.get("column"),
        "column_label": _field_label(document, entry, chain),
        "summary": _field_summary(
            document, entry, derivation, comment, nullable, alias_comments
        ),
        "target_comment": comment,
        "type": detail.get("type"),
        "transform": entry.get("transform"),
        "structural_role": _structural_role(document, entry, chain, detail.get("type")),
        "sources": _field_sources(document, entry),
        "generated_sources": list(entry.get("generated_sources") or []),
        "derivation": derivation,
        "expression": entry.get("expression"),
        "trace_complete": entry.get("trace_complete"),
        "trace_incomplete_reasons": entry.get("trace_incomplete_reasons"),
        "ambiguous": _is_ambiguous(entry),
        "mapping_chain_id": chain.get("mapping_chain_id") if chain else None,
        "tag": TAG_SQL_AND_METADATA_FACT if comment else TAG_SQL_FACT,
    }
    if "trace_incomplete_reasons" not in entry:
        field.pop("trace_incomplete_reasons")
    # WI-2.6: only when there is a comment to attribute. `confirmed` is the whole point of
    # the write-back loop, so the reader must be able to tell the answer from the export.
    comment_source = _comment_source(
        comment, str(detail.get("comment_source")) == COMMENT_SOURCE_PATCH
    )
    if comment_source is not None:
        field["target_comment_source"] = comment_source
    alias = _sql_alias(document, entry)
    if alias:
        field["sql_alias"] = alias
    if nullable:
        field["nullable_by_join"] = True
    if sql_comments:
        field["sql_comments"] = sql_comments
    spec = _build_metric_spec(document, entry, chain, field, context, nullable_argument)
    if spec is not None:
        field["metric_spec"] = spec
    return {key: field[key] for key in _FIELD_KEY_ORDER if key in field}


def _sql_alias(document: Mapping, entry: Mapping) -> str | None:
    """The name the SQL gave a value that a DDL position filed under another name.

    Three conditions, all of them the `alias_position_mismatch` finding's: the write is
    positional, the two names disagree, and the parsed name is an alias somebody wrote
    rather than a ``_col_N`` placeholder. Anything else would print a disagreement that
    is not one.
    """
    binding = document.get("target_field_binding") or {}
    if str(binding.get("method")) != _POSITIONAL_BINDING_METHOD:
        return None
    alias = str(entry.get("parsed_column") or "")
    if not alias or alias == str(entry.get("column")) or _name_is_generated(entry):
        return None
    return alias


def _chain_sql_comments(chain: dict | None, context: dict) -> list[str]:
    """Every comment the author wrote on this field's derivation, upstream first.

    Collected along the mapping chain rather than off the final projection alone: a value
    renamed three times carries its explanation at the step where it was computed, and a
    reader asking what the target column means needs that step's note as much as the last
    one's. Order is the chain's, duplicates are dropped -- the same note restated at two
    steps is one thing the author said.

    WI-2.8 D9: a body that IS SQL the author switched off is not a note about the column
    and does not travel here. It stays in the contract's own ``comments``, where a reader
    asking what the code used to look like can still find it.
    """
    index = context["output_comments"]
    collected: list[str] = []
    for step in (chain or {}).get("ordered_steps") or []:
        key = (str(step.get("scope_id")), str(step.get("output_field") or ""))
        collected.extend(index.get(key) or [])
    return _dedupe(item for item in collected if semantic_text.is_note(item))


def _alias_comments(chain: dict | None, entry: dict, context: dict) -> list[str]:
    """What the author wrote beside this output's own name, and nothing further upstream.

    Commented-out SQL is filtered out for the reason WI-2.8 D9 gives: this list is what
    the one-sentence summary appends as 「注释：…」, and an abandoned expression read
    there as the column's current definition.
    """
    index = context["output_comments"]
    if chain:
        key = (str(chain.get("target_scope_id")), str(chain.get("target_field") or ""))
        if key in index:
            return [item for item in index[key] if semantic_text.is_note(item)]
    return [
        item
        for item in index.get((_ROOT, str(entry.get("column") or ""))) or []
        if semantic_text.is_note(item)
    ]


def _field_sources(document: dict, entry: dict) -> list[dict]:
    """One entry per physical source, each carrying the column comment beside it."""
    return [
        {
            "table": source.get("table"),
            "column": source.get("column"),
            "comment": _input_column_comment(
                document, source.get("table"), source.get("column")
            ),
            "transform": source.get("transform"),
        }
        for source in entry.get("physical_sources") or []
    ]


def _field_summary(
    document: dict,
    entry: dict,
    derivation: Sequence[dict],
    comment: str | None,
    nullable: bool,
    alias_comments: Sequence[str] = (),
) -> str:
    """WI-1f item 2: one unlabelled sentence a reader can act on without the subsection.

    It restates what the other keys already hold -- the target comment, the chain's own
    restated steps, the source columns with their comments -- and states nothing new,
    so it cannot disagree with them. Pass-through steps are left out: eight lines of
    "直接投影自 …" are the definition of a direct read, which the sentence says instead.

    WI-1g item D1: the steps that happen inside a UNION branch are split out of the
    chain and handed over per branch. They are alternatives -- one row takes one of
    them -- and stringing them together with "再" claimed the value was processed once
    per branch in sequence.
    """
    restated = [
        step
        for step in derivation
        if step.get("text")
        and str(step.get("step_type")) not in semantic_text.PASS_THROUGH_STEP_TYPES
    ]
    branch_steps = _branch_step_groups(restated)
    steps = [str(step["text"]) for step in restated if not step.get("branch")]
    notes = _source_notes(document, entry)
    sentence = semantic_text.describe_field_summary(
        target_comment=comment,
        step_texts=steps,
        direct_notes=notes,
        source_notes=notes,
        expression=entry.get("expression"),
        nullable_by_join=nullable,
        branch_steps=branch_steps,
    )
    # WI-2.2: appended, never merged in. The sentence above restates the contract; the
    # comment is the author quoted, and it is marked as a quotation so the two cannot be
    # read as one claim by this view.
    return semantic_text.append_sql_comment(sentence, alias_comments)


def _branch_step_groups(steps: Sequence[dict]) -> list[dict]:
    """The restated steps that happen inside a UNION branch, one entry per branch."""
    grouped: dict[str, list[str]] = {}
    branches: dict[str, dict] = {}
    for step in steps:
        branch = step.get("branch")
        if not branch:
            continue
        scope_id = str(step.get("scope_id"))
        branches[scope_id] = branch
        grouped.setdefault(scope_id, []).append(str(step["text"]))
    return [
        {**branches[scope_id], "texts": texts}
        for scope_id, texts in sorted(
            grouped.items(), key=lambda item: branches[item[0]]["index"]
        )
    ]


def _source_notes(document: dict, entry: dict) -> list[str]:
    """``<table>.<column>（<comment>）`` per physical source, plus the generated ones."""
    metadata = _input_metadata(document)
    notes = []
    for source in entry.get("physical_sources") or []:
        table, column = str(source.get("table") or ""), str(source.get("column") or "")
        if not table or not column:
            continue
        item = metadata.get(table) or {}
        notes.append(
            semantic_text.source_note(
                table,
                column,
                _column_detail(item, column).get("comment"),
                _table_comment(item),
            )
        )
    notes.extend(
        semantic_text.generated_source_text(item)
        for item in entry.get("generated_sources") or []
    )
    return _dedupe(notes)


def _nullable_join_inputs(document: dict) -> dict[str, list[str]]:
    """``input id -> the scopes that join it on an outer join's nullable side``.

    LEFT keeps the left rows, so its *right* input can come back all-NULL; RIGHT is the
    mirror; FULL nulls either side. INNER and CROSS null nothing, and a join type
    outside the vocabulary (SEMI / ANTI) is not guessed at.
    """
    nullable: dict[str, list[str]] = {}
    for scope_id, block in _logic_blocks(document):
        if str(block.get("logic_type")) != "join":
            continue
        detail = block.get("join_relation_detail") or {}
        join_type = str(detail.get("join_type") or "").upper()
        sides = []
        if join_type in semantic_text.NULLABLE_RIGHT_JOIN_TYPES:
            sides.append(detail.get("right_input"))
        if join_type in semantic_text.NULLABLE_LEFT_JOIN_TYPES:
            sides.append(detail.get("left_input"))
        for side in sides:
            if side:
                nullable.setdefault(str(side), []).append(scope_id)
    return nullable


def _nullable_by_join(
    entry: dict, chain: dict | None, nullable_inputs: dict[str, list[str]]
) -> bool:
    """True only when every value this field can hold arrives through a nullable side.

    Two provable shapes, and nothing else is flagged (WI-1f: 做不到严格判断的场景不标).
    In both, every step after the join must carry the value unchanged -- a COALESCE or
    a CASE downstream can fill the null in, and then the claim would be false.
    """
    steps = (chain or {}).get("ordered_steps") or []
    if not steps or not nullable_inputs:
        return False
    for index, step in enumerate(steps):
        scopes = nullable_inputs.get(str(step.get("scope_id"))) or []
        rest = steps[index + 1 :]
        if not scopes or not _all_pass_through(rest):
            continue
        if any(str(later.get("scope_id")) in scopes for later in rest):
            return True
    return _reads_only_nullable_tables(entry, steps, nullable_inputs)


def _nullable_argument(
    document: dict, entry: dict, chain: dict | None, context: dict
) -> dict | None:
    """The outer join that can empty an aggregate's *argument*, or None (WI-2.1 fix).

    ``_nullable_by_join`` asks whether the field's own value is carried through a
    nullable side unchanged, which an aggregate step ends. But MAX / MIN / SUM over a
    group whose join matched nothing is itself NULL, so an argument arriving through that
    side makes the metric nullable too. COUNT is the exception -- it answers 0 -- and a
    COALESCE or CASE ELSE from the aggregate onwards fills the null in before it lands.

    Two shapes, and nothing else is flagged: the argument was expanded from one upstream
    scope that the aggregate's own scope joins on a nullable side, or -- with no scope in
    between, so no resolution names one -- every physical table it reads is joined there.
    """
    steps = (chain or {}).get("ordered_steps") or []
    step = _aggregate_step(steps)
    if step is None or _counting_call(step):
        return None
    if _fills_null(steps[_step_position(steps, step) :]):
        return None
    scope_id = str(step.get("scope_id"))
    nullable_inputs = context["nullable_inputs"]
    resolution = step.get("expression_resolution") or {}
    source = str(resolution.get("source_scope_id") or "")
    if source:
        return (
            _nullable_join_detail(document, source, scope_id)
            if scope_id in (nullable_inputs.get(source) or [])
            else None
        )
    tables = _entry_tables(entry)
    if not tables or not all(
        scope_id in (nullable_inputs.get(table) or []) for table in tables
    ):
        return None
    return _nullable_join_detail(document, tables[0], scope_id)


def _counting_call(step: dict) -> bool:
    function, _ = semantic_text.aggregate_call_parts(step.get("expression_sql"))
    return str(function or "").upper() in METRIC_COUNTING_FUNCTIONS


def _fills_null(steps: Sequence[dict]) -> bool:
    """Whether any of these steps provably puts a value back where the join left none."""
    return any(
        semantic_text.null_fill_default(step.get("expression_sql"))[0] is not None
        for step in steps
    )


def _nullable_join_detail(document: dict, input_id: str, scope_id: str) -> dict | None:
    """Which side of which join in ``scope_id`` can null ``input_id`` out, for the card."""
    sides = (
        ("right", semantic_text.NULLABLE_RIGHT_JOIN_TYPES),
        ("left", semantic_text.NULLABLE_LEFT_JOIN_TYPES),
    )
    for owner, block in _logic_blocks(document):
        if owner != scope_id or str(block.get("logic_type")) != "join":
            continue
        detail = block.get("join_relation_detail") or {}
        join_type = str(detail.get("join_type") or "").upper()
        for side, types in sides:
            if join_type in types and str(detail.get(f"{side}_input")) == input_id:
                return {"scope_id": input_id, "join_type": join_type, "side": side}
    return None


def _all_pass_through(steps: Sequence[dict]) -> bool:
    return all(
        str(step.get("step_type")) in semantic_text.PASS_THROUGH_STEP_TYPES
        for step in steps
    )


def _reads_only_nullable_tables(
    entry: dict, steps: Sequence[dict], nullable_inputs: dict[str, list[str]]
) -> bool:
    """The physical-table form: the joined relation *is* the table, so no step names it."""
    tables = _dedupe(
        str(source.get("table"))
        for source in entry.get("physical_sources") or []
        if source.get("table")
    )
    if not tables or not _all_pass_through(steps):
        return False
    joining = [nullable_inputs.get(table) or [] for table in tables]
    return all(joining) and any(
        str(steps[0].get("scope_id")) in scopes for scopes in joining
    )


def _field_label(document: dict, entry: dict, chain: dict | None) -> str:
    """The reader-facing field name, using the mapping document's four naming cases."""
    target = str(document.get("target_table") or "")
    name = str(entry.get("column"))
    if target.startswith(_DIRECTORY_TARGET_PREFIX):
        return f"{name}（写入目录 {target[len(_DIRECTORY_TARGET_PREFIX):]}）"
    if chain is not None and not (chain.get("final_output_fields") or []):
        # Composing `<target>.<field>` here would fabricate a physical field id
        # (`mart.t._col_6`) that the target table never declared.
        if chain.get("name_is_generated") or entry.get("name_is_generated"):
            return f"{name}（匿名投影，未绑定目标列）"
        return f"{name}（未绑定目标列）"
    if document.get("stmt_kind") == "MERGE" and "merge_branch" in entry:
        return (
            f"{target}.{name}（merge:{entry.get('merge_branch')} "
            f"分支 {entry.get('merge_when_index')}）"
        )
    return f"{target}.{name}" if target else name


def _is_ambiguous(entry: dict) -> bool:
    if entry.get("ambiguities"):
        return True
    return any(
        str(source.get("table")) == "AMBIGUOUS"
        for source in entry.get("physical_sources") or []
    )


def _derivation(chain: dict | None, context: dict) -> list[dict]:
    """R4: one restated line per ordered step, with the verbatim expression beside it."""
    steps = []
    for step in (chain or {}).get("ordered_steps") or []:
        scope_id = str(step.get("scope_id"))
        expression = step.get("expression_sql")
        has_udf = bool(
            set(step.get("logic_ids") or []) & context["udf_blocks"]
        ) and semantic_text.has_unknown_function(expression) is not False
        branch = context["union_branches"].get(scope_id)
        steps.append(
            {
                "step_no": step.get("step_no"),
                "scope_id": scope_id,
                "step_type": step.get("step_type"),
                # WI-1g item D1: which UNION branch this step happens in, when it does.
                # Branch steps are alternatives to each other, not stages of one chain,
                # and a reader (or the markdown's folding) cannot tell that from the
                # scope id without decoding a naming convention.
                **({"branch": branch} if branch else {}),
                "grain": step.get("grain_effect"),
                "text": semantic_text.describe_step(
                    str(step.get("step_type")),
                    expression,
                    group_by_keys=context["group_by_keys"].get(scope_id, []),
                    input_fields=step.get("input_fields") or [],
                    has_udf=has_udf,
                    column_types=context["column_types"],
                ),
                "expression": expression,
            }
        )
    return steps


def _group_by_keys(document: dict, scope_id: str) -> list[str]:
    """One scope's GROUP BY items as the reader sees them written (WI-1g item A1).

    Each item is named by ``_item_label`` -- its own ``expression_sql`` without
    qualifiers -- for the same reason a window's PARTITION BY is: piercing to the
    physical roots turns one logical key into the four columns a UNION and a CASE read
    underneath it, and "按 customer_id、cust_no、seg_code、amount 分组聚合" states a
    grain the statement never wrote. The physical fact stays in the action's ``fields[]``
    and in ``grain.keys[].physical_sources``.
    """
    scope = _scopes(document).get(scope_id) or {}
    keys: list[str] = []
    for block in scope.get("logic_blocks") or []:
        if block.get("logic_type") != "group_by":
            continue
        for item in (block.get("aggregation_detail") or {}).get("group_by_items") or []:
            label = _item_label(item) or str(item.get("expression_sql") or "")
            if label:
                keys.append(label)
    return _dedupe(keys)


def _structural_role(
    document: dict, entry: dict, chain: dict | None, declared_type: str | None
) -> str:
    """R5, restricted to the roles provable without R3 (see the module docstring).

    The decision reads the whole chain, not the end-to-end ``transform``: that key is
    the LAST step's transform, so a field whose final step is a plain projection of an
    upstream ``MAX(CASE ...)`` looks DIRECT there while being an aggregate underneath.
    """
    steps = (chain or {}).get("ordered_steps") or []
    if _is_constant_field(entry):
        return "constant"
    if _is_conditional_label(entry, steps):
        return "conditional_label"
    temporal = _is_temporal(declared_type or _source_type(document, entry))
    functions = _chain_aggregate_functions(entry, steps)
    if functions or _has_aggregate_step(entry, steps):
        if functions & semantic_text.NUMERIC_AGGREGATE_FUNCTIONS:
            return "measure"
        if functions & semantic_text.SELECTIVE_AGGREGATE_FUNCTIONS and temporal:
            return "event_time"
        return "measure"
    if temporal:
        return "event_time"
    if _is_direct_passthrough(entry, steps):
        return "attribute"
    return "derived"


def _is_constant_field(entry: dict) -> bool:
    if entry.get("source_kind") == "generated":
        return True
    return bool(entry.get("generated_sources")) and not entry.get("physical_sources")


def _is_conditional_label(entry: dict, steps: Sequence[dict]) -> bool:
    """Only the field's *own* last CASE decides the role (WI-2.1d item 3).

    A chain interleaves threads: a grouping key's CASE and a measure's cap arrive in one
    ordered list because the measure's window reads the key. Asking whether *any*
    ``case_when`` step carries a constant label therefore let one thread's label set name
    the other thread's role, and ``CASE WHEN x > 0 THEN 0 ELSE x END`` -- a cap, which is
    a number -- was published as a label. The step that produces this field's value is
    its last conditional one; everything before it fed something else.
    """
    expressions = [
        step.get("expression_sql")
        for step in steps
        if str(step.get("step_type")) == "case_when"
    ]
    if not expressions and entry.get("transform") == "CONDITIONAL":
        expressions = [entry.get("expression")]
    return bool(expressions) and semantic_text.is_constant_label_case(expressions[-1])


def _chain_aggregate_functions(entry: dict, steps: Sequence[dict]) -> set:
    functions: set = set()
    for step in steps:
        functions |= semantic_text.aggregate_functions(step.get("expression_sql"))
    if not steps:
        functions |= semantic_text.aggregate_functions(entry.get("expression"))
    return functions


def _has_aggregate_step(entry: dict, steps: Sequence[dict]) -> bool:
    if any(str(step.get("transform")) == "AGGREGATE" for step in steps):
        return True
    return any(
        str(source.get("transform")) == "AGGREGATE"
        for source in entry.get("physical_sources") or []
    )


def _is_direct_passthrough(entry: dict, steps: Sequence[dict]) -> bool:
    if steps:
        return all(
            str(step.get("step_type")) in ("direct_projection", "union")
            for step in steps
        )
    return str(entry.get("transform")) == "DIRECT"


def _source_type(document: dict, entry: dict) -> str | None:
    """The declared type of the single physical source, when there is exactly one."""
    sources = entry.get("physical_sources") or []
    if len(sources) != 1:
        return None
    detail = _column_detail(
        _input_metadata(document).get(str(sources[0].get("table"))) or {},
        sources[0].get("column"),
    )
    return detail.get("type")


def _is_temporal(declared_type: str | None) -> bool:
    return str(declared_type or "").lower().startswith(_TEMPORAL_TYPE_PREFIXES)


# ------------------------------------------------------------ output shape (R2, R3)


def _build_output_shape(
    document: dict,
    metric_argument_scopes: Sequence[str] = (),
    table_cards: Mapping | None = None,
    metric_anchor_scopes: Sequence[str] = (),
) -> dict:
    shape, evidence = _classify_shape(document)
    grain, visited = _build_grain(document, shape, evidence)
    decided = _fan_out_risks(
        document,
        visited,
        metric_argument_scopes,
        _card_lookup(table_cards),
        metric_anchor_scopes,
    )
    risks = [risk for risk, _level in decided]
    keys, unexposed, key_evidence, confidence = _key_block(document, grain, decided)
    return {
        "shape": shape,
        "shape_evidence": evidence,
        "grain": grain,
        # A key set nothing proves is published as "no key", not as a key with a caveat:
        # `key_confidence` says how far the list can be trusted, and `none` means the
        # list itself is empty rather than quietly weaker than it looks.
        "candidate_keys": keys if confidence != KEY_CONFIDENCE_NONE else [],
        # Published whatever the confidence: a logical key that never reaches the target
        # is a fact about the write, not a weaker form of the candidate list.
        "unexposed_keys": unexposed,
        "key_evidence": key_evidence,
        "key_confidence": confidence,
        "partition_columns": list(document.get("target_partition_columns") or []),
        "fan_out_risks": risks,
        "tag": TAG_STRUCTURAL_INFERENCE,
    }


def _key_block(
    document: dict, grain: dict, decided: Sequence[tuple[dict, str | None]]
) -> tuple[list[str], list[dict], list[str], str]:
    """``(candidate key columns, unexposed keys, evidence, confidence)`` for one grain.

    Three filters in a row, each answering a different question about the same risks:
    only a grain-path risk bears on row identity at all (WI-2.1c item 5), only one
    downstream of the grain-deciding scope can duplicate a proven key set (B12), and a
    verdict that rests on a table card's *candidate* key caps whatever is left.
    """
    walked, upstream = _split_key_risks(grain, _grain_path_risks([r for r, _ in decided]))
    keys, unexposed, evidence = _target_key_columns(document, grain, walked)
    confidence = _capped_confidence(
        _key_confidence(grain, keys, unexposed, walked),
        [level for risk, level in decided if str(risk.get("path")) == METRIC_PATH_GRAIN],
    )
    if confidence != KEY_CONFIDENCE_NONE:
        evidence = [*evidence, *_upstream_fan_out_evidence(upstream)]
    return keys, unexposed, evidence, confidence


def _classify_shape(document: dict) -> tuple[str, list[str]]:
    """R2, by priority. Anything the structure does not prove stays ``unknown``."""
    if _ROOT not in _scopes(document):
        return SHAPE_UNKNOWN, []
    if str(document.get("stmt_kind")) == "MERGE":
        # A MERGE writes through its WHEN branches, not through a ROOT projection; the
        # row shape of the target is the merge semantics, which this view does not model.
        return SHAPE_UNKNOWN, [_ROOT]
    aggregating = _blocks_of_type(document, _ROOT, "group_by") or _blocks_of_type(
        document, _ROOT, "aggregate"
    )
    if aggregating:
        return SHAPE_AGGREGATED, _block_ids(aggregating)
    dedup = _root_dedup_evidence(document)
    if dedup:
        return SHAPE_DEDUPLICATED, dedup
    if _root_reads_only_union_scopes(document):
        return SHAPE_UNION_MERGE, sorted(
            str(item) for item in (_scopes(document)[_ROOT].get("depends_on") or [])
        )
    joins = _blocks_of_type(document, _ROOT, "join")
    if joins:
        return SHAPE_ENRICHED, _block_ids(joins)
    filters = _blocks_of_type(document, _ROOT, "filter")
    return SHAPE_FILTERED, _block_ids(filters) or [_ROOT]


def _root_reads_only_union_scopes(document: dict) -> bool:
    scopes = _scopes(document)
    inputs = [str(item) for item in scopes[_ROOT].get("depends_on") or []]
    if not inputs:
        return False
    return all(
        str((scopes.get(item) or {}).get("kind")) in ("union", "union_branch")
        for item in inputs
    )


def _root_dedup_evidence(document: dict) -> list[str]:
    """ROOT's own DISTINCT, or a ranking window ROOT itself filters to ``= 1``.

    A ``row_number() = 1`` inside a JOIN's ON clause deduplicates the *right side* of
    that join, not ROOT's output, so it is deliberately not read here -- it is read by
    the fan-out rule instead.
    """
    distinct = _blocks_of_type(document, _ROOT, "distinct")
    if distinct:
        return _block_ids(distinct)
    evidence: list[str] = []
    for scope_id, block_id, spec in _ranking_window_specifications(document):
        output = str(spec.get("output_field") or "")
        for entry in spec.get("filter_after_window") or []:
            if entry.get("scope_id") == _ROOT and _entry_keeps_first_row(entry, output):
                evidence.extend([block_id, str(entry.get("logic_block_id"))])
        if scope_id != _ROOT:
            continue
        for block in _blocks_of_type(document, _ROOT, "filter"):
            if _predicate_block_keeps_first_row(block, output):
                evidence.extend([block_id, str(block.get("logic_block_id"))])
    return _dedupe(evidence)


def _ranking_window_specifications(document: dict) -> list[tuple[str, str, dict]]:
    """``(scope_id, logic_block_id, window_specification)`` for row_number/rank/dense_rank."""
    found = []
    for scope_id, block in _logic_blocks(document):
        spec = block.get("window_specification") or {}
        function = str(spec.get("window_function") or "").lower()
        if function in semantic_text.RANKING_WINDOW_FUNCTIONS:
            found.append((scope_id, str(block.get("logic_block_id")), spec))
    return found


def _entry_keeps_first_row(entry: dict, output_field: str) -> bool:
    """A ``filter_after_window`` / ``condition_filters`` entry that tests ``<col> = 1``."""
    named = any(
        str(field.get("column")) == output_field for field in entry.get("fields") or []
    )
    return named and semantic_text.equals_one_predicate(
        entry.get("expression"), output_field
    )


def _predicate_block_keeps_first_row(block: dict, output_field: str) -> bool:
    detail = block.get("filter_predicate_detail") or {}
    conjuncts = detail.get("conjuncts") or [{"expression": block.get("raw_expression")}]
    return any(
        semantic_text.equals_one_predicate(item.get("expression"), output_field)
        for item in conjuncts
    )


def _build_grain(
    document: dict, shape: str, shape_evidence: Sequence[str]
) -> tuple[dict, list[str]]:
    """R3's answer, with B9's pin markers and, when it gave up, B3's candidate."""
    grain, visited = _decide_grain(document, shape, shape_evidence)
    pinned = _with_pinned_keys(document, grain)
    candidate = _grain_candidate(document, pinned)
    return ({**pinned, "candidate": candidate} if candidate else pinned), visited


def _decide_grain(
    document: dict, shape: str, shape_evidence: Sequence[str]
) -> tuple[dict, list[str]]:
    """R3, as ``(grain, the scopes the walk visited)``.

    Two shapes R2 already decided are answered from R2 instead of being re-walked: a
    MERGE (and any document without a ROOT) writes through branch semantics this view
    does not model, and a ROOT that filters a ranking window to ``= 1`` is unique by
    that window's partition keys -- a *stronger* statement than the driving table's rows,
    which is what the walk would otherwise report after crossing the row-preserving
    filter. Everything else is the recursive walk.
    """
    root_visited = [_ROOT] if _ROOT in _scopes(document) else []
    if shape == SHAPE_UNKNOWN:
        return _grain([], BASIS_UNKNOWN, shape_evidence), root_visited
    if shape == SHAPE_DEDUPLICATED:
        keys = _root_dedup_logical_keys(document)
        if keys:
            return _grain(keys, BASIS_WINDOW_PARTITION, shape_evidence), root_visited
    return _resolve_grain(document)


def _resolve_grain(document: dict, start: str = _ROOT) -> tuple[dict, list[str]]:
    """Walk from ``start`` (ROOT, unless B3 asks about one layer of it) to whatever sets
    the output's row count.

    Each step asks one scope the same question, so ROOT is not a special case: a scope
    that groups, or deduplicates, answers with its own key set; a scope that only
    filters, windows or projects hands the question to its single input; a scope that
    joins hands it to its FROM item, and the joins it carries become fan-out risks. A
    physical table ends the walk with its own rows, because no input in this contract
    declares a primary key. Anything else stops with the reason it stopped.
    """
    scopes = _scopes(document)
    tables = set(document.get("source_tables") or [])
    visited: list[str] = []
    item = start
    for _ in range(GRAIN_DEPTH_LIMIT):
        if item in tables:
            path = visited[1:]
            return _grain([], BASIS_DRIVING_TABLE_ROWS, [*path, item], path), visited
        if item in visited:
            return _unknown_grain(f"驱动输入 {item} 自引用成环", visited[1:]), visited
        if item not in scopes:
            return _unknown_grain(f"驱动输入 {item} 不是本语句的 scope", visited[1:]), visited
        visited.append(item)
        basis, keys, evidence, following = _scope_grain(document, item)
        if following is None:
            return _grain(keys, str(basis), evidence, visited[1:-1]), visited
        item = following
    return (
        _unknown_grain(f"穿透层数超过上限 {GRAIN_DEPTH_LIMIT}", visited[1:]),
        visited,
    )


def _scope_grain(
    document: dict, scope_id: str
) -> tuple[str | None, list[dict], list[str], str | None]:
    """One scope's own verdict as ``(basis, keys, evidence, input to descend into)``.

    ``basis`` is None exactly when there is an input to descend into. A window is not a
    row-count change -- ``row_number() OVER (...)`` labels the rows it is given and
    returns every one of them -- so a window-only scope descends like any projection.
    """
    blocks = _scope_blocks(document, scope_id)
    types = {str(block.get("logic_type")) for block in blocks}
    # The same two types, asked in the same order, as R2's own aggregation test.
    aggregating = _blocks_of_type(document, scope_id, "group_by") or _blocks_of_type(
        document, scope_id, "aggregate"
    )
    if aggregating:
        keys = _aggregation_logical_keys(document, scope_id) or []
        # B10: no GROUP BY clause at all is an *empty grouping set*, not a missing key
        # list -- the relation collapses to one row. A GROUP BY that is present and
        # resolved to nothing is a different, undecided case and keeps its old answer.
        if not keys and not _blocks_of_type(document, scope_id, "group_by"):
            return BASIS_SINGLE_ROW, [], _block_ids(aggregating), None
        return BASIS_GROUP_BY, keys, _block_ids(aggregating), None
    if "distinct" in types:
        distinct = _blocks_of_type(document, scope_id, "distinct")
        return (
            BASIS_DISTINCT,
            _distinct_logical_keys(document, scope_id),
            _block_ids(distinct),
            None,
        )
    blocker = _grain_blocker(document, scope_id, types)
    if blocker:
        return BASIS_UNKNOWN, [], [blocker], None
    # Whatever is left keeps its input's rows one for one -- a filter drops whole rows
    # and a projection or window rewrites columns -- so the question moves to the FROM
    # item. A scope with no JOIN has exactly one candidate when it reads one input, and
    # the same rule reports the same reason when it reads several.
    item, reason = _scope_from_item(document, scope_id)
    if item is None:
        return BASIS_UNKNOWN, [], [str(reason)], None
    return None, [], [], item


def _grain_blocker(document: dict, scope_id: str, types: set) -> str | None:
    """Why one scope's row count cannot be carried back to a single input, or None.

    A LATERAL VIEW is read on the scope that carries it *and* on the scope that reads
    one: the contract gives the UDTF its own scope, so the scope doing the expanding
    reads both the base relation and the UDTF output, and neither is "the FROM item".
    """
    if "union" in types or (_scopes(document).get(scope_id) or {}).get(
        "union_branch_alignment"
    ):
        return f"{scope_id} 含 UNION（行数为各分支之和，非单一上游行数）"
    if _has_lateral_view(document, scope_id):
        return f"{scope_id} 含 LATERAL VIEW（行数展开）"
    inputs = _scope_inputs(document, scope_id)
    expanded = [item for item in inputs if _has_lateral_view(document, item)]
    if expanded:
        return f"{scope_id} 读取含 LATERAL VIEW 的 {'、'.join(expanded)}（行数展开）"
    if _AMBIGUOUS in inputs:
        return f"{scope_id} 的输入含 {_AMBIGUOUS}（裸列多源歧义），驱动输入无从判定"
    return None


def _has_lateral_view(document: dict, scope_id: str) -> bool:
    if _blocks_of_type(document, scope_id, "lateral_view"):
        return True
    step = next(
        (item for item in _profile_steps(document) if str(item.get("scope_id")) == scope_id),
        {},
    )
    return bool((step.get("logic") or {}).get("lateral_views"))


def _scope_inputs(document: dict, scope_id: str) -> list[str]:
    return [
        str(item) for item in (_scopes(document).get(scope_id) or {}).get("depends_on") or []
    ]


def _distinct_logical_keys(document: dict, scope_id: str) -> list[dict]:
    """A DISTINCT scope is unique by its whole output list: one logical key per output.

    ``DISTINCT CONCAT(a, b)`` is unique by the concatenation, not by ``a`` and ``b``
    separately, so the two physical columns are the key's *sources* rather than two keys.
    """
    return _dedupe(
        _key_object(
            scope_id,
            output.get("name"),
            output.get("expression"),
            output.get("expression_resolution"),
        )
        for output in (_scopes(document).get(scope_id) or {}).get("outputs") or []
    )


def _aggregation_logical_keys(document: dict, scope_id: str) -> list[dict] | None:
    """One aggregating scope's GROUP BY items as logical keys, or None when it does not
    aggregate.

    An empty list is a real answer: a scope that aggregates without GROUP BY returns one
    row for the whole relation. Each GROUP BY *item* is one key however many physical
    columns its expression reads -- ``GROUP BY CASE ... END`` is one key, not four.
    """
    group_by = _blocks_of_type(document, scope_id, "group_by")
    if not group_by:
        return [] if _blocks_of_type(document, scope_id, "aggregate") else None
    names = _output_name_index(document, scope_id)
    return _dedupe(
        _item_key(scope_id, names, item)
        for block in group_by
        for item in (block.get("aggregation_detail") or {}).get("group_by_items") or []
    )


def _root_dedup_logical_keys(document: dict) -> list[dict]:
    """The partition items of every ranking window ROOT filters to ``= 1``."""
    evidence = _root_dedup_evidence(document)
    keys: list[dict] = []
    for scope_id, block_id, spec in _ranking_window_specifications(document):
        if block_id not in evidence:
            continue
        names = _output_name_index(document, scope_id)
        keys.extend(
            _partition_item_key(scope_id, names, item)
            for item in spec.get("partition_by") or []
        )
    return _dedupe(keys)


def _partition_item_key(scope_id: str, names: dict, item: dict) -> dict:
    """One PARTITION BY item as a dedup key of ``scope_id``, named as that scope writes it.

    Unlike a GROUP BY item, a partition item is quoted back to the reader as the dedup
    key itself, so ``expression`` stays logical: ``PARTITION BY band`` deduplicates by
    ``band``, whatever ``band`` is derived from. The pierced columns remain in
    ``physical_sources``.

    The *name* is looked up from the item's written forms as well as from that label
    (WI-2.1d item 1). The label drops qualifiers and the output index is keyed by the
    text the scope wrote, so a ``PARTITION BY CASE ... END`` that the scope also projects
    was coming back unnamed -- and an unnamed key cannot be compared with the column an
    ON clause reads.
    """
    return _key_object(
        scope_id, _item_name(names, item), _item_label(item), item.get("expression_resolution")
    )


def _item_key(scope_id: str, names: dict, item: dict) -> dict:
    """One GROUP BY / PARTITION BY item as a logical key of ``scope_id``."""
    return _key_object(
        scope_id,
        _item_name(names, item),
        item.get("expression_sql"),
        item.get("expression_resolution") or {},
    )


def _item_name(names: dict, item: dict) -> str | None:
    """The output column this item is projected as, or None when it is not projected."""
    written = (
        item.get("expression_sql"),
        item.get("expanded_expression"),
        (item.get("expression_resolution") or {}).get("expanded_expression"),
        _item_label(item),
    )
    return next(
        (
            names[_normalized_expression(text)]
            for text in written
            if text and _normalized_expression(text) in names
        ),
        None,
    )


def _key_object(scope_id: str, name, expression, resolution) -> dict:
    """The published logical-key shape. ``name`` is None when the item is not projected."""
    return {
        "scope_id": str(scope_id),
        "name": str(name) if name else None,
        "expression": str(expression) if expression else None,
        "physical_sources": [
            {"table": table, "column": column}
            for table, column in _physical_fields(resolution)
        ],
    }


def _output_name_index(document: dict, scope_id: str) -> dict[str, str]:
    """Normalised output expression -> the output column name it is published under.

    Expressions are registered first and bare names second, so a column whose expression
    matches wins over a column that merely shares the item's spelling.
    """
    outputs = (_scopes(document).get(scope_id) or {}).get("outputs") or []
    index: dict[str, str] = {}
    for output in outputs:
        for text in (output.get("expression"), output.get("expanded_expression")):
            if output.get("name") and text:
                index.setdefault(_normalized_expression(text), str(output["name"]))
    for output in outputs:
        if output.get("name"):
            name = str(output["name"])
            index.setdefault(_normalized_expression(name), name)
    return index


def _normalized_expression(text) -> str:
    """Whitespace-collapsed and unwrapped, so ``(expr)`` and ``expr`` compare equal."""
    value = " ".join(str(text).split())
    while value.startswith("(") and value.endswith(")") and _wraps_whole(value):
        value = value[1:-1].strip()
    return value


def _wraps_whole(value: str) -> bool:
    """True when the leading ``(`` closes only at the very end of ``value``."""
    depth = 0
    for index, char in enumerate(value):
        depth += (char == "(") - (char == ")")
        if depth == 0:
            return index == len(value) - 1
    return False


# ------------------------------------------------- equality-pinned columns (B9)


def _scope_pins(document: dict, scope_id: str) -> dict[str, str]:
    """``lowered column -> the value text`` for one scope's own WHERE equality pins.

    Only the contract's AND-split ``conjuncts`` are read, so a predicate nested inside an
    OR is never a pin: the contract splits on ``AND`` alone, which leaves ``a = 1 OR
    b = 2`` whole, and an OR does not parse as an equality. HAVING is a separate logic
    type and is not read here -- it filters groups that already exist.
    """
    pins: dict[str, str] = {}
    for block in _blocks_of_type(document, scope_id, "filter"):
        detail = block.get("filter_predicate_detail") or {}
        for conjunct in detail.get("conjuncts") or []:
            parsed = semantic_text.equality_conjunct(conjunct.get("expression"))
            if parsed and parsed[2] in _PINNING_VALUE_KINDS:
                pins.setdefault(parsed[0].lower(), parsed[1])
    return pins


def _pinned_columns(document: dict, scope_id: str) -> dict[str, dict]:
    """Every column that cannot vary inside ``scope_id``, as ``lowered name -> record``.

    B9. A scope's own WHERE is read first, then the walk follows the FROM item down: a
    column a CTE pins and passes through unchanged is just as constant one layer up, and
    the driving path is the only direction a value travels without being recomputed. A
    scope on the way that renames or rewrites the column ends the descent *for that
    column*, so a pin can never be carried across an expression that could map two days
    onto one value.
    """
    pinned: dict[str, dict] = {}
    crossed: list[str] = []
    item = scope_id
    for _ in range(GRAIN_DEPTH_LIMIT):
        if item not in _scopes(document) or item in crossed:
            break
        for column, value in _scope_pins(document, item).items():
            if column in pinned or not _carried_through(document, crossed, column):
                continue
            pinned[column] = {"scope_id": item, "column": column, "value": value}
        following, _ = _scope_from_item(document, item)
        if following is None:
            break
        crossed.append(item)
        item = following
    return pinned


def _carried_through(document: dict, scopes: Sequence[str], column: str) -> bool:
    """True when every scope on the path publishes ``column`` as that very column."""
    return all(_carries_column_unchanged(document, item, column) for item in scopes)


def _carries_column_unchanged(document: dict, scope_id: str, column: str) -> bool:
    """One scope publishes ``column`` under its own name, from a bare reference to it.

    A scope with no output list states nothing either way -- a ``SELECT *`` that the
    contract could not expand -- and is read as transparent, because the alternative is
    to drop a pin the SQL plainly wrote.
    """
    outputs = (_scopes(document).get(scope_id) or {}).get("outputs") or []
    for output in outputs:
        if str(output.get("name") or "").lower() != column:
            continue
        text = output.get("expression") or output.get("name")
        return _bare_column_name(text) == column
    return not outputs


def _bare_column_name(text) -> str | None:
    """The unqualified name when ``text`` is a column reference, else None."""
    value = _normalized_expression(text or "")
    if not value or not _BARE_COLUMN.fullmatch(value):
        return None
    return value.split(".")[-1].strip('`"').lower()


def _key_column_name(key: dict) -> str | None:
    """A logical key's own column name, when the key *is* a column rather than reads one.

    The expression is asked first and the output name only when there is none: a CASE
    key projected as ``dt`` is named ``dt`` while being a different value from ``dt``,
    and dropping it because ``dt`` is pinned would throw away a real key.
    """
    return _bare_column_name(key.get("expression") or key.get("name"))


def _unpinned_keys(
    document: dict, scope_id: str, keys: Sequence[dict]
) -> tuple[list[dict], list[dict]]:
    """``(the keys that can still vary, the pin records for the ones that cannot)``."""
    pinned = _pinned_columns(document, scope_id)
    kept: list[dict] = []
    dropped: list[dict] = []
    for key in keys:
        name = _key_column_name(key)
        record = pinned.get(name) if name else None
        if record is None:
            kept.append(key)
        elif record not in dropped:
            dropped.append(record)
    return kept, dropped


def _pin_note(pinned: Sequence[dict]) -> str:
    """How a verdict sentence names the columns it dropped, or "" when it dropped none."""
    if not pinned:
        return ""
    named = "、".join(
        f"{item['column']} 被等值过滤钉死为 {item['value']}" for item in pinned
    )
    return f"（{named}，不计入键集）"


def _with_pinned_keys(document: dict, grain: dict) -> dict:
    """Mark every grain key its own scope pins to one value, without removing it.

    The reader asking "what does one row represent" still wants the partition day
    named, so the key stays in ``grain.keys`` carrying the value it is pinned to. The
    *unique* key set drops it instead -- that is what the fan-out verdict and
    :func:`_target_key_columns` read, through this same marker.
    """
    pins: dict[str, dict] = {}
    keys = []
    for key in grain.get("keys") or []:
        scope_id = str(key.get("scope_id"))
        if scope_id not in pins:
            pins[scope_id] = _pinned_columns(document, scope_id)
        record = pins[scope_id].get(_key_column_name(key) or "")
        keys.append({**key, "pinned": {"value": record["value"]}} if record else key)
    return {**grain, "keys": keys}


# ------------------------------------------------------ grain candidate (B3)


def _grain_candidate(document: dict, grain: dict) -> dict | None:
    """B3: what one row probably is, when a row-multiplying step stopped the walk.

    ``unknown`` stays the verdict -- an explode really does make the row count
    unprovable -- but it is not the whole of what the structure says. When the driving
    path crosses a LATERAL VIEW whose own upstream grain *is* decided, the shape of the
    answer follows: one upstream row per exploded value. That is published beside the
    verdict as a hypothesis, so the profile writer copies it and marks it inferred
    instead of inventing a grain of their own, which is what they did on the corpus.

    Nothing is offered where the hypothesis would not be one: a decided grain, several
    driving tables (a UNION's rows are a sum, not a product), a stop with some other
    cause, an upstream grain that is itself ``unknown``, or a shape whose rows are not
    counted from a table at all -- a MERGE's row shape is its branch semantics, and P3's
    widening of the path must not turn that into a guess at a row count.
    """
    if str(grain.get("basis")) != BASIS_UNKNOWN:
        return None
    if _classify_shape(document)[0] not in _ROW_COUNT_SHAPES:
        return None
    branches = _driving_branches(document)
    if len(branches) != 1 or not branches[0]["lateral_view_scopes"]:
        return None
    branch = branches[0]
    below = _below_expansion(branch)
    upstream, _visited = _resolve_grain(document, below)
    basis = str(upstream["basis"])
    if basis == BASIS_UNKNOWN:
        return None
    return {
        "keys": [
            *upstream["keys"],
            *_exploded_keys(document, branch["lateral_view_scopes"]),
        ],
        # Named only when the upstream grain is a table's own rows: that grain has no
        # key list of its own, and "one row per <nothing> per exploded value" is not an
        # answer. Every other basis carries its keys and leaves this null.
        "row_source": below if basis == BASIS_DRIVING_TABLE_ROWS else None,
        "basis": BASIS_CANDIDATE,
        "confidence": CONFIDENCE_HYPOTHESIS,
        "reason": _candidate_reason(branch, below, basis),
        "evidence": list(branch["lateral_view_scopes"]),
    }


def _below_expansion(branch: dict) -> str:
    """The item the driving path reaches just below its deepest LATERAL VIEW.

    Deepest rather than first: two stacked explodes both multiply, and the grain the
    candidate builds on is the one below every one of them.
    """
    chain = [_ROOT, *branch["via_scopes"], branch["table"]]
    deepest = max(chain.index(item) for item in branch["lateral_view_scopes"])
    return chain[deepest + 1]


def _exploded_keys(document: dict, scopes: Sequence[str]) -> list[dict]:
    """One logical key per column the LATERAL VIEWs on the path add, upstream first."""
    keys: list[dict] = []
    for scope_id in reversed(list(scopes)):
        for udtf in _lateral_view_inputs(document, scope_id):
            keys.extend(
                _key_object(
                    udtf,
                    output.get("name"),
                    output.get("expression"),
                    output.get("expression_resolution"),
                )
                for output in (_scopes(document).get(udtf) or {}).get("outputs") or []
            )
    return keys


def _candidate_reason(branch: dict, below: str, upstream_basis: str) -> str:
    """Why this is only a candidate, in the same structural words the verdict uses."""
    path = " → ".join(reversed(branch["lateral_view_scopes"]))
    return f"{path} 的 LATERAL VIEW 使行数展开；展开前 {below} 的粒度依据 {upstream_basis}"


def _unknown_grain(reason: str, via_scopes: Sequence[str]) -> dict:
    return _grain([], BASIS_UNKNOWN, [reason], via_scopes)


def _grain(
    keys: Sequence[str],
    basis: str,
    evidence: Sequence[str],
    via_scopes: Sequence[str] = (),
) -> dict:
    return {
        "keys": list(keys),
        "basis": basis,
        "via_scopes": [str(item) for item in via_scopes],
        "confidence": "structural",
        "evidence": [str(item) for item in evidence],
    }


def _scope_from_item(document: dict, scope_id: str) -> tuple[str | None, str | None]:
    """One scope's FROM item: the direct input no JOIN in it names as its ``right_input``.

    An input that is only ever a JOIN's right side is joined *to* the FROM item, not the
    FROM item itself. A self join reads one input on both sides, so being a right input
    only disqualifies an input that is never a left one.

    Zero or several candidates prove nothing about which input sets the row count -- a
    semi-join subquery in WHERE is a dependency too, and it is not the FROM item -- so
    the caller is handed the reason instead of a guess.
    """
    inputs = _scope_inputs(document, scope_id)
    sides = {
        side: {
            str((block.get("join_relation_detail") or {}).get(f"{side}_input") or "")
            for block in _blocks_of_type(document, scope_id, "join")
        }
        for side in ("left", "right")
    }
    candidates = [
        item for item in inputs if item not in sides["right"] or item in sides["left"]
    ]
    if len(candidates) == 1:
        return candidates[0], None
    return None, f"{scope_id} 的 FROM 项无法唯一确定（候选：{'、'.join(candidates) or '无'}）"


def _driving_source(document: dict) -> tuple[str | None, list[str], str | None]:
    """R3's driving side as ``(physical table, scopes pierced through, failure reason)``.

    A thin reading of the same walk ``output_shape`` publishes, for the two callers that
    want the table rather than the grain: R1's summary sentence and R7's driving role.
    Only a ``driving_table_rows`` grain names a table; every other basis answers with
    the reason, so neither caller can turn an aggregated upstream into "the main table".
    """
    grain, _ = _build_grain(document, *_classify_shape(document))
    evidence = grain["evidence"]
    if grain["basis"] != BASIS_DRIVING_TABLE_ROWS:
        return None, [], evidence[0] if evidence else None
    return evidence[-1], list(grain["via_scopes"]), None


def _target_key_columns(
    document: dict, grain: dict, risks: Sequence[dict]
) -> tuple[list[str], list[dict], list[str]]:
    """WI-1e: ``(target columns, logical keys the target never receives, evidence)``.

    The reader's question is which *target* columns identify a row, so every logical key
    is followed down the mapping chains and published under the column it lands on. A
    key that only reaches the target through an expression -- a COALESCE, a CASE -- maps
    distinct keys onto one value and is reported as unexposed instead of as a key.
    """
    exposed = _exposed_target_columns(document)
    basis = str(grain.get("basis"))
    unexposed: list[dict] = []
    notes: list[str] = []
    if basis in _PROVEN_BASES:
        columns: list[str] = []
        for key in grain.get("keys") or []:
            # B9: a column pinned to one value identifies nothing, so it is neither a
            # candidate key nor a governance finding when the write leaves it out.
            if key.get("pinned"):
                continue
            target = exposed.get(_key_reference(key))
            if target:
                columns.append(target)
                continue
            unexposed.append(key)
            notes.append(f"键 {_key_label(key)} 未直投到目标表列")
    elif basis == BASIS_DRIVING_TABLE_ROWS:
        columns, notes = _driving_key_columns(document, grain, risks, exposed)
    else:
        return [], [], []
    kept, dropped = _without_partition_columns(document, _dedupe(columns))
    return kept, unexposed, _dedupe([*notes, *dropped])


def _driving_key_columns(
    document: dict, grain: dict, risks: Sequence[dict], exposed: dict
) -> tuple[list[str], list[str]]:
    """A driving-table grain has no key of its own -- no input declares a primary key.

    The only candidate it can offer is the driving side of a JOIN every one of whose
    right sides is provably unique by the join keys, every ROOT join agreeing on the
    same key set, and every one of those keys actually written to the target.
    """
    if not risks or any(str(risk["status"]) != "safe" for risk in risks):
        return [], []
    driving = str((grain.get("evidence") or [""])[-1])
    key_sets = [
        _driving_side_keys(block.get("join_relation_detail") or {}, driving)
        for block in _blocks_of_type(document, _ROOT, "join")
    ]
    if not key_sets or not all(key_sets) or any(keys != key_sets[0] for keys in key_sets):
        return [], []
    columns = [exposed.get(key) for key in key_sets[0]]
    if not all(columns):
        return [], [
            f"主表连接键 {key} 未输出到目标表"
            for key, column in zip(key_sets[0], columns)
            if not column
        ]
    return [str(column) for column in columns], []


def _exposed_target_columns(document: dict) -> dict[str, str]:
    """``<owner>.<column>`` -> the target column it reaches by pass-through steps alone.

    Each chain is read from its last step backwards: the step that *produces* a value
    may be any expression, but every step after it must carry the value unchanged, so
    the walk stops at the first step that does not.
    """
    columns = {
        entry.get("output_ordinal"): str(entry.get("column"))
        for entry in document.get("end_to_end_lineage") or []
        if entry.get("column")
    }
    exposed: dict[str, str] = {}
    for chain in document.get("field_mapping_chains") or []:
        steps = chain.get("ordered_steps") or []
        target = columns.get(chain.get("target_position"))
        if not steps or not target:
            continue
        if str(steps[-1].get("scope_id")) == _ROOT and chain.get("target_field"):
            exposed.setdefault(f"{_ROOT}.{chain['target_field']}", target)
        for step in reversed(steps):
            exposed.setdefault(str(step.get("output_field")), target)
            inputs = [str(item) for item in step.get("input_fields") or []]
            if str(step.get("step_type")) not in _PASS_THROUGH_STEP_TYPES:
                break
            if len(inputs) != 1:
                break
            exposed.setdefault(inputs[0], target)
    return exposed


def _key_reference(key: dict) -> str:
    """The ``<scope>.<column>`` the exposure map is keyed by, or "" for an unnamed key."""
    name = key.get("name")
    return f"{key.get('scope_id')}.{name}" if name else ""


def _key_label(key: dict) -> str:
    """How one logical key is named to a reader: its output column, else its expression."""
    return _key_reference(key) or str(key.get("expression") or key.get("scope_id"))


def _without_partition_columns(
    document: dict, columns: Sequence[str]
) -> tuple[list[str], list[str]]:
    """Partition columns are metadata, not inferred keys, so they are never counted."""
    partitions = {str(item) for item in document.get("target_partition_columns") or []}
    kept = [column for column in columns if column not in partitions]
    notes = [
        f"目标列 {column} 是分区列，不计入候选键"
        for column in columns
        if column in partitions
    ]
    return kept, notes


def _key_confidence(
    grain: dict, keys: Sequence[str], unexposed: Sequence[dict], risks: Sequence[dict]
) -> str:
    """How far the published key set can be trusted (WI-1d, extended by WI-1e).

    ``proven`` is the strong claim and needs three things at once: a basis whose
    operation makes the keys unique (GROUP BY, DISTINCT, or a ranking window filtered to
    ``= 1``), a walk that crossed no unproven JOIN *after* the operation made them
    unique, and every one of those keys written to the target. When only the last fails,
    the keys are still proven but the *target* columns are not, and ``proven_unexposed``
    says exactly that.

    B12 is the "after" in the second condition, and :func:`_split_key_risks` decided it
    before the list arrived here: a JOIN feeding the grouping duplicates the rows being
    grouped, which inflates the aggregated numbers without adding one row to the output.
    A ``driving_table_rows`` grain has no operation making anything unique, so its list
    is unfiltered and a fan-out anywhere on its path still costs it the key.
    """
    basis = str(grain.get("basis"))
    # B10, asked before the risks: "the output is one row" is a statement about the
    # grouping set, and a JOIN that duplicates the rows being counted inflates the
    # number without adding a row to the output.
    if basis == BASIS_SINGLE_ROW:
        return KEY_CONFIDENCE_PROVEN
    if any(str(risk.get("status")) != "safe" for risk in risks):
        return KEY_CONFIDENCE_NONE
    if basis in _PROVEN_BASES:
        if not grain.get("keys"):
            return KEY_CONFIDENCE_NONE
        return KEY_CONFIDENCE_PROVEN_UNEXPOSED if unexposed else KEY_CONFIDENCE_PROVEN
    if basis == BASIS_DRIVING_TABLE_ROWS and keys:
        return KEY_CONFIDENCE_CANDIDATE
    return KEY_CONFIDENCE_NONE


def _split_key_risks(
    grain: dict, risks: Sequence[dict]
) -> tuple[list[dict], list[dict]]:
    """B12: ``(risks the key set answers for, risks the grain's operation made harmless)``.

    A GROUP BY, a DISTINCT or a ranking dedup makes its key set unique *in the output*,
    however many rows a JOIN upstream of it handed the operation -- the duplication
    inflates the aggregated values, which the metric-path risks report on their own, and
    adds no row to the output. Only a JOIN strictly downstream of the grain-deciding
    scope can multiply rows the operation already made unique. Every risk stays
    published either way; this only says which ones the key decision reads.
    """
    if str(grain.get("basis")) not in _PROVEN_BASES:
        return list(risks), []
    downstream = _scopes_below_grain(grain)
    kept: list[dict] = []
    upstream: list[dict] = []
    for risk in risks:
        harmless = (
            str(risk.get("status")) != "safe"
            and str(risk.get("scope_id")) not in downstream
        )
        (upstream if harmless else kept).append(risk)
    return kept, upstream


def _scopes_below_grain(grain: dict) -> set[str]:
    """The scopes the rows pass through *after* the grain-deciding scope emitted them.

    ``via_scopes`` is the grain walk's descent order with neither end in it, so ROOT in
    front of it is the whole chain from the output down to the scope that decided the
    grain, and everything before that scope is what can still duplicate its rows.
    """
    chain = [_ROOT, *(str(item) for item in grain.get("via_scopes") or [])]
    scope = _grain_scope(grain)
    return set(chain[: chain.index(scope)] if scope in chain else chain)


def _grain_scope(grain: dict) -> str | None:
    """Which scope decided the grain: its keys all name it, else its evidence id does."""
    for key in grain.get("keys") or []:
        return str(key.get("scope_id"))
    for item in grain.get("evidence") or []:
        return _scope_of_logic_block(item) or None
    return None


def _upstream_fan_out_evidence(risks: Sequence[dict]) -> list[str]:
    """Why a published key survived a JOIN the profile still reports as a risk."""
    return [
        semantic_text.upstream_fan_out_note(scope)
        for scope in _dedupe(str(risk.get("scope_id")) for risk in risks)
    ]


def _driving_side_keys(detail: dict, driving_table: str) -> list[str]:
    keys = [
        f"{field.get('table')}.{field.get('field')}"
        for pair in detail.get("join_key_pairs") or []
        for side in ("left_fields", "right_fields")
        for field in pair.get(side) or []
        if str(field.get("table")) == driving_table
    ]
    return _dedupe(keys)


# ------------------------------------------------------------- fan-out risk (R3)


def _fan_out_risks(
    document: dict,
    scope_ids: Sequence[str],
    argument_scope_ids: Sequence[str] = (),
    card_lookup=None,
    anchor_scope_ids: Sequence[str] = (),
) -> list[tuple[dict, str | None]]:
    """Every JOIN on the grain walk's path, then every JOIN on a metric argument path.

    ROOT's joins were always here; the walk adds the ones it crossed on the way down,
    because a fan-out two CTEs deep duplicates the rows ROOT projects just as surely as
    one in ROOT itself.

    WI-2.1c item 5 adds the second list. A JOIN that only feeds a metric's *argument*
    never changes the output's row count, so the grain walk rightly refuses to go
    there -- but duplicating the rows a ``SUM`` reads inflates that number all the same,
    which is a wrong value rather than extra rows. Each entry says which path it is on
    so the two are never read as one claim. A join in a scope none of the paths reached
    is still not listed: nothing proves its rows reach the output.

    WI-9 legacy a adds the third list, for the joins the first two structurally cannot
    reach: once a metric anchors to its own aggregating scope, the grain path starts
    there and follows driving inputs, so a lookup that anchor joins in -- and every JOIN
    inside that lookup -- was judged by nobody. They are the anchor's input subtree.
    """
    grain = _dedupe(scope_ids)
    seen = set(grain)
    argument = [item for item in _dedupe(argument_scope_ids) if item not in seen]
    seen.update(argument)
    anchor = [item for item in _dedupe(anchor_scope_ids) if item not in seen]
    return [
        _fan_out_risk(document, scope_id, block, path, card_lookup)
        for path, walked in (
            (METRIC_PATH_GRAIN, grain),
            (METRIC_PATH_ARGUMENT, argument),
            (METRIC_PATH_ANCHOR, anchor),
        )
        for scope_id in walked
        for block in _blocks_of_type(document, scope_id, "join")
    ]


def _grain_path_risks(risks: Sequence[dict]) -> list[dict]:
    """The risks that bear on row *identity*, i.e. the ones on the grain walk's path.

    WI-2.1c item 5 gave every risk a ``path``, and the key set never learned to read it.
    A JOIN that only feeds a metric's argument duplicates the rows a ``SUM`` reads, which
    makes that number wrong -- it does not duplicate a row of the output, so it cannot
    change which columns identify one. Letting it cost the statement its keys withdrew
    the strongest claim the profile can make (``proven``) over a different question, and
    left the reader with no key set at all rather than a key set and a caveat. The risk
    stays published either way; only the key decision filters.
    """
    return [risk for risk in risks if str(risk.get("path")) == METRIC_PATH_GRAIN]


def _fan_out_risk(
    document: dict, scope_id: str, block: dict, path: str, card_lookup=None
) -> tuple[dict, str | None]:
    """One published risk, plus the card confidence that decided it (or ``None``).

    The level is not part of the risk: what the reader needs is the verdict and the
    sentence naming the proof. It is returned beside it because a *candidate* key is the
    corpus's best guess rather than a proof, so a verdict that rests on one caps the key
    confidence of the whole statement -- see :func:`_capped_confidence`.
    """
    detail = block.get("join_relation_detail") or {}
    block_id = str(block.get("logic_block_id"))
    status, reason, basis, level, pinned = _fan_out_verdict(
        document, block_id, detail, card_lookup
    )
    risk = {
        "logic_block_id": block_id,
        "scope_id": scope_id,
        "join_type": detail.get("join_type"),
        "right": detail.get("right_input"),
        "status": status,
        "reason": reason,
        "path": path,
    }
    if basis:
        risk["basis"] = basis
    # B9: the verdict rests on a column the right side cannot vary, so the decision is
    # published beside it rather than left inside the sentence.
    if pinned:
        risk["pinned_keys"] = list(pinned)
    return risk, level


def _fan_out_verdict(
    document: dict, block_id: str, detail: dict, card_lookup=None
) -> tuple[str, str, str | None, str | None, list[dict]]:
    """``(status, reason, basis, card key confidence, pinned keys)``.

    Only three shapes can be proven safe from inside one statement; everything else is
    ``risk`` or ``unknown``. The fourth shape needs a corpus: a JOIN onto a physical
    table has no primary key this statement can see, but a table card may carry another
    task's proof that the table is written one row per the very columns this ON clause
    names -- a fact, not a guess (WI-2.8 D2).
    """
    right = str(detail.get("right_input") or "")
    if right in set(document.get("source_tables") or []):
        carded = _card_verdict(right, detail, card_lookup)
        return (*carded, []) if carded else ("unknown", "物理表无主键事实", None, None, [])
    if right not in _scopes(document):
        return "unknown", f"右侧 {right} 不是本语句的 scope，无唯一性事实", None, None, []
    columns = _join_side_columns(detail, "right")
    if not columns:
        return (*_keyless_join_verdict(detail), None, None, [])
    grouped = _grouped_uniqueness(document, right, columns)
    if grouped is not None and grouped[0] == "safe":
        return grouped[0], grouped[1], None, None, grouped[2]
    proven = _ranking_uniqueness(document, right, (block_id, detail), columns)
    if proven is not None:
        function, partition, consumer = proven
        scope = "无分区" if not partition else f"按 {'、'.join(partition)} 分区"
        return "safe", f"右侧 {function} {scope}并以 = 1 过滤（{consumer}）", None, None, []
    fallback = grouped or ("risk", "右侧未被证明按连接键唯一", [])
    return fallback[0], fallback[1], None, None, fallback[2]


def _keyless_join_verdict(detail: dict) -> tuple[str, str]:
    """``(status, reason)`` for a JOIN whose right side offers no scope-level column."""
    if _join_side_keys(detail, "right"):
        return "risk", "右侧连接键没有 scope 级列名，唯一性无从判定"
    return "risk", "该 JOIN 无可证明的连接键，右侧唯一性无从判定"


def _card_verdict(
    right: str, detail: dict, card_lookup
) -> tuple[str, str, str, str] | None:
    """The corpus's answer for a JOIN onto a physical table, or None when it has none.

    Half a proven key set proves nothing -- one customer may hold many countries -- so
    the ON clause's right-hand columns must cover the card's whole key set before the
    verdict changes.
    """
    if card_lookup is None:
        return None
    proof = _card_key_proof(card_lookup(right))
    if proof is None:
        return None
    task, keys, level = proof
    columns = _join_side_columns(detail, "right")
    if not columns or not _comparable(keys) <= _comparable(columns):
        return None
    return "safe", _card_reason(task, keys, level), FAN_OUT_BASIS_TABLE_CARD, level


def _card_lookup(table_cards: Mapping | None):
    """``table name -> card`` over a ``tables-json/1`` corpus, or None when none was given.

    Re-implemented here rather than imported from ``table_cards``, which imports this
    module: the identity rule is the corpus-wide suffix rule ``glossary_values`` already
    owns, so only the walk is local.
    """
    index = list((table_cards or {}).get("tables") or [])
    if not index:
        return None

    def lookup(name):
        for card in index:
            spellings = [card.get("table"), *(card.get("aliases") or [])]
            if any(
                spelling and glossary_values.same_table(name, spelling)
                for spelling in spellings
            ):
                return card
        return None

    return lookup


def _card_key_proof(card) -> tuple[str, list[str], str] | None:
    """``(task, keys, confidence)`` from the strongest producer on one card, or None."""
    for level in _CARD_KEY_CONFIDENCES:
        for producer in (card or {}).get("produced_by") or []:
            keys = [str(key) for key in producer.get("candidate_keys") or []]
            if keys and str(producer.get("key_confidence")) == level:
                return str(producer.get("task")), keys, level
    return None


def _card_reason(task: str, keys: Sequence[str], level: str) -> str:
    names = "、".join(keys)
    if level == KEY_CONFIDENCE_PROVEN:
        return f"生产任务 {task} 已证明 {names} 唯一（表卡）"
    return f"生产任务 {task} 按 {names} 产出（表卡候选键，未证唯一）"


def _capped_confidence(confidence: str, levels: Sequence[str | None]) -> str:
    """A candidate key is not a proof, so a card that offered one caps the whole claim."""
    if KEY_CONFIDENCE_CANDIDATE not in levels:
        return confidence
    if confidence in (KEY_CONFIDENCE_PROVEN, KEY_CONFIDENCE_PROVEN_UNEXPOSED):
        return KEY_CONFIDENCE_CANDIDATE
    return confidence


def _grouped_uniqueness(
    document: dict, scope_id: str, columns: Sequence[str]
) -> tuple[str, str, list[dict]] | None:
    """The GROUP BY verdict, decided on ``scope_id``'s own logical keys (WI-2.1d item 1).

    The comparison used to run on the columns both sides pierce to, which is a different
    question from the one being asked. Three GROUP BY items written as CASE expressions
    over overlapping columns pierce to a set two join keys already cover, so the join
    was granted ``safe`` while the right side held one row per *three* keys -- many rows
    per join key, which is the fan-out this verdict exists to catch.

    A logical key is one GROUP BY item, named by the output column that scope publishes
    it as (its own text when it publishes none), and a join key is the column name the
    ON clause reads on that same side. That is the one vocabulary both are written in.
    The pierced columns stay in the sentence as a note, never in the verdict.
    """
    keys = _aggregation_logical_keys(document, scope_id)
    if keys is None:
        return None
    if not keys:
        return "safe", "右侧为全表聚合，至多一行", []
    # B9: a key the right side pins to one literal cannot make two rows out of one, so
    # it leaves the set the join keys have to cover.
    free, pinned = _unpinned_keys(document, scope_id, keys)
    labels = _logical_key_names(keys)
    note = f"{_pin_note(pinned)}{_physical_key_note(keys)}"
    if not free:
        return "safe", (
            f"右侧按 {'、'.join(labels)} GROUP BY，等值过滤后键集为空，右侧至多一行{note}"
        ), pinned
    free_labels = _logical_key_names(free)
    if _comparable(free_labels) <= _comparable(columns):
        return "safe", (
            f"右侧按 {'、'.join(free_labels)} GROUP BY，键集被连接键覆盖{note}"
        ), pinned
    return "risk", (
        f"右侧按 {'、'.join(free_labels)} GROUP BY，"
        f"连接键 {'、'.join(columns)} 未覆盖该键集{note}"
    ), pinned


def _logical_key_names(keys: Sequence[dict]) -> list[str]:
    """Each logical key as its own scope names it: its output column, else its text."""
    return _dedupe(
        str(key.get("name") or key.get("expression") or key.get("scope_id"))
        for key in keys
    )


def _comparable(values: Iterable[str]) -> set[str]:
    """Names compared as SQL compares identifiers: unwrapped, unspaced, case-blind."""
    return {_normalized_expression(value).lower() for value in values}


def _physical_key_note(keys: Sequence[dict]) -> str:
    """The pierced columns as an aside. They are evidence for a reader, never a verdict."""
    sources = _dedupe(
        f"{item.get('table')}.{item.get('column')}"
        for key in keys
        for item in key.get("physical_sources") or []
    )
    if not sources:
        return ""
    shown = sources[:_PHYSICAL_NOTE_LIMIT]
    tail = f" 等 {len(sources)} 列" if len(sources) > len(shown) else ""
    return f"（键的物理来源 {'、'.join(shown)}{tail}）"


def _join_side_columns(detail: dict, side: str) -> list[str]:
    """One side's join keys as the column names that side's own scope publishes them by."""
    return _dedupe(
        str((pair.get(side) or {}).get("column"))
        for pair in detail.get("join_key_pairs") or []
        if (pair.get(side) or {}).get("column")
    )


def _join_side_keys(detail: dict, side: str) -> list[str]:
    """One side's join keys as ``table.column``, falling back to ``scope.column``."""
    keys: list[str] = []
    for pair in detail.get("join_key_pairs") or []:
        physical = [
            f"{field.get('table')}.{field.get('field')}"
            for field in pair.get(f"{side}_fields") or []
            if field.get("table") and field.get("field")
        ]
        if physical:
            keys.extend(physical)
            continue
        reference = pair.get(side) or {}
        if reference.get("column"):
            keys.append(f"{reference.get('scope')}.{reference.get('column')}")
    return _dedupe(keys)


def _window_partition_labels(spec: dict) -> list[str]:
    """The same partition as a reader sees it written -- what the reason sentence says."""
    return _dedupe(
        label for item in spec.get("partition_by") or [] for label in _item_labels(item)
    )


def _ranking_uniqueness(
    document: dict,
    scope_id: str,
    join_block: tuple[str, dict],
    join_columns: Sequence[str],
) -> tuple[str, list[str], str] | None:
    """``(function, partition labels, consumer id)`` when the right side proves one row per key.

    WI-2.1d item 1: the subset test runs on the partition's *logical* keys -- the column
    each PARTITION BY item is published as on this scope -- against the column names the
    ON clause reads on the same side. Piercing both to physical columns made a partition
    on one derived column look like a partition on the four columns that column reads,
    which is a wider key set than the SQL wrote.
    """
    names = _output_name_index(document, scope_id)
    for owner, _, spec in _ranking_window_specifications(document):
        if owner != scope_id:
            continue
        keys = [
            _partition_item_key(scope_id, names, item)
            for item in spec.get("partition_by") or []
        ]
        if not _comparable(_logical_key_names(keys)) <= _comparable(join_columns):
            continue
        consumer = _keeps_first_row_consumer(document, scope_id, spec, [join_block])
        if consumer:
            return (
                str(spec.get("window_function")),
                _window_partition_labels(spec),
                consumer,
            )
    return None


def _keeps_first_row_consumer(
    document: dict,
    scope_id: str,
    spec: dict,
    join_blocks: Sequence[tuple[str, dict]] | None = None,
) -> str | None:
    """The logic block that filters this window's output to ``= 1``, if any.

    Three places can carry it, checked in that order: the contract's own
    ``filter_after_window`` pointer, the window scope's own WHERE/HAVING, and the ON
    clause of a JOIN that reads the scope.
    """
    output = str(spec.get("output_field") or "")
    if not output:
        return None
    for entry in spec.get("filter_after_window") or []:
        if _entry_keeps_first_row(entry, output):
            return str(entry.get("logic_block_id"))
    for block in _scope_blocks(document, scope_id):
        if str(block.get("logic_type")) in _PREDICATE_LOGIC_TYPES and (
            _predicate_block_keeps_first_row(block, output)
        ):
            return str(block.get("logic_block_id"))
    candidates = join_blocks if join_blocks is not None else _all_join_blocks(document)
    for block_id, detail in candidates:
        if scope_id not in (detail.get("left_input"), detail.get("right_input")):
            continue
        if any(
            _entry_keeps_first_row(condition, output)
            for condition in detail.get("condition_filters") or []
        ):
            return block_id
    return None


# ------------------------------------------------- corpus-layer facade (WI-8 / WI-9)
#
# `ontology` asks this module the questions it already answers -- is the right side of
# this JOIN unique by its keys, which scope do a CTE's rows come from, which columns is
# this scope grouped by -- one corpus at a time instead of one statement at a time. They
# are published under public names rather than reached into privately: the rules stay
# defined once, in the module that owns the concept, and a change to one of them shows
# up in both layers at the same time.


def join_blocks(document: dict) -> list[tuple[str, str, dict]]:
    """``(scope_id, logic_block_id, join_relation_detail)`` for every JOIN, in scope order."""
    return [
        (scope_id, str(block.get("logic_block_id")), block.get("join_relation_detail") or {})
        for scope_id, block in _logic_blocks(document)
        if block.get("logic_type") == "join"
    ]


def driving_table(document: dict, item: str) -> tuple[str | None, list[str]]:
    """``(the physical table whose rows this input is, the scopes walked to reach it)``.

    R3's own descent, started from an arbitrary input rather than from ROOT: a JOIN side
    that is a CTE is not an entity, and the entity behind it is whatever physical table
    its rows are. A walk that ends anywhere else answers ``None`` and the reader is told
    the path stopped rather than given a table the SQL did not name.
    """
    tables = set(document.get("source_tables") or [])
    scopes = _scopes(document)
    visited: list[str] = []
    for _ in range(GRAIN_DEPTH_LIMIT):
        if item in tables:
            return item, visited
        if item in visited or item not in scopes:
            return None, visited
        visited.append(item)
        following, _reason = _scope_from_item(document, item)
        if following is None:
            return None, visited
        item = following
    return None, visited


def ranking_partition_keys(document: dict) -> list[tuple[str, str, list[dict]]]:
    """``(scope_id, logic_block_id, partition keys)`` per ranking window, keys logical."""
    found = []
    for scope_id, block_id, spec in _ranking_window_specifications(document):
        names = _output_name_index(document, scope_id)
        found.append(
            (
                scope_id,
                block_id,
                [
                    _partition_item_key(scope_id, names, item)
                    for item in spec.get("partition_by") or []
                ],
            )
        )
    return found


#: One aggregating scope's GROUP BY items as logical keys, or None when it does not
#: aggregate -- the same answer R3's grain walk reads.
aggregation_keys = _aggregation_logical_keys

#: The GROUP BY verdict for one JOIN's right side: ``(status, reason)`` or None.
grouped_uniqueness = _grouped_uniqueness

#: The ranking-window verdict for the same side: ``(function, partition, consumer)``.
ranking_uniqueness = _ranking_uniqueness

#: One side's join keys as the column names that side's own scope publishes them by.
join_side_columns = _join_side_columns

#: ``table name -> card`` over a ``tables-json/1`` corpus, or None when none was given.
card_lookup = _card_lookup

#: ``(task, keys, confidence)`` from the strongest producer on one card, or None.
card_key_proof = _card_key_proof

#: Names compared as SQL compares identifiers: unwrapped, unspaced, case-blind.
comparable = _comparable


def _all_join_blocks(document: dict) -> list[tuple[str, dict]]:
    return [
        (str(block.get("logic_block_id")), block.get("join_relation_detail") or {})
        for _, block in _logic_blocks(document)
        if block.get("logic_type") == "join"
    ]


# ----------------------------------------------------------------- stages (R4, R6)


def _build_stages(document: dict) -> list[dict]:
    physical = _upstream_physical_tables(document)
    steps = {str(step.get("scope_id")): step for step in _profile_steps(document)}
    return [
        _build_stage(document, scope_id, steps.get(scope_id) or {}, physical)
        for scope_id in _stage_order(document)
    ]


def _stage_order(document: dict) -> list[str]:
    """Topological order over ``scope_graph``'s scope-to-scope edges; ROOT stays last."""
    scopes = _scopes(document)
    parents: dict[str, set[str]] = {scope_id: set() for scope_id in scopes}
    for edge in (document.get("scope_graph") or {}).get("edges") or []:
        source, target = str(edge.get("from")), str(edge.get("to"))
        if source in scopes and target in scopes and source != target:
            parents[target].add(source)
    ordered: list[str] = []
    emitted: set[str] = set()
    while True:
        layer = sorted(
            scope_id
            for scope_id in scopes
            if scope_id not in emitted and parents[scope_id] <= emitted
        )
        if not layer:
            break
        ordered.extend(layer)
        emitted.update(layer)
    # A cycle would strand scopes; they are appended rather than dropped.
    ordered.extend(sorted(scope_id for scope_id in scopes if scope_id not in emitted))
    tail = [_ROOT] if _ROOT in scopes else []
    return [scope_id for scope_id in ordered if scope_id != _ROOT] + tail


def _upstream_physical_tables(document: dict) -> dict[str, list[str]]:
    """Each scope's source boundary: the contract's own value where it publishes one."""
    declared = {
        str(step.get("scope_id")): [
            str(table) for table in step.get("physical_source_tables") or []
        ]
        for step in _profile_steps(document)
    }
    scopes = _scopes(document)
    tables = set(document.get("source_tables") or [])
    resolved: dict[str, set[str]] = {}

    def walk(scope_id: str, seen: frozenset) -> set[str]:
        if scope_id in resolved:
            return resolved[scope_id]
        if scope_id in seen:
            return set()
        found: set[str] = set()
        for dependency in (scopes.get(scope_id) or {}).get("depends_on") or []:
            name = str(dependency)
            if name in tables:
                found.add(name)
            elif name in scopes:
                found |= walk(name, seen | {scope_id})
        resolved[scope_id] = found
        return found

    return {
        scope_id: declared.get(scope_id) or sorted(walk(scope_id, frozenset()))
        for scope_id in scopes
    }


def _build_stage(
    document: dict, scope_id: str, step: dict, physical: dict[str, list[str]]
) -> dict:
    scope = _scopes(document).get(scope_id) or {}
    tables = set(document.get("source_tables") or [])
    inputs = [str(item) for item in scope.get("depends_on") or []]
    outputs = [str(item.get("name")) for item in scope.get("outputs") or []]
    direct_tables = sorted(item for item in inputs if item in tables)
    stage = {
        "scope_id": scope_id,
        "name": step.get("name") or _stage_name(scope_id),
        "kind": scope.get("kind"),
        "role": step.get("role") or scope.get("role"),
        "direct_inputs": inputs,
        "direct_source_tables": direct_tables,
        "upstream_physical_tables": physical.get(scope_id, []),
        "actions": _stage_actions(document, scope_id, step),
        "outputs": outputs,
        "output_count": len(outputs),
        "pattern_signature": _pattern_signature(document, scope_id, scope, step),
    }
    return {key: stage[key] for key in _STAGE_KEY_ORDER}


def _stage_name(scope_id: str) -> str:
    if scope_id == _ROOT or ":" not in scope_id:
        return scope_id
    return scope_id.split(":", 1)[1]


def _pattern_signature(document: dict, scope_id: str, scope: dict, step: dict) -> str:
    """A stable shape key for folding parallel same-shaped stages; carries no identifier."""
    blocks = _scope_blocks(document, scope_id)
    counts = Counter(str(block.get("logic_type")) for block in blocks)
    windows = sorted(
        {
            str((block.get("window_specification") or {}).get("window_function") or "")
            for block in blocks
            if block.get("logic_type") == "window"
        }
    )
    tables = set(document.get("source_tables") or [])
    inputs = [str(item) for item in scope.get("depends_on") or []]
    # WI-1g item E1: the *kind* of the direct inputs, never their names. Two stages that
    # both read one physical table are the same shape; one reading a table and one
    # reading three derived scopes are not, and the old `physical_input=yes/no` folded
    # them together.
    physical_inputs = [item for item in inputs if item in tables]
    branch_inputs = [item for item in inputs if item.startswith("union:")]
    derives = sum(
        1
        for output in scope.get("outputs") or []
        if str(output.get("transform")) == _DERIVE_TRANSFORM
    )
    return "|".join(
        [
            f"role={step.get('role') or scope.get('role')}",
            f"kind={scope.get('kind')}",
            f"inputs=tables:{len(physical_inputs)},scopes:"
            f"{len(inputs) - len(physical_inputs)},union:"
            f"{'yes' if branch_inputs or scope.get('union_branch_alignment') else 'no'}",
            "blocks=" + ",".join(f"{name}={counts[name]}" for name in sorted(counts)),
            f"derive={derives}",
            "window=" + ",".join(windows),
            "agg=" + ",".join(_aggregate_function_names(document, scope_id)),
        ]
    )


def _aggregate_function_names(document: dict, scope_id: str) -> list[str]:
    names: set[str] = set()
    for block in _scope_blocks(document, scope_id):
        for item in (block.get("aggregation_detail") or {}).get("aggregate_items") or []:
            if item.get("aggregate_function"):
                names.add(str(item["aggregate_function"]).lower())
        if block.get("logic_type") == "aggregate":
            names |= {
                name.lower()
                for name in semantic_text.aggregate_functions(block.get("raw_expression"))
            }
    return sorted(names)


# ------------------------------------------------------------------ stage actions


def _stage_actions(document: dict, scope_id: str, step: dict) -> list[dict]:
    """One scope's actions in SQL evaluation order, then by ``logic_block_id``.

    Logic block ids sort alphabetically, which put ``case_when`` in front of the
    ``filter`` and ``join`` that feed it -- a reader following ROOT saw the derived
    CASE before the rows it is computed over. ``ACTION_TYPE_ORDER`` restates the order
    in which the engine applies them instead; the sort is stable, so same-typed actions
    keep the block-id order the blocks were collected in.
    """
    blocks = _scope_blocks(document, scope_id)
    anchor = _aggregation_anchor(blocks)
    actions: list[dict] = []
    for block in blocks:
        logic_type = str(block.get("logic_type"))
        if logic_type in _PREDICATE_LOGIC_TYPES:
            actions.extend(_filter_actions(document, block))
        elif logic_type == "join":
            actions.append(_join_action(document, block))
        elif logic_type == "case_when":
            actions.append(_case_action(document, block))
        elif logic_type == "window":
            actions.append(_window_action(document, scope_id, block))
        elif logic_type == "distinct":
            actions.append(_distinct_action(block))
        elif str(block.get("logic_block_id")) == anchor:
            actions.append(_aggregate_action(document, scope_id, blocks, block))
    actions.extend(_union_actions(document, scope_id))
    actions.extend(_lateral_view_actions(step, scope_id))
    actions.extend(_derive_actions(document, scope_id))
    actions.sort(key=_action_sort_rank)
    return [_ordered_action(action) for action in actions]


def _action_sort_rank(action: dict) -> int:
    return _ACTION_TYPE_RANK.get(str(action.get("type")), len(ACTION_TYPE_ORDER))


def _aggregation_anchor(blocks: Sequence[dict]) -> str | None:
    """One aggregate action per scope, anchored on the GROUP BY block when there is one."""
    for logic_type in ("group_by", "aggregate"):
        found = [block for block in blocks if str(block.get("logic_type")) == logic_type]
        if found:
            return str(found[0].get("logic_block_id"))
    return None


def _ordered_action(action: dict) -> dict:
    return {key: action[key] for key in _ACTION_KEY_ORDER if key in action}


def _action(action_type: str, text: str | None, **extra) -> dict:
    comments = [str(item) for item in extra.pop("sql_comments", None) or []]
    return {
        "type": action_type,
        "text": text,
        "fields": extra.pop("fields", []),
        # WI-2.2: present only when the author wrote one, like every other optional
        # per-action fact.
        **({"sql_comments": comments} if comments else {}),
        "evidence": extra.pop("evidence", None),
        "tag": extra.pop("tag", TAG_SQL_FACT),
        **extra,
    }


def _filter_actions(document: dict, block: dict) -> list[dict]:
    detail = block.get("filter_predicate_detail") or {}
    having = detail.get("predicate_type") == "having"
    partition = bool(detail.get("is_partition_filter"))
    evidence = str(block.get("logic_block_id"))
    conjuncts = detail.get("conjuncts") or [
        {
            "expression": detail.get("expression") or block.get("raw_expression"),
            "expression_resolution": detail.get("expression_resolution"),
        }
    ]
    actions = []
    for conjunct in conjuncts:
        expression = conjunct.get("expression")
        text = (
            semantic_text.describe_having(expression)
            if having
            else semantic_text.describe_filter(
                expression, is_partition_filter=partition
            )
        )
        actions.append(
            _action(
                "having" if having else "filter",
                text,
                expression=expression,
                fields=_rule_fields(
                    document, _physical_fields(conjunct.get("expression_resolution"))
                ),
                sql_comments=block.get("comments"),
                evidence=evidence,
            )
        )
    return actions


def _join_action(document: dict, block: dict) -> dict:
    detail = block.get("join_relation_detail") or {}
    pairs: list[dict] = []
    for pair in detail.get("join_key_pairs") or []:
        pairs.extend(_join_key_pair(pair)[0])
    extras = [
        condition.get("expression") for condition in detail.get("condition_filters") or []
    ]
    return _action(
        "join",
        semantic_text.describe_join(
            detail.get("join_type"), detail.get("right_input"), _dedupe(pairs), extras
        ),
        expression=detail.get("condition_expression"),
        fields=_join_condition_physical_fields(document, detail),
        sql_comments=block.get("comments"),
        evidence=str(block.get("logic_block_id")),
    )


def _aggregate_action(
    document: dict, scope_id: str, blocks: Sequence[dict], anchor: dict
) -> dict:
    detail = anchor.get("aggregation_detail") or {}
    items = detail.get("aggregate_items") or []
    column_types = _column_types(document)
    calls = [
        semantic_text.describe_aggregate_call(item.get("expression_sql"), column_types)
        for item in items
    ]
    pairs: list[tuple[str, str]] = []
    for item in [*(detail.get("group_by_items") or []), *items]:
        pairs.extend(_physical_fields(item.get("expression_resolution")))
    if not calls:
        aggregates = [
            block for block in blocks if str(block.get("logic_type")) == "aggregate"
        ]
        calls = [
            semantic_text.describe_aggregate_call(
                block.get("raw_expression"), column_types
            )
            for block in aggregates
        ]
        for block in aggregates:
            pairs.extend(
                (str(usage.get("source_id")), str(name))
                for usage in block.get("field_usage") or []
                if usage.get("source_type") == "physical_table"
                for name in usage.get("used_fields") or []
            )
    return _action(
        "aggregate",
        semantic_text.describe_aggregation(_group_by_keys(document, scope_id), calls),
        fields=_rule_fields(document, pairs),
        sql_comments=anchor.get("comments"),
        evidence=str(anchor.get("logic_block_id")),
    )


def _case_action(document: dict, block: dict) -> dict:
    expression = block.get("raw_expression")
    branches = semantic_text.describe_case(expression)
    outputs = [str(name) for name in block.get("output_fields") or []]
    text = branches
    if branches and outputs:
        text = f"派生 {outputs[0]}：{branches}"
    pairs = [
        (str(usage.get("source_id")), str(name))
        for usage in block.get("field_usage") or []
        if usage.get("source_type") == "physical_table"
        for name in usage.get("used_fields") or []
    ]
    return _action(
        "case_when",
        text,
        expression=expression,
        fields=_rule_fields(document, pairs),
        sql_comments=block.get("comments"),
        evidence=str(block.get("logic_block_id")),
    )


def _distinct_action(block: dict) -> dict:
    return _action(
        "distinct",
        semantic_text.describe_distinct(),
        evidence=str(block.get("logic_block_id")),
    )


def _union_actions(document: dict, scope_id: str) -> list[dict]:
    alignment = (_scopes(document).get(scope_id) or {}).get("union_branch_alignment") or {}
    branches = alignment.get("branches") or []
    if not branches:
        return []
    labels = [
        "、".join(str(table) for table in branch.get("source_tables") or [])
        or str(branch.get("branch_id"))
        for branch in branches
    ]
    return [
        _action("union", semantic_text.describe_union(labels), evidence=scope_id)
    ]


def _lateral_view_actions(step: dict, scope_id: str) -> list[dict]:
    lateral_views = (step.get("logic") or {}).get("lateral_views") or []
    return [
        _action(
            "lateral_view",
            semantic_text.describe_lateral_view(lateral_view),
            evidence=scope_id,
        )
        for lateral_view in lateral_views
    ]


def _derive_actions(document: dict, scope_id: str) -> list[dict]:
    """One action per plain-expression output column of this scope (WI-1g item B).

    A 19-stage task deriving 24 metrics by arithmetic showed none of them in ``stages``:
    the logic blocks carry filters, joins, windows and CASEs, and an ordinary
    ``a - b AS delta`` is not a logic block at all -- it lives only on the scope's
    output list. The evidence is that output's own ``source_logic_blocks`` when the
    contract published any, and the scope id otherwise, which is where the fact is.
    """
    scope = _scopes(document).get(scope_id) or {}
    actions = []
    for output in scope.get("outputs") or []:
        if str(output.get("transform")) != _DERIVE_TRANSFORM:
            continue
        expression = output.get("expression")
        blocks = [str(item) for item in output.get("source_logic_blocks") or []]
        actions.append(
            _action(
                "derive",
                _derive_text(str(output.get("name") or ""), expression, output),
                column=output.get("name"),
                expression=expression,
                fields=_rule_fields(
                    document, _physical_fields(output.get("expression_resolution"))
                ),
                # A derive action IS one output column, so its comments are that output's
                # -- the alias comment sits outside the logic block's expression.
                sql_comments=output.get("comments"),
                evidence=blocks[0] if blocks else scope_id,
            )
        )
    return actions


def _derive_text(column: str, expression, output: dict) -> str | None:
    """The restatement of one derived column, or None when it falls outside the vocabulary."""
    text = semantic_text.describe_function_expression(expression)
    if not _output_is_black_box(output, expression):
        return text
    return semantic_text.UDF_MARKER if text is None else f"{text}；{semantic_text.UDF_MARKER}"


def _output_is_black_box(output: dict, expression) -> bool:
    """The contract's UDF verdict, overruled by the parser's own builtin whitelist.

    WI-1g item E3: ``function_catalog`` does not know ``HOUR`` / ``RANK`` / ``LAG``, so
    the contract reports them as UDFs. ``has_unknown_function`` answers from sqlglot's
    Spark grammar instead, and only a name sqlglot itself cannot place stays a black box.
    """
    if not (output.get("expression_features") or {}).get("has_udf"):
        return False
    unknown = semantic_text.has_unknown_function(expression)
    return unknown is not False


def _window_action(document: dict, scope_id: str, block: dict) -> dict:
    spec = block.get("window_specification") or {}
    function = str(spec.get("window_function") or "")
    intent, consumer = _window_intent(document, scope_id, spec)
    partition = [
        label for item in spec.get("partition_by") or [] for label in _item_labels(item)
    ]
    order = [
        (label, item.get("direction"))
        for item in spec.get("order_by") or []
        for label in _item_labels(item)
    ]
    pairs: list[tuple[str, str]] = []
    for item in [*(spec.get("partition_by") or []), *(spec.get("order_by") or [])]:
        pairs.extend(_physical_fields(item.get("expression_resolution")))
    return _action(
        "window",
        semantic_text.describe_window_action(
            window_function=function,
            output_field=spec.get("output_field"),
            partition_labels=_dedupe(partition),
            order_labels=order,
            intent=intent,
            consumer_scope=_scope_of_logic_block(consumer) if consumer else None,
        ),
        expression=spec.get("expression_sql"),
        fields=_rule_fields(document, pairs),
        sql_comments=block.get("comments"),
        evidence=str(block.get("logic_block_id")),
        tag=TAG_STRUCTURAL_INFERENCE,
        intent=intent,
        consumed_by=consumer,
    )


def _window_intent(document: dict, scope_id: str, spec: dict) -> tuple[str, str | None]:
    """R6. A ranking window only means dedup once something filters it to ``= 1``."""
    function = str(spec.get("window_function") or "").lower()
    if function not in semantic_text.RANKING_WINDOW_FUNCTIONS:
        return WINDOW_INTENT_BY_FUNCTION.get(function, "other"), None
    consumer = _keeps_first_row_consumer(document, scope_id, spec)
    if consumer is None:
        return "rank_within_group", None
    order = spec.get("order_by") or []
    descending = order and str(order[0].get("direction") or "ASC").upper() == "DESC"
    return ("keep_latest_per_group" if descending else "keep_first_per_group"), consumer


def _item_label(item: dict) -> str:
    """The logical name one PARTITION BY / ORDER BY item carries in its own scope.

    The restatement says what the SQL was written against, so the item is named by its
    own ``expression_sql`` without qualifiers or backticks: a bare column prints as the
    column name, an expression prints as the expression. Resolving to the physical
    columns underneath would state a grouping the statement never wrote --
    ``PARTITION BY band`` over a derived ``CASE WHEN amount >= 100 ...`` groups by
    ``band``, not by ``amount``. The physical fact stays in the action's ``fields[]``
    and in the key's ``physical_sources``.
    """
    rendered = semantic_text.expression_text(
        semantic_text.parse_expression(item.get("expression_sql"))
    )
    if rendered:
        return rendered
    names = [
        str(ref.get("column")) for ref in item.get("source_fields") or [] if ref.get("column")
    ]
    return names[0] if names else ""


def _item_labels(item: dict) -> list[str]:
    """``_item_label`` as a list, empty when the item cannot be named at all."""
    label = _item_label(item)
    return [label] if label else []


# ------------------------------------------------------- field key roles (R5 tail)


def _apply_key_roles(fields: Sequence[dict], output_shape: dict) -> None:
    """R5's two grain-dependent roles, applied once ``output_shape`` is known.

    ``candidate_keys`` are target column names since WI-1e, so the role is a name match
    rather than a walk back to the physical sources.

    ``partition`` wins over ``candidate_key``: the plan states that a partition column
    is not counted as a candidate key, so a column that is both is reported as the
    metadata fact rather than as the inference. ``constant`` wins too -- a column built
    from literals says more about itself than "it is one of the keys", which section 2
    states anyway.
    """
    keys = {str(item) for item in output_shape.get("candidate_keys") or []}
    partitions = {str(item) for item in output_shape.get("partition_columns") or []}
    for field in fields:
        column = str(field.get("column"))
        if column in partitions:
            field["structural_role"] = "partition"
        elif column in keys and field.get("structural_role") != "constant":
            field["structural_role"] = "candidate_key"


# --------------------------------------------------------------------- confidence


def _build_confidence(
    document: dict,
    diagnostics: dict | None,
    fields: Sequence[dict],
    output_shape: dict,
    stages: Sequence[dict],
    rules: Sequence[dict] = (),
    values: Sequence[dict] = (),
) -> dict:
    # WI-1f: a task-level diagnostics document keeps script-scoped facts at the top and
    # everything one statement produced under `statement_diagnostics.<id>`. Reading only
    # the top level published "解析警告：无" for a statement that had one.
    statement_id = document.get("statement_id")
    gaps = fact_gaps_for(diagnostics, statement_id)
    warnings = warnings_for(diagnostics, statement_id)
    available = diagnostics is not None
    not_applicable = _binding_not_applicable_reason(document)
    return {
        "metadata_coverage": _metadata_coverage(document, fields, rules, values),
        # WI-2.6: how much of this task has been answered. Always present, and zero is a
        # fact worth publishing -- "nobody has confirmed anything here yet" is the state
        # the write-back loop exists to change, and a reader has to be able to see it.
        "confirmations": _confirmations(document, fields, rules, values),
        "trace_incomplete_fields": [
            field["column"] for field in fields if not field.get("trace_complete")
        ],
        "ambiguous_fields": [
            field["column"] for field in fields if field.get("ambiguous")
        ],
        "diagnostics_available": available,
        "fact_gap_count": len(gaps) if available else None,
        "fact_gap_types": _counted(gap.get("gap_type") for gap in gaps)
        if available
        else None,
        "warning_counts": _counted(warning.get("type") for warning in warnings)
        if available
        else None,
        "findings": _build_findings(document, diagnostics, rules, fields),
        # Q4. Only when the contract says this statement had no binding to make, and only
        # the token it said it with. It is not a finding -- nobody acts on a CTAS defining
        # its own columns -- but section 6 gives target binding its own line, and that line
        # would otherwise report the one statement kind whose binding is a settled fact as
        # "契约未给出绑定事实".
        **(
            {"target_binding_not_applicable": not_applicable} if not_applicable else {}
        ),
        "inferred_items": _inferred_items(fields, output_shape, stages),
    }


def _binding_not_applicable_reason(document: Mapping) -> str | None:
    """The token behind ``target_field_binding.status == "not_applicable"``, if that is it."""
    binding = document.get("target_field_binding") or {}
    if binding.get("status") != _NOT_APPLICABLE_BINDING_STATUS:
        return None
    return str(binding.get("reason") or "") or None


def _metadata_coverage(
    document: dict,
    fields: Sequence[dict] = (),
    rules: Sequence[dict] = (),
    values: Sequence[dict] = (),
) -> dict:
    """How much of what the fields mean the metadata could supply, counted not judged."""
    metadata = _input_metadata(document)
    output_metadata = _output_metadata(document)
    coverage = {
        "input_tables_complete": sum(
            1 for item in metadata.values() if item.get("metadata_complete")
        ),
        "input_tables_total": len(metadata),
        "target_comments_available": any(
            detail.get("comment")
            for detail in output_metadata.get("column_details") or []
        ),
        "target_metadata_source": output_metadata.get("metadata_source"),
        # WI-2.2: counted, not judged, and kept out of `findings` deliberately -- a
        # statement without comments is not a governance problem, it is a statement
        # without comments. The three counts say how much author commentary this
        # document had to work with.
        "sql_comment_counts": _sql_comment_counts(document),
    }
    # WI-2.4: how far the value dictionary got with this task's fields. Absent rather
    # than zeroed when the task has no observed values at all -- a statement that
    # compares nothing against a constant has no value domain to be short of.
    glossary = glossary_values.glossary_coverage(fields, rules, values)
    if glossary["values_total"]:
        coverage["glossary"] = glossary
    # WI-2.6: what a reviewed metadata patch supplied for THIS statement. Absent when no
    # patch touched it, so a document parsed without one is the document it always was.
    patched = _patch_counts(document)
    if patched["tables"] or patched["columns"]:
        coverage["patch"] = patched
    return coverage


def _metadata_items(document: dict) -> list[dict]:
    """Every table metadata blob the statement carries, inputs and target alike."""
    return [
        *(_input_metadata(document).values()),
        *(
            ((document.get("related_metadata") or {}).get("output_tables") or {}).values()
        ),
    ]


def _patch_counts(document: dict) -> dict[str, int]:
    """How many tables and columns in this statement carry a patched comment."""
    items = _metadata_items(document)
    return {
        "tables": sum(1 for item in items if _table_comment_is_patched(item)),
        "columns": sum(
            1
            for item in items
            for detail in item.get("column_details") or []
            if str(detail.get("comment_source")) == COMMENT_SOURCE_PATCH
        ),
    }


def _confirmations(
    document: dict,
    fields: Sequence[dict] = (),
    rules: Sequence[dict] = (),
    values: Sequence[dict] = (),
) -> dict[str, int]:
    """WI-2.6: how many open questions this task has actually had answered.

    Five counts, one per kind of answer the 待确认清单 can produce: a field value's
    meaning, a RULE value's meaning (WI-2.12: the codes a WHERE or a CASE condition pins
    a column to, which is where a warehouse keeps most of them) and a term's meaning come
    back through ``glossary.overrides.json`` (those three are filled in by
    ``apply_glossary``, the only side that has read the corpus dictionary), a column
    comment and a table comment come back through a metadata patch.
    """
    patched = _patch_counts(document)
    coverage = glossary_values.glossary_coverage(fields, rules, values)
    return {
        "values_confirmed": coverage["field_values_confirmed"],
        "rule_values_confirmed": coverage["rule_values_confirmed"],
        "terms_confirmed": 0,
        "columns_patched": patched["columns"],
        "tables_patched": patched["tables"],
    }


def _sql_comment_counts(document: dict) -> dict[str, int]:
    """How many comments the contract carries, by where the author wrote them."""
    scopes = _scopes(document).values()
    return {
        "header": len(document.get("statement_comments") or []),
        "output": sum(
            len(output.get("comments") or [])
            for scope in scopes
            for output in scope.get("outputs") or []
        ),
        "logic": sum(
            len(block.get("comments") or [])
            for scope in scopes
            for block in scope.get("logic_blocks") or []
        ),
    }


def _inferred_items(
    fields: Sequence[dict], output_shape: dict, stages: Sequence[dict]
) -> dict[str, int]:
    """Which paths in this document hold an inference rather than a copied fact, counted.

    WI-1g item E7: a 52-field task listed 52 separate ``fields[7].structural_role``
    entries, one per index, which is a count written out longhand -- the index says
    nothing a reader can act on, and the markdown already grouped them back. The JSON
    now publishes the grouping itself, keyed by the path pattern.
    """
    counts: dict[str, int] = {}

    def add(path: str, times: int = 1) -> None:
        if times:
            counts[path] = counts.get(path, 0) + times

    add("fields[].structural_role", len(fields))
    for path in (
        "output_shape.shape",
        "output_shape.grain",
        "output_shape.candidate_keys",
        "output_shape.unexposed_keys",
        "output_shape.key_confidence",
    ):
        add(path)
    add("output_shape.fan_out_risks[]", len(output_shape.get("fan_out_risks") or []))
    add(
        "stages[].actions[].intent",
        sum(
            1
            for stage in stages
            for action in stage.get("actions") or []
            if action.get("type") == "window"
        ),
    )
    return counts


def _counted(values: Iterable) -> dict:
    counts = Counter(str(value) for value in values)
    return {name: counts[name] for name in sorted(counts)}


# --------------------------------------------------------- metric definition (WI-2.1)

# The roles a metric card is built for. A field outside them still gets one when its
# chain crosses an aggregate step -- the role is decided by the *last* transform, so a
# plain projection of an upstream SUM is a metric the role vocabulary does not name.
METRIC_ROLES = ("measure", "event_time")

METRIC_SPEC_KEY_ORDER = (
    "subject",
    "time_range",
    # WI-2.1c item 2. Published only when it is true: the absence of the key is "no
    # run-time function was found", which is what every other card already means.
    "time_dependent",
    "inclusion",
    "aggregation",
    "unit",
    "null_handling",
    "refresh",
    "post_aggregation",
    "evidence",
)

# Where an inclusion condition sits. A CASE inside the aggregate call restricts which
# rows the call counts, which is not the same statement as a WHERE that drops the row
# from every other measure too, so the two are never merged into one list entry.
METRIC_INCLUSION_WHERE = ("filter", "aggregate_case", "join_condition")

# METRIC_PATHS / METRIC_PATH_GRAIN / METRIC_PATH_ARGUMENT are declared with the shape
# vocabulary at the top of the module, because WI-2.1c's fan-out verdicts use them too.

# COUNT answers 0 for a group that matched nothing; every other aggregate answers NULL.
# So a nullable argument makes the metric nullable -- except under a counting call.
METRIC_COUNTING_FUNCTIONS = frozenset({"COUNT", "COUNT_IF", "APPROX_COUNT_DISTINCT"})

METRIC_TIME_RANGE_KINDS = (
    semantic_text.VALUE_KIND_LITERAL,
    semantic_text.VALUE_KIND_INSTANCE_DATE,
    semantic_text.VALUE_KIND_PARAMETER,
    semantic_text.VALUE_KIND_EXPRESSION,
    semantic_text.VALUE_KIND_RANGE,
)

# The two kinds that pin a column to one constant day. `_pinned_literal` reads both,
# because splitting the instance date out of `literal` must not un-notice a statement
# whose two sides pin two different days.
_PINNED_TIME_RANGE_KINDS = (
    semantic_text.VALUE_KIND_LITERAL,
    semantic_text.VALUE_KIND_INSTANCE_DATE,
)

# How far the aggregation-path walk may descend. Same reasoning, and same number, as the
# grain walk's own limit: a contract deeper than this is pathological, and stopping is
# an honest partial answer rather than a hang.
METRIC_PATH_DEPTH_LIMIT = GRAIN_DEPTH_LIMIT


def _build_metric_spec(
    document: dict,
    entry: dict,
    chain: dict | None,
    field: dict,
    context: dict,
    nullable_argument: dict | None = None,
) -> dict | None:
    """WI-2.1: one field's metric definition, or None when the field is not a metric.

    Every slot is read along the two paths ``METRIC_PATHS`` names. A JOIN's right side on
    neither of them is a bypass and stays out; a slot neither path proves is published
    empty or ``null``.
    """
    steps = (chain or {}).get("ordered_steps") or []
    step = _aggregate_step(steps)
    if str(field.get("structural_role")) not in METRIC_ROLES and step is None:
        return None
    scope_id, paths = _metric_anchor(document, chain, step, steps, context)
    aggregation = _metric_aggregation(document, step, context) if step else None
    time_range = _metric_time_range(document, context["rules"], paths)
    inclusion = _metric_inclusion(document, context["rules"], paths, step)
    spec = {
        "subject": _metric_subject(document, paths, scope_id, entry, step is not None),
        "time_range": time_range,
        "inclusion": inclusion,
        "aggregation": aggregation,
        "unit": _metric_unit(document, entry, field, aggregation, context),
        "null_handling": _metric_null_handling(field, steps, step, nullable_argument),
        # WI-2.2: the contract now carries the task's schedule, so the slot is filled
        # from it -- and stays null when no task JSON supplied one. A cadence is never
        # guessed from a partition column or a table name.
        "refresh": _metric_refresh(context["task_meta"]),
        "post_aggregation": _metric_post_aggregation(field, step),
        "evidence": _metric_evidence(document, field, step, paths, context["rules"]),
        **(
            {"time_dependent": True}
            if _field_expressions_are_time_dependent(entry, steps)
            else {}
        ),
    }
    return {key: spec[key] for key in METRIC_SPEC_KEY_ORDER if key in spec}


def _metric_refresh(task_meta: dict | None) -> dict | None:
    """The metric's update cadence, copied from the task metadata or ``None``.

    Both forms are published side by side because they answer different questions: the
    cycle is what a reader wants ("daily"), the cron is what actually runs. Either one
    alone is enough to publish the slot; neither is derived from the other.
    """
    if not task_meta:
        return None
    cycle = task_meta.get("schedule_cycle")
    cron = task_meta.get("schedule")
    if not cycle and not cron:
        return None
    return {"cycle": cycle, "cron": cron, "source": REFRESH_SOURCE_TASK_META}


def _metric_anchor(
    document: dict,
    chain: dict | None,
    step: dict | None,
    steps: Sequence[dict],
    context: dict,
) -> tuple[str | None, dict[str, list[str]]]:
    """``(subject scope, the two paths)``, recording the argument path for the shape block.

    The scope is published only when this document declares one: ``subject.scope_id`` is
    read as a scope id, and a table name sitting in that slot would be a false one.
    """
    anchor = str(step.get("scope_id")) if step else _subject_scope(steps)
    paths = _metric_paths(document, chain, step, anchor, context)
    context["metric_argument_scopes"].extend(paths[METRIC_PATH_ARGUMENT])
    context["metric_anchor_scopes"].extend(paths[METRIC_PATH_ANCHOR])
    return (anchor if anchor in _scopes(document) else None), paths


def _metric_paths(
    document: dict, chain: dict | None, step: dict | None, anchor: str, context: dict
) -> dict[str, list[str]]:
    """``{"grain": [...], "argument": [...], "anchor": [...]}`` -- three scope paths.

    A scope the grain path already walked is not repeated on the argument path: it is
    the same filter either way, and the reader asking "is this the driving side"
    should get one answer per condition rather than two. The anchor path is the same
    rule applied once more, and it is read by the fan-out verdict only -- ``METRIC_PATHS``
    stays the two the card's conditions are read along.
    """
    grain = _aggregation_path(document, anchor if step else _ROOT, context)
    argument: list[str] = []
    for scope_id in _argument_scopes(document, chain, step):
        argument.extend(_aggregation_path(document, scope_id, context))
    argument = _dedupe(item for item in argument if item not in grain)
    walked = {*grain, *argument}
    subtree = _input_subtree(document, anchor) if step else []
    return {
        METRIC_PATH_GRAIN: list(grain),
        METRIC_PATH_ARGUMENT: argument,
        METRIC_PATH_ANCHOR: [item for item in subtree if item not in walked],
    }


def _input_subtree(document: dict, scope_id: str) -> list[str]:
    """Every scope ``scope_id`` reads, transitively -- driving side or not, breadth first.

    The one walk in this module that does not ask which input sets the row count: below
    an aggregation that question is already answered, and what is left to judge is every
    branch whose rows the aggregate reads.
    """
    path: list[str] = []
    queue = [scope_id]
    while queue and len(path) < METRIC_PATH_DEPTH_LIMIT:
        item = queue.pop(0)
        if item in path or item not in _scopes(document):
            continue
        path.append(item)
        queue.extend(_scope_inputs(document, item))
    return path


def _argument_scopes(document: dict, chain: dict | None, step: dict | None) -> list[str]:
    """The scopes the metric's value was read from, as its own step's resolution names them.

    Read off the resolution rather than off the chain's step order: a chain that carries
    a grouping key and a measure interleaves two threads, so "the steps before the
    aggregate" includes scopes *downstream* of it. The resolution answers the question
    actually being asked -- which upstream scope this expression was expanded from --
    and a metric with no aggregate step asks it of its last step instead. Anything this
    document does not declare as a scope is dropped rather than walked.
    """
    steps = (chain or {}).get("ordered_steps") or []
    anchor = step if step is not None else (steps[-1] if steps else {})
    resolution = (anchor or {}).get("expression_resolution") or {}
    found = [str(resolution.get("source_scope_id") or "")]
    found.extend(
        str(trace.get("to_scope_id") or "")
        for trace in resolution.get("scope_output_trace") or []
    )
    return _dedupe(item for item in found if item in _scopes(document))


def _step_position(steps: Sequence[dict], step: dict | None) -> int:
    """Where the aggregate sits in the chain; a chain without one is argument throughout."""
    if step is None:
        return len(steps)
    return next(
        (index for index, item in enumerate(steps) if item is step), len(steps)
    )


def _aggregate_step(steps: Sequence[dict]) -> dict | None:
    """The last aggregating step of a chain: the scope whose GROUP BY sets the metric.

    WI-2.1d item 4: a step aggregates when its expression *carries* an aggregate call,
    not only when the contract typed the step AGGREGATE. ``DATE_FORMAT(MAX(t), ...)`` is
    typed by its outermost node, which is a scalar call, and reading only that type left
    the field's whole metric card without an aggregation to report.
    """
    found = [step for step in steps if _step_aggregates(step)]
    return found[-1] if found else None


def _step_aggregates(step: dict) -> bool:
    """Whether one chain step collapses rows -- by its type, else by its expression."""
    if str(step.get("step_type")) == "aggregate":
        return True
    if str(step.get("transform")) == "AGGREGATE":
        return True
    return semantic_text.outer_aggregate_call(step.get("expression_sql")) is not None


def _subject_scope(steps: Sequence[dict]) -> str:
    """Where a non-aggregated metric's value comes from: its chain's first step."""
    return str(steps[0].get("scope_id")) if steps else _ROOT


def _aggregation_path(document: dict, scope_id: str, context: dict) -> list[str]:
    """``scope_id`` and every scope its driving inputs descend through, breadth first.

    The same question R3's grain walk asks, asked for a different reason and answered
    with the whole path rather than with its end: which scopes' conditions are part of
    what this number counts. A JOIN's right side is never a driving input, so a lookup's
    own WHERE cannot leak into the card.
    """
    cached = context["aggregation_paths"].get(scope_id)
    if cached is not None:
        return cached
    path: list[str] = []
    queue = [scope_id]
    while queue and len(path) < METRIC_PATH_DEPTH_LIMIT:
        item = queue.pop(0)
        if item in path or item not in _scopes(document):
            continue
        path.append(item)
        queue.extend(_driving_inputs(document, item))
    context["aggregation_paths"][scope_id] = path
    return path


def _driving_inputs(document: dict, scope_id: str) -> list[str]:
    """The inputs whose rows this scope's rows come from, or [] when it cannot be told.

    A UNION answers with every branch -- each row arrives through one of them, so all of
    them are on the path. Everything else answers with its single FROM item, and a scope
    whose FROM item is ambiguous stops the descent rather than guessing.
    """
    scope = _scopes(document).get(scope_id) or {}
    if scope.get("union_branch_alignment") or str(scope.get("kind")) in (
        "union",
        "union_branch",
    ):
        return _scope_inputs(document, scope_id)
    item, _ = _scope_from_item(document, scope_id)
    return [item] if item else []


def _metric_subject(
    document: dict, paths: Mapping[str, Sequence[str]], scope_id: str, entry: dict,
    aggregated: bool,
) -> dict:
    """Which rows are being counted: the scope, and the physical tables the path reads.

    The counted rows stay the driving ones even when the number itself is read off a
    joined-in table -- one row per driving key is what the GROUP BY made. ``argument_tables``
    names that other table when *every* argument column comes from off the driving path;
    a mixed expression is still read over the driving rows, and moving the subject for it
    would state a grain the statement never wrote.
    """
    read = _entry_tables(entry)
    tables = _path_tables(document, paths["grain"]) if aggregated else read
    arguments = [item for item in read if item not in tables] if tables else []
    subject = {"scope_id": scope_id, "tables": tables}
    if arguments and len(arguments) == len(read):
        subject["argument_tables"] = arguments
    subject["text"] = semantic_text.describe_metric_subject(
        tables, scope_id, subject.get("argument_tables") or ()
    )
    return subject


def _entry_tables(entry: dict) -> list[str]:
    """The physical tables one end-to-end entry's value is read from, ambiguity dropped."""
    return _dedupe(
        str(source.get("table"))
        for source in entry.get("physical_sources") or []
        if source.get("table") and str(source.get("table")) != _AMBIGUOUS
    )


def _path_tables(document: dict, path: Sequence[str]) -> list[str]:
    return _dedupe(
        table for item in path for table in sorted(_direct_source_tables(document, item))
    )


def _direct_source_tables(document: dict, scope_id: str) -> list[str]:
    tables = set(document.get("source_tables") or [])
    return [item for item in _scope_inputs(document, scope_id) if item in tables]


def _metric_time_range(
    document: dict, rules: Sequence[dict], paths: Mapping[str, Sequence[str]]
) -> list[dict]:
    """The conjuncts on either path that bound a date, partition or variable.

    Each one carries the path it was read from, because a date on the argument side is a
    different statement from a date on the driving side -- and when the two disagree,
    which they did in the case this rule was written for, the reader has to see both.
    """
    found = []
    for name, rule in _paths_filters(rules, paths):
        if not _is_date_filter(document, rule):
            continue
        column, qualified = _rule_column(rule)
        found.append(
            {
                "column": qualified or column,
                "expression": _conjunct_text(rule),
                "kind": _time_range_kind(rule),
                "scope_id": str(rule.get("scope_id")),
                "path": name,
            }
        )
    return _mark_time_range_mismatches(found)


def _time_range_kind(rule: Mapping) -> str:
    """The published kind of one date conjunct, ``instance_date`` included.

    WI-2.9 item A. A literal written as a day (``'20260814'``, ``'2026-08-14'``) is the
    instance's own date -- the one thing a daily task's partition filter is expected to
    carry. A literal written any other way stays ``literal``, and a substitution stays
    ``parameter``: the shape is read from the constant, never assumed from the column.
    """
    kind = (
        semantic_text.predicate_value_kind(rule.get("expression"))
        or semantic_text.VALUE_KIND_EXPRESSION
    )
    if kind != semantic_text.VALUE_KIND_LITERAL:
        return kind
    parsed = semantic_text.equality_conjunct(rule.get("expression"))
    if parsed and semantic_text.looks_like_date_literal(parsed[1]):
        return semantic_text.VALUE_KIND_INSTANCE_DATE
    return kind


def _mark_time_range_mismatches(items: list[dict]) -> list[dict]:
    """WI-2.1c item 3: one column pinned to two different literals on the two paths.

    Only a disagreement *across* the paths is marked. The grain side and the argument
    side are two statements about two different relations, and when they name the same
    column and two different days the metric counts rows from one day against values
    from another -- which one is wrong is not decided here. Two conjuncts on the same
    path are one relation filtered twice and prove nothing.
    """
    pinned = [_pinned_literal(item) for item in items]
    for index, item in enumerate(items):
        value = pinned[index]
        if value is None:
            continue
        if any(
            other is not None
            and other != value
            and items[position]["path"] != item["path"]
            and _bare_column(items[position]) == _bare_column(item)
            for position, other in enumerate(pinned)
        ):
            item["mismatch"] = True
    return items


def _pinned_literal(item: Mapping) -> str | None:
    """The literal one time-range conjunct pins its column to, or None for anything else."""
    if str(item.get("kind")) not in _PINNED_TIME_RANGE_KINDS:
        return None
    parsed = semantic_text.equality_conjunct(item.get("expression"))
    return parsed[1] if parsed else None


def _bare_column(item: Mapping) -> str:
    return str(item.get("column") or "").rpartition(".")[2]


def _paths_filters(
    rules: Sequence[dict], paths: Mapping[str, Sequence[str]]
) -> list[tuple[str, dict]]:
    """``(path name, conjunct)`` for both paths, grain first, in rule order within each."""
    return [
        (name, rule)
        for name in METRIC_PATHS
        for rule in _path_filters(rules, paths.get(name) or ())
    ]


def _path_filters(rules: Sequence[dict], path: Sequence[str]) -> list[dict]:
    """WHERE conjuncts of the scopes on the path, in rule order. HAVING is not one:
    it filters groups the aggregate already formed, not the rows it counted."""
    scopes = set(path)
    return [
        rule
        for rule in rules
        if str(rule.get("kind")) == "filter" and str(rule.get("scope_id")) in scopes
    ]


def _conjunct_text(rule: dict) -> str:
    """The conjunct as the SQL wrote it, qualifiers dropped so it reads as a condition."""
    expression = rule.get("expression")
    parsed = semantic_text.parse_expression(expression)
    return semantic_text.expression_text(parsed) or str(expression or "").strip()


def _rule_column(rule: dict) -> tuple[str | None, str | None]:
    """``(bare column name, <table>.<column>)`` of one filter conjunct, either may be None.

    The qualified form is composed only from the rule's own physical fields, so it can
    never name a table this column was not resolved to.
    """
    names = semantic_text.predicate_columns(rule.get("expression"))
    column = names[0] if names else None
    if not column:
        return None, None
    owners = _dedupe(
        str(field.get("table"))
        for field in rule.get("fields") or []
        if str(field.get("column")) == column and field.get("table")
    )
    return column, f"{owners[0]}.{column}" if len(owners) == 1 else None


def _is_date_filter(document: dict, rule: dict) -> bool:
    """Three provable date signals, any one of which is enough.

    The declared type, the contract's own partition verdict (``is_partition_filter``, or
    the column being one of the target's partition columns), and the *shape* of the
    constant. The last one carries statements whose metadata was never supplied, which
    in practice is most of them.
    """
    column, _ = _rule_column(rule)
    if not column:
        return False
    if _is_temporal_column(document, column):
        return True
    partitions = {str(item) for item in document.get("target_partition_columns") or []}
    if rule.get("is_partition_filter") or column in partitions:
        return True
    return semantic_text.predicate_pins_a_date(rule.get("expression"))


def _metric_inclusion(
    document: dict,
    rules: Sequence[dict],
    paths: Mapping[str, Sequence[str]],
    step: dict | None,
) -> list[dict]:
    """The non-date conditions that decide which rows the number counts."""
    found = [
        _inclusion(rule.get("expression"), "filter", str(rule.get("scope_id")), name)
        for name, rule in _paths_filters(rules, paths)
        if not _is_date_filter(document, rule)
    ]
    found.extend(
        _inclusion(condition, "join_condition", str(rule.get("scope_id")), name)
        for name in METRIC_PATHS
        for rule in rules
        if str(rule.get("kind")) == "join_condition"
        and str(rule.get("scope_id")) in set(paths.get(name) or ())
        for condition in rule.get("extra_conditions") or []
        if condition
    )
    found.extend(
        _inclusion(condition, "aggregate_case", str(step.get("scope_id")), "grain")
        for condition in semantic_text.aggregate_case_conditions(
            (step or {}).get("expression_sql")
        )
    )
    return _dedupe(found)


def _inclusion(expression, where: str, scope_id: str, path: str) -> dict:
    parsed = semantic_text.parse_expression(expression)
    text = semantic_text.expression_text(parsed) or str(expression or "").strip()
    return {
        "expression": text,
        "text": semantic_text.describe_inclusion(text, where),
        "scope_id": scope_id,
        "where": where,
        "path": path,
    }


def _metric_aggregation(document: dict, step: dict, context: dict) -> dict | None:
    """The call and the grain: ``F(argument)`` plus the GROUP BY keys it is taken over."""
    scope_id = str(step.get("scope_id"))
    function, argument = semantic_text.aggregate_call_parts(step.get("expression_sql"))
    keys = _metric_group_keys(document, scope_id, context["exposed"])
    return {
        "function": function,
        "argument": argument,
        "argument_comment": _argument_comment(document, argument),
        "group_keys": keys,
        "text": semantic_text.describe_metric_aggregation(
            function, argument, [str(key["name"]) for key in keys if key.get("name")]
        ),
    }


def _metric_group_keys(document: dict, scope_id: str, exposed: dict) -> list[dict]:
    """One entry per GROUP BY item, with the target column it lands on (WI-1e) or None."""
    keys = _aggregation_logical_keys(document, scope_id) or []
    return [
        {
            "name": key.get("name") or _expression_label(key.get("expression")),
            "target_column": exposed.get(_key_reference(key)),
        }
        for key in keys
    ]


def _expression_label(expression) -> str | None:
    """A GROUP BY item that is not projected is named by its own text, unqualified."""
    if not expression:
        return None
    parsed = semantic_text.parse_expression(expression)
    return semantic_text.expression_text(parsed) or str(expression)


def _argument_comment(document: dict, argument: str | None) -> str | None:
    """The column comment of a bare-column aggregate argument, when exactly one says so."""
    if not argument:
        return None
    comments = _dedupe(
        str(_column_detail(item, argument).get("comment"))
        for item in _input_metadata(document).values()
        if _column_detail(item, argument).get("comment")
    )
    return comments[0] if len(comments) == 1 else None


def _chain_expressions(entry: dict, steps: Sequence[dict]) -> list[str]:
    """Every SQL text one field's value was written in: the projection and each step."""
    return _dedupe(
        str(item)
        for item in [
            entry.get("expression"),
            *[step.get("expression_sql") for step in steps],
        ]
        if item
    )


def _field_expressions_are_time_dependent(entry: dict, steps: Sequence[dict]) -> bool:
    """WI-2.1c item 2: does this field's value depend on when the job ran?"""
    return any(
        semantic_text.nondeterministic_functions(expression)
        for expression in _chain_expressions(entry, steps)
    )


def _unit_expressions(entry: dict, field: dict, aggregation: dict | None) -> list[str]:
    """The forms the metric's value is written in, most specific first."""
    return _dedupe(
        str(item)
        for item in (
            (aggregation or {}).get("argument"),
            field.get("expression") or entry.get("expression"),
        )
        if item
    )


def _metric_unit(
    document: dict, entry: dict, field: dict, aggregation: dict | None, context: dict
) -> dict:
    """The declared type, plus a unit word only when a comment or the call earns one."""
    argument = (aggregation or {}).get("argument")
    declared = str(context["column_types"].get(str(argument)) or "") if argument else ""
    hint, source = semantic_text.unit_hint(
        [field.get("target_comment"), (aggregation or {}).get("argument_comment")],
        (aggregation or {}).get("function"),
        temporal_argument=_is_temporal(declared),
        temporal_type=_is_temporal(field.get("type") or _source_type(document, entry)),
        # WI-2.1c item 1: a date difference states its own unit, and the call that says
        # so is inside the expression rather than being the aggregate's own name.
        expressions=_unit_expressions(entry, field, aggregation),
    )
    return {"type": field.get("type"), "hint": hint, "hint_source": source}


def _metric_null_handling(
    field: dict,
    steps: Sequence[dict],
    step: dict | None,
    nullable_argument: dict | None = None,
) -> dict:
    """``nullable_by_join`` plus the one default value the contract can prove.

    ``nullable_argument`` is published only when the flag was earned by the *argument*
    rather than by the field's own chain: the card then names the join and the side, so
    the reader is told why an unmatched key leaves this number empty.
    """
    default, source = _proven_default(field, step, _steps_after(steps, step))
    handling = {"nullable_by_join": bool(field.get("nullable_by_join"))}
    if nullable_argument:
        handling["nullable_argument"] = nullable_argument
    handling["default"] = default
    handling["default_source"] = source
    return handling


def _proven_default(
    field: dict, step: dict | None, after: Sequence[dict]
) -> tuple[str | None, str | None]:
    """``(value, source)`` of the one default this field's own value proves (WI-2.1d item 2).

    One ordered chain interleaves threads -- a measure's steps and the grouping key's sit
    in it together, because the window that carries the measure reads the key -- so
    sweeping every step for any COALESCE or CASE published the *neighbouring* column's
    fallback as this metric's default: a value this field never takes.

    Three readings survive that, each tied to a value this field actually holds. A step
    after the aggregate -- the field's own final expression being the last of them --
    counts when the COALESCE *is* that expression, because then it fills the null of the
    value that expression produces; ``COALESCE(a, 0) - COALESCE(b, 0)`` fills its two
    operands and leaves the difference with no default of its own. The aggregate call
    counts at any depth, because a fill inside its argument is what the call read. And a
    CASE ELSE is read only from the final expression, at its top level and only when it
    is a scalar constant: a nested CASE is some call's argument, and an ELSE that is a
    column carries another value through rather than filling anything in.
    """
    tail = field.get("expression")
    for item in [*(step.get("expression_sql") for step in after), tail]:
        value = semantic_text.top_level_coalesce_default(item)
        if value is not None:
            return value, "COALESCE"
    value = semantic_text.coalesce_default((step or {}).get("expression_sql"))
    if value is not None:
        return value, "COALESCE"
    value = semantic_text.constant_case_default(tail)
    return (value, "CASE_ELSE") if value is not None else (None, None)


def _steps_after(steps: Sequence[dict], step: dict | None) -> list[dict]:
    """The chain steps that run after the aggregate, or the whole chain without one."""
    if step is None:
        return list(steps)
    return list(steps[_step_position(steps, step) + 1 :])


def _metric_post_aggregation(field: dict, step: dict | None) -> list[str]:
    """What happens to the number after it is aggregated, in the words R4 already used.

    WI-2.1d item 4 adds the wrapper: a scalar call around the aggregate happens after it
    inside one expression rather than in a later chain step, so listing only later steps
    left ``DATE_FORMAT(MAX(t), 'yyyy-MM-dd')`` looking like a bare ``MAX``.
    """
    if step is None:
        return []
    boundary = step.get("step_no")
    wrapper = semantic_text.describe_aggregate_wrapper(step.get("expression_sql"))
    return _dedupe(
        [
            *([wrapper] if wrapper else []),
            *[
                str(item["text"])
                for item in field.get("derivation") or []
                if item.get("text")
                and item.get("step_no") is not None
                and boundary is not None
                and item["step_no"] > boundary
                and str(item.get("step_type"))
                not in semantic_text.PASS_THROUGH_STEP_TYPES
            ],
        ]
    )


def _metric_evidence(
    document: dict,
    field: dict,
    step: dict | None,
    paths: Mapping[str, Sequence[str]],
    rules: Sequence[dict],
) -> list[str]:
    """Every id the card was read from: the aggregate's blocks, the conditions, the chain."""
    found = [str(item) for item in (step or {}).get("logic_ids") or []]
    if step is not None:
        found.extend(
            _block_ids(_blocks_of_type(document, str(step.get("scope_id")), "group_by"))
        )
    found.extend(str(rule.get("evidence")) for _, rule in _paths_filters(rules, paths))
    if field.get("mapping_chain_id"):
        found.append(str(field["mapping_chain_id"]))
    return _dedupe(item for item in found if item and item != "None")



# --------------------------------------------------------- governance findings (WI-1f)


FINDING_ALIAS_POSITION_MISMATCH = "alias_position_mismatch"
FINDING_PARTITION_MISMATCH = "partition_literal_mismatch"
FINDING_NONDETERMINISTIC_FUNCTION = "nondeterministic_function"
FINDING_HARDCODED_DATE = "hardcoded_date_literal"
FINDING_METADATA_CONFLICTS = "metadata_conflicts"
FINDING_TARGET_BINDING = "target_binding"
FINDING_TABLE_COMMENT_MISSING = "table_comment_missing"

# Rendered in this order, most actionable first. The order is fixed so two runs of the
# same document cannot list the same findings differently.
FINDING_KINDS = (
    FINDING_ALIAS_POSITION_MISMATCH,
    FINDING_PARTITION_MISMATCH,
    FINDING_NONDETERMINISTIC_FUNCTION,
    FINDING_HARDCODED_DATE,
    FINDING_METADATA_CONFLICTS,
    FINDING_TARGET_BINDING,
    FINDING_TABLE_COMMENT_MISSING,
)

# WI-2.9 item A. Not every provable fact is a lead somebody has to act on, and rendering
# them as if they were is what made the list unreadable: "this statement reads one day"
# is how a scheduled daily task is supposed to look, and it sat beside "the job may be
# writing values into the wrong columns" wearing the same ⚠.
#
# `warn` -- a person has to do something, and the numbers or their meaning are at stake.
# `info` -- true, worth keeping in the JSON, and no action follows from it.
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"

FINDING_SEVERITIES = (SEVERITY_WARN, SEVERITY_INFO)

# Why the `info` ones are not leads:
#
# - `hardcoded_date_literal`: a task instance covers one day, so its partition filter
#   naming that day is the design. The day itself is published on section 1's 取数日 line.
# - `partition_literal_mismatch`: two sides reading two different days is a *definition*
#   the reader needs (the reminder side takes the day before), and it is stated as one on
#   the metric card's 时间范围 line rather than as a defect.
# - `table_comment_missing`: section 6 already counts metadata completeness one line
#   above, the glossary already publishes the per-column 待补注释 lists, and nothing about
#   a value or its meaning changes with the answer.
# - `target_binding` (B11): how a write binds its columns is a fact about the statement,
#   and a warehouse may write positionally everywhere. On a wide corpus it warned on
#   nearly every statement, which is the same as warning on none. The lead is the *name
#   mismatch*: where `alias_position_mismatch` is also present, `_target_binding_findings`
#   raises this one back to `warn` so the reader has the binding line beside it.
#
# Two kinds here are the DEFAULT rather than the whole answer: their producer overrides
# the severity from the evidence (B11).
#
# - `metadata_conflicts` stays `warn`, except for `kept_authoritative`: two sources
#   describing one table and the loader keeping the authoritative one is a fact about the
#   metadata load, not about this task, and nobody acts on it.
# - `nondeterministic_function` stays `warn`, except where every affected field is an
#   audit column -- a constant projection whose expression is only the run-time call.
FINDING_SEVERITY = {
    FINDING_ALIAS_POSITION_MISMATCH: SEVERITY_WARN,
    FINDING_PARTITION_MISMATCH: SEVERITY_INFO,
    FINDING_NONDETERMINISTIC_FUNCTION: SEVERITY_WARN,
    FINDING_HARDCODED_DATE: SEVERITY_INFO,
    FINDING_METADATA_CONFLICTS: SEVERITY_WARN,
    FINDING_TARGET_BINDING: SEVERITY_INFO,
    FINDING_TABLE_COMMENT_MISSING: SEVERITY_INFO,
}

# B11. The one resolution that says the loader already did the right thing: a second
# description of the same table was set aside in favour of the authoritative one.
METADATA_CONFLICT_RESOLVED = "kept_authoritative"

# The one finding section 6 gives its own line instead of listing under 治理线索: the
# reader asking "can I trust which column each value landed in" should not have to find
# it among the others.
FINDING_OWN_LINE = FINDING_TARGET_BINDING

# WI-1g item C. How many mismatching projections the finding names before it says how
# many there are and leaves the rest to the mapping chains it cites.
ALIAS_MISMATCH_PREVIEW_COUNT = 3

# The binding method the finding is about: the values were matched to target columns by
# their *position* in the DDL, so a name mismatch means the write is positional and the
# names disagree -- either the data went into the wrong column or the metadata's column
# order is stale.
_POSITIONAL_BINDING_METHOD = "ddl_position"

# The names sqlglot's `qualify` invents for a projection the author did not alias. They
# are the absence of an alias, not an alias that disagrees -- see `_name_is_generated`.
_GENERATED_NAME_SHAPE = re.compile(r"_col_\d+|_c\d+")

_TARGET_BINDING_METHOD_NOTES = {
    "ddl_position": "按 DDL 位置绑定，目标表 DDL 变更会导致列错位",
    "projection_alias": "按投影别名绑定",
}

# The status Core publishes for a statement that had no binding to make (Q4).
_NOT_APPLICABLE_BINDING_STATUS = "not_applicable"

# Q4. What a fallback fell back on, in the reader's words. `status=fallback、
# method=sql_projection` was true and unusable: it said the target metadata was not applied
# without saying whether anybody can act on that -- a target nobody supplied metadata for is
# a gap to close, a projection that disagrees with the DDL is a statement to go and read,
# and an unexpanded `SELECT *` is neither of those. The token is Core's; the gloss is this
# document's.
_TARGET_BINDING_FALLBACK_NOTES = {
    "no_target_metadata": "按 SQL 投影绑定：目标表无元数据",
    "projection_target_count_mismatch": "按 SQL 投影绑定：投影列数与目标列数不一致",
    "target_column_names_not_unique": "按 SQL 投影绑定：目标列名不唯一",
    "star_projection_unexpanded": "按 SQL 投影绑定：SELECT * 未展开，缺来源表结构",
    "insert_column_list_unknown_column": "按 SQL 投影绑定：INSERT 列清单里有目标元数据没有的列",
    "unsupported_statement_kind": "按 SQL 投影绑定：该语句种类不做位置绑定",
    "other": "按 SQL 投影绑定：原因见 issues",
}

_FINDING_KEY_ORDER = ("kind", "severity", "text", "evidence")


def _finding(
    kind: str, text: str, evidence: Iterable = (), severity: str | None = None
) -> dict:
    """One finding. ``severity`` overrides the kind's default from the evidence (B11)."""
    return {
        "kind": kind,
        "severity": severity or FINDING_SEVERITY.get(kind, SEVERITY_WARN),
        "text": text,
        "evidence": [str(item) for item in evidence if item],
    }


def _build_findings(
    document: dict,
    diagnostics: dict | None,
    rules: Sequence[dict],
    fields: Sequence[dict] = (),
) -> list[dict]:
    """Governance leads the contract already proves, in ``FINDING_KINDS`` order.

    Every one is a structural or metadata fact restated, never a judgement: "these two
    tables are filtered to different date literals" is provable from the rules, while
    "the task reads stale data" is not, and is not said.
    """
    comparisons = _literal_comparisons(document, rules)
    alias_mismatch = _alias_position_findings(document, fields)
    found = [
        *alias_mismatch,
        *_partition_mismatch_findings(comparisons, fields),
        *_nondeterministic_findings(rules, fields),
        *_hardcoded_date_findings(comparisons),
        *_metadata_conflict_findings(diagnostics),
        # B11: the binding line is a lead only beside the name mismatch it explains.
        *_target_binding_findings(document, mismatched=bool(alias_mismatch)),
        *_table_comment_findings(document),
    ]
    order = {kind: index for index, kind in enumerate(FINDING_KINDS)}
    found.sort(key=lambda item: order.get(item["kind"], len(FINDING_KINDS)))
    return [{key: item[key] for key in _FINDING_KEY_ORDER} for item in found]


def _alias_position_findings(document: dict, fields: Sequence[dict]) -> list[dict]:
    """Positional binding where the SQL alias and the DDL column at that position differ.

    WI-1g item C. Core already counts these (``target_field_binding.corrected_column_count``)
    and keeps the alias under ``end_to_end_lineage[].parsed_column``, but the skeleton
    only said "按 DDL 位置绑定" -- the reader never learned that 25 of 52 written values
    landed in a column whose declared name is not the one the SQL wrote. It is one of
    two things and both need a person: the job writes data into the wrong columns, or
    the target metadata's column order is out of date. Neither is decided here.
    """
    binding = document.get("target_field_binding") or {}
    if str(binding.get("method")) != _POSITIONAL_BINDING_METHOD:
        return []
    entries = document.get("end_to_end_lineage") or []
    mismatched = [
        entry
        for entry in entries
        if entry.get("parsed_column")
        and str(entry.get("parsed_column")) != str(entry.get("column"))
        and not _name_is_generated(entry)
    ]
    if not mismatched:
        return []
    chains = {str(field.get("column")): field.get("mapping_chain_id") for field in fields}
    examples = "、".join(
        f"目标 {entry.get('column')} ← 别名 {entry.get('parsed_column')}"
        for entry in mismatched[:ALIAS_MISMATCH_PREVIEW_COUNT]
    )
    shown = (
        f"前 {ALIAS_MISMATCH_PREVIEW_COUNT} 例：{examples}"
        if len(mismatched) > ALIAS_MISMATCH_PREVIEW_COUNT
        else examples
    )
    return [
        _finding(
            FINDING_ALIAS_POSITION_MISMATCH,
            f"按位置写入且 {len(mismatched)}/{len(entries)} 个投影的 SQL 别名与 DDL "
            f"同位置列名不同（如 {shown}）——生产数据写错列或元数据列序过期，需 DESC 表核对",
            [chains.get(str(entry.get("column"))) for entry in mismatched],
        )
    ]


def _name_is_generated(entry: Mapping) -> bool:
    """Whether ``parsed_column`` is a placeholder rather than an alias somebody wrote.

    Two answers, in order. The contract's own ``name_is_generated`` is the fact and wins
    where it is published -- but it is published only while the generated name is still
    *unbound*, and a positional write binds every one of them, which is exactly the case
    this guard exists for. So the fallback is the placeholder's shape: sqlglot's
    ``qualify`` names an unaliased projection ``_col_N`` (and ``_c_N`` in some
    dialects), and ``select_scope`` already treats those two spellings as generated.
    """
    if entry.get("name_is_generated"):
        return True
    return bool(_GENERATED_NAME_SHAPE.fullmatch(str(entry.get("parsed_column") or "")))


def _literal_comparisons(document: dict, rules: Sequence[dict]) -> list[dict]:
    """Every ``<column> = <right side>`` conjunct of a filter, classified by right side.

    ``literal`` / ``parameter`` / ``expression`` are the three things a date filter can
    be pinned to, and only the first is a hardcoded date. ``${bizdate}`` parses as a
    sqlglot parameter, so the distinction is read from the tree rather than by matching
    the text for a dollar sign.
    """
    found: list[dict] = []
    for rule in rules:
        if str(rule.get("kind")) != "filter":
            continue
        parsed = semantic_text.equality_conjunct(rule.get("expression"))
        if parsed is None:
            continue
        column, value, kind = parsed
        tables = [
            str(field.get("table"))
            for field in rule.get("fields") or []
            if str(field.get("column")) == column and field.get("table")
        ]
        found.append(
            {
                "column": column,
                "value": value,
                "value_kind": kind,
                "tables": _dedupe(tables),
                "partition": bool(rule.get("is_partition_filter")),
                "temporal": _is_temporal_column(document, column),
                "evidence": str(rule.get("rule_id") or rule.get("evidence") or ""),
            }
        )
    return found


def _is_temporal_column(document: dict, column: str) -> bool:
    """True when every table declaring this column declares it date-like.

    "Every" rather than "any": a column two tables type differently proves nothing, and
    this feeds a finding, not a guess.
    """
    declared = [
        str(_column_detail(item, column).get("type") or "")
        for item in _input_metadata(document).values()
        if _column_detail(item, column)
    ]
    return bool(declared) and all(_is_temporal(item) for item in declared)


def _partition_mismatch_findings(
    comparisons: Sequence[dict], fields: Sequence[dict] = ()
) -> list[dict]:
    """Two input tables pinned to different literals on the same column name.

    Only equality against a literal counts: ``dt >= a AND dt < b`` is one range written
    in two conjuncts, not a mismatch, and two tables is the smallest thing that can
    disagree -- one table filtered twice on the same column is its own business.

    WI-2.1c item 3: the evidence also names the mapping chains of the metrics whose own
    time range carries the disagreement, so a reader who found the finding can go
    straight to the numbers it affects instead of re-deriving which fields those are.
    """
    findings = []
    for column in _dedupe(item["column"] for item in comparisons):
        group = [
            item
            for item in comparisons
            if item["column"] == column
            and item["value_kind"] == semantic_text.VALUE_KIND_LITERAL
        ]
        values = _dedupe(item["value"] for item in group)
        tables = _dedupe(table for item in group for table in item["tables"])
        if len(values) < 2 or len(tables) < 2:
            continue
        findings.append(_partition_mismatch_finding(column, group, fields))
    return findings


def _partition_mismatch_finding(
    column: str, group: Sequence[dict], fields: Sequence[dict]
) -> dict:
    stated = "、".join(
        f"{table}.{column} = {item['value']}"
        for item in group
        for table in item["tables"]
    )
    return _finding(
        FINDING_PARTITION_MISMATCH,
        f"多张输入表在 {column} 上的过滤字面量不一致：{stated}",
        [
            *[item["evidence"] for item in group],
            *_mismatched_metric_chains(fields, column),
        ],
    )


def _mismatched_metric_chains(fields: Sequence[dict], column: str) -> list[str]:
    """The mapping chains of the metrics whose time range disagrees on ``column``."""
    return _dedupe(
        str(field.get("mapping_chain_id"))
        for field in fields
        if field.get("mapping_chain_id")
        for item in (field.get("metric_spec") or {}).get("time_range") or []
        if item.get("mismatch") and _bare_column(item) == str(column)
    )


# WI-2.1c item 2. A field is named by the column it writes and a condition by its rule
# id, because that is how a reader looks either of them up in this document.
_NONDETERMINISTIC_FIELD_PREFIX = "字段 "
_NONDETERMINISTIC_RULE_PREFIX = "规则 "


def _nondeterministic_findings(
    rules: Sequence[dict], fields: Sequence[dict]
) -> list[dict]:
    """One finding when the statement's value depends on when it runs, or on chance.

    ``CURRENT_TIMESTAMP`` / ``CURRENT_DATE`` / ``NOW()`` / a bare ``UNIX_TIMESTAMP()`` /
    ``RAND`` / ``UUID`` all answer differently on a re-run, so a backfill of an old day
    does not reproduce the row it is replacing. That is a structural fact about the SQL,
    not a judgement about the job, and it is stated as one.
    """
    named: list[str] = []
    evidence: list[str] = []
    affected: list[dict] = []
    rule_hit = False
    for field in fields:
        if not (field.get("metric_spec") or {}).get("time_dependent") and not any(
            semantic_text.nondeterministic_functions(item.get("expression"))
            for item in [field, *(field.get("derivation") or [])]
        ):
            continue
        named.append(f"{_NONDETERMINISTIC_FIELD_PREFIX}{field.get('column')}")
        evidence.append(str(field.get("mapping_chain_id") or ""))
        affected.append(field)
    for rule in rules:
        if str(rule.get("kind")) not in _PREDICATE_LOGIC_TYPES:
            continue
        if not semantic_text.nondeterministic_functions(rule.get("expression")):
            continue
        named.append(f"{_NONDETERMINISTIC_RULE_PREFIX}{rule.get('rule_id')}")
        evidence.append(str(rule.get("evidence") or ""))
        rule_hit = True
    if not named:
        return []
    audit = [] if rule_hit else _audit_columns(affected)
    reason = (
        AUDIT_ONLY_NOTE.format(columns="、".join(audit))
        if audit and len(audit) == len(affected)
        else ""
    )
    return [
        _finding(
            FINDING_NONDETERMINISTIC_FUNCTION,
            "依赖作业运行时刻或随机值而非数据日期，补跑历史会得到不同结果："
            + "、".join(named)
            + reason,
            evidence,
            severity=SEVERITY_INFO if reason else SEVERITY_WARN,
        )
    ]


# B11. What the reader is told instead of a warning: the call decides one column's stamp
# and nothing else, so a re-run reproduces every number the table carries.
AUDIT_ONLY_NOTE = "（仅用于审计列 {columns}，不进入过滤、关联、分组或指标）"


def _audit_columns(fields: Sequence[dict]) -> list[str]:
    """The affected fields that are audit columns, named; empty when any one is not.

    An audit column is a *constant projection* whose expression is only the run-time call
    -- ``insert_time = current_timestamp()``. Constant is the structural role's own word
    for "built from no physical column", so such a field feeds no filter, join, group or
    metric in this statement; wrapping the call in anything else (``date_sub(current_date(),
    1)``) makes it a derived value somebody reads as data, and it is not one of these.
    """
    named = [str(field.get("column")) for field in fields if _is_audit_column(field)]
    return named if len(named) == len(fields) else []


def _is_audit_column(field: Mapping) -> bool:
    if str(field.get("structural_role")) != "constant":
        return False
    if (field.get("metric_spec") or {}).get("time_dependent"):
        return False
    steps = field.get("derivation") or []
    if len(steps) > 1:
        return False
    return all(
        _is_bare_nondeterministic_call(item.get("expression"))
        for item in [field, *steps]
    )


def _is_bare_nondeterministic_call(expression: object) -> bool:
    """Whether the whole expression IS one run-time call, rather than containing one."""
    node = semantic_text.parse_expression(str(expression or ""))
    name = semantic_text.function_name(node)
    return bool(name) and name in semantic_text.NONDETERMINISTIC_FUNCTIONS


def _hardcoded_date_findings(comparisons: Sequence[dict]) -> list[dict]:
    """A partition or date filter pinned to a literal rather than to a variable."""
    pinned = [
        item
        for item in comparisons
        if item["value_kind"] == semantic_text.VALUE_KIND_LITERAL
        and (item["partition"] or item["temporal"])
    ]
    if not pinned:
        return []
    stated = "、".join(
        f"{item['column']} = {item['value']}" for item in _dedupe_by_text(pinned)
    )
    return [
        _finding(
            FINDING_HARDCODED_DATE,
            f"分区/日期过滤使用字面量而非变量或函数：{stated}",
            [item["evidence"] for item in pinned],
        )
    ]


def _dedupe_by_text(items: Sequence[dict]) -> list[dict]:
    return unique_ordered(items, lambda item: (item["column"], item["value"]))


def _metadata_conflict_findings(diagnostics: dict | None) -> list[dict]:
    """Metadata the loader refused or overrode, one line per conflicting table.

    Only the 2.0 diagnostics document carries these (``metadata_coverage``); a 1.0
    statement document has no such key and yields nothing, which is the honest answer.
    """
    conflicts = ((diagnostics or {}).get("metadata_coverage") or {}).get(
        "metadata_conflicts"
    ) or []
    findings = []
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        table = str(conflict.get("table") or "").strip()
        resolution = str(conflict.get("resolution") or conflict.get("reason") or "未说明")
        source = conflict.get("source_file")
        subject = table or f"元数据文件 {source}" if source else table or "未命名来源"
        findings.append(
            _finding(
                FINDING_METADATA_CONFLICTS,
                f"{subject}：元数据来源冲突，处理方式 {resolution}",
                [table, source],
                # B11: a conflict the loader settled by keeping the authoritative
                # description states what the LOADER did, not what this task does, and
                # there is nothing for a reader of the task to act on.
                severity=(
                    SEVERITY_INFO
                    if resolution == METADATA_CONFLICT_RESOLVED
                    else SEVERITY_WARN
                ),
            )
        )
    return findings


def _target_binding_findings(document: dict, *, mismatched: bool = False) -> list[dict]:
    """How the written values were matched to target columns -- or why they were not.

    ``mismatched`` is whether this same statement also carries
    ``alias_position_mismatch``. Only then is the binding method a lead: positional
    writing on its own is a house style, while positional writing whose names disagree is
    the thing a reader has to go and check (B11). The text is the same either way.
    """
    severity = SEVERITY_WARN if mismatched else SEVERITY_INFO
    binding = document.get("target_field_binding") or {}
    absent = document.get("target_binding_absent_reason")
    if binding.get("status") == _NOT_APPLICABLE_BINDING_STATUS:
        # Nothing was bound and nothing was meant to be: a CTAS defines the columns it
        # writes. Listing it beside the bindings that did fall back would spend the reader's
        # attention on the one entry that never needs any.
        return []
    if binding:
        method = str(binding.get("method") or "未知")
        note = _TARGET_BINDING_FALLBACK_NOTES.get(
            str(binding.get("fallback_reason") or "")
        ) or _TARGET_BINDING_METHOD_NOTES.get(method)
        text = f"status={binding.get('status')}、method={method}"
        return [
            _finding(
                FINDING_TARGET_BINDING,
                f"{text}（{note}）" if note else text,
                severity=severity,
            )
        ]
    if absent:
        return [
            _finding(
                FINDING_TARGET_BINDING,
                f"未做目标列绑定（target_binding_absent_reason={absent}）",
                severity=severity,
            )
        ]
    return []


def _table_comment_findings(document: dict) -> list[dict]:
    """Input and target tables the metadata describes without a table-level comment."""
    missing = [
        table
        for table, item in sorted(_input_metadata(document).items())
        if not _table_comment(item)
    ]
    target = str(document.get("target_table") or "")
    if target and not _table_comment(_output_metadata(document)):
        missing.append(target)
    if not missing:
        return []
    return [
        _finding(
            FINDING_TABLE_COMMENT_MISSING,
            f"缺少表注释的表（{len(missing)} 张）：{'、'.join(missing)}",
        )
    ]
