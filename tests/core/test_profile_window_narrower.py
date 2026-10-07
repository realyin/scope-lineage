"""A window grouped on fewer columns than the batch key of the rows it reads (M4).

``lead(d) OVER (PARTITION BY k ORDER BY d)`` over rows another statement writes one per
``(k, env, d)`` lines up two ``env`` values of one ``k`` in one chain: each row may take
its neighbour from the other ``env``. The profile cannot know whether that is meant, so
it says the structure -- the writer's batch key, read as what tells the input rows
apart, and the columns of it the window neither groups nor orders by -- as a ``warn``
finding ``window_partition_narrower``. The key comes from, in order: the window input's
own dedup inside the statement, another statement of the same task writing the table,
and a table card's ``produced_by[].batch_write_keys``.

Left out, so the finding does not fire on what is meant: a ranking window kept to
``= 1`` (narrowing is a dedup's purpose), a PARTITION BY / ORDER BY item that is an
expression rather than a bare column, and the window's own statement as the writer.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {
    "dw.m": ["k", "env", "v", "note", "dt"],
    "dw.ver": ["k", "env", "d", "e"],
    "ods.s": ["k", "sk", "env", "v", "ts", "dt"],
    "ods.v": ["k", "env", "d", "ts"],
}

KIND = "window_partition_narrower"

WRITER = (
    "MERGE INTO dw.ver tgt USING (SELECT k, env, d, NULL AS e FROM (SELECT k, env, d,"
    " row_number() OVER (PARTITION BY k, env, d ORDER BY ts DESC) rn FROM ods.v) a"
    " WHERE a.rn = 1) src ON tgt.k = src.k AND tgt.d = src.d WHEN NOT MATCHED THEN INSERT *;\n"
)


def _chain(partition: str) -> str:
    return (
        "MERGE INTO dw.ver tgt USING (SELECT a.*, lead(d, 1, '9999') OVER"
        f" (PARTITION BY {partition} ORDER BY d) AS nd FROM (SELECT * FROM dw.ver) a) src"
        " ON tgt.k = src.k AND tgt.d = src.d AND tgt.env = src.env"
        " WHEN MATCHED THEN UPDATE SET tgt.e = src.nd;\n"
    )


def _task(script: str, task: str = "v", table_cards=None) -> dict:
    document = to_task_lineage_dict(parse_task_lineage(script, task, schema=SCHEMA))
    return build_semantic_profile(document, table_cards=table_cards)


def _findings(profile: dict) -> list[tuple[str, dict]]:
    statements = profile.get("statements") or [profile]
    return [
        (statement.get("statement_id"), finding)
        for statement in statements
        for finding in statement["confidence"]["findings"]
        if finding["kind"] == KIND
    ]


def test_a_window_narrower_than_a_sibling_writer_s_batch_key_is_a_finding():
    found = _findings(_task(WRITER + _chain("k")))
    assert len(found) == 1
    statement_id, finding = found[0]
    assert statement_id == "stmt:002"
    assert finding["severity"] == "warn"
    assert "stmt:001 本批写入键是 k、env、d（推断为输入行的区分键）" in finding["text"]
    assert finding["text"].endswith("其中 env 不在窗口分组与排序里")
    # The window's own logic block, so a packet can hang the lead on the window's rule.
    assert len(finding["evidence"]) == 1 and ":window:" in finding["evidence"][0]


def test_a_window_grouped_on_the_whole_key_is_not():
    assert _findings(_task(WRITER + _chain("k, env"))) == []


def test_a_row_number_kept_to_one_in_where_is_a_dedup_not_a_narrow_window():
    script = WRITER + (
        "INSERT OVERWRITE TABLE dw.m SELECT k, env, '' v, '' note, d FROM (SELECT k, env, d,"
        " row_number() OVER (PARTITION BY k ORDER BY d DESC) rn FROM dw.ver) x WHERE x.rn = 1;\n"
    )
    assert _findings(_task(script)) == []


def test_a_row_number_kept_to_one_in_a_join_on_is_a_dedup_too():
    script = WRITER + (
        "INSERT OVERWRITE TABLE dw.m SELECT s.k, s.env, s.v, '' note, s.dt FROM ods.s s"
        " LEFT JOIN (SELECT k, d, row_number() OVER (PARTITION BY k ORDER BY d DESC) rn"
        " FROM dw.ver) x ON s.k = x.k AND x.rn = 1;\n"
    )
    assert _findings(_task(script)) == []


def test_a_partition_item_that_is_an_expression_is_not_compared():
    assert _findings(_task(WRITER + _chain("upper(k)"))) == []


def test_the_window_s_own_statement_is_not_its_writer():
    assert _findings(_task(_chain("k"))) == []


def test_the_window_input_s_own_grouping_is_the_first_source():
    found = _findings(
        _task(
            "INSERT OVERWRITE TABLE dw.ver SELECT k, env, d, lead(d, 1, '9999') OVER"
            " (PARTITION BY k ORDER BY d) AS e FROM (SELECT k, env, d FROM ods.v"
            " GROUP BY k, env, d) g;\n"
        )
    )
    assert len(found) == 1
    assert found[0][1]["text"].endswith("其中 env 不在窗口分组与排序里")


def test_a_window_grouped_on_the_whole_input_grouping_is_not():
    found = _findings(
        _task(
            "INSERT OVERWRITE TABLE dw.ver SELECT k, env, d, lead(d, 1, '9999') OVER"
            " (PARTITION BY k, env ORDER BY d) AS e FROM (SELECT k, env, d FROM ods.v"
            " GROUP BY k, env, d) g;\n"
        )
    )
    assert found == []


def test_a_writer_in_another_task_is_read_off_its_table_card():
    writer = _task(WRITER, task="w")
    cards = build_table_cards([writer])
    (card,) = [item for item in cards["tables"] if item["table"] == "dw.ver"]
    assert card["produced_by"][0]["batch_write_keys"] == ["k", "env", "d"]

    reader = _task(_chain("k"), task="r", table_cards=cards)
    (found,) = _findings(reader)
    assert "w / stmt:001 本批写入键是 k、env、d" in found[1]["text"]
    assert found[1]["text"].endswith("其中 env 不在窗口分组与排序里")


def test_a_bare_statement_reads_the_card_too():
    cards = build_table_cards([_task(WRITER, task="w")])
    document = to_lineage_dict(parse_scope_lineage(_chain("k").rstrip(";\n"), "r", schema=SCHEMA))
    assert len(_findings(build_semantic_profile(document, table_cards=cards))) == 1
