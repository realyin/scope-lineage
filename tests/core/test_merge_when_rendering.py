"""A MERGE's WHEN condition is a branch condition, not a row filter (decision 2.2).

The WHEN conditions became ROOT filter blocks with ``predicate_type: "merge_when"``
(1.13-j). Every derived view read them as WHERE: ``describe`` wrote
``WHEN MATCHED AND s.op = 'D' THEN DELETE`` as "keeps only the rows with op = 'D'" --
the opposite of what it does, labelled a SQL fact -- and the rule's ``kind: filter``
carried it on into the non-null constraints, the metric paths and the material packet's
record-range filters. A block also had nothing saying which WHEN it belongs to: its id
numbers only the conditioned clauses.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.mapping_markdown import render_mapping_markdown
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets

SCHEMA = {
    "s.delta": ["cust_id", "op", "status", "ts", "dt", "phone"],
    "m.tgt": ["cust_id", "status", "upd", "dt", "phone"],
}

THREE_WHENS = (
    "MERGE INTO m.tgt t USING s.delta s ON t.cust_id = s.cust_id AND t.dt = s.dt "
    "WHEN MATCHED AND s.op = 'D' THEN DELETE "
    "WHEN MATCHED AND s.status <> t.status THEN UPDATE SET t.status = s.status, t.upd = s.ts "
    "WHEN NOT MATCHED AND s.op <> 'D' THEN INSERT (cust_id, status, upd, dt) "
    "VALUES (s.cust_id, s.status, s.ts, s.dt)"
)

UNCONDITIONED_MIDDLE = (
    "MERGE INTO m.tgt t USING s.delta s ON t.cust_id = s.cust_id "
    "WHEN MATCHED AND s.op = 'D' THEN DELETE "
    "WHEN MATCHED THEN UPDATE SET t.status = s.status "
    "WHEN NOT MATCHED AND s.op <> 'D' THEN INSERT (cust_id, status) VALUES (s.cust_id, s.status)"
)

NOT_NULL_UPDATE = (
    "MERGE INTO m.tgt t USING (SELECT cust_id, phone, status FROM s.delta) s "
    "ON t.cust_id = s.cust_id "
    "WHEN MATCHED AND s.phone IS NOT NULL THEN UPDATE SET t.phone = s.phone "
    "WHEN NOT MATCHED THEN INSERT (cust_id, phone, status) VALUES (s.cust_id, s.phone, s.status)"
)


def _document(sql: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))


def _root_filter_blocks(document: dict) -> list[dict]:
    return [
        block
        for block in document["scopes"]["ROOT"].get("logic_blocks") or []
        if block["logic_type"] == "filter"
    ]


def _root_stage_lines(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    start = next(i for i, line in enumerate(lines) if "（`ROOT`，" in line)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines)
    )
    return lines[start:end]


# ------------------------------------------------------------- the block's identity


def test_each_when_block_names_its_clause() -> None:
    blocks = _root_filter_blocks(_document(THREE_WHENS))

    assert [b["filter_predicate_detail"]["merge_when_index"] for b in blocks] == [0, 1, 2]


def test_an_unconditioned_when_keeps_its_index() -> None:
    blocks = _root_filter_blocks(_document(UNCONDITIONED_MIDDLE))

    # The middle WHEN has no condition and no block; the last block is clause 2, not 1.
    assert [b["filter_predicate_detail"]["merge_when_index"] for b in blocks] == [0, 2]


def test_a_where_block_carries_no_merge_when_index() -> None:
    document = _document(
        "INSERT OVERWRITE TABLE m.tgt SELECT cust_id, status, ts AS upd, dt, phone "
        "FROM s.delta WHERE op = 'D'"
    )

    [block] = _root_filter_blocks(document)
    assert "merge_when_index" not in block["filter_predicate_detail"]


# ------------------------------------------------------------------ semantic.json


def test_when_conditions_are_merge_when_rules_not_filters() -> None:
    profile = build_semantic_profile(_document(THREE_WHENS))
    root_rules = [rule for rule in profile["rules"] if rule["scope_id"] == "ROOT"]

    assert [rule["kind"] for rule in root_rules] == ["merge_when"] * 3
    assert [
        (rule["merge_when_index"], rule["clause"], rule["action"]) for rule in root_rules
    ] == [(0, "matched", "delete"), (1, "matched", "update"), (2, "not_matched", "insert")]
    assert "is_partition_filter" not in root_rules[0]


def test_the_stage_action_is_a_branch_condition() -> None:
    profile = build_semantic_profile(_document(THREE_WHENS))
    root = next(stage for stage in profile["stages"] if stage["scope_id"] == "ROOT")

    actions = [action for action in root["actions"] if action["type"] == "merge_when"]
    assert len(actions) == 3
    assert not [action for action in root["actions"] if action["type"] == "filter"]
    assert "删除" in actions[0]["text"]
    assert all("只保留" not in action["text"] for action in actions)


def test_when_columns_are_not_filter_usages() -> None:
    # Guard: a WHEN block carries no `expression_resolution` today, so no physical usage
    # is recorded from it at all; should one ever be, it must not be `filter`.
    profile = build_semantic_profile(_document(THREE_WHENS))
    [source] = [item for item in profile["inputs"] if item["table"] == "s.delta"]
    usages = {column["name"]: column["usages"] for column in source["used_columns"]}

    assert "filter" not in usages.get("op", [])


# ------------------------------------------------------------------- semantic.md


def test_the_markdown_never_says_a_when_keeps_rows() -> None:
    markdown = render_semantic_markdown(build_semantic_profile(_document(THREE_WHENS)))
    stage = _root_stage_lines(markdown)

    assert not [line for line in stage if "只保留" in line]
    delete = [line for line in stage if "op = 'D'" in line]
    assert delete and all("删除" in line for line in delete)
    assert "过滤 3 处" not in markdown
    assert "MERGE 分支条件" in markdown


def test_the_rule_table_labels_a_branch_condition() -> None:
    markdown = render_semantic_markdown(build_semantic_profile(_document(THREE_WHENS)))
    rows = [line for line in markdown.splitlines() if line.startswith("| rule:")]

    assert len(rows) == 3
    assert all("MERGE 分支条件（merge_when）" in row for row in rows)


# --------------------------------------------------------- downstream rule readers


def test_a_when_not_null_test_is_no_not_null_constraint() -> None:
    # Guard: a WHEN block carries no `expression_resolution`, so its rule names no
    # physical field and the constraint reader could not attach it even as `filter`.
    # With `kind: merge_when` it is not read at all, whatever the fields become.
    document = _document(NOT_NULL_UPDATE)
    ontology = build_ontology([document], [build_semantic_profile(document)])

    assert not [
        item for item in ontology["constraints"] if item["kind"] == "not_null"
    ]


def test_the_packet_lists_when_conditions_apart_from_filters() -> None:
    (packet,) = build_packets([(_document(THREE_WHENS), None)])
    rules = packet["rules"] if "rules" in packet else packet["lineage"]["rules"]

    assert not [rule for rule in rules if rule["kind"] == "filter"]
    whens = [rule for rule in rules if rule["kind"] == "merge_when"]
    assert len(whens) == 3
    assert "删除" in whens[0]["text"]


def test_the_mapping_document_names_a_branch_condition() -> None:
    document = _document(THREE_WHENS)
    rendered = render_mapping_markdown(document)

    assert "过滤：" not in rendered
    assert "MERGE 分支条件：" in rendered


# ------------------------------------------------------------------ sentinels


def test_a_where_is_still_a_filter() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT OVERWRITE TABLE m.tgt SELECT cust_id, status, ts AS upd, dt, phone "
            "FROM s.delta WHERE phone IS NOT NULL"
        )
    )

    [rule] = profile["rules"]
    assert rule["kind"] == "filter"
    markdown = render_semantic_markdown(profile)
    assert "只保留" in markdown
