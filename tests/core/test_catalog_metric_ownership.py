"""6.3-a: a metric's attributes belong to what it is on; a grain names a bound identifier.

The documentation says a metric's dimensions are "attributes of ``on``, or concepts linked
to ``on``", and (owner decision D3) its ``measure`` is an attribute of ``on`` or of a
concept linked to it. ``_metric`` checked only that each was an attribute, so a metric on
a channel could measure a fee waiver's amount and break down by a customer's gender.

A representation's grain identifier may come from another concept (a summary table keyed
by loan number and period), so ownership is not enforced there; but an identifier no
column of the table binds is worth a warning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage.catalog import load_catalog, validate_catalog

from .catalog_demo import copy_demo, item, mutate, rules, write_file


def _metric(**extra) -> dict:
    metric = {"id": "metric:probe", "name": "probe", "on": "concept:loan", "aggregation": "sum"}
    metric.update(extra)
    return metric


def _report(tmp_path: Path, metric: dict):
    root = copy_demo(tmp_path)
    write_file(root / "metrics.yaml", {"metrics": [metric]})
    return validate_catalog(load_catalog(root))


def test_attributes_of_an_unrelated_concept_are_errors(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _metric(
            on="concept:channel",
            measure="attr:fee_waiver.amount",
            dimensions=["attr:customer.gender"],
        ),
    )
    assert sorted(rules(report.errors)) == ["metric_dimension", "metric_measure"]


@pytest.mark.parametrize(
    "change",
    [
        # the concept's own attributes
        {"measure": "attr:loan.principal", "dimensions": ["attr:loan.loan_status"]},
        # an attribute of a concept a relation links to `on` (borrower -> loan)
        {"dimensions": ["attr:borrower.credit_limit"]},
        # a role linked to `on` carries its player's attributes, as its tables do
        {"dimensions": ["attr:customer.gender"]},
        # an event's participants are linked to it
        {"on": "concept:disbursement", "measure": "attr:disbursement.amount",
         "dimensions": ["attr:loan.loan_status"]},
        # a measure taken from a linked concept
        {"on": "concept:disbursement", "measure": "attr:loan.principal"},
    ],
)
def test_attributes_of_on_or_of_a_linked_concept_are_accepted(
    tmp_path: Path, change: dict
) -> None:
    assert _report(tmp_path, _metric(**change)).errors == []


def test_a_concept_dimension_is_still_checked_as_before(tmp_path: Path) -> None:
    """Sentinel: the concept branch of the rule is unchanged."""
    report = _report(tmp_path, _metric(dimensions=["concept:channel"]))
    assert rules(report.errors) == ["metric_dimension"]


def test_a_grain_identifier_no_column_binds_is_a_warning(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)

    def change(data: dict) -> None:
        rep = item(data["representations"], "table", "demo_dwd.dwd_lending_loan_df")
        rep["grain"]["identifiers"] = ["id:repayment_txn_no"]

    mutate(root, "mapping/lending.yaml", change)
    report = validate_catalog(load_catalog(root))
    assert report.errors == []
    found = [w for w in report.warnings if w.rule == "grain_identifier_unbound"]
    assert [w.at for w in found] == ["demo_dwd.dwd_lending_loan_df"]
    assert "id:repayment_txn_no" in found[0].message


def test_the_demo_grains_are_all_bound(tmp_path: Path) -> None:
    """Sentinel: a grain over a bound identifier (own or foreign) warns about nothing."""
    report = validate_catalog(load_catalog(copy_demo(tmp_path)))
    assert "grain_identifier_unbound" not in rules(report.warnings)
