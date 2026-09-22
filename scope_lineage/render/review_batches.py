"""N1b: the provisional concepts cut into batches one reviewer can actually finish.

M1 publishes a ``provisional`` concept for every table no business key could place, and
K4b answers them one reviewed file at a time. On a wide corpus that is hundreds of
questions against a round capped at eight human ones and a single overrides file: the
reviewer is handed a pile rather than a queue, and the round never ends.

This module cuts the pile. It reads a built ontology and writes, per batch, a markdown
worksheet, a skeleton overrides file with one empty ``merge_into`` slot per concept, and
an index saying in which order to work them. Three rules keep a batch worth opening.

1. **A batch is a unit of judgement, not a slice of a list.** ``--by family`` groups the
   concepts by ``table_family`` -- the copies of one logical table answer as one, and
   splitting them across two batches asks the same question twice -- and fills batches up
   to ``--batch-size`` without ever breaking a family apart. ``--by domain`` does the same
   over the tables' ``naming_hints.domain`` (then ``project``), because a domain is who a
   reviewer would have to ask. ``--by size`` is the plain chunk, for a corpus whose
   metadata says neither.
2. **The order is what the answer unblocks.** Batches, groups inside them and concepts
   inside those are ranked by the relations the concept carries: an answer about a
   concept the whole corpus joins is worth more than one about a table nobody reads.
3. **The worksheet carries the evidence, never the verdict.** Each batch names the
   non-provisional concepts its concepts most relate to -- candidate merge targets,
   ranked by shared key stems and by the relations between them -- and the comments and
   key columns a decision rests on. It never proposes the merge: that is the reviewer's
   answer, and a skeleton that pre-filled it would be this layer confirming its own guess.

Everything is sorted, so two runs over one ontology write the same bytes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .concept_relations import concept_impact, provisional_concept_ids
from .concepts import CONCEPT_OVERRIDES_DOC_FORMAT, key_stem
from .markdown_text import cell
from .ontology import table_family

#: The document ``build_review_batches`` publishes.
DOC_FORMAT = "concept-review-batches/1"
#: How the provisional concepts may be cut.
BATCH_BY = ("family", "domain", "size")
#: How many concepts one batch holds before the next one starts. Eight human questions
#: per batch is the cap the prompt keeps; thirty concepts is what a reviewer gets
#: through when most of them answer themselves off the table cards.
DEFAULT_BATCH_SIZE = 30
#: The directory the three kinds of file are written under, relative to ``--out``.
BATCHES_DIR = "batches"
#: The group a table with neither a domain nor a project falls into.
UNLABELLED_GROUP = "（未标注领域）"
#: How many candidate merge targets one worksheet prints.
MERGE_TARGETS_SHOWN = 8
#: What the evidence table says when nothing keyed the table -- which is the M1 case
#: itself, and the most useful thing the row can say.
NO_CANDIDATE_KEY = "（没有候选键——这正是它成为临时概念的原因）"


# ------------------------------------------------------------------- the batches


def build_review_batches(
    ontology: Mapping, *, by: str = "family", batch_size: int = DEFAULT_BATCH_SIZE
) -> dict:
    """The provisional concepts of one ontology, cut into batches in review order."""
    if str(by) not in BATCH_BY:
        raise ValueError(f"unknown grouping: {by} (one of {', '.join(BATCH_BY)})")
    size = max(1, int(batch_size))
    rows = _rows(ontology)
    groups = _groups(rows, ontology, by=str(by))
    batches = [
        _batch(index, members, ontology)
        for index, members in enumerate(_fill(groups, size), start=1)
    ]
    return {
        "doc_format": DOC_FORMAT,
        "by": str(by),
        "batch_size": size,
        "provisional_count": len(rows),
        "batches": batches,
    }


def _rows(ontology: Mapping) -> list[dict]:
    """One row per provisional concept, ranked by what its relations unblock."""
    concepts = list(ontology.get("concepts") or [])
    provisional = provisional_concept_ids(concepts)
    # N2: shared with the index, which prints the top of this same order.
    impact = concept_impact(list(ontology.get("relations") or []))
    rows = [
        {
            "id": str(concept["id"]),
            "name": str(concept.get("name")),
            "name_tier": str(concept.get("name_tier")),
            "kind": str(concept.get("kind")),
            "tables": [str(item["table"]) for item in concept.get("tables") or []],
            "impact": impact.get(str(concept["id"]), {}).get("relations", 0),
            "tasks": impact.get(str(concept["id"]), {}).get("tasks", 0),
        }
        for concept in concepts
        if str(concept.get("id")) in provisional
    ]
    return sorted(rows, key=_row_rank)


def _row_rank(row: Mapping) -> tuple:
    return (-int(row["impact"]), -int(row["tasks"]), str(row["id"]))


def _groups(rows: Sequence[Mapping], ontology: Mapping, *, by: str) -> list[dict]:
    """The rows folded into the units a batch is filled from, strongest first.

    ``size`` has no unit above the concept, so every row is its own group of one and the
    fill degenerates into a plain chunk of the ranked list -- which is exactly what
    ``--by size`` means.
    """
    if by == "size":
        return [{"group": None, "rows": [row]} for row in rows]
    label = _family_label if by == "family" else _domain_label(ontology)
    members: dict[str, list] = {}
    for row in rows:
        members.setdefault(label(row), []).append(dict(row))
    groups = [{"group": name, "rows": members[name]} for name in sorted(members)]
    return sorted(groups, key=_group_rank)


def _group_rank(group: Mapping) -> tuple:
    rows = group["rows"]
    return (
        -sum(int(row["impact"]) for row in rows),
        -sum(int(row["tasks"]) for row in rows),
        -len(rows),
        str(group["group"]),
    )


def _family_label(row: Mapping) -> str:
    """Q3's family key of the one table this concept stands for."""
    return table_family(str((row["tables"] or [""])[0]))


def _domain_label(ontology: Mapping):
    """The metadata's own answer to "whose table is this": the domain, else the project."""
    hints = {
        str(table.get("id")): dict(table.get("naming_hints") or {})
        for table in ontology.get("tables") or []
    }

    def label(row: Mapping) -> str:
        hint = hints.get(str((row["tables"] or [""])[0])) or {}
        return str(hint.get("domain") or hint.get("project") or UNLABELLED_GROUP)

    return label


def _fill(groups: Sequence[Mapping], size: int) -> list[list[dict]]:
    """Groups packed into batches in order, never breaking one apart.

    A group larger than the cap is a batch of its own rather than a group cut in two:
    the copies of one table are one question, and half an answer is not a smaller
    question, it is the same question asked twice.
    """
    batches: list[list[dict]] = []
    current: list[dict] = []
    for group in groups:
        held = sum(len(item["rows"]) for item in current)
        if current and held + len(group["rows"]) > size:
            batches.append(current)
            current = []
        current = [*current, {**group}]
        if sum(len(item["rows"]) for item in current) >= size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches


def _batch(index: int, members: Sequence[Mapping], ontology: Mapping) -> dict:
    """One batch: its concepts, the groups they came from and what they leave open."""
    rows = [
        {**row, "group": group["group"]} for group in members for row in group["rows"]
    ]
    identifiers = [str(row["id"]) for row in rows]
    return {
        "id": f"batch-{index:02d}",
        "number": index,
        "groups": [str(group["group"]) for group in members if group["group"] is not None],
        "size": len(rows),
        "concepts": identifiers,
        "rows": rows,
        "open_item_groups": _open_item_groups(ontology, set(identifiers)),
        "merge_targets": _merge_targets(ontology, identifiers),
    }


def _open_item_groups(ontology: Mapping, identifiers: set) -> list[dict]:
    """Q3's folded open questions, cut to the ones about this batch's concepts."""
    return [
        {
            "group_id": str(group["group_id"]),
            "kind": str(group.get("kind")),
            "count": int(group.get("count") or 0),
            "impact": int(group.get("impact") or 0),
            "write_back_pattern": group.get("write_back_pattern"),
        }
        for group in ontology.get("open_item_groups") or []
        if str(group.get("concept")) in identifiers
    ]


# ------------------------------------------------------- the candidate merge targets


def _merge_targets(ontology: Mapping, identifiers: Sequence[str]) -> list[dict]:
    """The folded concepts this batch most relates to, ranked, never chosen.

    Two kinds of evidence, counted apart because they say different things: an edge
    between the two concepts means some task put them in one query, and a shared key
    stem means both are written on the same business key. Neither is a merge. A reviewer
    reading the pair decides, and the worksheet's job is to put the pair in front of
    them rather than to make them search the whole document for it.
    """
    concepts = list(ontology.get("concepts") or [])
    provisional = provisional_concept_ids(concepts)
    batch = set(str(item) for item in identifiers)
    stems = _stems({item["id"]: item for item in concepts}, batch)
    edges = _edge_counts(list(ontology.get("relations") or []), batch)
    scored = [
        {
            "id": str(concept["id"]),
            "name": str(concept.get("name")),
            "kind": str(concept.get("kind")),
            "relations": edges.get(str(concept["id"]), 0),
            "shared_stems": sorted(stems & _concept_stems(concept)),
        }
        for concept in concepts
        if str(concept["id"]) not in provisional and str(concept["id"]) not in batch
    ]
    ranked = sorted(
        (item for item in scored if item["relations"] or item["shared_stems"]),
        key=lambda item: (-item["relations"], -len(item["shared_stems"]), item["id"]),
    )
    return ranked[:MERGE_TARGETS_SHOWN]


def _stems(index: Mapping[str, Mapping], batch: set) -> set:
    return {stem for name in sorted(batch) for stem in _concept_stems(index.get(name) or {})}


def _concept_stems(concept: Mapping) -> set:
    """Every key stem this concept is written on: its own, its merges, its key columns."""
    identity = dict(concept.get("identity") or {})
    stems = {str(identity.get("stem") or "")} | {
        str(item) for item in identity.get("merged_stems") or []
    }
    stems |= {key_stem(column) for column in identity.get("columns_seen") or []}
    stems |= {
        key_stem(column)
        for member in concept.get("tables") or []
        for column in member.get("key_columns") or []
    }
    return {stem for stem in stems if stem}


def _edge_counts(relations: Sequence[Mapping], batch: set) -> dict[str, int]:
    """How many concept relations join each far concept to one of this batch's."""
    counted: dict[str, int] = {}
    for relation in relations:
        ends = (str(relation.get("from")), str(relation.get("to")))
        for near, far in (ends, ends[::-1]):
            if near in batch and far not in batch:
                counted[far] = counted.get(far, 0) + 1
    return counted


# ------------------------------------------------------------------ what gets written


def batch_overrides_skeleton(batch: Mapping, ontology: Mapping) -> dict:
    """One batch's ``concepts.overrides.json``, with the answers left blank.

    Every concept of the batch gets an empty ``merge_into``, because that is the
    question M1 asked and the one the reviewer is here to answer. Empty is a real
    value here: ``apply_concept_overrides`` reads a blank ``merge_into`` as "not
    answered", so a skeleton that reaches the builder untouched changes nothing and
    reports nothing -- the reviewer finds out from the counters, not from a document
    that quietly grew a merge.
    """
    return {
        "doc_format": CONCEPT_OVERRIDES_DOC_FORMAT,
        "comments": _skeleton_comments(batch, ontology),
        "concepts": {
            str(identifier): {"merge_into": ""} for identifier in batch["concepts"]
        },
    }


def _skeleton_comments(batch: Mapping, ontology: Mapping) -> list[str]:
    """The lines a reviewer reads before filling anything in: scope, then what is open."""
    groups = "、".join(str(item) for item in batch["groups"]) or "按影响排序"
    lines = [
        f"{batch['id']}：{batch['size']} 个临时概念（{groups}）。逐个填 merge_into，"
        "或者把这一条整个删掉——留空表示「本轮没答」，应用时什么也不会发生。",
        "不要改别的批次的文件；两份文件都点到同一个键时，后给的那一份生效，"
        "并报在 concept_overrides_applied.conflicts[] 里，由人来定。",
    ]
    lines.extend(
        f"待判定分组 {group['group_id']}（{group['kind']}，{group['count']} 条，"
        f"影响 {group['impact']}）：{group.get('write_back_pattern') or '无回写模式'}"
        for group in batch["open_item_groups"]
    )
    return lines


def render_batch_markdown(batch: Mapping, ontology: Mapping) -> str:
    """One batch's worksheet: the concepts, the candidates, and the evidence."""
    lines = [
        f"# 概念评审批次 {batch['id']}",
        "",
        f"{batch['size']} 个临时概念"
        + (f"（{'、'.join(str(item) for item in batch['groups'])}）" if batch["groups"] else "")
        + "。答完写进 "
        f"`{batch['id']}.overrides.json`，**只写这一批**，不要改别的批次的文件。"
        "去问人的问题这一批最多 8 条。",
        "",
        "## 本批概念",
        "",
        "| 概念 | 种类 | 表 | 关系 | 命名候选 | 回写键 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    index = {str(item["id"]): item for item in ontology.get("concepts") or []}
    lines.extend(_concept_row(row, index.get(str(row["id"])) or {}) for row in batch["rows"])
    lines.extend(_merge_target_section(batch))
    lines.extend(_evidence_section(batch, ontology, index))
    return "\n".join(lines) + "\n"


def _concept_row(row: Mapping, concept: Mapping) -> str:
    candidates = "、".join(
        f"{cell(str(item.get('text')))}（{item.get('source')}）"
        for item in (concept.get("name_candidates") or [])[:3]
    )
    return (
        f"| {cell(str(row['name']))}（`{row['name_tier']}`） "
        f"| {row['kind']} "
        f"| {'、'.join(f'`{table}`' for table in row['tables'])} "
        f"| {row['impact']} 条 / {row['tasks']} 个任务 "
        f"| {candidates or '（无）'} "
        f"| `{row['id']}` 的 `merge_into` |"
    )


def _merge_target_section(batch: Mapping) -> list[str]:
    """The folded concepts worth reading beside this batch -- candidates, not answers."""
    lines = ["", "## 候选归并目标（语料已经折出来的概念）", ""]
    if not batch["merge_targets"]:
        return [
            *lines,
            "本批的概念与任何已折出的概念都没有共同键词根、也没有关系相连——"
            "要么它们自成一件事，要么得用 `new_concepts` 把几张一起收成一个新概念。",
        ]
    lines.extend(
        [
            "按「与本批概念之间的关系条数」「共同键词根」排序。**这不是建议**："
            "同键不等于同一件事，同查询更不等于。读完两边的表再决定。",
            "",
            "| 概念 | 种类 | 关系 | 共同键词根 | 回写 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {cell(str(item['name']))} | {item['kind']} | {item['relations']} 条 "
        f"| {'、'.join(f'`{stem}`' for stem in item['shared_stems']) or '（无）'} "
        f"| `merge_into: \"{item['id']}\"` |"
        for item in batch["merge_targets"]
    )
    return lines


def _evidence_section(batch: Mapping, ontology: Mapping, index: Mapping) -> list[str]:
    """What a decision rests on: the table's own comment and the columns it is keyed by."""
    tables = {str(item.get("id")): item for item in ontology.get("tables") or []}
    lines = [
        "",
        "## 判断依据（表注释与键列）",
        "",
        "| 表 | 表注释 | 键列 | 列注释 |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        _evidence_row(table, tables.get(table) or {}, index.get(str(row["id"])) or {})
        for row in batch["rows"]
        for table in row["tables"]
    )
    lines.extend(_open_items_lines(batch))
    return lines


def _evidence_row(table: str, entity: Mapping, concept: Mapping) -> str:
    columns = _evidence_columns(table, entity, concept)
    comments = [
        f"{attribute['column']}：{cell(str(attribute.get('comment')))}"
        for attribute in entity.get("attributes") or []
        if str(attribute.get("column")) in columns and attribute.get("comment")
    ]
    keys = "、".join(f"`{column}`" for column in columns) or NO_CANDIDATE_KEY
    return (
        f"| `{table}` "
        f"| {cell(str(entity.get('comment') or '（无）'))} "
        f"| {keys} "
        f"| {'；'.join(comments) or '（无）'} |"
    )


def _evidence_columns(table: str, entity: Mapping, concept: Mapping) -> list[str]:
    """The columns a reviewer reads to decide: the membership's, else the table's own.

    A provisional concept whose member carries no key columns is the M1 case itself --
    nothing keyed the table -- and the table's own ``candidate_keys`` are then the last
    thing the corpus has to say about it. Empty on both counts is an answer too, and the
    cell says so rather than printing a bare dash.
    """
    columns = [
        str(column)
        for member in concept.get("tables") or []
        if str(member.get("table")) == table
        for column in member.get("key_columns") or []
    ]
    if columns:
        return columns
    identity = dict(entity.get("identity") or {})
    return [
        str(column)
        for key in identity.get("candidate_keys") or []
        for column in key.get("columns") or []
    ]


def _open_items_lines(batch: Mapping) -> list[str]:
    lines = ["", "## 本批的待判定分组", ""]
    if not batch["open_item_groups"]:
        return [*lines, "本批的概念没有待判定项。"]
    lines.extend(
        [
            "| 分组 | 种类 | 条数 | 影响 | 回写模式 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| `{group['group_id']}` | {group['kind']} | {group['count']} | {group['impact']} "
        f"| `{group.get('write_back_pattern') or '（无）'}` |"
        for group in batch["open_item_groups"]
    )
    return lines


def render_batch_index_markdown(batches: Mapping) -> str:
    """The reading order, which is the whole point of cutting the pile up."""
    rows = list(batches.get("batches") or [])
    lines = [
        "# 概念评审分批",
        "",
        f"{batches['provisional_count']} 个临时概念切成 {len(rows)} 批"
        f"（按 `{batches['by']}`，每批最多 {batches['batch_size']} 个）。"
        "**从上往下做**：越靠前的批次，答案解开的边越多。一批一份 overrides 文件，"
        "跑的时候按同样的顺序重复 `--concept-overrides`。",
        "",
        "| 顺序 | 批次 | 概念数 | 分组 | 关系 | 待判定分组 | 工作表 | 回写文件 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_index_row(position, batch) for position, batch in enumerate(rows, start=1))
    return "\n".join(lines) + "\n"


def _index_row(position: int, batch: Mapping) -> str:
    impact = sum(int(row["impact"]) for row in batch["rows"])
    groups = "、".join(str(item) for item in batch["groups"]) or "（按影响排序）"
    return (
        f"| {position} | `{batch['id']}` | {batch['size']} | {cell(groups)} "
        f"| {impact} 条 | {len(batch['open_item_groups'])} "
        f"| [{batch['id']}.md]({batch['id']}.md) "
        f"| `{batch['id']}.overrides.json` |"
    )


def write_review_batches(
    ontology: Mapping,
    out: Path | str,
    *,
    by: str = "family",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[str]:
    """The three kinds of file, under ``<out>/batches/``; the paths it wrote."""
    batches = build_review_batches(ontology, by=by, batch_size=batch_size)
    directory = Path(out) / BATCHES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.md").write_text(
        render_batch_index_markdown(batches), encoding="utf-8"
    )
    written = [f"{BATCHES_DIR}/index.md"]
    for batch in batches["batches"]:
        (directory / f"{batch['id']}.md").write_text(
            render_batch_markdown(batch, ontology), encoding="utf-8"
        )
        (directory / f"{batch['id']}.overrides.json").write_text(
            json.dumps(
                batch_overrides_skeleton(batch, ontology), ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        written.extend(
            [f"{BATCHES_DIR}/{batch['id']}.md", f"{BATCHES_DIR}/{batch['id']}.overrides.json"]
        )
    return written
