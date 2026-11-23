"""``CatalogState``: the files a server was started with, re-read when they change."""

from __future__ import annotations

import json
import os

import pytest
from service_paths import CUSTOMER

from scope_lineage.cli_catalog_answers import CatalogAnswerError
from scope_lineage_service.state import CatalogState, _directory_signature


def _touch_later(path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))


def test_start_refuses_an_unreadable_ontology(tmp_path) -> None:
    with pytest.raises(CatalogAnswerError) as raised:
        CatalogState(str(tmp_path / "none.json"))
    assert raised.value.exit_code == 2


def test_start_refuses_a_missing_semantics_directory(inputs, tmp_path) -> None:
    with pytest.raises(CatalogAnswerError) as raised:
        CatalogState(str(inputs["ontology"]), semantics=str(tmp_path / "none"))
    assert raised.value.exit_code == 2


def test_the_ontology_is_read_again_when_it_changes(inputs) -> None:
    state = CatalogState(str(inputs["ontology"]))
    before = state.inputs().document
    assert state.inputs().document is before

    document = json.loads(inputs["ontology"].read_text(encoding="utf-8"))
    document["catalog"]["name"] = "changed"
    inputs["ontology"].write_text(json.dumps(document), encoding="utf-8")
    _touch_later(inputs["ontology"])

    assert state.inputs().document["catalog"]["name"] == "changed"


def test_a_semantics_document_added_later_is_seen(inputs) -> None:
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]))
    assert set(state.inputs().semantics) == {CUSTOMER}

    source = json.loads((inputs["semantics"] / f"{CUSTOMER}.json").read_text(encoding="utf-8"))
    source["table"] = "demo_dwd.another_table"
    (inputs["semantics"] / "demo_dwd.another_table.json").write_text(
        json.dumps(source), encoding="utf-8"
    )

    assert set(state.inputs().semantics) == {CUSTOMER, "demo_dwd.another_table"}


def test_the_directory_signature_covers_every_json_file_below_it(inputs) -> None:
    """Each ``*.json`` at any depth (what ``catalog`` reads), and a change to any of them."""
    root = inputs["semantics"]
    (root / "nested" / "deeper").mkdir(parents=True)
    (root / "nested" / "deeper" / "x.json").write_text("{}", encoding="utf-8")
    (root / "nested" / "notes.txt").write_text("not read", encoding="utf-8")
    signature = _directory_signature(root)

    expected = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.json"))
    assert [entry[0] for entry in signature] == expected
    assert _directory_signature(root) == signature
    _touch_later(root / "nested" / "deeper" / "x.json")
    assert _directory_signature(root) != signature


def test_an_ontology_broken_after_start_is_reported_until_it_is_fixed(inputs) -> None:
    state = CatalogState(str(inputs["ontology"]))
    good = inputs["ontology"].read_text(encoding="utf-8")
    inputs["ontology"].write_text("{half", encoding="utf-8")
    _touch_later(inputs["ontology"])

    with pytest.raises(CatalogAnswerError):
        state.inputs()

    inputs["ontology"].write_text(good, encoding="utf-8")
    _touch_later(inputs["ontology"])
    assert state.inputs().document["doc_format"] == "ontology-json/3"


def test_health_names_the_inputs_and_whether_they_load(inputs) -> None:
    state = CatalogState(
        str(inputs["ontology"]), semantics=str(inputs["semantics"]), pending=str(inputs["pending"])
    )
    health = state.health()

    assert health["status"] == "ok"
    assert health["ontology"]["doc_format"] == "ontology-json/3"
    assert health["semantics"]["documents"] == 1
    assert health["pending"]["configured"] is True
    assert health["read_only"] is True
