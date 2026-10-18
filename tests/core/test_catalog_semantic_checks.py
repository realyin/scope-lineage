"""Semantic completeness: the warnings that name what a catalog leaves out, and the density
counts that measure how much meaning it carries.

Each warning fixture is the demo catalog with one thing removed or added; the demo itself
raises none of them, so each test names exactly the warning it is about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage.catalog import load_catalog, render_summary, validate_catalog

from .catalog_demo import DEMO, copy_demo, item, mutate, rules, write_file

STATUS_HIS = "demo_dwd.dwd_lending_loan_status_his"
SEMANTIC = {
    "state_attribute_without_states",
    "measure_without_unit",
    "zipper_without_validity",
    "participation_without_event",
    "generalization_cycle",
    "relation_without_definition",
}


def _validate(root: Path):
    return validate_catalog(load_catalog(root))


def _warnings(root: Path, rule: str) -> list:
    report = _validate(root)
    assert report.errors == []
    return [w for w in report.warnings if w.rule == rule]


def _loan(data: dict) -> dict:
    return item(data["concepts"], "concept:loan")


def _relation(**fields) -> dict:
    relation = {
        "id": "rel:extra", "kind": "association", "from": "concept:customer",
        "to": "concept:loan", "name": "links", "cardinality": {"from": "1", "to": "0..*"},
        "definition": "a definition",
    }
    relation.update(fields)
    return relation


def _add_relations(root: Path, *relations: dict) -> None:
    mutate(root, "relations.yaml", lambda d: d["relations"].extend(relations))


def test_the_demo_raises_no_semantic_warning() -> None:
    assert not SEMANTIC & set(rules(_validate(DEMO).warnings))


def test_a_state_attribute_with_a_code_set_and_no_states(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "concepts/lending.yaml", lambda d: _loan(d).pop("states"))

    [warning] = _warnings(root, "state_attribute_without_states")

    assert warning.at == "concept:loan"
    assert "attr:loan.loan_status" in warning.message
    assert warning.file == "concepts/lending.yaml"


def test_a_state_attribute_without_a_code_set_is_not_flagged(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)

    def change(data: dict) -> None:
        loan = _loan(data)
        loan.pop("states")
        item(loan["attributes"], "attr:loan.loan_status").pop("code_set")

    mutate(root, "concepts/lending.yaml", change)

    assert _warnings(root, "state_attribute_without_states") == []


def test_a_measure_without_a_unit(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "concepts/lending.yaml",
           lambda d: item(_loan(d)["attributes"], "attr:loan.principal").pop("unit"))

    [warning] = _warnings(root, "measure_without_unit")

    assert warning.at == "attr:loan.principal"


def test_a_zipper_table_needs_both_validity_columns(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "mapping/lending.yaml", lambda d: item(
        item(d["representations"], "table", STATUS_HIS)["bindings"], "column", "end_date"
    ).pop("time_role"))

    [warning] = _warnings(root, "zipper_without_validity")

    assert warning.at == STATUS_HIS
    assert "valid_to" in warning.message
    assert "valid_from" not in warning.message


def test_a_participation_relation_between_two_non_events(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    _add_relations(
        root,
        _relation(id="rel:non_event", kind="participation"),
        _relation(id="rel:with_event", kind="participation", to="concept:repayment"),
    )

    assert [w.at for w in _warnings(root, "participation_without_event")] == ["rel:non_event"]


def test_a_generalization_cycle_is_named_once(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    _add_relations(
        root,
        _relation(id="rel:loan_is_a_installment_loan", kind="generalization",
                  **{"from": "concept:loan", "to": "concept:installment_loan"}),
        _relation(id="rel:customer_is_a_customer", kind="generalization",
                  **{"from": "concept:customer", "to": "concept:customer"}),
    )

    warnings = _warnings(root, "generalization_cycle")

    assert [w.at for w in warnings] == ["concept:customer", "concept:installment_loan"]
    assert "concept:installment_loan -> concept:loan -> concept:installment_loan" in warnings[1].message


def test_a_relation_without_a_definition(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    _add_relations(root, _relation(definition="  "), _relation(id="rel:other", definition=None))
    mutate(root, "relations.yaml", lambda d: item(d["relations"], "rel:other").pop("definition"))

    assert [w.at for w in _warnings(root, "relation_without_definition")] == ["rel:extra", "rel:other"]


# --- D7: density ----------------------------------------------------------------------


def test_the_density_counts_what_the_catalog_carries() -> None:
    density = _validate(DEMO).counts["density"]

    assert density["attribute_unit"] == {"count": 6, "total": 6, "ratio": 1.0}
    assert density["attribute_derivation"] == {"count": 1, "total": 18, "ratio": 0.06}
    assert density["code_set_values"]["total"] == 4
    assert density["relation_definition"] == {"count": 5, "total": 5, "ratio": 1.0}
    assert density["states"] == 2
    assert density["roles"] == 1
    assert density["metrics"] == 0
    assert density["constraints"] == 7
    assert density["constraints_with_rules"] == 0


def test_density_moves_with_the_catalog(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "constraints.yaml", lambda d: item(d["constraints"], "cons:principal_positive")
           .update(rules=["demo_dwd.t#r1"]))
    write_file(root / "metrics.yaml", {"metrics": [{
        "id": "metric:n", "name": "n", "on": "concept:loan", "aggregation": "count",
    }]})

    density = _validate(root).counts["density"]

    assert density["constraints_with_rules"] == 1
    assert density["metrics"] == 1


def test_a_ratio_over_nothing_is_null(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    for name in ("relations.yaml", "constraints.yaml"):
        (root / name).unlink()

    density = validate_catalog(load_catalog(root)).counts["density"]

    assert density["relation_definition"] == {"count": 0, "total": 0, "ratio": None}


def test_the_summary_shows_density_on_one_line() -> None:
    text = render_summary(_validate(DEMO))

    [line] = [line for line in text.splitlines() if line.startswith("  density:")]
    assert "unit 6/6" in line
    assert "derivation 1/18" in line
    assert "states=2" in line
    assert "constraints_with_rules=0" in line
    assert "metrics=0" in text.splitlines()[1]


@pytest.mark.parametrize("rule", sorted(SEMANTIC))
def test_every_semantic_warning_is_documented(rule: str) -> None:
    docs = Path(__file__).resolve().parents[2] / "docs"
    for language in ("en", "zh-CN"):
        assert rule in (docs / language / "ontology-catalog.md").read_text(encoding="utf-8"), language
