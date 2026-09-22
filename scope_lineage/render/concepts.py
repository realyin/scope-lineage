"""K1 / K2: a concept layer above the table-level ontology.

``ontology.entities[]`` answer "what is this **table**": one entity per physical table,
its candidate keys, its columns, its family. That is the honest reading of a warehouse,
and it is not the reading a business asks for. A business asks about 「客户」, and the
warehouse spells 客户 as ``ods.customer_base``, ``dwd.customer_df``, ``dwd.customer_di``
and three staging copies. It also asks about 「消息发送」 -- which is not a thing but
something that *happened*, and which sits beside 客户 rather than under it.

This module folds the tables that share one business key into one **concept**, and says
which of three kinds it is:

* ``entity`` -- a thing the business keeps (客户, 门店),
* ``event`` -- something that happened, keyed by a time or an event id (消息发送, 回款),
* ``summary`` -- a number somebody aggregated (客户日汇总).

Three rules keep it a candidate rather than a claim.

1. **The seed is a key, not a word.** A concept exists because some table carries a
   candidate key that reduces to one non-generic stem -- never because two names look
   alike. Three things then place a table on it: its own candidate key (at any tier, with
   the tier travelling along as ``membership_basis``), a ``declared_hints[]`` primary-key
   comment, or a JOIN, which makes it a ``reference`` member because it *carries* the key
   without being unique by it. A table whose only key is ``id`` and which no JOIN reaches
   is published in ``unassigned_tables[]`` with the reason, because "we could not tell"
   is an answer.
2. **Every kind carries its votes.** ``kind_evidence[]`` lists each signal and what it
   voted for. Signals that agree earn ``implied``; signals that disagree earn
   ``hypothesis`` and the reviewer sees exactly which two disagreed.
3. **The name is never derived from a number.** ``name`` is the best of a ranked
   ``name_candidates[]`` and always ``hypothesis``: a column comment and a table comment
   are metadata, and metadata goes stale. The stem itself is the last resort.

``entities[]`` stay exactly as they were: a concept *points at* the tables that represent
it, and the table-level reading is what a reviewer checks the fold against.

Input is derived documents only -- the ontology dict this module is called from and the
table cards underneath it. Grain and task roles are read off the cards' ``produced_by``
/ ``consumed_by`` blocks, so no semantic profile is needed here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

#: The three kinds a concept can be. ``event`` and ``entity`` are deliberately siblings.
CONCEPT_ENTITY = "entity"
CONCEPT_EVENT = "event"
CONCEPT_SUMMARY = "summary"

#: Tie-break order when only word hints vote: the least committal kind wins.
KIND_ORDER = (CONCEPT_ENTITY, CONCEPT_EVENT, CONCEPT_SUMMARY)

# Mirrors `ontology.TIER_IMPLIED` / `TIER_HYPOTHESIS`. Spelled here rather than imported
# because `ontology` imports this module; `tests/core/test_concepts.py` pins them equal.
TIER_IMPLIED = "implied"
TIER_HYPOTHESIS = "hypothesis"

#: Candidate-key tiers, strongest first. A warehouse rarely *proves* a key -- the proof
#: needs a producing task that deduplicated by it -- so reading only the proven ones
#: leaves nearly every table unplaced, which models nothing. Every tier seeds; the tier
#: travels with the membership and caps the concept's own.
SEED_TIERS = ("confirmed", "proven", "implied", "hypothesis", "conflict")
#: The tiers that let a concept reach `implied`.
STRONG_TIERS = ("confirmed", "proven")

#: Why this table belongs to this concept.
BASIS_KEY_PREFIX = "key:"
BASIS_DECLARED_HINT = "declared_hint"
BASIS_REFERENCE = "reference"

#: What one member table is to its concept.
ROLE_PRIMARY = "primary"
ROLE_SNAPSHOT = "snapshot"
ROLE_DETAIL = "detail"
ROLE_SUMMARY = "summary"
ROLE_INTERMEDIATE = "intermediate"
#: O1 related this table to the concept's key without the table being keyed by it: it
#: carries the key as a foreign key. That is how an event table takes part in 客户.
ROLE_REFERENCE = "reference"

#: K4d: how strong a claim one role makes about the concept. A merge that finds one
#: table on both sides keeps the stronger of the two readings, because deduping into
#: the survivor's row drops what the folded concept knew about that table.
ROLE_STRENGTH = (
    ROLE_PRIMARY,
    ROLE_SNAPSHOT,
    ROLE_DETAIL,
    ROLE_SUMMARY,
    ROLE_INTERMEDIATE,
    ROLE_REFERENCE,
)

#: How representative a member's own comment is of the concept, for naming.
ROLE_NAMING_RANK = {
    ROLE_PRIMARY: 0,
    ROLE_SNAPSHOT: 0,
    ROLE_DETAIL: 1,
    ROLE_SUMMARY: 1,
    ROLE_INTERMEDIATE: 2,
    ROLE_REFERENCE: 2,
}

#: Relation kinds that make the `from` side a reference member. A union sibling is the
#: same shape written twice, not one table pointing at another.
REFERENCE_RELATION_KINDS = ("join_association", "hinted")

REASON_NO_CANDIDATE_KEY = "no_candidate_key"
REASON_GENERIC_KEY = "generic_key_only"
REASON_SPLIT_KEY = "key_spans_several_stems"

NAME_FROM_KEY_COMMENT = "key_column_comment"
NAME_FROM_TABLE_COMMENT = "table_comment"
NAME_FROM_STEM = "key_stem"
#: K4b: a name no column and no table comment proposed -- a reviewer did.
NAME_FROM_OVERRIDE = "override"

CONCEPT_ID_PREFIX = "concept:"

#: Whole name segments that say "this column is a key", not what the key is *of*.
KEY_AFFIXES = ("no", "id", "code", "cd", "num", "key")

#: Stems that identify a row without naming a thing. A table keyed only by one of these
#: is not a concept, it is a table with a surrogate key.
SURROGATE_STEMS = frozenset(
    {"id", "uuid", "dt", "etl", "create", "update", "row", "seq", "rn", "pk"}
)
#: K4b: the same idea for the id a log, a trace or a digest hands a row. A warehouse
#: writes ``rowkey`` on three unrelated tables because all three came off one log
#: pipeline, never because the three hold one business thing -- and a review round
#: watched exactly that grow a "concept" out of three row ids.
#:
#: Spelled as the stems ``key_stem`` reduces the columns to, so ``log_id`` is here as
#: ``log`` and ``trace_id`` as ``trace``. The id-shaped spellings (``msgid``,
#: ``traceid``, ``logid``) are listed whole *instead of* their bare stems wherever the
#: bare word names a business thing as readily as a log: ``msg_id`` reduces to ``msg``,
#: and 消息发送 is a concept a corpus really has, so only ``msgid`` is generic and a
#: ``msg_id`` that is really a digest is caught by its comment below.
LOG_ID_STEMS = frozenset(
    {
        "rowkey",
        "rowid",
        "logid",
        "log",
        "traceid",
        "trace",
        "reqid",
        "requestid",
        "request",
        "req",
        "msgid",
        "md5",
        "hash",
        "guid",
        "snowflake",
        "random",
        "rand",
    }
)
GENERIC_STEMS = SURROGATE_STEMS | LOG_ID_STEMS

#: What a key column's comment says when the value was *generated for this row* rather
#: than named: a log id, a digest, a random, a snowflake. Matched anywhere in the
#: comment, case-insensitively.
#:
#: ``uuid`` and ``guid`` are deliberately absent, although a column *named* one of them
#: is generic above. As a comment they are already a ``NAME_STOPLIST_EXACT`` word --
#: 「UUID」 says the comment named nothing -- and a ``cust_no`` whose values happen to be
#: uuids is still 客户's key. One word cannot mean both "this comment named nothing" and
#: "this column is nobody's business key".
LOG_ID_COMMENT_MARKERS = (
    "日志id",
    "日志编号",
    "日志主键",
    "md5",
    "hash",
    "哈希",
    "随机",
    "雪花",
    "snowflake",
)

#: Segments that make a column a point in time.
TIME_SEGMENTS = frozenset(
    {"dt", "date", "time", "ts", "datetime", "day", "hour", "minute", "month", "year", "at"}
)
#: Segments that make a column an event identifier.
EVENT_SEGMENTS = frozenset({"event", "log", "trace", "flow", "serial"})
_TEMPORAL_TYPES = ("timestamp", "date", "datetime")

#: Table-name suffixes, matched as whole segments (the same discipline `table_family`
#: uses): a full snapshot, a period increment, and a build step.
FULL_SNAPSHOT_SUFFIXES = ("df", "hf", "mf", "wf", "all")
INCREMENT_SUFFIXES = ("di", "hi", "mi", "wi")
PERIOD_SUFFIXES = FULL_SNAPSHOT_SUFFIXES + INCREMENT_SUFFIXES
_STAGE_RE = re.compile(r"\A(?:tmp|bak|mid|step|stage)\d*\Z")

#: Grain bases (``semantic_profile``'s vocabulary) that make a member a summary.
AGGREGATED_BASES = ("group_by", "single_row")
DRIVING_ROWS_BASIS = "driving_table_rows"
DRIVING_ROLE = "driving"

#: Secondary evidence only: a word in a name or a comment never decides a kind on its
#: own when a structural signal spoke, and it is always published as its own vote.
WORD_HINTS = (
    (CONCEPT_EVENT, ("发送", "回款", "交易", "日志", "记录", "流水", "事件", "log", "event", "hist")),
    (CONCEPT_ENTITY, ("信息", "档案", "主数据", "维", "dim", "info")),
    (CONCEPT_SUMMARY, ("汇总", "日报", "统计", "agg", "report")),
)

SIGNAL_KEY_EVENT_COLUMN = "key_event_column"
SIGNAL_DRIVING_LOG_SOURCE = "driving_rows_over_log_source"
SIGNAL_INCREMENT_EVENT_TIME = "increment_with_event_time"
SIGNAL_ALL_MEMBERS_SUMMARY = "all_members_summary"
SIGNAL_WORD_HINT = "word_hint"
SIGNAL_NONE = "no_signal"
#: K4c: the only "signal" behind a concept a reviewer created -- the reviewer.
SIGNAL_OVERRIDE = "override"

#: Chinese suffixes a table comment carries because of *how* the table is stored, not
#: because of what it holds. Longest first: 「信息表」 is stripped before 「表」.
TABLE_COMMENT_SUFFIXES = (
    "基础信息表", "扩展信息表", "日快照表", "维度表", "事实表", "信息表", "明细表",
    "汇总表", "临时表", "记录表", "快照表", "流水表", "日快照", "中间表", "宽表",
    "维表", "日表", "信息", "明细", "汇总", "临时", "记录", "快照", "流水", "表",
)
#: The same idea for the column comment that names the key: 客户编号 is 客户. Longest
#: first, and at most one of them comes off -- 客户编号 is 客户, not 客.
KEY_COMMENT_SUFFIXES = ("编号", "编码", "代码", "号码", "标识", "号")
#: Words that merely *end* in a key marker. 账号 is what the column holds, not 账 plus a
#: marker, so a bare 号 never comes off one of these.
KEY_SUFFIX_PROTECTED = ("账号", "卡号", "型号", "工号", "学号", "代号", "席号")
#: How much has to survive a key marker for what is left to be a name.
MIN_NAME_CJK = 2
#: Segment-marked latin suffixes, safe on any comment because the `_` marks them.
LATIN_COMMENT_SUFFIXES = ("_df", "_di", "_hf", "_hi", "_id", "_no", "_code", "_cd")

_CJK_RE = re.compile(r"[一-鿿]")
#: A camelCase boundary, so ``collectionUnit`` reads as two words rather than one.
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
#: A trailing aside -- 「渠道维表（合成）」 -- says something about the table, not about the
#: thing it holds, and it hides the storage suffix behind it.
_ASIDE_RE = re.compile(r"[（(][^（()）]*[）)]\s*$")
#: A catalog stamps its own bookkeeping into the comment -- 「合同号 【updt:n】【Sec:D】」.
#: None of it describes the thing, and it hides every suffix rule behind it, so it comes
#: out of every comment before a single candidate is derived.
_TAG_RE = re.compile(r"[【\[][^【】\[\]]*[】\]]")

#: Texts that only say "this is a key" and name nothing. The Chinese ones match as a
#: **prefix** -- 唯一键, 唯一主键, 主键id are all the marker plus noise -- while the latin
#: ones match whole, because `id`/`key` open plenty of real English phrases.
NAME_STOPLIST_PREFIXES = ("唯一", "主键", "标识", "编号", "编码", "代码", "序号", "流水号")
NAME_STOPLIST_EXACT = ("id", "unique", "key", "guid", "uuid", "pk", "no", "code")
NAME_STOPLIST = frozenset(NAME_STOPLIST_PREFIXES + NAME_STOPLIST_EXACT)
#: Words that say where a table sits in a pipeline rather than what it holds. Taken out
#: wherever they appear, before the storage suffixes.
STAGING_TOKENS = ("中间过程", "过程表", "临时", "备份", "backup", "tmp")
#: A candidate still carrying one of these reads as a table name, not a business name.
JUNK_MARKERS = ("_", "backup", "tmp")

_CONCEPT_KEYS = (
    "id",
    "name",
    "name_tier",
    "name_candidates",
    # Present only when another concept proposed the same name (K2).
    "possible_duplicate_of",
    "kind",
    "kind_tier",
    "kind_evidence",
    "identity",
    "tables",
    "attributes",
    "tier",
    # K4c: present only on a concept a reviewed `concepts.overrides.json` created --
    # no candidate key seeded it, a person did.
    "origin",
    # K4b: present only after a reviewed `concepts.overrides.json` touched this
    # concept -- which other concepts were folded into it, which one it was split out
    # of, and who said so.
    "merged_from",
    "split_from",
    "confirmation",
)


@dataclass(frozen=True)
class _Seed:
    """One entity's answer to "which concept does this table represent, and how"."""

    table: str
    entity: Mapping
    stem: str | None
    tier: str | None
    reason: str | None
    basis: str | None = None
    key_columns: tuple[str, ...] = ()
    stem_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    partitions: frozenset[str] = frozenset()
    types: Mapping[str, str] = field(default_factory=dict)
    comments: tuple[str, ...] = ()


# ------------------------------------------------------------------------ public API


def key_stem(column, synonyms: Mapping[str, str] | None = None) -> str:
    """The business word one key column reduces to -- ``cust_no`` and ``cust_id`` → ``cust``.

    Mechanical and lossy on purpose: lowercase, then drop whole leading and trailing
    segments that only say "this is a key" (``_no`` / ``_id`` / ``_code`` / ``_cd`` /
    ``_num`` / ``_key``), never the last segment left. ``synonyms`` is the corpus's own
    O5 evidence folded to one spelling per synonym group, so ``customer_id`` reaches
    ``cust`` only because some task proved the two columns hold the same value -- never
    because the two words look alike.
    """
    name = str(column or "").strip().lower()
    name = str((synonyms or {}).get(name, name)).strip().lower()
    parts = [part for part in name.split("_") if part]
    while len(parts) > 1 and parts[-1] in KEY_AFFIXES:
        parts.pop()
    while len(parts) > 1 and parts[0] in KEY_AFFIXES:
        parts.pop(0)
    return "_".join(parts)


def is_generic_stem(stem: str, comments: Iterable = ()) -> bool:
    """Whether a stem identifies rows without naming a thing.

    Two rules. The list above is the closed one. The second is evidence: if the key
    columns that reduce to this stem carry three or more *different* non-empty comments
    and no two-character Chinese fragment appears in all of them, the warehouse is using
    one spelling for several unrelated things and the stem cannot seed one concept.

    The fragments are looked for *after* 编号/编码/代码 are taken off, because every
    comment on a key column ends in one of those and a shared suffix is not a shared
    subject: 渠道编码 / 省份编码 / 状态编码 agree on nothing that matters.
    """
    if str(stem) in GENERIC_STEMS:
        return True
    texts = sorted({str(text).strip() for text in comments if str(text or "").strip()})
    if len(texts) < 3:
        return False
    subjects = [key_comment_name(text) or text for text in texts]
    shared = set.intersection(*[_cjk_bigrams(text) for text in subjects])
    return not shared


def is_log_identifier(column, comment="") -> bool:
    """Whether a key column holds a *generated* id rather than a business key.

    Either rule is enough: the comment says where the value came from (a log id, an
    md5, a hash, a uuid, a snowflake, a random), or the stem is one of the log and
    tracing identifiers above. Such a column never seeds a concept -- three tables
    sharing a ``rowkey`` share a log pipeline, not a business thing -- but it stays in
    the member's ``key_columns``, because it may well be what identifies a row *within*
    a concept some other key seeded.
    """
    lowered = str(comment or "").lower()
    if any(marker in lowered for marker in LOG_ID_COMMENT_MARKERS):
        return True
    return key_stem(column) in LOG_ID_STEMS


def key_basis(tier: str) -> str:
    """The ``membership_basis`` a candidate key at ``tier`` gives a member."""
    return f"{BASIS_KEY_PREFIX}{tier}"


def build_concepts(ontology: Mapping, cards: Mapping) -> dict:
    """``{"concepts": [...], "unassigned_tables": [...]}`` for one corpus's ontology.

    ``ontology`` is the document being built -- entities, their identities, and the
    relations O1 read off the JOINs; ``cards`` are the table cards underneath it, read
    for grain, producers and consumers.
    """
    entities = list(ontology.get("entities") or [])
    index = {str(card.get("table")): card for card in cards.get("tables") or []}
    synonyms = synonym_folding(entities)
    seeds = [_seed(entity, synonyms) for entity in entities]
    generic = _generic_stems(seeds)
    members: dict[str, list[_Seed]] = {}
    for seed in seeds:
        if seed.stem is not None and seed.stem not in generic:
            members.setdefault(seed.stem, []).append(seed)
    _attach_references(ontology, entities, synonyms, members, generic)
    concepts = [
        _concept(stem, sorted(group, key=_member_rank), index, synonyms)
        for stem, group in members.items()
    ]
    concepts.sort(key=lambda concept: (-len(concept["tables"]), str(concept["id"])))
    _mark_duplicate_names(concepts)
    placed = {seed.table for group in members.values() for seed in group}
    keyed = {
        seed.table
        for seed in seeds
        if seed.stem is not None and seed.stem not in generic
    }
    return {
        "concepts": concepts,
        "unassigned_tables": _unassigned(seeds, placed),
        "retired_stems": _retired_stems(
            entities, synonyms, index, generic, set(members), keyed
        ),
    }


def _mark_duplicate_names(concepts: Sequence[dict]) -> None:
    """Two concepts proposing one name point at each other rather than merging.

    Two distinct keys reached the same word. Merging them would answer a question this
    layer cannot answer -- whether one thing is spelled twice, or two things share a
    word -- so both say who else claimed the name and the review round decides. The key
    is absent when nothing else claimed it, so the common concept is the document it was.
    """
    claimed: dict[str, list[str]] = {}
    for concept in concepts:
        claimed.setdefault(str(concept["name"]), []).append(str(concept["id"]))
    for concept in concepts:
        others = [
            other for other in claimed[str(concept["name"])] if other != str(concept["id"])
        ]
        if not others:
            continue
        concept["possible_duplicate_of"] = sorted(others)
        ordered = {key: concept[key] for key in _CONCEPT_KEYS if key in concept}
        concept.clear()
        concept.update(ordered)


def _member_rank(seed: _Seed) -> tuple:
    """Members a key placed come before members a JOIN did, then by name."""
    return (seed.basis == BASIS_REFERENCE, seed.table)


# ------------------------------------------------------------------------- seeding


def synonym_folding(entities: Sequence[Mapping]) -> dict[str, str]:
    """One spelling per O5 synonym group: the shortest stem, then alphabetical.

    The ontology publishes a synonym on both ends, so the graph is undirected; folding
    it to one representative is what lets two tables that spell the same key differently
    reach the same concept.
    """
    groups: dict[str, set[str]] = {}
    for entity in entities:
        for attribute in entity.get("attributes") or []:
            name = str(attribute.get("column")).lower()
            linked = {
                str(item.get("column")).lower()
                for item in attribute.get("synonyms") or []
                if item.get("column")
            }
            if not linked:
                continue
            group = groups.setdefault(name, {name}) | linked | {name}
            for member in group:
                groups[member] = group
    folded: dict[str, str] = {}
    for name, group in groups.items():
        pick = min(sorted(group), key=lambda item: (len(key_stem(item)), key_stem(item)))
        if pick != name:
            folded[name] = pick
    return folded


def _seed(entity: Mapping, synonyms: Mapping[str, str]) -> _Seed:
    """Which concept this entity represents, or the reason it represents none."""
    table = str(entity.get("id"))
    identity = entity.get("identity") or {}
    types, comments = _column_facts(entity)
    partitions = frozenset(str(column) for column in identity.get("partition_columns") or [])
    claims = _identity_claims(identity)
    if not claims:
        return _Seed(table, entity, None, None, REASON_NO_CANDIDATE_KEY)
    reason = REASON_SPLIT_KEY
    for key in claims:
        columns = tuple(str(column) for column in key.get("columns") or [])
        core = tuple(
            column
            for column in columns
            if column not in partitions
            and not _is_event_column(column, types)
            and not is_log_identifier(column, comments.get(column, ""))
        )
        stems = {key_stem(column, synonyms) for column in core}
        if len(stems) != 1 or stems <= GENERIC_STEMS:
            reason = REASON_SPLIT_KEY if len(stems) > 1 else REASON_GENERIC_KEY
            continue
        tier = key.get("tier")
        return _Seed(
            table=table,
            entity=entity,
            stem=stems.pop(),
            tier=str(tier) if tier else None,
            reason=None,
            basis=key_basis(str(tier)) if tier else BASIS_DECLARED_HINT,
            key_columns=columns,
            stem_columns=core,
            extra_columns=tuple(column for column in columns if column not in core),
            partitions=partitions,
            types=types,
            comments=tuple(comments.get(column, "") for column in core),
        )
    return _Seed(table, entity, None, None, reason)


def _identity_claims(identity: Mapping) -> list[dict]:
    """Everything that claims to identify a row, strongest first, hints last.

    A declared hint is read only after every candidate key has failed: the catalog says
    one column is the key, which cannot say which *combination* identifies a row, so it
    is the answer of last resort rather than a competing one.
    """
    keys = [
        key
        for key in identity.get("candidate_keys") or []
        if str(key.get("tier")) in SEED_TIERS
    ]
    hints = [
        {"columns": hint.get("columns"), "tier": None}
        for hint in identity.get("declared_hints") or []
    ]
    return sorted(keys, key=_key_rank) + hints


def _column_facts(entity: Mapping) -> tuple[dict, dict]:
    """``({column: type}, {column: comment})`` off the entity's own attributes."""
    attributes = entity.get("attributes") or []
    return (
        {str(item.get("column")): str(item.get("type") or "") for item in attributes},
        {str(item.get("column")): str(item.get("comment") or "") for item in attributes},
    )


def _key_rank(key: Mapping) -> tuple:
    tier = str(key.get("tier"))
    columns = [str(column) for column in key.get("columns") or []]
    index = SEED_TIERS.index(tier) if tier in SEED_TIERS else len(SEED_TIERS)
    return (index, len(columns), columns)


def _generic_stems(seeds: Sequence[_Seed]) -> set[str]:
    """The stems the genericity rule rejects, judged over every member's key comments."""
    comments: dict[str, set[str]] = {}
    for seed in seeds:
        if seed.stem is None:
            continue
        comments.setdefault(seed.stem, set()).update(
            text for text in seed.comments if text
        )
    return {
        stem for stem in comments if is_generic_stem(stem, sorted(comments[stem]))
    }


def _retired_stems(
    entities: Sequence[Mapping],
    synonyms: Mapping[str, str],
    index: Mapping[str, Mapping],
    generic: set,
    seeded: set,
    keyed: set,
) -> list[dict]:
    """The stems a generic rule refused although the corpus really keys tables by them.

    A generic rule is a *judgement* -- the closed surrogate list, the log and tracing
    ids, and the comment rule -- and a judgement changes between releases. When it does,
    a stem that seeded a concept last run seeds nothing this run, and every answer a
    reviewer wrote about ``concept:<stem>`` becomes an ``unknown_concept``. Publishing
    the refused stems with the tables that carried them is what keeps those answers
    addressable: ``apply_concept_overrides`` revives the concept from exactly this list.

    A table some key really did place is left out: its identity is not in question, and a
    revived concept could only *carry* its key anyway. A table a JOIN merely reached is
    kept, because a ``reference`` membership never said what the table is.
    """
    found: dict[str, list[dict]] = {}
    for entity in entities:
        if str(entity.get("id")) in keyed:
            continue
        seed = _refused_seed(entity, synonyms, generic, seeded)
        if seed is None or seed.stem is None:
            continue
        card = index.get(seed.table) or {}
        found.setdefault(seed.stem, []).append(
            {
                "table": seed.table,
                "role": _role(seed, card, _producing_basis(card)),
                "key_columns": list(seed.stem_columns),
            }
        )
    return [
        {"stem": stem, "tables": sorted(found[stem], key=lambda item: item["table"])}
        for stem in sorted(found)
    ]


def _refused_seed(
    entity: Mapping, synonyms: Mapping[str, str], generic: set, seeded: set
) -> _Seed | None:
    """The seed this entity's strongest key would have given, had a rule not refused it.

    Read exactly as ``_seed`` reads it -- partitions and event columns out, the O5
    synonyms folded -- with one deliberate difference: the log-id columns stay in, because
    taking them out is one of the very rules this list exists to survive.
    """
    identity = entity.get("identity") or {}
    types, comments = _column_facts(entity)
    partitions = frozenset(str(column) for column in identity.get("partition_columns") or [])
    for key in _identity_claims(identity):
        columns = tuple(str(column) for column in key.get("columns") or [])
        core = tuple(
            column
            for column in columns
            if column not in partitions and not _is_event_column(column, types)
        )
        stems = {key_stem(column, synonyms) for column in core}
        if len(stems) != 1:
            continue
        stem = stems.pop()
        if stem in seeded or not _is_refused(stem, core, comments, generic):
            continue
        return _Seed(
            table=str(entity.get("id")),
            entity=entity,
            stem=stem,
            tier=str(key.get("tier")) if key.get("tier") else None,
            reason=None,
            basis=BASIS_OVERRIDE,
            key_columns=columns,
            stem_columns=core,
            extra_columns=tuple(column for column in columns if column not in core),
            partitions=partitions,
            types=types,
        )
    return None


def _is_refused(stem: str, core: Sequence[str], comments: Mapping, generic: set) -> bool:
    """Whether one of the generic rules is why this stem seeded nothing."""
    return (
        stem in GENERIC_STEMS
        or stem in generic
        or any(is_log_identifier(column, comments.get(column, "")) for column in core)
    )


def _unassigned(seeds: Sequence[_Seed], placed: set[str]) -> list[dict]:
    """The tables no key, no declared hint and no JOIN could place, and why."""
    found = [
        {
            "table": seed.table,
            "reason": REASON_GENERIC_KEY if seed.stem else str(seed.reason),
        }
        for seed in seeds
        if seed.table not in placed
    ]
    return sorted(found, key=lambda item: str(item["table"]))


def _attach_references(
    ontology: Mapping,
    entities: Sequence[Mapping],
    synonyms: Mapping[str, str],
    members: dict,
    generic: set,
) -> None:
    """O1's JOINs, read as participation: who carries this concept's key.

    An event table is never *keyed* by 客户 -- it is keyed by its own id and a time --
    so no key rule can place it under 客户. The JOIN can: a task that joined it onto the
    customer's key proved it carries that key, which is exactly what taking part in the
    concept means. The membership is published as ``reference`` and it is deliberately
    the weakest one: it lends the concept neither a kind vote nor an attribute.
    """
    by_id = {str(entity.get("id")): entity for entity in entities}
    for relation in ontology.get("relations") or []:
        if str(relation.get("kind")) not in REFERENCE_RELATION_KINDS:
            continue
        target = _side_stem(relation.get("to") or {}, synonyms)
        if target is None or target in generic or target not in members:
            continue
        source = relation.get("from") or {}
        table = str(source.get("entity"))
        if table not in by_id or any(seed.table == table for seed in members[target]):
            continue
        members[target].append(_reference(by_id[table], target, source, synonyms))


def _side_stem(side: Mapping, synonyms: Mapping[str, str]) -> str | None:
    """The one non-generic stem a relation end's columns reduce to, or ``None``."""
    stems = {key_stem(str(column), synonyms) for column in side.get("columns") or []}
    if len(stems) != 1 or stems <= GENERIC_STEMS:
        return None
    return stems.pop()


def _reference(
    entity: Mapping, stem: str, side: Mapping, synonyms: Mapping[str, str]
) -> _Seed:
    types, comments = _column_facts(entity)
    columns = tuple(str(column) for column in side.get("columns") or [])
    core = tuple(column for column in columns if key_stem(column, synonyms) == stem)
    return _Seed(
        table=str(entity.get("id")),
        entity=entity,
        stem=stem,
        tier=None,
        reason=None,
        basis=BASIS_REFERENCE,
        key_columns=columns,
        stem_columns=core,
        types=types,
        comments=tuple(comments.get(column, "") for column in core),
    )


def _is_event_column(column: str, types: Mapping[str, str]) -> bool:
    """Whether a column is a point in time or an event id -- not what a row is *of*.

    Used to take the time out of a composite key: ``(cust_no, dt)`` identifies a customer
    on a day, and the concept is the customer.
    """
    segments = {part for part in str(column).lower().split("_") if part}
    if segments & TIME_SEGMENTS or segments & EVENT_SEGMENTS:
        return True
    return str(types.get(str(column)) or "").lower().startswith(_TEMPORAL_TYPES)


def _is_event_time(column: str, types: Mapping[str, str]) -> bool:
    """Whether a column times *something that happened*, which is stricter.

    ``dt`` says which day's copy of a snapshot this is, and ``etl_time`` / ``create_time``
    say when a row was loaded; neither is an event, and letting them vote turns every
    daily summary into an event. A column qualifies only when some segment of it names
    the thing that happened -- ``send_time``, ``paid_at``, ``event_time``.
    """
    if not _is_event_column(column, types):
        return False
    segments = [part for part in str(column).lower().split("_") if part]
    return any(
        part not in TIME_SEGMENTS and part not in GENERIC_STEMS for part in segments
    )


# ------------------------------------------------------------------- one concept


def _concept(
    stem: str, members: Sequence[_Seed], index: Mapping[str, Mapping], synonyms
) -> dict:
    tables = [_member(seed, index) for seed in members]
    # A reference member carries the key, it is not described by it: letting it vote
    # would make 客户 an event as soon as one event table joined it.
    keyed = [seed for seed in members if seed.basis != BASIS_REFERENCE]
    own = [item for item in tables if str(item["role"]) != ROLE_REFERENCE]
    kind, tier, evidence = _kind(keyed, own, index)
    roles = {str(item["table"]): str(item["role"]) for item in tables}
    candidates = _name_candidates(stem, members, index, roles)
    built = {
        "id": f"{CONCEPT_ID_PREFIX}{stem}",
        "name": str(candidates[0]["text"]),
        "name_tier": TIER_HYPOTHESIS,
        "name_candidates": candidates,
        "kind": kind,
        "kind_tier": tier,
        "kind_evidence": evidence,
        "identity": {
            "stem": stem,
            "columns_seen": sorted(
                {column for seed in members for column in seed.stem_columns}
            ),
        },
        "tables": tables,
        "attributes": _attributes(keyed, synonyms),
        # A concept is an inference over the corpus, never something the SQL wrote, so
        # `implied` is as strong as it gets -- and only when some member's key was proved.
        # Seeded only by assumed keys, declared hints or JOINs, it stays a `hypothesis`.
        "tier": (
            TIER_IMPLIED
            if any(str(seed.tier) in STRONG_TIERS for seed in members)
            else TIER_HYPOTHESIS
        ),
    }
    return {key: built[key] for key in _CONCEPT_KEYS if key in built}


def _member(seed: _Seed, index: Mapping[str, Mapping]) -> dict:
    card = index.get(seed.table) or {}
    grain = _producing_basis(card)
    role = ROLE_REFERENCE if seed.basis == BASIS_REFERENCE else _role(seed, card, grain)
    return {
        "table": seed.table,
        "role": role,
        "membership_basis": str(seed.basis),
        "key_columns": list(seed.key_columns),
        "grain": grain,
    }


def _producing_basis(card: Mapping) -> str | None:
    for producer in card.get("produced_by") or []:
        basis = (producer.get("grain") or {}).get("basis")
        if basis:
            return str(basis)
    return None


def _role(seed: _Seed, card: Mapping, grain: str | None) -> str:
    """Which copy of the concept this table is.

    The cascade is ordered by how specific the evidence is, not by how common the role
    is: a build step is a build step whatever its key says, an event time in the key
    outranks the name, a full snapshot keyed by the stem alone is the primary copy, and
    only then does the producing grain get to call the table a summary.
    """
    suffix = _name_suffix(seed.table)
    outside = [column for column in seed.extra_columns if column not in seed.partitions]
    events = [column for column in outside if _is_event_time(column, seed.types)]
    if _STAGE_RE.match(suffix) or _task_internal(card):
        return ROLE_INTERMEDIATE
    if events:
        return ROLE_DETAIL
    if not outside and (suffix in FULL_SNAPSHOT_SUFFIXES or suffix not in PERIOD_SUFFIXES):
        return ROLE_PRIMARY
    if grain in AGGREGATED_BASES:
        return ROLE_SUMMARY
    if not outside and suffix in INCREMENT_SUFFIXES:
        return ROLE_SNAPSHOT
    return ROLE_DETAIL if outside else ROLE_PRIMARY


def _name_suffix(table: str) -> str:
    return str(table).lower().rpartition(".")[2].split("_")[-1]


def _task_internal(card: Mapping) -> bool:
    """Written and read by exactly one task: a step of that task, not a shared table."""
    producers = {str(item.get("task")) for item in card.get("produced_by") or []}
    consumers = {str(item.get("task")) for item in card.get("consumed_by") or []}
    return bool(producers) and bool(consumers) and producers == consumers and len(producers) == 1


# ---------------------------------------------------------------------- the kind


def _kind(
    members: Sequence[_Seed], tables: Sequence[Mapping], index: Mapping[str, Mapping]
) -> tuple[str, str, list[dict]]:
    """The concept's kind, its tier and every signal's vote, agreeing or not."""
    votes = _structural_signals(members, tables, index) + _word_signals(members, index)
    if not votes:
        return CONCEPT_ENTITY, TIER_HYPOTHESIS, [
            {"signal": SIGNAL_NONE, "vote": CONCEPT_ENTITY}
        ]
    structural = {
        str(vote["vote"]) for vote in votes if str(vote["signal"]) != SIGNAL_WORD_HINT
    }
    if CONCEPT_EVENT in structural:
        kind = CONCEPT_EVENT
    elif CONCEPT_SUMMARY in structural:
        kind = CONCEPT_SUMMARY
    else:
        kind = _word_majority(votes)
    tier = TIER_IMPLIED if len({str(vote["vote"]) for vote in votes}) == 1 else TIER_HYPOTHESIS
    return kind, tier, votes


def _word_majority(votes: Sequence[Mapping]) -> str:
    words = [str(vote["vote"]) for vote in votes if str(vote["signal"]) == SIGNAL_WORD_HINT]
    if not words:
        return CONCEPT_ENTITY
    return min(
        set(words), key=lambda kind: (-words.count(kind), KIND_ORDER.index(kind))
    )


def _structural_signals(
    members: Sequence[_Seed], tables: Sequence[Mapping], index: Mapping[str, Mapping]
) -> list[dict]:
    """The votes the corpus's own shape casts: keys, grain and period suffixes."""
    votes: list[dict] = []
    for seed in members:
        card = index.get(seed.table) or {}
        for column in seed.extra_columns:
            if column not in seed.partitions and _is_event_time(column, seed.types):
                votes.append(_vote(SIGNAL_KEY_EVENT_COLUMN, CONCEPT_EVENT, seed.table, column))
        for source in _driving_log_sources(card, index):
            votes.append(_vote(SIGNAL_DRIVING_LOG_SOURCE, CONCEPT_EVENT, seed.table, source))
        if _name_suffix(seed.table) in INCREMENT_SUFFIXES:
            for column in _event_times(card, seed):
                votes.append(
                    _vote(SIGNAL_INCREMENT_EVENT_TIME, CONCEPT_EVENT, seed.table, column)
                )
    if tables and all(str(item["role"]) == ROLE_SUMMARY for item in tables):
        votes.append(_vote(SIGNAL_ALL_MEMBERS_SUMMARY, CONCEPT_SUMMARY))
    return votes


def _vote(signal: str, vote: str, table: str | None = None, detail: str | None = None) -> dict:
    built = {"signal": signal, "vote": vote, "table": table, "detail": detail}
    return {key: value for key, value in built.items() if value is not None}


def _event_times(card: Mapping, seed: _Seed) -> list[str]:
    return [
        str(column.get("name"))
        for column in card.get("columns") or []
        if str(column.get("name")) not in seed.partitions
        and _is_event_time(str(column.get("name")), seed.types)
    ]


def _driving_log_sources(card: Mapping, index: Mapping[str, Mapping]) -> list[str]:
    """The log-like tables whose rows this table counts one for one."""
    wanted = {
        (str(producer.get("task")), str(producer.get("statement_id")))
        for producer in card.get("produced_by") or []
        if str((producer.get("grain") or {}).get("basis")) == DRIVING_ROWS_BASIS
    }
    if not wanted:
        return []
    return sorted(
        str(other.get("table"))
        for other in index.values()
        for consumer in other.get("consumed_by") or []
        if str(consumer.get("role_in_task")) == DRIVING_ROLE
        and (str(consumer.get("task")), str(consumer.get("statement_id"))) in wanted
        and _word_votes(f"{other.get('table')} {other.get('comment') or ''}") == [CONCEPT_EVENT]
    )


def _word_signals(members: Sequence[_Seed], index: Mapping[str, Mapping]) -> list[dict]:
    votes: list[dict] = []
    for seed in members:
        card = index.get(seed.table) or {}
        text = f"{seed.table} {card.get('comment') or seed.entity.get('comment') or ''}"
        votes.extend(
            _vote(SIGNAL_WORD_HINT, kind, seed.table, text.strip())
            for kind in _word_votes(text)
        )
    return votes


def _word_votes(text: str) -> list[str]:
    lowered = str(text or "").lower()
    return [kind for kind, words in WORD_HINTS if any(word in lowered for word in words)]


# ------------------------------------------------------------------ attributes


def _attributes(members: Sequence[_Seed], synonyms: Mapping[str, str]) -> list[dict]:
    """Every member's columns, folded by stem, each saying which table supplied it."""
    found: dict[str, dict] = {}
    for seed in members:
        for attribute in seed.entity.get("attributes") or []:
            name = str(attribute.get("column"))
            stem = key_stem(name, synonyms)
            entry = found.setdefault(
                stem, {"stem": stem, "type": None, "comment": None, "sources": []}
            )
            entry["type"] = entry["type"] or attribute.get("type")
            entry["comment"] = entry["comment"] or attribute.get("comment")
            source = {"table": seed.table, "column": name}
            if source not in entry["sources"]:
                entry["sources"].append(source)
    return [found[stem] for stem in sorted(found)]


# ----------------------------------------------------------- K2: naming candidates


_SOURCE_ORDER = {
    NAME_FROM_KEY_COMMENT: 0,
    NAME_FROM_TABLE_COMMENT: 1,
    NAME_FROM_STEM: 2,
}


def _name_candidates(
    stem: str,
    members: Sequence[_Seed],
    index: Mapping[str, Mapping],
    roles: Mapping[str, str],
) -> list[dict]:
    """Ranked names for the concept, strongest evidence first, the stem last.

    Nothing here is a decision: ``name`` is the top candidate and every candidate keeps
    the table and column it came from, so disagreeing metadata is visible rather than
    averaged away. A candidate that still reads as a table name (it kept an ``_``, or a
    staging word survived) sinks below the stem rather than being dropped -- it is
    evidence, just not a name.
    """
    found = _key_comment_candidates(members, stem) + _table_comment_candidates(
        members, index, roles
    )
    found.append({"text": stem, "source": NAME_FROM_STEM, "count": 1, "name_evidence": []})
    return sorted(
        found,
        key=lambda item: (
            _is_junk(str(item["text"])),
            -int(item["count"]),
            _SOURCE_ORDER[str(item["source"])],
            str(item["text"]),
        ),
    )


def _is_junk(text: str) -> bool:
    lowered = str(text).lower()
    return any(marker in lowered for marker in JUNK_MARKERS)


def _names_only_a_key(text: str, stem: str) -> bool:
    """Whether a key column's comment says "this is a key" and nothing else."""
    lowered = str(text).strip().lower()
    if not lowered or lowered in NAME_STOPLIST_EXACT:
        return True
    if lowered.startswith(NAME_STOPLIST_PREFIXES):
        return True
    chinese = len(_CJK_RE.findall(text))
    if chinese:
        return chinese < MIN_NAME_CJK
    return len(lowered) < 2 or lowered == str(stem).lower()


def key_comment_name(comment) -> str:
    """What one key column's comment names, or ``""`` when it names nothing.

    The tags come off first, then at most one trailing key marker -- and only when what
    is left is still a name: 合同号 is 合同 and 交易流水号 is 交易流水, but 编号 and 客编号
    are a marker with nothing in front of it, and 贷款账号 is not 贷款账, because 账号 is
    the word for what the column holds.
    """
    current = _strip_latin_suffixes(_strip_tags(comment))
    if not _CJK_RE.search(current) or current.endswith(KEY_SUFFIX_PROTECTED):
        return current
    suffix = next(
        (item for item in KEY_COMMENT_SUFFIXES if current.endswith(item)), None
    )
    if suffix is None:
        return current
    remainder = current[: -len(suffix)].strip()
    return remainder if len(_CJK_RE.findall(remainder)) >= MIN_NAME_CJK else ""


def key_column_name(column) -> str:
    """What one key column's *name* says, once it stops being an identifier (K4d).

    The fallback for a business role no column comment could name. Publishing
    ``collection_unit_id`` as the role an entity plays publishes the warehouse's
    spelling as the business's word, so the key markers come off and the words come
    out. A CJK name is already words and is used as it stands.

    The markers come off the segments the warehouse itself marked with ``_``, exactly
    as ``key_stem`` reads them -- and **only** those. A camelCase hump is not a segment
    anybody declared: ``openId`` is one word the warehouse wrote, and reading it as
    ``open`` would throw half of what it wrote away. So the segments answer first and
    the humps are split into words afterwards: ``trace_node_code`` is 「trace node」,
    while ``openId`` is 「open id」.
    """
    text = str(column or "").strip()
    if _CJK_RE.search(text):
        return text
    parts = [part for part in text.split("_") if part]
    while len(parts) > 1 and parts[-1].lower() in KEY_AFFIXES:
        parts.pop()
    while len(parts) > 1 and parts[0].lower() in KEY_AFFIXES:
        parts.pop(0)
    return " ".join(
        word for part in parts for word in _CAMEL_RE.sub(" ", part).lower().split()
    )


def key_comment_says_nothing(text, column) -> bool:
    """Whether a column comment says nothing the column's own name does not (K4d).

    A role reads the comment first and the column name second, and a catalog that fills
    every comment with the column identifier -- or with 「ID」 -- makes the first route
    answer with exactly the string the second one exists to rewrite. Such a comment has
    to count as *no answer*, or the fallback never runs and the published role is the
    raw identifier after all.

    Three ways to say nothing: it is a key marker with no name in front of it (the rule
    the naming candidates already use), it still reads as an identifier (it kept an
    ``_``, or a staging word survived), or it is the column's own name over again.
    """
    lowered = str(text).strip().lower()
    if _names_only_a_key(lowered, key_stem(column)) or _is_junk(lowered):
        return True
    return lowered == str(column).strip().lower()


def _key_comment_candidates(members: Sequence[_Seed], stem: str) -> list[dict]:
    items = []
    for seed in members:
        for column, comment in zip(seed.stem_columns, seed.comments):
            text = key_comment_name(comment)
            if text and not _names_only_a_key(text, stem):
                items.append((text, {"table": seed.table, "column": column}))
    return _grouped(items, NAME_FROM_KEY_COMMENT)


def _table_comment_candidates(
    members: Sequence[_Seed], index: Mapping[str, Mapping], roles: Mapping[str, str]
) -> list[dict]:
    """The comments of the most representative members only.

    A build step and a table that merely references the concept describe themselves, not
    the concept, so their comments are read only when no primary or snapshot member had
    one. Taking the best rank that answers at all beats mixing all three and ranking by
    count, where five staging copies outvote the one snapshot.
    """
    items = []
    for rank in sorted(set(ROLE_NAMING_RANK.values())):
        items = [
            (text, {"table": seed.table})
            for seed in members
            if ROLE_NAMING_RANK.get(str(roles.get(seed.table)), 2) == rank
            for text in [_table_comment_text(seed, index)]
            if text
        ]
        if items:
            break
    texts = {text for text, _ in items}
    if len(texts) > 1:
        prefix = _common_prefix(sorted(texts))
        if prefix:
            return [
                {
                    "text": prefix,
                    "source": NAME_FROM_TABLE_COMMENT,
                    "count": len(items),
                    "name_evidence": [evidence for _, evidence in items],
                }
            ]
    return _grouped(items, NAME_FROM_TABLE_COMMENT)


def _table_comment_text(seed: _Seed, index: Mapping[str, Mapping]) -> str:
    card = index.get(seed.table) or {}
    comment = card.get("comment") or seed.entity.get("comment")
    return _strip_suffixes(_strip_staging(_strip_tags(comment)), TABLE_COMMENT_SUFFIXES)


def _strip_staging(comment) -> str:
    """The pipeline words out of a comment, wherever they sit inside it."""
    current = str(comment or "")
    for token in STAGING_TOKENS:
        while True:
            found = current.lower().find(token)
            if found < 0:
                break
            current = current[:found] + current[found + len(token) :]
    return current.strip(" \t_-/")


def _grouped(items: Sequence[tuple], source: str) -> list[dict]:
    found: dict[str, dict] = {}
    for text, evidence in items:
        entry = found.setdefault(
            text, {"text": text, "source": source, "count": 0, "name_evidence": []}
        )
        entry["count"] += 1
        entry["name_evidence"].append(evidence)
    return list(found.values())


def _common_prefix(texts: Sequence[str]) -> str:
    first, last = texts[0], texts[-1]
    size = 0
    while size < min(len(first), len(last)) and first[size] == last[size]:
        size += 1
    return first[:size]


def _strip_suffixes(comment, cjk_suffixes: Sequence[str]) -> str:
    """A comment with the storage words taken off, or ``""`` when nothing is left.

    The Chinese suffix lists are a metadata convention, so they only ever apply to text
    that holds Chinese: an English comment is kept exactly as the catalog wrote it, and
    the only latin suffixes stripped are the ones a ``_`` already marked as a segment.
    """
    current = _strip_latin_suffixes(_strip_tags(comment))
    while current and _CJK_RE.search(current):
        cjk = next((item for item in cjk_suffixes if current.endswith(item)), None)
        if cjk is None:
            break
        current = _strip_latin_suffixes(current[: -len(cjk)])
    return current


def _strip_tags(comment) -> str:
    """Every 【…】 / [...] annotation block and the trailing （…） aside, out.

    Applied to key comments and table comments alike and before anything else: a
    catalog's own bookkeeping is not a description, and while it sits at the end of the
    string no suffix rule can see the word it is hiding.
    """
    current = _TAG_RE.sub(" ", str(comment or "")).strip()
    while True:
        aside = _ASIDE_RE.search(current)
        if aside is None:
            return current.strip(" \t_-/,，、")
        current = current[: aside.start()].strip()


def _strip_latin_suffixes(text: str) -> str:
    """The `_`-marked latin suffixes only. An English comment is otherwise untouched."""
    current = str(text).strip()
    while True:
        found = next(
            (
                suffix
                for suffix in LATIN_COMMENT_SUFFIXES
                if current.lower().endswith(suffix) and len(current) > len(suffix)
            ),
            None,
        )
        if found is None:
            return current
        current = current[: -len(found)].strip()


def _cjk_bigrams(text: str) -> set[str]:
    chars = str(text)
    return {
        chars[index : index + 2]
        for index in range(len(chars) - 1)
        if _CJK_RE.match(chars[index]) and _CJK_RE.match(chars[index + 1])
    }


# ------------------------------------------------- K4b: the reviewed concept layer

#: The reviewed document ``ontology --concept-overrides`` reads.
CONCEPT_OVERRIDES_DOC_FORMAT = "concept-overrides/1"
#: The one tier the corpus cannot reach on its own. Mirrors ``ontology.TIER_CONFIRMED``,
#: spelled here for the same reason the other two tiers are.
TIER_CONFIRMED = "confirmed"

#: The membership a reviewer added by hand: neither a key, nor a hint, nor a JOIN said
#: this table belongs here -- a person did.
BASIS_OVERRIDE = "override"

#: What one concept's entry may say. Anything else is reported, never applied.
CONCEPT_OVERRIDE_FIELDS = (
    "name",
    "kind",
    "merge_into",
    "roles",
    "add_tables",
    "confirmed_by",
    "date",
    "basis",
    "note",
)
#: What the document itself may hold.
CONCEPT_OVERRIDES_DOC_FIELDS = ("doc_format", "concepts", "new_concepts", "splits")
#: What one ``new_concepts[]`` entry may say (K4c).
NEW_CONCEPT_FIELDS = (
    "id",
    "name",
    "kind",
    "tables",
    "key_columns",
    "confirmed_by",
    "date",
    "basis",
    "note",
)
#: A concept id a reviewer may write: the prefix and a slug, so the id stays the thing
#: every other document spells it as.
CONCEPT_ID_RE = re.compile(r"\Aconcept:[a-z0-9_-]+\Z")
#: The roles a reviewer may move a member to -- exactly the ones K1 publishes.
MEMBER_ROLES = (
    ROLE_PRIMARY,
    ROLE_SNAPSHOT,
    ROLE_DETAIL,
    ROLE_SUMMARY,
    ROLE_INTERMEDIATE,
    ROLE_REFERENCE,
)


def apply_concept_overrides(ontology: dict, overrides: Mapping) -> None:
    """Fold a reviewed ``concepts.overrides.json`` into the concept layer.

    K1--K3 publish candidates: a name that is always a hypothesis, a kind decided by
    votes, and a fold that refuses to merge two stems it cannot tell apart. A review
    round is the only thing that can answer those, so this is where the concept layer
    reaches ``confirmed`` -- and, exactly like ``ontology.overrides.json``, an entry
    naming something the corpus does not contain is reported rather than dropped,
    because a typo in a reviewed file is what its author cannot see.

    Four kinds of answer, applied in the order a reviewer arrives at them: the concepts
    the corpus never published (K4c) first, so every later entry can address them, then
    the field edits (a name, a kind, a member's role), then the merges those names
    justify, then the splits. It runs *before* ``build_concept_relations`` so a merge
    moves the edges of the concept it folded rather than leaving them beside it, and so
    the edges that start at a created concept's tables fold onto it.
    """
    applied = {
        "concepts": 0,
        "created": [],
        "tables_added": 0,
        "merges": 0,
        "splits": 0,
        "unmatched": [],
        "warnings": [],
        "ignored_fields": [],
    }
    ontology["concept_overrides_applied"] = applied
    _ignored_fields(applied, "(document)", overrides, CONCEPT_OVERRIDES_DOC_FIELDS)
    corpus = _Corpus(ontology.get("entities") or [])
    ontology.setdefault("concepts", [])
    _new_concepts(ontology, list(overrides.get("new_concepts") or []), applied, corpus)
    index = {str(concept["id"]): concept for concept in ontology["concepts"]}
    merges = _concept_fields(
        ontology, dict(overrides.get("concepts") or {}), index, applied, corpus
    )
    _forget_unassigned(ontology, corpus.added)
    _concept_merges(ontology, merges, applied)
    _concept_splits(ontology, list(overrides.get("splits") or []), applied)
    applied["created"].sort(key=lambda item: str(item["id"]))
    applied["unmatched"].sort(key=lambda item: (item["key"], item["reason"]))
    applied["warnings"].sort(key=lambda item: (item["key"], item["warning"]))
    applied["ignored_fields"].sort(key=lambda item: item["key"])


def _ignored_fields(
    applied: dict, name: str, entry: Mapping, known: Sequence[str]
) -> None:
    """A field this release does not read is reported, never dropped in silence."""
    extra = sorted(str(field) for field in entry if str(field) not in known)
    if extra:
        applied["ignored_fields"].append({"key": name, "fields": extra})


class _Corpus:
    """The tables the document publishes, for the entries that name one (K4b).

    ``added`` collects the tables a reviewer put on a concept by hand, so the caller
    can take them out of ``unassigned_tables[]`` once every entry has been read.
    """

    def __init__(self, entities: Sequence[Mapping]) -> None:
        self.entities = {str(entity.get("id")): entity for entity in entities}
        self.synonyms = synonym_folding(list(entities))
        self.added: set[str] = set()


def _concept_fields(
    ontology: dict, entries: Mapping, index: dict, applied: dict, corpus: _Corpus
) -> list[tuple]:
    """Apply the name, kind, role and membership edits; hand back the merges beside them."""
    merges = []
    for name in sorted(entries):
        entry = dict(entries[name] or {})
        concept = index.get(str(name)) or _revive(
            ontology, str(name), entry, applied, corpus
        )
        if concept is None:
            continue
        index[str(name)] = concept
        _ignored_fields(applied, str(name), entry, CONCEPT_OVERRIDE_FIELDS)
        stamp = _confirmation(entry)
        touched = [
            _confirm_name(concept, entry),
            _confirm_kind(concept, entry, applied, str(name)),
            _confirm_roles(concept, entry, applied, str(name)),
            _add_tables(concept, entry, corpus, applied, str(name), stamp),
        ]
        if any(touched):
            concept["confirmation"] = stamp
            _reorder(concept)
            applied["concepts"] += 1
        if entry.get("merge_into"):
            merges.append((str(name), str(entry["merge_into"]), stamp))
    return merges


def _confirmation(entry: Mapping) -> dict:
    """Who answered, when and on what grounds.

    ``basis`` is published as ``confirmed_basis`` for the same reason the table-level
    confirmations publish it that way: ``membership_basis`` beside it is a machine
    token, and one word cannot be a vocabulary and a sentence at the same time.
    """
    stamp = {}
    for field_name, published in (
        ("confirmed_by", "confirmed_by"),
        ("date", "date"),
        ("basis", "confirmed_basis"),
        ("note", "note"),
    ):
        if entry.get(field_name):
            stamp[published] = str(entry[field_name])
    return stamp


def _confirm_name(concept: dict, entry: Mapping) -> bool:
    if not entry.get("name"):
        return False
    concept["name"] = str(entry["name"])
    concept["name_tier"] = TIER_CONFIRMED
    concept["name_candidates"] = _confirmed_candidates(
        str(entry["name"]), concept.get("name_candidates") or []
    )
    return True


def _confirmed_candidates(name: str, candidates: Sequence[Mapping]) -> list[dict]:
    """The confirmed name at the head of the ranked list, saying who put it there.

    A reviewer's name is evidence the corpus does not hold, and a confirmed name the
    candidates never mention reads as the published name contradicting everything under
    it. When the corpus *did* propose this name, that candidate keeps its
    ``name_evidence`` and only changes hands -- the reviewer's answer is why it leads
    now, and the column that first said it is still worth seeing.
    """
    same = [dict(item) for item in candidates if str(item.get("text")) == name]
    fresh = {
        "text": name,
        "source": NAME_FROM_OVERRIDE,
        "count": 1,
        "name_evidence": [],
    }
    lead = same[0] if same else fresh
    return [
        {**lead, "source": NAME_FROM_OVERRIDE},
        *(dict(item) for item in candidates if str(item.get("text")) != name),
    ]


def _confirm_kind(concept: dict, entry: Mapping, applied: dict, key: str) -> bool:
    kind = str(entry.get("kind") or "")
    if not kind:
        return False
    if kind not in KIND_ORDER:
        applied["unmatched"].append({"key": key, "reason": f"unknown_kind: {kind}"})
        return False
    concept["kind"] = kind
    concept["kind_tier"] = TIER_CONFIRMED
    return True


def _confirm_roles(concept: dict, entry: Mapping, applied: dict, key: str) -> bool:
    """Move named members to the roles the reviewer read off the tables themselves."""
    roles = dict(entry.get("roles") or {})
    members = {str(item["table"]): item for item in concept.get("tables") or []}
    touched = False
    for table in sorted(roles):
        role, member = str(roles[table]), members.get(str(table))
        if member is None:
            applied["unmatched"].append({"key": key, "reason": f"unknown_table: {table}"})
        elif role not in MEMBER_ROLES:
            applied["unmatched"].append({"key": key, "reason": f"unknown_role: {role}"})
        else:
            member["role"] = role
            member["role_tier"] = TIER_CONFIRMED
            touched = True
    return touched


def _add_tables(
    concept: dict,
    entry: Mapping,
    corpus: _Corpus,
    applied: dict,
    key: str,
    stamp: Mapping,
) -> bool:
    """Put tables on this concept that no key, no hint and no JOIN could place there.

    ``roles`` moves a member the corpus already found; this adds one it never did --
    a table whose only key is a surrogate, or whose metadata says nothing, and which a
    reviewer recognises anyway. The membership is published as ``override`` because
    that is exactly what it is, at tier ``confirmed`` because a person answered, and it
    lends the concept the table's columns. It lands *before* the relation fold, so the
    edges that start at the table fold onto the concept the reviewer named.

    One role is the exception (K4d). ``reference`` *means* "this table merely carries
    the key", so a reviewed reference add publishes ``membership_basis: "reference"``
    and never stands in for what the table is -- otherwise the one sentence that says
    "it only carries this key" would move the table's identity onto the concept it was
    added to. The reviewer's stamp travels on the row instead, because the basis can no
    longer say that a person put it there.
    """
    asked = dict(entry.get("add_tables") or {})
    members = {str(item["table"]) for item in concept.get("tables") or []}
    touched = False
    for table in sorted(asked):
        reason = _add_reason(str(table), str(asked[table]), corpus, members)
        if reason is not None:
            applied["unmatched"].append({"key": key, "reason": reason})
            continue
        _add_member(concept, corpus, str(table), str(asked[table]), stamp)
        corpus.added.add(str(table))
        applied["tables_added"] += 1
        touched = True
    return touched


def _member_basis(role: str) -> str:
    """The basis one reviewed membership publishes (K4d).

    ``reference`` is the weakest thing K1 says about a table, and a reviewer writing it
    is saying exactly that -- so it is published as a ``reference`` membership, which
    ``build_concept_relations`` already knows never answers *what this table is*. Every
    other role is a membership a person vouched for, and says so.
    """
    return BASIS_REFERENCE if role == ROLE_REFERENCE else BASIS_OVERRIDE


def _add_reason(table: str, role: str, corpus: _Corpus, members: set) -> str | None:
    """Why this table cannot be added, or None when it can."""
    if table not in corpus.entities:
        return f"unknown_table: {table}"
    if role not in MEMBER_ROLES:
        return f"unknown_role: {role}"
    if table in members:
        return f"already_a_member: {table}"
    return None


def _add_member(
    concept: dict, corpus: _Corpus, table: str, role: str, stamp: Mapping
) -> None:
    """One reviewed membership, with the table's columns joining the attribute union."""
    member = {
        "table": table,
        "role": role,
        "membership_basis": _member_basis(role),
        "key_columns": [],
        "grain": None,
        "role_tier": TIER_CONFIRMED,
        **dict(stamp),
    }
    concept["tables"] = sorted(
        [*(concept.get("tables") or []), member],
        key=lambda item: (str(item["role"]) == ROLE_REFERENCE, str(item["table"])),
    )
    seed = _Seed(
        table=table,
        entity=corpus.entities[table],
        stem=None,
        tier=None,
        reason=None,
        basis=BASIS_OVERRIDE,
    )
    concept["attributes"] = _merge_attributes(
        concept.get("attributes") or [], _attributes([seed], corpus.synonyms)
    )


def _forget_unassigned(ontology: dict, added: set) -> None:
    """A table a reviewer placed is no longer one the corpus could not place."""
    if not added:
        return
    ontology["unassigned_tables"] = [
        item
        for item in ontology.get("unassigned_tables") or []
        if str(item.get("table")) not in added
    ]


# ------------------------------------------------- K4c: concepts a reviewer created


def _new_concepts(
    ontology: dict, entries: Sequence[Mapping], applied: dict, corpus: _Corpus
) -> None:
    """Publish the concepts the corpus could not seed and a reviewer recognised anyway.

    ``add_tables`` needs a concept to add to; this is the case where there is none --
    every table that holds the thing is keyed by a surrogate, so no stem ever grew. The
    concept is ``confirmed`` throughout, because nothing but the reviewer says it exists,
    and it lands before the merges, the splits and the relation fold.
    """
    for entry in entries:
        item = dict(entry or {})
        identifier = str(item.get("id") or "")
        _ignored_fields(applied, identifier or "(new_concepts)", item, NEW_CONCEPT_FIELDS)
        _create_concept(ontology, item, identifier, applied, corpus)


def _create_concept(
    ontology: dict,
    entry: Mapping,
    identifier: str,
    applied: dict,
    corpus: _Corpus,
    *,
    revived: bool = False,
) -> dict | None:
    """One published concept, or ``None`` with the reason it could not be published."""
    index = {str(item["id"]): item for item in ontology.get("concepts") or []}
    kind = str(entry.get("kind") or CONCEPT_ENTITY)
    reason = _create_reason(identifier, kind, entry, index)
    if reason is not None:
        applied["unmatched"].append(
            {"key": identifier or "(new_concepts)", "reason": reason}
        )
        return None
    members = _new_members(
        dict(entry.get("tables") or {}), identifier, applied, corpus, index
    )
    if not members:
        return None
    concept = _fresh_concept(identifier, entry, kind, members, corpus)
    ontology["concepts"] = sorted(
        [*(ontology.get("concepts") or []), concept],
        key=lambda item: (-len(item["tables"]), str(item["id"])),
    )
    tables = [str(item["table"]) for item in members]
    record = {"id": identifier, "tables": tables}
    applied["created"].append({**record, "revived": True} if revived else record)
    corpus.added.update(tables)
    return concept


def _create_reason(
    identifier: str, kind: str, entry: Mapping, index: Mapping
) -> str | None:
    """Why this concept cannot be published, or None when it can."""
    if not CONCEPT_ID_RE.match(identifier):
        return f"invalid_concept_id: {identifier}"
    if identifier in index:
        return f"already_a_concept: {identifier}"
    if kind not in KIND_ORDER:
        return f"unknown_kind: {kind}"
    if not entry.get("tables"):
        return "no_tables"
    return None


def _new_members(
    asked: Mapping, key: str, applied: dict, corpus: _Corpus, index: Mapping
) -> list[dict]:
    """The memberships the entry named that the corpus can carry, refusals reported."""
    identified = {
        str(item.get("table"))
        for concept in index.values()
        for item in concept.get("tables") or []
        if str(item.get("membership_basis")) != BASIS_REFERENCE
    }
    members = []
    for table in sorted(asked):
        role = str(asked[table])
        reason = _new_member_reason(str(table), role, corpus, identified)
        if reason is not None:
            applied["unmatched"].append({"key": key, "reason": reason})
            continue
        members.append(_new_member(str(table), role))
    return members


def _new_member_reason(
    table: str, role: str, corpus: _Corpus, identified: set
) -> str | None:
    """Why this table cannot represent the new concept, or None when it can.

    One identity at most, exactly as ``add_tables`` reads it: a table some other concept
    is what it *is* may still carry this concept's key, so a ``reference`` role is
    allowed anywhere and every other role is refused.
    """
    if table not in corpus.entities:
        return f"unknown_table: {table}"
    if role not in MEMBER_ROLES:
        return f"unknown_role: {role}"
    if role != ROLE_REFERENCE and table in identified:
        return f"already_a_member: {table}"
    return None


def _new_member(table: str, role: str) -> dict:
    """One membership of a created concept, at the only tier a person can give it.

    ``key_columns`` stays empty for the same reason ``add_tables`` leaves it empty: no
    key placed this table here, and writing one would say a key did. The basis follows
    the same K4d rule ``add_tables`` follows: a ``reference`` role lends no identity.
    """
    return {
        "table": table,
        "role": role,
        "membership_basis": _member_basis(role),
        "key_columns": [],
        "grain": None,
        "role_tier": TIER_CONFIRMED,
    }


def _fresh_concept(
    identifier: str, entry: Mapping, kind: str, members: Sequence[Mapping], corpus: _Corpus
) -> dict:
    """The published shape of a created concept: confirmed throughout, and it says so."""
    stem = identifier[len(CONCEPT_ID_PREFIX) :]
    name = str(entry.get("name") or stem)
    tables = [str(item["table"]) for item in members]
    built = {
        "id": identifier,
        "name": name,
        "name_tier": TIER_CONFIRMED,
        "name_candidates": [
            {"text": name, "source": NAME_FROM_OVERRIDE, "count": 1, "name_evidence": []}
        ],
        "kind": kind,
        "kind_tier": TIER_CONFIRMED,
        "kind_evidence": [{"signal": SIGNAL_OVERRIDE, "vote": kind}],
        "identity": _created_identity(stem, _created_columns(entry, tables, corpus)),
        "tables": list(members),
        "attributes": _attributes(_override_seeds(tables, corpus), corpus.synonyms),
        "tier": TIER_CONFIRMED,
        "origin": BASIS_OVERRIDE,
        "confirmation": _confirmation(entry),
    }
    return {key: built[key] for key in _CONCEPT_KEYS if key in built}


def _created_identity(stem: str, columns: Sequence[str]) -> dict:
    """The stem the id spells, and the stems its own key columns answer to (K4d).

    ``concept:slot`` is what the reviewer called the thing; ``ad_slot_code`` is what the
    warehouse writes on the tables that point at it. An edge travels on the column, so
    unless the column's own stem reaches the concept, the entry names a key that can
    never find it. ``merged_stems`` is the index K3 already reads for exactly that --
    the stems this concept answers to besides its own -- so the columns join it there.
    A generic stem is left out for the reason it was generic in the first place: ``dt``
    identifies a row without naming a thing, whoever wrote it down.
    """
    stems = {key_stem(column) for column in columns}
    return {
        "stem": stem,
        "columns_seen": list(columns),
        "merged_stems": sorted(
            item
            for item in stems
            if item and item != stem and not is_generic_stem(item)
        ),
    }


def _override_seeds(tables: Sequence[str], corpus: _Corpus) -> list[_Seed]:
    """One seed per member of a created concept, so it lends the concept its columns."""
    return [
        _Seed(
            table=table,
            entity=corpus.entities[table],
            stem=None,
            tier=None,
            reason=None,
            basis=BASIS_OVERRIDE,
        )
        for table in tables
    ]


def _created_columns(entry: Mapping, tables: Sequence[str], corpus: _Corpus) -> list[str]:
    """The columns that identify the concept: the reviewer's, else what its tables share."""
    named = [str(column) for column in entry.get("key_columns") or []]
    if named:
        return sorted(set(named))
    claimed = [_key_columns(corpus.entities[table]) for table in tables]
    return sorted(set.intersection(*claimed)) if claimed else []


def _key_columns(entity: Mapping) -> set[str]:
    """Every column this table claims identifies a row, at any tier, hints included."""
    identity = entity.get("identity") or {}
    return {
        str(column)
        for claim in _identity_claims(identity)
        for column in claim.get("columns") or []
    }


def _revive(
    ontology: dict, identifier: str, entry: Mapping, applied: dict, corpus: _Corpus
) -> dict | None:
    """An answer addressed to a concept a generic rule retired, applied anyway.

    The reviewer answered for ``concept:<stem>`` in an earlier run, and this run's
    genericity judgement no longer lets that stem seed. Reporting ``unknown_concept``
    would quietly drop a decision a person made, so the stem's own ``retired_stems[]``
    entry -- the tables that carried it, in the roles they carried it in -- is read as an
    implicit ``new_concepts`` entry, and the concept comes back ``confirmed``.

    A stem that came back leaves ``retired_stems[]`` in the same run (K4d): one document
    cannot both publish the concept and go on saying the stem was refused, and the line
    the 概念层 renders off that list is addressed to a reviewer who has *lost* a concept.
    It is reported once, in ``created[]``, with ``revived: true``.
    """
    prefixed = identifier.startswith(CONCEPT_ID_PREFIX)
    stem = identifier[len(CONCEPT_ID_PREFIX) :] if prefixed else ""
    retired = next(
        (
            item
            for item in ontology.get("retired_stems") or []
            if str(item.get("stem")) == stem and stem
        ),
        None,
    )
    if retired is None:
        applied["unmatched"].append({"key": identifier, "reason": "unknown_concept"})
        return None
    tables = list(retired.get("tables") or [])
    implicit = {
        **{field: entry[field] for field in NEW_CONCEPT_FIELDS if entry.get(field)},
        "id": identifier,
        "tables": {str(item["table"]): str(item["role"]) for item in tables},
        "key_columns": sorted(
            {column for item in tables for column in item.get("key_columns") or []}
        ),
    }
    concept = _create_concept(
        ontology, implicit, identifier, applied, corpus, revived=True
    )
    if concept is not None:
        ontology["retired_stems"] = [
            item
            for item in ontology.get("retired_stems") or []
            if str(item.get("stem")) != stem
        ]
    return concept


def _reorder(concept: dict) -> None:
    """One key order per concept, whatever order the edits above arrived in."""
    ordered = {key: concept[key] for key in _CONCEPT_KEYS if key in concept}
    concept.clear()
    concept.update(ordered)


# ------------------------------------------------------------------- K4b: merges


def _concept_merges(ontology: dict, merges: Sequence[tuple], applied: dict) -> None:
    """Fold one concept into another: its tables, its attributes and its stem.

    The stem travels because that is how ``build_concept_relations`` places the far end
    of an edge; without it a merge would move the tables and leave the relations that
    named the folded concept pointing at an id nothing publishes any more.
    """
    for source, target, stamp in merges:
        index = {str(concept["id"]): concept for concept in ontology["concepts"]}
        reason = _merge_reason(source, target, index)
        if reason is not None:
            applied["unmatched"].append({"key": source, "reason": reason})
            continue
        _fold_concept(index[source], index[target], stamp, applied, source)
        ontology["concepts"] = [
            concept for concept in ontology["concepts"] if str(concept["id"]) != source
        ]
        applied["merges"] += 1
    _forget_merged(ontology)


def _merge_reason(source: str, target: str, index: Mapping) -> str | None:
    """Why this merge cannot be applied, or None when it can."""
    if source == target:
        return "merge_into_self"
    if source not in index:
        return "unknown_concept"
    if target not in index:
        return f"unknown_concept: {target}"
    return None


def _fold_concept(
    source: Mapping, into: dict, stamp: Mapping, applied: dict, key: str
) -> None:
    warning = _primary_warning(source, into)
    if warning is not None:
        applied["warnings"].append({"key": key, "warning": warning})
    into["tables"] = _merge_members(
        into.get("tables") or [], source.get("tables") or []
    )
    into["attributes"] = _merge_attributes(
        into.get("attributes") or [], source.get("attributes") or []
    )
    into["identity"] = _merge_identity(into.get("identity") or {}, source)
    into["merged_from"] = sorted(
        {
            *(into.get("merged_from") or []),
            str(source["id"]),
            *(source.get("merged_from") or []),
        }
    )
    into["confirmation"] = dict(stamp)
    _reorder(into)


def _merge_members(current: Sequence[Mapping], extra: Sequence[Mapping]) -> list[dict]:
    """One row per table, in the stronger of the two roles the two sides read (K4d).

    Deduping into the survivor's row drops what the folded concept knew: a table 客户
    merely *carries* is 往来方's own snapshot, and after the fold it is a snapshot of
    the surviving concept, not a reference to it.
    """
    merged: dict[str, dict] = {}
    for item in [*current, *extra]:
        table = str(item["table"])
        kept = merged.get(table)
        if kept is None or _role_strength(item) < _role_strength(kept):
            merged[table] = dict(item)
    return sorted(
        merged.values(),
        key=lambda item: (str(item["role"]) == ROLE_REFERENCE, str(item["table"])),
    )


def _role_strength(member: Mapping) -> int:
    """Where this member's role sits in ``ROLE_STRENGTH``, unknown roles weakest."""
    role = str(member.get("role"))
    return ROLE_STRENGTH.index(role) if role in ROLE_STRENGTH else len(ROLE_STRENGTH)


def _primary_warning(source: Mapping, into: Mapping) -> str | None:
    """Why this merge is worth a second look, or None when it is not (K4d).

    A merge is *directed*, and the direction is the reviewer's to choose: fold the side
    with fewer ``primary`` copies into the other. Folding two concepts that each have
    their own primary copy leaves one concept claiming two tables are *the* copy of it,
    which is either two things after all or a merge written the wrong way round. Both
    rows stay -- dropping one would answer a question only the reviewer can -- and the
    two tables are named so the next round can answer it.
    """
    folded, kept = _primary_tables(source), _primary_tables(into)
    tables = sorted(folded | kept)
    if not folded or not kept or len(tables) < 2:
        return None
    return f"merge_kept_two_primaries: {', '.join(tables)}"


def _primary_tables(concept: Mapping) -> set[str]:
    return {
        str(item["table"])
        for item in concept.get("tables") or []
        if str(item.get("role")) == ROLE_PRIMARY
    }


def _merge_identity(identity: Mapping, source: Mapping) -> dict:
    """The surviving concept's own stem, plus every stem folded into it."""
    folded = dict(source.get("identity") or {})
    merged = dict(identity)
    merged["merged_stems"] = sorted(
        {
            *(identity.get("merged_stems") or []),
            *(folded.get("merged_stems") or []),
            str(folded.get("stem")),
        }
    )
    merged["columns_seen"] = sorted(
        {*(identity.get("columns_seen") or []), *(folded.get("columns_seen") or [])}
    )
    return merged


def _merge_attributes(current: Sequence[Mapping], extra: Sequence[Mapping]) -> list[dict]:
    """One row per stem, with both concepts' source columns behind it."""
    merged: dict[str, dict] = {}
    for attribute in [*current, *extra]:
        item = merged.setdefault(str(attribute.get("stem")), {**attribute, "sources": []})
        for origin in attribute.get("sources") or []:
            if dict(origin) not in item["sources"]:
                item["sources"].append(dict(origin))
    for item in merged.values():
        item["sources"].sort(
            key=lambda origin: (str(origin.get("table")), str(origin.get("column")))
        )
    return [merged[stem] for stem in sorted(merged)]


def _forget_merged(ontology: dict) -> None:
    """A duplicate flag pointing at a concept a merge answered is no longer a question."""
    published = {str(concept["id"]) for concept in ontology["concepts"]}
    for concept in ontology["concepts"]:
        if "possible_duplicate_of" not in concept:
            continue
        others = [item for item in concept["possible_duplicate_of"] if item in published]
        if others:
            concept["possible_duplicate_of"] = others
        else:
            concept.pop("possible_duplicate_of")


# -------------------------------------------------------------------- K4b: splits


def _concept_splits(ontology: dict, splits: Sequence[Mapping], applied: dict) -> None:
    """Publish ``concept:<stem>-<n>`` per named group, keeping what nobody claimed."""
    for split in splits:
        source = str(split.get("from") or "")
        index = {str(concept["id"]): concept for concept in ontology["concepts"]}
        concept = index.get(source)
        if concept is None:
            applied["unmatched"].append({"key": source, "reason": "unknown_concept"})
            continue
        parts = _split_parts(concept, list(split.get("into") or []), applied)
        if not parts:
            continue
        taken = {str(item["table"]) for part in parts for item in part["tables"]}
        concept["tables"] = [
            item for item in concept["tables"] if str(item["table"]) not in taken
        ]
        kept = [item for item in ontology["concepts"] if str(item["id"]) != source]
        kept += [concept] if concept["tables"] else []
        ontology["concepts"] = sorted(
            kept + parts, key=lambda item: (-len(item["tables"]), str(item["id"]))
        )
        applied["splits"] += 1
    _forget_merged(ontology)


def _split_parts(concept: Mapping, into: Sequence[Mapping], applied: dict) -> list[dict]:
    """One new concept per group the reviewer named, numbered as the file lists them."""
    members = {str(item["table"]): item for item in concept.get("tables") or []}
    stem = str((concept.get("identity") or {}).get("stem"))
    parts = []
    for number, part in enumerate(into, start=1):
        tables = [str(table) for table in part.get("tables") or []]
        for table in tables:
            if table not in members:
                applied["unmatched"].append(
                    {"key": str(concept["id"]), "reason": f"unknown_table: {table}"}
                )
        claimed = [members[table] for table in tables if table in members]
        if claimed:
            identifier = f"{CONCEPT_ID_PREFIX}{stem}-{number}"
            parts.append(_split_concept(concept, part, claimed, identifier))
    return parts


def _split_concept(
    concept: Mapping, part: Mapping, claimed: Sequence[Mapping], identifier: str
) -> dict:
    """One of the concepts a split published: the named tables and what they carry."""
    tables = {str(item["table"]) for item in claimed}
    built = {
        **{key: concept[key] for key in _CONCEPT_KEYS if key in concept},
        "id": identifier,
        "name": str(part.get("name") or concept.get("name")),
        "name_tier": TIER_CONFIRMED,
        "tables": [dict(item) for item in claimed],
        "attributes": [
            attribute
            for attribute in concept.get("attributes") or []
            if any(
                str(origin.get("table")) in tables
                for origin in attribute.get("sources") or []
            )
        ],
        "split_from": str(concept["id"]),
    }
    for absent in ("possible_duplicate_of", "merged_from", "confirmation"):
        built.pop(absent, None)
    return {key: built[key] for key in _CONCEPT_KEYS if key in built}
