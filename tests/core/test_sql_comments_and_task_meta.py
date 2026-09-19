"""WI-2.2: SQL comments and task metadata as published contract facts.

Three claims are pinned here, in the order the data flows:

1. **The parser keeps the comments sqlglot attaches.** A statement header block, an
   alias comment and a comment inside a condition each land on a different node, and
   each has its own contract key. ``--strip-comments`` removes all three *and* the
   inline copies that already rode along inside the rendered expressions, so the flag
   is a real privacy switch rather than a partial one.
2. **Task metadata is copied, never composed.** ``owner_email`` is excluded by name
   (personal data), unknown keys are ignored, and every value is a string or ``null``.
3. **A ``.sql`` input has no ``task_meta`` key at all** -- absence means "no task JSON
   supplied it", never "the task has no owner".

Every fixture here is synthetic; the comments are invented Chinese text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage import parse_task_lineage
from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.contract.validation import validate_lineage_document
from scope_lineage.scope import sql_comments
from scope_lineage.scope.scope_builder import parse_scope_lineage


COMMENTED_SQL = """-- 任务：每日客户画像
-- 口径：仅统计活跃客户
INSERT OVERWRITE TABLE mart.customer_profile PARTITION (dt = '${bizdate}')
SELECT
  a.cust_id AS cust_id,  -- 客户号
  /* 金额（元） */
  SUM(b.amt) AS total_amt,
  'SF' AS channel -- 自营暂固定为 SF
FROM ods.customer a
LEFT JOIN ods.payment b ON a.cust_id = b.cust_id  -- 按客户号关联
WHERE a.status = '1' -- 仅活跃
GROUP BY a.cust_id
"""

SCHEMA = {
    "ods.customer": ["cust_id", "status"],
    "ods.payment": ["cust_id", "amt"],
}

TASK_META_INPUT = {
    "task_id": "12345",
    "task_name": "customer_profile_daily",
    "task_type": "SparkSQL",
    "project_name": "demo_project",
    "project_code": "DEMO",
    "owner": "demo_owner",
    "owner_email": "demo_owner@example.com",
    "schedule": "0 30 2 * * ?",
    "schedule_cycle": "DAY",
    "description": "每日客户画像",
    "expect_date": "2026-09-18",
    "source_file": "demo/customer_profile_daily.json",
    "sql": "SELECT 1",
    "input_tables": ["ods.customer"],
}


def _document(sql: str = COMMENTED_SQL, **kwargs) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "wi22", schema=SCHEMA, **kwargs))


def _outputs(document: dict, scope_id: str = "ROOT") -> dict[str, dict]:
    scope = document["scopes"][scope_id]
    return {str(item["name"]): item for item in scope.get("outputs") or []}


def _blocks(document: dict, scope_id: str = "ROOT") -> dict[str, dict]:
    scope = document["scopes"][scope_id]
    return {str(item["logic_block_id"]): item for item in scope.get("logic_blocks") or []}


# --------------------------------------------------------- 1. statement_comments


def test_the_statement_header_block_is_published_in_order() -> None:
    assert _document()["statement_comments"] == [
        "任务：每日客户画像",
        "口径：仅统计活跃客户",
    ]


def test_a_statement_without_comments_publishes_an_empty_list() -> None:
    document = _document("INSERT INTO mart.t SELECT id FROM ods.customer")
    assert document["statement_comments"] == []


def test_the_key_is_always_present_so_absence_never_means_unknown() -> None:
    assert "statement_comments" in _document("INSERT INTO mart.t SELECT 1 AS id")


# ------------------------------------------------------------- 2. output comments


def test_an_alias_comment_is_published_on_that_output_column() -> None:
    outputs = _outputs(_document())
    assert outputs["cust_id"]["comments"] == ["客户号"]
    assert outputs["total_amt"]["comments"] == ["金额（元）"]
    assert outputs["channel"]["comments"] == ["自营暂固定为 SF"]


def test_an_output_without_a_comment_omits_the_key() -> None:
    document = _document("INSERT INTO mart.t SELECT a.cust_id AS id FROM ods.customer a")
    assert "comments" not in _outputs(document)["id"]


# --------------------------------------------------------- 3. logic block comments


def test_a_join_condition_comment_is_published_on_the_join_block() -> None:
    blocks = _blocks(_document())
    join = next(b for b in blocks.values() if b["logic_type"] == "join")
    assert join["comments"] == ["按客户号关联"]


def test_a_where_comment_is_published_on_the_filter_block() -> None:
    blocks = _blocks(_document())
    where = next(b for b in blocks.values() if b["logic_type"] == "filter")
    assert where["comments"] == ["仅活跃"]


def test_a_block_without_a_comment_omits_the_key() -> None:
    blocks = _blocks(_document())
    group_by = next(b for b in blocks.values() if b["logic_type"] == "group_by")
    assert "comments" not in group_by


def test_a_comment_like_string_literal_is_not_read_as_a_comment() -> None:
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.customer WHERE status = '-- not a comment'"
    )
    blocks = _blocks(document)
    where = next(b for b in blocks.values() if b["logic_type"] == "filter")
    assert "comments" not in where


# ------------------------------------------------------------- 4. --strip-comments


def test_stripping_removes_all_three_comment_facts() -> None:
    document = _document(strip_comments=True)
    assert document["statement_comments"] == []
    assert all("comments" not in item for item in _outputs(document).values())
    assert all("comments" not in item for item in _blocks(document).values())


def test_stripping_also_removes_the_inline_copies_inside_expressions() -> None:
    """The flag is a privacy switch: a comment must not survive in `raw_expression`."""
    document = _document(strip_comments=True)
    serialized = json.dumps(document, ensure_ascii=False)
    for comment in ("客户号", "仅活跃", "按客户号关联", "每日客户画像"):
        assert comment not in serialized


def test_collecting_is_the_default() -> None:
    assert _document()["statement_comments"]


# ------------------------------------------------------------------- 5. task_meta


def test_task_meta_is_copied_under_neutral_key_names() -> None:
    result = parse_task_lineage(
        COMMENTED_SQL, task_name="wi22", schema=SCHEMA, task_meta=TASK_META_INPUT
    )
    assert to_task_lineage_dict(result)["task_meta"] == {
        "task_name": "customer_profile_daily",
        "task_id": "12345",
        "project": "demo_project",
        "owner": "demo_owner",
        "schedule": "0 30 2 * * ?",
        "schedule_cycle": "DAY",
        "description": "每日客户画像",
        "expect_date": "2026-09-18",
        "source_file": "demo/customer_profile_daily.json",
    }


def test_the_owner_email_is_never_carried() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.t SELECT 1 AS id",
        task_name="wi22",
        task_meta=TASK_META_INPUT,
    )
    document = to_task_lineage_dict(result)
    assert "owner_email" not in document["task_meta"]
    assert "example.com" not in json.dumps(document, ensure_ascii=False)


def test_an_empty_or_missing_value_becomes_null_and_unknown_keys_are_ignored() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.t SELECT 1 AS id",
        task_name="wi22",
        task_meta={"task_name": "  ", "owner": 0, "instance_id": "ignored"},
    )
    meta = to_task_lineage_dict(result)["task_meta"]
    assert meta["task_name"] is None
    assert meta["owner"] == "0"
    assert meta["schedule_cycle"] is None
    assert "instance_id" not in meta


def test_a_sql_input_has_no_task_meta_key_at_all() -> None:
    result = parse_task_lineage("INSERT INTO mart.t SELECT 1 AS id", task_name="wi22")
    assert "task_meta" not in to_task_lineage_dict(result)


def test_an_empty_meta_object_publishes_no_key_either() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.t SELECT 1 AS id", task_name="wi22", task_meta={}
    )
    assert "task_meta" not in to_task_lineage_dict(result)


# -------------------------------------------------- 6. the normalized-SQL path keeps them


def test_the_task_path_keeps_the_comments_the_statement_path_finds() -> None:
    """`parse_task_lineage` parses a *repaired* copy of the script; the repairs are
    text-level and must not cost the script its comments."""
    result = parse_task_lineage(COMMENTED_SQL, task_name="wi22", schema=SCHEMA)
    statement = to_task_lineage_dict(result)["statement_lineage"]["stmt:001"]
    assert statement["statement_comments"] == [
        "任务：每日客户画像",
        "口径：仅统计活跃客户",
    ]
    outputs = {item["name"]: item for item in statement["scopes"]["ROOT"]["outputs"]}
    assert outputs["cust_id"]["comments"] == ["客户号"]


def test_the_task_level_strip_flag_reaches_every_statement() -> None:
    result = parse_task_lineage(
        COMMENTED_SQL, task_name="wi22", schema=SCHEMA, strip_comments=True
    )
    serialized = json.dumps(to_task_lineage_dict(result), ensure_ascii=False)
    assert "客户号" not in serialized


# ------------------------------------------------------------------- 7. schema/validation


def test_a_commented_statement_document_validates_against_the_schema() -> None:
    from .statement_document import build_statement_documents

    lineage, _ = build_statement_documents(
        parse_scope_lineage(COMMENTED_SQL, "wi22", schema=SCHEMA)
    )
    validate_lineage_document(lineage)


# ------------------------------------------------------------------- 8. the scanner


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a = 1 /* one */", ["one"]),
        ("a = 1 -- one", ["one"]),
        ("a = '-- literal'", []),
        ("a = '/* literal */'", []),
        ("`-- quoted ident` = 1", []),
        ("a = 1 /* one */ AND b = 2 /* two */", ["one", "two"]),
        ("a = 1 /* one */ AND b = 2 /* one */", ["one"]),
        ("a /*  padded  */ = 1", ["padded"]),
        ("a = 1 /* */", []),
        ("a = 'it''s' -- after", ["after"]),
    ],
)
def test_the_sql_comment_scanner_skips_quoted_regions(text: str, expected) -> None:
    assert sql_comments.comments_in_sql(text) == expected


def test_adjacent_duplicates_collapse_but_repeats_further_apart_do_not() -> None:
    assert sql_comments.normalize([" a ", "a", "b", "a"]) == ["a", "b", "a"]
    assert sql_comments.normalize([None, "", "   "]) == []


# ------------------------------------------------------------------- 9. the CLI flag


def test_the_cli_strip_flag_removes_comments_from_the_written_artifact(
    tmp_path: Path,
) -> None:
    from scope_lineage.cli import main

    sql_file = tmp_path / "commented.sql"
    sql_file.write_text(COMMENTED_SQL, encoding="utf-8")
    out = tmp_path / "out"
    assert main(["parse", "--sql-file", str(sql_file), "--out", str(out), "--strip-comments"]) == 0
    written = (out / "commented" / "lineage.json").read_text(encoding="utf-8")
    assert "客户号" not in written


def test_the_cli_carries_the_task_json_meta_without_the_owner_email(
    tmp_path: Path,
) -> None:
    from scope_lineage.cli import main

    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps({"meta": {**TASK_META_INPUT, "sql": COMMENTED_SQL}}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert main(["parse", "--task-file", str(task_file), "--out", str(out)]) == 0
    document = json.loads(
        (out / "customer_profile_daily" / "lineage.json").read_text(encoding="utf-8")
    )
    assert document["task_meta"]["owner"] == "demo_owner"
    assert document["task_meta"]["source_file"] == "task.json"
    assert "owner_email" not in document["task_meta"]


# ------------------------------------------------------- 10. PII redaction (default on)

REDACTION_SQL = """-- 对账人 zhangsan@example.invalid
INSERT INTO mart.t
SELECT a.cust_id AS cust_id  -- 有问题找 13800138000
FROM ods.customer a
WHERE a.status = '1' -- 身份证 110101199003078219 已核验，日期 20260814，金额 1000.50
"""


def _redacted_document() -> dict:
    return _document(REDACTION_SQL)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("联系 zhangsan@example.invalid", "联系 <email>"),
        # the sentence around the address survives: masking must not delete prose
        ("联系 zhangsan@example.invalid（值班）", "联系 <email>（值班）"),
        ("对账人:lisi@example.invalid,谢谢", "对账人:<email>,谢谢"),
        ("手机 13800138000", "手机 <phone>"),
        ("手机 +86 13800138000", "手机 <phone>"),
        ("手机 +8613800138000", "手机 <phone>"),
        ("身份证 110101199003078219", "身份证 <id>"),
        ("身份证 11010119900307821X", "身份证 <id>"),
        ("旧身份证 110101900307821", "旧身份证 <id>"),
        ("旧身份证 110101900101123", "旧身份证 <id>"),
        # a 15- or 18-digit run whose middle is not a legal birth date is not an ID
        # number: a serial number, a bar code, an order key. The shape is what is
        # masked, and these do not have it.
        ("流水号 123456789012345", "流水号 123456789012345"),
        ("流水号 123456789012345678", "流水号 123456789012345678"),
        ("条码 000000199003078219", "条码 000000199003078219"),
        # not contact shapes: a partition date, an amount, a long key, a short code
        ("分区 20260814", "分区 20260814"),
        ("金额 1000.50 元", "金额 1000.50 元"),
        ("流水号 12345678901234567890", "流水号 12345678901234567890"),
        ("状态码 1380013", "状态码 1380013"),
        # 12xxxxxxxxx is not a mainland mobile prefix
        ("编号 12800138000", "编号 12800138000"),
    ],
)
def test_redact_masks_contact_shapes_and_leaves_ordinary_numbers_alone(
    text: str, expected: str
) -> None:
    assert sql_comments.redact(text) == expected


def test_the_three_shapes_are_masked_in_the_published_comments() -> None:
    document = _redacted_document()
    assert document["statement_comments"] == ["对账人 <email>"]
    assert _outputs(document)["cust_id"]["comments"] == ["有问题找 <phone>"]
    where = next(b for b in _blocks(document).values() if b["logic_type"] == "filter")
    assert where["comments"] == ["身份证 <id> 已核验，日期 20260814，金额 1000.50"]


def test_no_contact_shape_survives_anywhere_in_the_document() -> None:
    serialized = json.dumps(_redacted_document(), ensure_ascii=False)
    for shape in ("zhangsan@example.invalid", "13800138000", "110101199003078219"):
        assert shape not in serialized


def test_the_inline_copy_inside_raw_expression_is_masked_too() -> None:
    """Redaction is not a filter over the comment keys: the same comment rides along
    inside the rendered expression, and an address left there is still published."""
    where = next(
        block
        for block in _blocks(_redacted_document()).values()
        if block["logic_type"] == "filter"
    )
    assert "110101199003078219" not in where["raw_expression"]
    assert "<id>" in where["raw_expression"]


def test_redaction_is_off_when_the_caller_says_so() -> None:
    document = _document(REDACTION_SQL, redact_comments=False)
    assert document["statement_comments"] == ["对账人 zhangsan@example.invalid"]
    assert _outputs(document)["cust_id"]["comments"] == ["有问题找 13800138000"]


def test_redaction_does_not_touch_the_sql_expression_itself() -> None:
    """Only the comment text is rewritten. A digit run inside a predicate is data the
    statement operates on, and masking it would change what the SQL says."""
    document = _document(
        "INSERT INTO mart.t SELECT id FROM ods.customer "
        "WHERE id_no = '110101199003078219' AND email = 'a@b.invalid'"
    )
    where = next(b for b in _blocks(document).values() if b["logic_type"] == "filter")
    assert "110101199003078219" in where["raw_expression"]
    assert "a@b.invalid" in where["raw_expression"]


def test_the_task_path_redacts_every_statement_and_the_description() -> None:
    result = parse_task_lineage(
        REDACTION_SQL,
        task_name="wi22",
        schema=SCHEMA,
        task_meta={**TASK_META_INPUT, "description": "每日客户画像，问 lisi@example.invalid"},
    )
    document = to_task_lineage_dict(result)
    assert document["task_meta"]["description"] == "每日客户画像，问 <email>"
    serialized = json.dumps(document, ensure_ascii=False)
    assert "zhangsan@example.invalid" not in serialized
    assert "13800138000" not in serialized


def test_the_task_path_keeps_the_description_verbatim_when_redaction_is_off() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.t SELECT 1 AS id",
        task_name="wi22",
        task_meta={**TASK_META_INPUT, "description": "问 lisi@example.invalid"},
        redact_comments=False,
    )
    meta = to_task_lineage_dict(result)["task_meta"]
    assert meta["description"] == "问 lisi@example.invalid"


def test_stripping_and_redacting_are_independent_switches() -> None:
    """Stripping leaves nothing to mask, so the pair is not a contradiction: the
    document simply has no comments at all."""
    document = _document(REDACTION_SQL, strip_comments=True, redact_comments=True)
    assert document["statement_comments"] == []
    serialized = json.dumps(document, ensure_ascii=False)
    for text in ("<email>", "<phone>", "<id>", "对账人", "有问题找"):
        assert text not in serialized


def test_the_cli_redacts_by_default_and_the_flag_turns_it_off(tmp_path: Path) -> None:
    from scope_lineage.cli import main

    sql_file = tmp_path / "pii.sql"
    sql_file.write_text(REDACTION_SQL, encoding="utf-8")

    default_out = tmp_path / "default"
    assert main(["parse", "--sql-file", str(sql_file), "--out", str(default_out)]) == 0
    written = (default_out / "pii" / "lineage.json").read_text(encoding="utf-8")
    assert "<email>" in written
    assert "zhangsan@example.invalid" not in written

    verbatim_out = tmp_path / "verbatim"
    assert main([
        "parse",
        "--sql-file",
        str(sql_file),
        "--out",
        str(verbatim_out),
        "--no-redact-comments",
    ]) == 0
    written = (verbatim_out / "pii" / "lineage.json").read_text(encoding="utf-8")
    assert "zhangsan@example.invalid" in written


# ------------------------------------------------- 10. the script header block (B1)
#
# A task script usually opens with the block that says what the job does, and that block
# sits above the session settings rather than above the INSERT. sqlglot attaches it to the
# first `SET`, which this tool does not model, so it used to be dropped: the single best
# sentence about the task never reached any artifact. It is published on the first modelled
# write statement and, once, as the task document's `script_comments`.

PREAMBLE_SQL = """-- 任务：门店日销汇总（合成示例）
-- 口径：仅统计营业中的门店
SET spark.sql.shuffle.partitions=200;
SET spark.sql.adaptive.enabled=true;
INSERT INTO mart.store_daily
SELECT s.store_id AS store_id, SUM(s.amount) AS total_amount
FROM ods.store_event s
WHERE s.status = 'OPEN'
GROUP BY s.store_id
"""

PREAMBLE_SCHEMA = {"ods.store_event": ["store_id", "amount", "status"]}

SCRIPT_HEADER = ["任务：门店日销汇总（合成示例）", "口径：仅统计营业中的门店"]

TWO_WRITE_SQL = """-- 任务：门店日销汇总（合成示例）
SET spark.sql.shuffle.partitions=200;
INSERT INTO mart.store_daily SELECT s.store_id AS store_id FROM ods.store_event s;
-- 第二步：只写营业中的门店
INSERT INTO mart.store_open SELECT s.store_id AS store_id FROM ods.store_event s
"""


def _statement(sql: str = PREAMBLE_SQL, **kwargs) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, "b1", schema=PREAMBLE_SCHEMA, **kwargs)
    )


def _task(sql: str = PREAMBLE_SQL, schema=PREAMBLE_SCHEMA, **kwargs) -> dict:
    return to_task_lineage_dict(
        parse_task_lineage(sql, task_name="b1", schema=schema, **kwargs)
    )


def test_a_header_block_above_a_set_preamble_reaches_the_first_write() -> None:
    assert _statement()["statement_comments"] == SCRIPT_HEADER


def test_the_task_document_publishes_the_header_once_at_task_level() -> None:
    document = _task()
    assert document["script_comments"] == SCRIPT_HEADER
    assert document["statement_lineage"]["stmt:003"]["statement_comments"] == (
        SCRIPT_HEADER
    )


def test_the_script_header_precedes_the_statements_own_header_block() -> None:
    sql = (
        "-- 任务：门店日销汇总（合成示例）\n"
        "SET spark.sql.shuffle.partitions=200;\n"
        "-- 本条：只汇总营业中的门店\n"
        "INSERT INTO mart.store_daily SELECT s.store_id AS store_id FROM ods.store_event s\n"
    )
    assert _statement(sql)["statement_comments"] == [
        "任务：门店日销汇总（合成示例）",
        "本条：只汇总营业中的门店",
    ]


def test_a_note_written_between_two_writes_stays_on_the_second_one() -> None:
    document = _task(TWO_WRITE_SQL)
    assert document["script_comments"] == ["任务：门店日销汇总（合成示例）"]
    lineage = document["statement_lineage"]
    assert lineage["stmt:002"]["statement_comments"] == [
        "任务：门店日销汇总（合成示例）"
    ]
    assert lineage["stmt:003"]["statement_comments"] == ["第二步：只写营业中的门店"]


def test_a_repeat_of_the_header_on_the_first_write_is_published_once() -> None:
    sql = (
        "-- 任务：门店日销汇总（合成示例）\n"
        "SET spark.sql.shuffle.partitions=200;\n"
        "-- 任务：门店日销汇总（合成示例）\n"
        "INSERT INTO mart.store_daily SELECT s.store_id AS store_id FROM ods.store_event s\n"
    )
    assert _statement(sql)["statement_comments"] == [
        "任务：门店日销汇总（合成示例）"
    ]


def test_a_script_without_a_preamble_publishes_no_script_comments() -> None:
    document = _task(COMMENTED_SQL, schema=SCHEMA)
    assert document["script_comments"] == []
    assert document["statement_lineage"]["stmt:001"]["statement_comments"] == [
        "任务：每日客户画像",
        "口径：仅统计活跃客户",
    ]


def test_stripping_removes_the_script_header_everywhere() -> None:
    assert _statement(strip_comments=True)["statement_comments"] == []
    document = _task(strip_comments=True)
    assert document["script_comments"] == []
    assert document["statement_lineage"]["stmt:003"]["statement_comments"] == []
    assert "门店日销汇总" not in json.dumps(document, ensure_ascii=False)


def test_a_contact_shape_in_the_script_header_is_masked_like_any_other_comment() -> None:
    sql = (
        "-- 口径问题联系 demo_owner@example.com（合成地址）\n"
        "SET spark.sql.shuffle.partitions=200;\n"
        "INSERT INTO mart.store_daily SELECT s.store_id AS store_id FROM ods.store_event s\n"
    )
    masked = ["口径问题联系 <email>（合成地址）"]
    assert _statement(sql)["statement_comments"] == masked
    document = _task(sql)
    assert document["script_comments"] == masked
    assert "example.com" not in json.dumps(document, ensure_ascii=False)


def test_the_first_write_may_be_a_ctas_and_the_header_still_reaches_it() -> None:
    sql = (
        "-- 任务：门店快照（合成示例）\n"
        "SET spark.sql.adaptive.enabled=true;\n"
        "CREATE TABLE mart.store_snapshot AS\n"
        "SELECT s.store_id AS store_id FROM ods.store_event s\n"
    )
    assert _statement(sql)["statement_comments"] == ["任务：门店快照（合成示例）"]
    assert _task(sql)["script_comments"] == ["任务：门店快照（合成示例）"]


def test_the_boundary_is_the_first_write_not_the_first_modelled_statement() -> None:
    """A row mutation before the first write is part of the preamble too.

    The task document models a leading DELETE as a state transition, but it carries no
    comments key, and the statement document records it as skipped -- so a comment written
    above it reached no artifact either way. Publishing it as the script header is the
    documented boundary ("everything before the first write"), and it keeps the two
    contracts saying the same thing about the same script. The cost is real and bounded:
    a note that was written about the DELETE is published as the script's opening block.
    """
    sql = (
        "-- 清理昨天的分区（合成示例）\n"
        "DELETE FROM mart.store_daily WHERE dt = '20260101';\n"
        "INSERT INTO mart.store_daily SELECT s.store_id AS store_id FROM ods.store_event s\n"
    )
    assert _task(sql)["script_comments"] == ["清理昨天的分区（合成示例）"]
    assert _statement(sql)["statement_comments"] == ["清理昨天的分区（合成示例）"]
