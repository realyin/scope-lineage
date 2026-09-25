"""``validate_catalog``: structure, references and warnings, one broken fixture per rule.

Each referential case is the demo catalog with exactly one value changed, and asserts that
exactly that rule fires -- a check that also trips a neighbouring rule is reported as a
different failure than one that fires on the wrong object.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage.catalog import load_catalog, validate_catalog

from .catalog_demo import DEMO, copy_demo, item, mutate, read_file, rules


def _validate(root: Path):
    return validate_catalog(load_catalog(root))


def _concept(data: dict, concept_id: str) -> dict:
    return item(data["concepts"], concept_id)


def _rep(data: dict, table: str) -> dict:
    return item(data["representations"], "table", table)


def _binding(data: dict, table: str, column: str) -> dict:
    return item(_rep(data, table)["bindings"], "column", column)


CUSTOMER_INFO = "demo_dwd.dwd_party_customer_info_df"
LOAN_DF = "demo_dwd.dwd_lending_loan_df"


def test_the_demo_catalog_is_valid() -> None:
    report = _validate(DEMO)

    assert report.errors == []
    assert report.ok
    assert rules(report.warnings) == ["drafted_ratio", "unmapped_binding"]
    assert report.counts["concepts"] == 10
    assert report.counts["concepts_by_kind"] == {"entity": 5, "event": 4, "role": 1}
    assert report.counts["bindings"] > report.counts["representations"]


# --- structure -------------------------------------------------------------------------


SCHEMA_CASES = {
    "unknown concept kind": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:customer").update(kind="thing"),
    ),
    "missing required name": (
        "domains.yaml",
        lambda d: d["domains"][0].pop("name"),
    ),
    "misspelt key": (
        "relations.yaml",
        lambda d: d["relations"][0].update(inverse="is held by"),
    ),
    "wrong manifest format": (
        "catalog.yaml",
        lambda d: d.update(doc_format="catalog-yaml/2"),
    ),
    "entity without a primary identifier": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:channel").pop("primary_identifier"),
    ),
    "participants on an entity": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:channel").update(participants=[]),
    ),
    "attribute binding without ref": (
        "mapping/party.yaml",
        lambda d: _binding(d, CUSTOMER_INFO, "gender_cd").pop("ref"),
    ),
    "boolean code value": (
        "code_sets.yaml",
        lambda d: d["code_sets"][0]["values"][0].update(value=False),
    ),
    "bad status": (
        "terms.yaml",
        lambda d: d["terms"][0].update(status="approved"),
    ),
    "top-level list key missing": (
        "constraints.yaml",
        lambda d: d.update(rules=d.pop("constraints")),
    ),
}


@pytest.mark.parametrize("case", sorted(SCHEMA_CASES))
def test_structure_errors_name_the_file_and_the_path(tmp_path: Path, case: str) -> None:
    relative, change = SCHEMA_CASES[case]
    root = copy_demo(tmp_path)
    mutate(root, relative, change)

    report = _validate(root)

    assert rules(report.errors) == ["schema"]
    assert {error.file for error in report.errors} == {relative}
    assert not report.ok


def test_structure_errors_hold_back_the_reference_checks(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "domains.yaml", lambda d: d["domains"][0].pop("name"))
    # A dangling reference that the reference stage would report on its own.
    mutate(root, "terms.yaml", lambda d: d["terms"][0].update(refers_to="concept:ghost"))

    report = _validate(root)

    assert rules(report.errors) == ["schema"]
    assert report.references_checked is False


# --- ids -------------------------------------------------------------------------------


def _duplicate_domain(data: dict) -> None:
    data["domains"].append(dict(data["domains"][0]))


def _loan_again_in_party(data: dict) -> None:
    """``concepts/lending.yaml`` sorts first, so its concept:loan is the one kept."""
    lending = read_file(DEMO / "concepts" / "lending.yaml")
    data["concepts"].append(_concept(lending, "concept:loan"))


ID_CASES = {
    "duplicate_id: same file": ("duplicate_id", "domains.yaml", _duplicate_domain),
    "duplicate_id: across files": (
        "duplicate_id",
        "concepts/party.yaml",
        _loan_again_in_party,
    ),
    "id_prefix: domain spelt as concept": (
        "id_prefix",
        "domains.yaml",
        lambda d: d["domains"].append(
            {"id": "concept:ops", "name": "运营", "description": "ops"}
        ),
    ),
    "id_prefix: attribute under another concept": (
        "id_prefix",
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:channel")["attributes"][0].update(
            id="attr:customer.channel_name"
        ),
    ),
}


# --- references ------------------------------------------------------------------------


def _state_on_foreign_attribute(data: dict) -> None:
    _concept(data, "concept:loan")["states"]["attribute"] = "attr:customer.gender"


def _transition_by_entity(data: dict) -> None:
    _concept(data, "concept:loan")["states"]["transitions"][0]["event"] = "concept:loan"


def _transition_from_unknown_state(data: dict) -> None:
    _concept(data, "concept:loan")["states"]["transitions"][0]["from"] = "lost"


def _twice_the_same_role_name(data: dict) -> None:
    participants = _concept(data, "concept:repayment")["participants"]
    participants[0]["role_name"] = participants[1]["role_name"]


def _duplicate_table(data: dict) -> None:
    data["representations"].append(dict(_rep(data, LOAN_DF)))


def _duplicate_column(data: dict) -> None:
    bindings = _rep(data, LOAN_DF)["bindings"]
    bindings.append(dict(bindings[0]))


REFERENCE_CASES = {
    "duplicate_code_value": (
        "code_sets.yaml",
        lambda d: item(d["code_sets"], "code:gender")["values"].append(
            {"value": "F", "meaning": "female again"}
        ),
    ),
    "identifier_identifies: a role": (
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:customer_id").update(
            identifies="concept:borrower"
        ),
    ),
    "identifier_identifies: unknown": (
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:loan_no").update(identifies="concept:ghost"),
    ),
    "identifier_scope": (
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:app_account_id").update(
            scope={"per": ["concept:nowhere"]}
        ),
    ),
    "identifier_state: unknown value": (
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:verified_customer_no")["arises_when"].update(
            state="concept:customer#frozen"
        ),
    ),
    "identifier_state: concept without states": (
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:verified_customer_no")["arises_when"].update(
            state="concept:channel#verified"
        ),
    ),
    "identifier_maps_to": (
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:customer_id")["maps_to"][0].update(
            identifier="id:ghost"
        ),
    ),
    "concept_domain": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:customer").update(domain="domain:nowhere"),
    ),
    "concept_identifier": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:channel")["identifiers"].append("id:ghost"),
    ),
    "primary_identifier": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:customer").update(primary_identifier="id:loan_no"),
    ),
    "role_player": (
        "concepts/lending.yaml",
        lambda d: _concept(d, "concept:borrower").update(player="concept:repayment"),
    ),
    "role_context": (
        "concepts/lending.yaml",
        lambda d: _concept(d, "concept:borrower").update(context="concept:loan"),
    ),
    "event_participant": (
        "concepts/lending.yaml",
        lambda d: _concept(d, "concept:repayment")["participants"][0].update(
            concept="concept:disbursement"
        ),
    ),
    "duplicate_role_name": ("concepts/lending.yaml", _twice_the_same_role_name),
    "event_occurred_at": (
        "concepts/lending.yaml",
        lambda d: _concept(d, "concept:repayment").update(occurred_at="attr:loan.principal"),
    ),
    "state_attribute": ("concepts/lending.yaml", _state_on_foreign_attribute),
    "state_event": ("concepts/lending.yaml", _transition_by_entity),
    "state_value": ("concepts/lending.yaml", _transition_from_unknown_state),
    "attribute_code_set": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:customer")["attributes"][0].update(
            code_set="code:nothing"
        ),
    ),
    "relation_endpoint": (
        "relations.yaml",
        lambda d: d["relations"][0].update(to="domain:party"),
    ),
    "constraint_on: unknown": (
        "constraints.yaml",
        lambda d: d["constraints"][0].update(on="attr:loan.ghost"),
    ),
    "constraint_on: a code set": (
        "constraints.yaml",
        lambda d: d["constraints"][0].update(on="code:gender"),
    ),
    "term_refers_to": (
        "terms.yaml",
        lambda d: d["terms"][0].update(refers_to="concept:ghost"),
    ),
    "representation_concept": (
        "mapping/lending.yaml",
        lambda d: _rep(d, LOAN_DF).update(concept="concept:ghost"),
    ),
    "representation_grain": (
        "mapping/lending.yaml",
        lambda d: _rep(d, LOAN_DF)["grain"].update(identifiers=["attr:loan.principal"]),
    ),
    "duplicate_table": ("mapping/lending.yaml", _duplicate_table),
    "duplicate_column": ("mapping/lending.yaml", _duplicate_column),
    "binding_attribute: another concept's": (
        "mapping/party.yaml",
        lambda d: _binding(d, CUSTOMER_INFO, "gender_cd").update(ref="attr:loan.principal"),
    ),
    "binding_attribute: unknown": (
        "mapping/party.yaml",
        lambda d: _binding(d, CUSTOMER_INFO, "gender_cd").update(ref="attr:customer.ghost"),
    ),
    "binding_identifier": (
        "mapping/party.yaml",
        lambda d: _binding(d, CUSTOMER_INFO, "customer_id").update(ref="id:loan_no"),
    ),
    "binding_foreign_identifier": (
        "mapping/lending.yaml",
        lambda d: _binding(d, LOAN_DF, "customer_id").update(ref="id:loan_no"),
    ),
    "binding_foreign_identifier: not an identifier": (
        "mapping/lending.yaml",
        lambda d: _binding(d, LOAN_DF, "customer_id").update(ref="concept:customer"),
    ),
}


def _cases() -> list[tuple[str, str, str, object]]:
    cases = [(name, *spec) for name, spec in ID_CASES.items()]
    for name, (relative, change) in REFERENCE_CASES.items():
        cases.append((name, name.split(":")[0], relative, change))
    return sorted(cases, key=lambda case: case[0])


@pytest.mark.parametrize(
    "name, rule, relative, change", _cases(), ids=[case[0] for case in _cases()]
)
def test_each_reference_rule_fires_alone(
    tmp_path: Path, name: str, rule: str, relative: str, change
) -> None:
    root = copy_demo(tmp_path)
    mutate(root, relative, change)

    report = _validate(root)

    assert rules(report.errors) == [rule], [error.message for error in report.errors]
    assert report.references_checked is True
    assert all(error.message for error in report.errors)


def test_a_role_view_may_bind_its_players_identifier_and_attributes() -> None:
    """``dwd_lending_borrower_df`` binds id:customer_id and attr:customer.gender."""
    report = _validate(DEMO)

    assert not [e for e in report.errors if e.rule.startswith("binding_")]


def test_a_subtype_may_list_its_supertypes_identifier() -> None:
    """``concept:installment_loan`` lists id:loan_no, which identifies concept:loan."""
    assert _validate(DEMO).errors == []


# --- warnings --------------------------------------------------------------------------


WARNING_CASES = {
    "concept_without_definition": (
        "concepts/party.yaml",
        lambda d: _concept(d, "concept:channel").pop("definition"),
    ),
    "relation_without_name": (
        "relations.yaml",
        lambda d: d["relations"][1].pop("name"),
    ),
    "empty_code_set": (
        "code_sets.yaml",
        lambda d: item(d["code_sets"], "code:waiver_type").update(values=[]),
    ),
}


@pytest.mark.parametrize("rule", sorted(WARNING_CASES))
def test_warnings_do_not_fail_the_catalog(tmp_path: Path, rule: str) -> None:
    relative, change = WARNING_CASES[rule]
    root = copy_demo(tmp_path)
    mutate(root, relative, change)

    report = _validate(root)

    assert report.errors == []
    assert rule in rules(report.warnings)


def test_unmapped_bindings_are_named_one_by_one() -> None:
    unmapped = [w for w in _validate(DEMO).warnings if w.rule == "unmapped_binding"]

    assert [w.at for w in unmapped] == ["demo_dwd.dwd_party_customer_ext_df.ext_json"]


def test_the_drafted_ratio_counts_every_object_with_a_status(tmp_path: Path) -> None:
    report = _validate(DEMO)

    drafted = report.counts["status"]["drafted"]
    total = sum(report.counts["status"].values())
    (warning,) = [w for w in report.warnings if w.rule == "drafted_ratio"]
    assert f"{drafted}/{total}" in warning.message


def test_a_fully_confirmed_catalog_has_no_drafted_warning(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    for path in root.rglob("*.y*ml"):
        text = path.read_text(encoding="utf-8").replace("status: drafted", "status: confirmed")
        path.write_text(text, encoding="utf-8")
    mutate(root, "terms.yaml", lambda d: [t.update(status="confirmed") for t in d["terms"]])
    json_file = root / "mapping" / "collection.json"
    json_file.write_text(
        json_file.read_text(encoding="utf-8").replace('"drafted"', '"confirmed"'),
        encoding="utf-8",
    )

    assert "drafted_ratio" not in rules(_validate(root).warnings)


def test_the_report_serialises(tmp_path: Path) -> None:
    payload = _validate(DEMO).to_dict()

    assert payload["doc_format"] == "catalog-report/1"
    assert payload["catalog"] == "demo-lending"
    assert payload["ok"] is True
    assert set(payload) >= {"errors", "warnings", "counts"}
    assert set(payload["warnings"][0]) == {"rule", "file", "at", "message"}


def test_the_file_schemas_share_one_definition_of_the_common_fields() -> None:
    """Nine self-contained schemas (one per file kind, so an editor can use each alone)
    repeat the common fields; this keeps the copies from drifting apart."""
    from scope_lineage.catalog.model import FILE_KINDS
    from scope_lineage.catalog.structure import packaged_schema

    common = ("id", "status", "source", "evidence", "notes")
    shapes = [
        {key: packaged_schema(kind.schema)["definitions"][key] for key in common}
        for kind in FILE_KINDS.values()
    ]
    assert all(shape == shapes[0] for shape in shapes)
