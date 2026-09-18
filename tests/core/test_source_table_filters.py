"""mapping.md section 2 lists, per physical source table, the predicates applied to it.

The question the section answers is "I read table A — what did the SQL filter A on?".
The facts already exist in the contract (filter conjuncts, JOIN ON non-key predicates,
DIRECT pass-through columns); the renderer only regroups them by physical table and
never guesses: a predicate on a window/union/expression column of an intermediate
result is listed separately, not attributed to a table.
"""

from __future__ import annotations

import copy

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.mapping_markdown import render_mapping_markdown
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.a": ["id", "dt", "status", "amt"],
    "ods.b": ["id", "dt", "flag", "x"],
    "ods.c": ["id", "dt"],
}

SQL = """INSERT OVERWRITE TABLE mart.t
WITH s AS (
  SELECT id, amt, status, ROW_NUMBER() OVER (PARTITION BY id ORDER BY amt) AS rn
  FROM ods.a
  WHERE dt = '2024-01-01' AND status IN (1, 2)
)
SELECT s.id, b.x
FROM s
JOIN ods.b b ON s.id = b.id AND b.flag = 1
WHERE b.dt = '2024-01-01'
  AND s.amt > b.x
  AND s.status = 1
  AND s.rn = 1
  AND NOT b.id IN (SELECT id FROM ods.c WHERE dt = '2024-01-01')
GROUP BY s.id, b.x
HAVING SUM(b.x) > 0
"""


def _document(sql: str = SQL, schema=SCHEMA) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "case_task", schema=schema))


def _sources_section(rendered: str) -> str:
    start = rendered.index("## 2. 来源表")
    end = rendered.index("## 3. ")
    return rendered[start:end]


def _table_block(section: str, table: str) -> str:
    """The nested bullets under one table's line, up to the next top-level bullet."""
    lines = section.splitlines()
    start = lines.index(f"- {table}")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("- ") or line.startswith("## "):
            break
        block.append(line)
    return "\n".join(block)


def test_where_conjuncts_are_grouped_under_their_physical_table() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    assert "- 过滤条件（WHERE / JOIN ON 中作用于来源表列的谓词，按表归并" in section
    a_block = _table_block(section, "ods.a")
    assert "  - `` `a`.`dt` = '2024-01-01' ``（WHERE @ cte:s）" in a_block
    assert "  - `` `a`.`status` IN (1, 2) ``（WHERE @ cte:s）" in a_block
    b_block = _table_block(section, "ods.b")
    assert "  - `` `b`.`dt` = '2024-01-01' ``（WHERE @ ROOT）" in b_block


def test_join_on_non_key_predicates_are_listed_as_join_on_filters() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    b_block = _table_block(section, "ods.b")
    assert "  - `` `b`.`flag` = 1 ``（JOIN ON @ ROOT）" in b_block
    # the equality key itself is a relation (section 3), never a filter
    assert "`s`.`id` = `b`.`id`" not in section


def test_direct_passthrough_columns_pierce_to_the_physical_table() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    a_block = _table_block(section, "ods.a")
    assert "  - `` `s`.`status` = 1 ``（WHERE @ ROOT；经 cte:s.status 直传）" in a_block


def test_cross_table_conjunct_is_listed_under_every_table_it_touches() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    a_block = _table_block(section, "ods.a")
    b_block = _table_block(section, "ods.b")
    assert "  - `` `s`.`amt` > `b`.`x` ``（WHERE @ ROOT；跨表 ods.b；经 cte:s.amt 直传）" in a_block
    assert "  - `` `s`.`amt` > `b`.`x` ``（WHERE @ ROOT；跨表 ods.a）" in b_block


def test_window_column_predicate_is_not_attributed_to_a_table() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    assert "- 其他过滤（作用于中间结果列，未直传到物理表）：" in section
    assert "  - `` `s`.`rn` = 1 ``（cte:s.rn；WHERE @ ROOT）" in section
    assert "`s`.`rn` = 1" not in _table_block(section, "ods.a")


def test_subquery_internal_columns_stay_with_the_subquery_scope() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    c_block = _table_block(section, "ods.c")
    # the subquery's own WHERE is a filter on ods.c …
    assert "  - `` `c`.`dt` = '2024-01-01' ``（WHERE @ subq:derived_0）" in c_block
    # … but the outer NOT IN predicate filters ods.b, not ods.c
    assert "NOT `b`.`id` IN" not in c_block
    b_block = _table_block(section, "ods.b")
    assert "NOT `b`.`id` IN (SELECT" in b_block
    assert "（WHERE @ ROOT）" in b_block.split("NOT `b`.`id` IN")[1].splitlines()[0]


def test_having_is_not_a_source_table_filter() -> None:
    section = _sources_section(render_mapping_markdown(_document()))
    assert "SUM(`b`.`x`) > 0" not in section
    assert "HAVING 见第 6 节" in section


def test_table_without_predicates_says_so() -> None:
    sql = """INSERT OVERWRITE TABLE mart.t
SELECT a.id, b.x FROM ods.a a JOIN ods.b b ON a.id = b.id WHERE a.dt = '2024-01-01'
"""
    section = _sources_section(render_mapping_markdown(_document(sql)))
    assert "- ods.b：无直接过滤条件" in section
    assert "  - `` `a`.`dt` = '2024-01-01' ``（WHERE @ ROOT）" in _table_block(section, "ods.a")
    assert "其他过滤" not in section


def test_no_predicates_at_all_renders_one_plain_line() -> None:
    sql = "INSERT OVERWRITE TABLE mart.t SELECT id FROM ods.a"
    section = _sources_section(render_mapping_markdown(_document(sql)))
    assert "- 过滤条件：无（WHERE / JOIN ON 中没有作用于来源表列的谓词）" in section
    assert "无直接过滤条件" not in section


def test_identical_predicates_in_one_scope_are_listed_once() -> None:
    sql = """INSERT OVERWRITE TABLE mart.t
SELECT a.id FROM ods.a a WHERE a.dt = '2024-01-01' AND a.dt = '2024-01-01'
"""
    section = _sources_section(render_mapping_markdown(_document(sql)))
    assert section.count("`` `a`.`dt` = '2024-01-01' ``（WHERE @ ROOT）") == 1


def _union_sql(branches: int) -> str:
    branch = "SELECT id FROM ods.a WHERE dt = '2024-01-01' AND status = {n}"
    return "INSERT OVERWRITE TABLE mart.t\n" + "\nUNION ALL\n".join(
        branch.format(n=n) for n in range(1, branches + 1)
    )


def test_same_predicate_across_a_few_scopes_lists_every_scope_on_one_line() -> None:
    section = _sources_section(render_mapping_markdown(_document(_union_sql(3))))
    a_block = _table_block(section, "ods.a")
    assert (
        "  - `` `a`.`dt` = '2024-01-01' ``（WHERE @ union:main:b01、union:main:b02、union:main:b03）"
        in a_block
    )
    assert a_block.count("`a`.`dt` = '2024-01-01'") == 1
    # predicates that differ per branch stay separate
    assert "  - `` `a`.`status` = 1 ``（WHERE @ union:main:b01）" in a_block
    assert "  - `` `a`.`status` = 3 ``（WHERE @ union:main:b03）" in a_block


def test_same_predicate_across_many_scopes_collapses_to_a_count() -> None:
    section = _sources_section(render_mapping_markdown(_document(_union_sql(5))))
    a_block = _table_block(section, "ods.a")
    assert "  - `` `a`.`dt` = '2024-01-01' ``（WHERE @ union:main:b01 等 5 处）" in a_block
    assert a_block.count("`a`.`dt` = '2024-01-01'") == 1


def test_filters_survive_a_document_without_logic_blocks() -> None:
    document = _document()
    stripped = copy.deepcopy(document)
    for scope in stripped["scopes"].values():
        scope.pop("logic_blocks", None)
    section = _sources_section(render_mapping_markdown(stripped))
    assert "- 过滤条件：无（WHERE / JOIN ON 中没有作用于来源表列的谓词）" in section


def test_sources_section_rendering_is_deterministic() -> None:
    document = _document()
    first = render_mapping_markdown(document)
    second = render_mapping_markdown(copy.deepcopy(document))
    assert first == second
