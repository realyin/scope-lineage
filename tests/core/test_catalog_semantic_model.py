"""The catalog's semantic additions: constraints that carry rules and predicates, metrics,
attribute additivity and binding time roles -- each written, checked and built.

Every fixture is the demo catalog with one thing added, so a green demo run proves the
addition broke nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.catalog import (
    build_ontology,
    check_fragment,
    load_catalog,
    merge_fragments,
    ontology_findings,
    validate_catalog,
)

from .catalog_demo import DEMO, copy_demo, item, mutate, rules, write_file

LOAN_DF = "demo_dwd.dwd_lending_loan_df"
STATUS_HIS = "demo_dwd.dwd_lending_loan_status_his"


def _validate(root: Path):
    return validate_catalog(load_catalog(root))


def _constraint(data: dict, constraint_id: str) -> dict:
    return item(data["constraints"], constraint_id)


def _metric(**extra) -> dict:
    metric = {
        "id": "metric:principal_total",
        "name": "principal total",
        "on": "concept:loan",
        "aggregation": "sum",
    }
    metric.update(extra)
    return metric


def _with_metrics(tmp_path: Path, *metrics: dict) -> Path:
    root = copy_demo(tmp_path)
    write_file(root / "metrics.yaml", {"metrics": list(metrics)})
    return root


# --- D2: constraints carry the rules they come from, and a structured predicate --------


def test_a_constraint_may_name_the_rules_it_carries_and_a_predicate(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)

    def change(data: dict) -> None:
        constraint = _constraint(data, "cons:principal_positive")
        constraint["rules"] = ["demo_dwd.dwd_lending_loan_df#r1", "demo_ods.src_t#r12"]
        constraint["predicate"] = {"column": "principal_amt", "op": ">", "value": 0}

    mutate(root, "constraints.yaml", change)

    report = _validate(root)
    assert report.errors == []
    built = item(build_ontology(load_catalog(root))["constraints"], "cons:principal_positive")
    assert built["rules"] == ["demo_dwd.dwd_lending_loan_df#r1", "demo_ods.src_t#r12"]
    assert built["predicate"] == {"column": "principal_amt", "op": ">", "value": 0}


@pytest.mark.parametrize(
    "rule_ref",
    ["dwd_lending_loan_df#r1", "demo_dwd.t#1", "demo_dwd.t#rule1", "demo.dwd.t#r1", "demo_dwd.t"],
)
def test_a_rule_reference_must_be_table_hash_rule_id(tmp_path: Path, rule_ref: str) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "constraints.yaml",
           lambda d: _constraint(d, "cons:principal_positive").update(rules=[rule_ref]))

    [error] = _validate(root).errors

    assert error.rule == "schema"
    assert error.at == "constraints[1].rules[0]"


@pytest.mark.parametrize(
    "predicate",
    [
        {"column": "c", "op": "between", "value": 1},
        {"column": "c", "op": "="},
        {"column": "c", "op": "in", "value": "a"},
        {"column": "c", "op": "is_null", "value": 1},
        {"op": "=", "value": 1},
        {"column": "c", "op": "=", "value": 1, "extra": True},
    ],
)
def test_a_malformed_predicate_is_a_schema_error(tmp_path: Path, predicate: dict) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "constraints.yaml",
           lambda d: _constraint(d, "cons:principal_positive").update(predicate=predicate))

    assert rules(_validate(root).errors) == ["schema"]


@pytest.mark.parametrize(
    "predicate",
    [
        {"column": "c", "op": "not_null"},
        {"column": "c", "op": "in", "value": ["a", "b"]},
        {"column": "c", "op": "like", "value": "x%"},
        {"column": "c", "op": "!=", "value": "a"},
    ],
)
def test_a_well_formed_predicate_passes(tmp_path: Path, predicate: dict) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "constraints.yaml",
           lambda d: _constraint(d, "cons:principal_positive").update(predicate=predicate))

    assert _validate(root).errors == []


# --- D3: metrics -----------------------------------------------------------------------


def test_a_metric_file_is_read_checked_counted_and_built(tmp_path: Path) -> None:
    full = _metric(
        definition="Sum of the principal of every loan.",
        measure="attr:loan.principal",
        filter="only loans not settled",
        constraints=["cons:principal_positive"],
        time_window="month to date",
        dimensions=["attr:loan.loan_status"],
        additivity="additive",
        unit="CNY",
        status="confirmed",
        source="owner",
        evidence=["demo_dwd.dwd_lending_loan_df.principal_amt"],
        notes="a note",
    )
    root = _with_metrics(tmp_path, full, _metric(id="metric:loan_count", aggregation="count"))

    report = _validate(root)
    assert report.errors == []
    assert report.counts["metrics"] == 2
    document = build_ontology(load_catalog(root))
    assert ontology_findings(document) == []
    assert document["counts"]["metrics"] == 2
    assert [m["id"] for m in document["metrics"]] == ["metric:loan_count", "metric:principal_total"]
    built = item(document["metrics"], "metric:principal_total")
    assert list(built) == [
        "id", "name", "definition", "on", "measure", "aggregation", "filter", "constraints",
        "time_window", "dimensions", "additivity", "unit", "status", "source", "evidence", "notes",
    ]
    minimal = item(document["metrics"], "metric:loan_count")
    assert minimal == {
        "id": "metric:loan_count", "name": "principal total", "on": "concept:loan",
        "aggregation": "count", "constraints": [], "dimensions": [],
        "status": "drafted", "source": None, "evidence": [],
    }


def test_a_catalog_without_metrics_builds_an_empty_list() -> None:
    document = build_ontology(load_catalog(DEMO))

    assert document["metrics"] == []
    assert document["counts"]["metrics"] == 0
    assert validate_catalog(load_catalog(DEMO)).counts["metrics"] == 0


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"on": "attr:loan.principal"}, "metric_on"),
        ({"on": "concept:nowhere"}, "metric_on"),
        ({"measure": "concept:loan"}, "metric_measure"),
        ({"dimensions": ["attr:loan.loan_status", "attr:nowhere.x"]}, "metric_dimension"),
        ({"constraints": ["cons:nowhere"]}, "metric_constraint"),
        ({"id": "measure:principal_total"}, "id_prefix"),
    ],
)
def test_a_metric_reference_of_the_wrong_kind_is_an_error(
    tmp_path: Path, change: dict, rule: str
) -> None:
    root = _with_metrics(tmp_path, _metric(**change))

    assert rules(_validate(root).errors) == [rule]


@pytest.mark.parametrize(
    "change",
    [{"aggregation": "median"}, {"additivity": "partly"}, {"formula": "x"}, {"on": None}],
)
def test_a_malformed_metric_is_a_schema_error(tmp_path: Path, change: dict) -> None:
    metric = _metric(**change)
    metric = {key: value for key, value in metric.items() if value is not None}
    root = _with_metrics(tmp_path, metric)

    assert rules(_validate(root).errors) == ["schema"]


def test_a_metric_id_shared_with_another_object_is_a_duplicate(tmp_path: Path) -> None:
    root = _with_metrics(tmp_path, _metric(), _metric())

    assert rules(_validate(root).errors) == ["duplicate_id"]


def test_a_fragment_may_carry_metrics_and_the_merge_adds_them(tmp_path: Path) -> None:
    fragment = {"doc_format": "catalog-fragment/1", "group": "g", "metrics": [_metric()]}
    assert check_fragment(fragment, "f.json") == []
    catalog = load_catalog(copy_demo(tmp_path))

    result = merge_fragments(catalog, [("f.json", fragment)])

    assert result.ok
    assert result.added["metric"] == 1
    assert result.changed == {"metrics.yaml"}
    assert [m["id"] for _f, m in catalog.records("metrics")] == ["metric:principal_total"]
    again = merge_fragments(catalog, [("f.json", fragment)])
    assert again.unchanged == 1
    other = dict(fragment, metrics=[_metric(aggregation="avg")])
    assert [c.rule for c in merge_fragments(catalog, [("g.json", other)]).conflicts] == [
        "merge_conflict"
    ]


def test_a_malformed_metric_in_a_fragment_is_reported() -> None:
    fragment = {
        "doc_format": "catalog-fragment/1", "group": "g", "metrics": [_metric(aggregation="mode")],
    }

    [finding] = check_fragment(fragment, "f.json")

    assert finding.at == "metrics[0].aggregation"


# --- D4 / D5: attribute additivity, binding time role -----------------------------------


def test_attribute_additivity_and_binding_time_role_are_carried_into_the_build(
    tmp_path: Path,
) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "concepts/lending.yaml", lambda d: item(
        item(d["concepts"], "concept:loan")["attributes"], "attr:loan.principal"
    ).update(additivity="semi_additive"))

    def roles(data: dict) -> None:
        bindings = item(data["representations"], "table", STATUS_HIS)["bindings"]
        item(bindings, "column", "start_date").update(time_role="valid_from")
        item(bindings, "column", "end_date").update(time_role="valid_to")

    mutate(root, "mapping/lending.yaml", roles)

    assert _validate(root).errors == []
    document = build_ontology(load_catalog(root))
    assert ontology_findings(document) == []
    loan = item(document["concepts"], "concept:loan")
    assert item(loan["attributes"], "attr:loan.principal")["additivity"] == "semi_additive"
    assert "additivity" not in item(loan["attributes"], "attr:loan.loan_status")
    bindings = item(document["representations"], "table", STATUS_HIS)["bindings"]
    assert item(bindings, "column", "start_date")["time_role"] == "valid_from"
    assert item(bindings, "column", "end_date")["time_role"] == "valid_to"
    assert "time_role" not in item(bindings, "column", "loan_no")


def test_an_unknown_additivity_or_time_role_is_a_schema_error(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "concepts/lending.yaml", lambda d: item(
        item(d["concepts"], "concept:loan")["attributes"], "attr:loan.principal"
    ).update(additivity="sometimes"))
    mutate(root, "mapping/lending.yaml", lambda d: item(
        item(d["representations"], "table", STATUS_HIS)["bindings"], "column", "start_date"
    ).update(time_role="start"))

    errors = _validate(root).errors

    assert rules(errors) == ["schema"]
    assert len(errors) == 2


def test_the_fragment_accepts_additivity_and_time_role() -> None:
    fragment = {
        "doc_format": "catalog-fragment/1",
        "group": "g",
        "attributes": {"concept:loan": [{
            "id": "attr:loan.fee", "name": "fee", "definition": "a fee", "category": "measure",
            "type": "decimal(18,2)", "unit": "CNY", "additivity": "additive",
        }]},
        "representations": [{
            "table": "demo_dwd.t", "concept": "concept:loan", "kind": "state_history",
            "grain": {"identifiers": ["id:loan_no"], "source": "declared"},
            "time": "zipper", "table_status": "active",
            "bindings": [{"column": "start_date", "to": "technical", "time_role": "valid_from"}],
        }],
    }

    assert check_fragment(fragment, "f.json") == []


def test_the_ontology_schema_describes_the_additions() -> None:
    from scope_lineage.catalog.structure import packaged_schema

    schema = packaged_schema("ontology-v3")
    assert "metrics" in schema["properties"]
    assert "metric" in schema["definitions"]
    assert "metrics" in schema["properties"]["counts"]["properties"]
    assert json.dumps(schema).count("time_role") >= 1
