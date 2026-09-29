"""Shared helpers for the catalog tests: the demo catalog and ways to break one copy of it.

Every failing fixture is the demo with exactly one thing changed, so a test names the one
rule it is about and a green demo run proves the fixture broke nothing else.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

import yaml

from scope_lineage.catalog.loader import yaml_loader

DEMO = Path(__file__).resolve().parents[2] / "examples" / "catalog-demo"
# The demo's lineage corpus: eight synthetic scheduler tasks that write and read the
# demo's tables, and the schema metadata they are parsed with.
CORPUS = Path(__file__).resolve().parents[2] / "examples" / "catalog-demo-corpus"


def parse_demo_corpus(target: Path) -> Path:
    """Parse the demo's tasks into ``target`` exactly as the docs tell a reader to."""
    from scope_lineage.cli import main

    code = main([
        "parse",
        "--input-dir", str(CORPUS / "tasks"),
        "--schema", str(CORPUS / "schema_info.json"),
        "--out", str(target),
    ])
    assert code == 0, "the demo corpus must parse"
    return target


def demo_tables(lineage: Path, target: Path) -> Path:
    """``scope-lineage tables`` over the parsed corpus: the file ``--tables`` reads."""
    from scope_lineage.cli import main

    assert main(["tables", "--lineage", str(lineage), "--out", str(target)]) == 0
    return target / "tables.json"


def copy_demo(tmp_path: Path) -> Path:
    target = tmp_path / "catalog"
    shutil.copytree(DEMO, target)
    return target


def read_file(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    # The catalog's own YAML reading (1.2 booleans): ``on:`` stays a key, not True.
    return yaml.load(text, Loader=yaml_loader())  # noqa: S506 - a SafeLoader subclass


def write_file(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def mutate(root: Path, relative: str, change: Callable[[dict], None]) -> None:
    """Load one catalog file, let ``change`` edit it in place, write it back."""
    path = root / relative
    data = read_file(path)
    change(data)
    write_file(path, data)


def item(items: list, key: str, value: str | None = None) -> dict:
    """The one entry of ``items`` whose ``key`` (``id`` by default) is ``value``."""
    if value is None:
        key, value = "id", key
    matches = [entry for entry in items if entry.get(key) == value]
    assert len(matches) == 1, f"expected one {key}={value!r}, got {len(matches)}"
    return matches[0]


def rules(findings) -> list[str]:
    return sorted({finding.rule for finding in findings})


LOAN_TABLE = "demo_dwd.dwd_lending_loan_df"
SECOND_SELF_RELATION = "rel:loan_descends_from_root"


def add_second_self_relation(root: Path, **named: str) -> None:
    """A second relation from the loan to itself, carried by a new column ``root_loan_no``
    beside ``orig_loan_no``; ``named`` maps a self-referencing column to the relation it
    says it realises (``relation:``), and a column left out names none."""

    def relations(data: dict) -> None:
        data["relations"].append({
            "id": SECOND_SELF_RELATION,
            "kind": "association",
            "from": "concept:loan",
            "to": "concept:loan",
            "name": "descends from",
            "inverse_name": "is the root of",
            "cardinality": {"from": "0..*", "to": "0..1"},
            "definition": "The first loan of a renewal chain; root_loan_no names it.",
        })

    def mapping(data: dict) -> None:
        bindings = item(data["representations"], "table", LOAN_TABLE)["bindings"]
        at = bindings.index(item(bindings, "column", "orig_loan_no")) + 1
        bindings.insert(
            at, {"column": "root_loan_no", "to": "foreign_identifier", "ref": "id:loan_no"}
        )
        for column, relation in named.items():
            item(bindings, "column", column)["relation"] = relation

    mutate(root, "relations.yaml", relations)
    mutate(root, "mapping/lending.yaml", mapping)


def bind_another_instances_attribute(root: Path) -> None:
    """The demo's loan table also repeats the renewed loan's status next to
    ``orig_loan_no``: an attribute of the table's own concept, of another instance."""

    def change(data: dict) -> None:
        loan = item(data["representations"], "table", "demo_dwd.dwd_lending_loan_df")
        loan["bindings"].insert(-1, {
            "column": "orig_loan_status",
            "to": "foreign_attribute",
            "ref": "attr:loan.loan_status",
            "via": "orig_loan_no",
        })

    mutate(root, "mapping/lending.yaml", change)


def add_a_players_self_reference(root: Path, ref: str) -> None:
    """The demo's borrower role view gains ``referrer_customer_id`` -- another customer,
    by the player's identifier, under a customer-to-customer relation -- and
    ``referrer_attr``, bound to ``ref`` as ``foreign_attribute`` via that column."""

    def relation(data: dict) -> None:
        data["relations"].append({
            "id": "rel:customer_refers_customer",
            "kind": "association",
            "from": "concept:customer",
            "to": "concept:customer",
            "name": "refers",
            "inverse_name": "is referred by",
            "cardinality": {"from": "0..*", "to": "0..1"},
        })

    def bindings(data: dict) -> None:
        view = item(data["representations"], "table", "demo_dwd.dwd_lending_borrower_df")
        view["bindings"][-1:-1] = [
            {"column": "referrer_customer_id", "to": "foreign_identifier", "ref": "id:customer_id"},
            {
                "column": "referrer_attr",
                "to": "foreign_attribute",
                "ref": ref,
                "via": "referrer_customer_id",
            },
        ]

    mutate(root, "relations.yaml", relation)
    mutate(root, "mapping/lending.yaml", bindings)
