"""Check 9 doubts ``snapshot`` only over a day-level pull bounded by the batch.

A table rebuilt whole each batch (``INSERT OVERWRITE ... PARTITION (dt = <batch>)``) may
still filter its input by a business date: keep history from a fixed year on, compare
this year with last, take the batch's month. None of these pulls a day's new rows, yet
each was a ``window`` -- every shape the bound recogniser did not know -- and check 9 told
the writer to confirm the table was not incremental. Writers flipped a correct
``snapshot`` to ``incremental`` to silence it.

A window now has to refer to the batch -- the input's partition value, a run parameter,
or the current date -- at day level. A bound on a fixed literal is a ``cutoff``; a year,
quarter or month of the batch is a ``period``; an equality with a day a rule computes (a
CASE over the batch, the latest value a subquery finds) picks one snapshot of the input,
a ``snapshot_pick``; none of them warns. A condition on the input's partition column is
a partition read, not a business-date filter. All names are synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.semantics.checks_context import check_time
from scope_lineage.semantics.packet_facts import input_time_facts

TABLE = "demo_dwd.dwd_order_df"
COLUMNS = [
    {"name": "order_time", "type": "string", "partition": False},
    {"name": "partition_date", "type": "string", "partition": False},
    {"name": "dt", "type": "string", "partition": True},
]


def _rule(expression: str, partition: bool = False, column: str = "") -> dict:
    column = column or ("dt" if partition else "order_time")
    return {
        "kind": "filter", "partition_filter": partition, "tables": [TABLE],
        "expression": expression, "statement_id": "stmt:001", "id": "p1",
        "columns": [f"{TABLE}.{column}"],
    }


def _shape(expression: str, partition: str = "`o`.`dt` = '20261018'", column: str = "") -> str:
    facts = input_time_facts(
        TABLE, [_rule(partition, partition=True), _rule(expression, column=column)], COLUMNS
    )
    [date_filter] = facts["date_filters"]
    return date_filter["shape"]


@pytest.mark.parametrize("expression", [
    "SUBSTRING(`o`.`order_time`, 1, 4) >= '2025'",
    "`o`.`order_time` >= '2024-01-01'",
    "MONTH(`o`.`order_time`) BETWEEN 7 AND 9",
])
def test_a_bound_on_a_fixed_literal_is_a_cutoff(expression: str) -> None:
    assert _shape(expression) == "cutoff"


@pytest.mark.parametrize("expression", [
    "SUBSTRING(`o`.`order_time`, 1, 4) = SUBSTRING('20261018', 1, 4)",
    "YEAR(`o`.`order_time`) = YEAR(CURRENT_DATE)",
    "DATE_FORMAT(`o`.`order_time`, 'yyyyMM') = SUBSTRING('${bizdate}', 1, 6)",
    "SUBSTRING(`o`.`order_time`, 1, 7) = '2026-10'",
    "`o`.`order_time` >= CAST(SUBSTRING('20261018', 5, 2) AS INT)",
])
def test_a_year_quarter_or_month_of_the_batch_is_a_period(expression: str) -> None:
    assert _shape(expression) == "period"


@pytest.mark.parametrize(("expression", "partition"), [
    ("`o`.`order_time` >= '20261018'", "`o`.`dt` = '20261018'"),
    ("TO_DATE(`o`.`order_time`) = '2026-10-18'", "`o`.`dt` = '20261018'"),
    ("SUBSTRING(`o`.`open_date`, 1, 10) >= '${bizdate}'", "`o`.`dt` = '${bizdate}'"),
    ("`o`.`order_time` >= DATE_SUB(CURRENT_DATE, 1)", "`o`.`dt` = '20261018'"),
])
def test_a_day_level_bound_on_the_batch_is_a_window(expression: str, partition: str) -> None:
    assert _shape(expression, partition) == "window"


@pytest.mark.parametrize("expression", [
    "`o`.`partition_date` = (CASE WHEN DAYOFWEEK('2026-10-18') = 5 "
    "THEN DATE_ADD('2026-10-18', 1) ELSE '2026-10-18' END)",
    "`o`.`partition_date` = (SELECT MAX(`x`.`partition_date`) AS `_col_0` FROM `demo`.`x` AS `x`)",
])
def test_an_equality_with_a_computed_day_picks_a_snapshot(expression: str) -> None:
    assert _shape(expression, column="partition_date") == "snapshot_pick"


@pytest.mark.parametrize("expression", [
    "SUBSTRING(`o`.`order_time`, 1, 10) <= CASE WHEN DAYOFWEEK(TO_DATE('2026-10-18')) < 6 "
    "THEN DATE_ADD('2026-10-18', -1) ELSE '2026-10-18' END",
    "`o`.`order_time` < DATE_ADD('2026-10-18', 1)",
    "DATE_ADD('2026-10-18', 1) > `o`.`order_time`",
    "SUBSTRING(`o`.`order_time`, 1, 4) < SUBSTRING('20261018', 1, 4)",
    "SUBSTRING(`o`.`order_time`, 6, 2) < SUBSTRING('20261018', 5, 2)",
])
def test_an_upper_bound_on_a_computed_day_is_an_upper_bound(expression: str) -> None:
    assert _shape(expression) == "upper_bound"


def test_a_condition_on_the_partition_column_is_no_date_filter() -> None:
    facts = input_time_facts(TABLE, [_rule(
        "`o`.`id` IN (SELECT `o`.`id` FROM `demo`.`o` AS `o` WHERE `o`.`dt` = '20261018')",
        column="dt",
    )], COLUMNS)

    assert facts["date_filters"] == []


def _packet(*shapes: str) -> dict:
    filters = [{"column": "order_time", "expression": f"f{i}", "shape": shape}
               for i, shape in enumerate(shapes)]
    return {"inputs": [{"table": TABLE, "full_snapshot": True, "date_filters": filters}]}


def _snapshot() -> dict:
    return {"summary": {"refresh": {"time": "snapshot", "how_to_read": ""}, "watch": []}}


def test_a_snapshot_over_cutoffs_and_periods_passes() -> None:
    (result,) = check_time(_snapshot(), _packet("cutoff", "period", "snapshot_pick"))

    assert result["status"] == "pass"


def test_the_warning_says_a_window_is_not_proof_of_an_increment() -> None:
    (result,) = check_time(_snapshot(), _packet("window"))

    assert result["status"] == "warn"
    assert "按批次日" in result["message"]
    assert "不要只为消除这条提示改成 incremental" in result["message"]
