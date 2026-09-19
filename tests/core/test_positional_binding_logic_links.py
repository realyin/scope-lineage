"""An INSERT bound to the target DDL by position must not lend its logic blocks around.

When the SELECT aliases and the DDL order disagree, projection *i*'s alias can be the
bound name of a different projection *j*. Keying anything by the alias therefore reaches
*j*'s facts, and a direct projection ends up carrying a CASE it never wrote.
"""

from __future__ import annotations

import pytest

from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


SQL = """
INSERT OVERWRITE TABLE mart.hourly_gap_summary
SELECT
  t.delta_18 AS delta_18,
  CASE WHEN t.ratio_7 > 0 THEN 0 ELSE t.ratio_7 END AS ratio_7,
  CASE WHEN t.gap_10 > 0 THEN 1 ELSE 0 END AS gap_10
FROM mart.hourly_gap t
"""

SCHEMA = {"mart.hourly_gap": ["gap_10", "delta_18", "ratio_7"]}


def _target_metadata() -> TargetMetadataMap:
    """Target DDL order (gap_10, delta_18, ratio_7) crosses the SELECT alias order."""
    item = TargetTableMetadata(
        table_name="mart.hourly_gap_summary",
        full_table_name="spark_catalog.mart.hourly_gap_summary",
        columns=[
            TargetColumnMetadata(name="gap_10", data_type="bigint", ordinal=0),
            TargetColumnMetadata(name="delta_18", data_type="decimal(18,2)", ordinal=1),
            TargetColumnMetadata(name="ratio_7", data_type="decimal(18,2)", ordinal=2),
        ],
        partition_columns=[],
        ddl=(
            "CREATE TABLE mart.hourly_gap_summary("
            "gap_10 BIGINT, delta_18 DECIMAL(18,2), ratio_7 DECIMAL(18,2))"
        ),
        source_file="synthetic-target-metadata.json",
        structure_source="ddl",
    )
    return TargetMetadataMap({item.table_name: item})


@pytest.fixture(scope="module")
def root_scope():
    result = parse_scope_lineage(
        SQL, "positional_binding_logic_links", schema=SCHEMA, target_metadata=_target_metadata()
    )
    assert result.target_field_binding.get("method") == "ddl_position"
    return result.scopes["ROOT"]


def test_the_binding_crosses_aliases_with_bound_names(root_scope) -> None:
    """The premise of the other tests: alias of i == bound name of j."""
    bound = [(output.name, output.output_ordinal) for output in root_scope.outputs]
    assert bound == [("gap_10", 0), ("delta_18", 1), ("ratio_7", 2)]
    assert [column.parsed_name for column in root_scope.columns] == [
        "delta_18",
        "ratio_7",
        "gap_10",
    ]


def test_a_direct_projection_never_borrows_another_columns_case(root_scope) -> None:
    direct = root_scope.outputs[0]

    assert direct.transform == "DIRECT"
    assert direct.source_logic_blocks == []


def test_each_case_output_carries_only_its_own_block(root_scope) -> None:
    blocks_by_id = {block.logic_block_id: block for block in root_scope.logic_blocks}

    for output in root_scope.outputs[1:]:
        assert len(output.source_logic_blocks) == 1
        block = blocks_by_id[output.source_logic_blocks[0]]
        assert block.output_fields == [output.name]
        assert block.raw_expression == output.expression
