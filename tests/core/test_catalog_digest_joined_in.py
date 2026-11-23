"""``catalog digest --lineage``: the JOINs a measure's value is brought in through.

A measure summed by a coarser key and joined back onto finer rows repeats on every row
sharing that key, and adding it across rows counts it again. Whether that happens is a
fact of the lineage: the value enters its scope from a JOIN's right side, and the JOIN's
left keys reach columns of the written table. The digest gives each measure column
``joined_in``: one entry per such JOIN on the value's path -- its rule id, the left keys
as this table's columns, and the fan-out status the profile would give it (``safe`` /
``risk`` / ``unknown``) -- only when every key reaches a column of this table. A JOIN
below an aggregate is folded by it and not listed. Nothing is compared with the grain
here; ``catalog_check.py`` does that.

Everything is synthetic, parsed with ``scope-lineage parse`` the way a corpus is.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.cli import main

from .table_semantics_demo import EXAMPLE, read_json, write_json

ITEM = "demo_ods.ods_item_df"
FACT = "demo_ods.ods_fact_df"
RATE = "demo_ods.ods_rate_df"

T_COARSE = "demo_dwd.dwd_item_coarse_df"
T_FULL = "demo_dwd.dwd_item_full_df"
T_SURROGATE = "demo_dwd.dwd_item_surrogate_df"
T_BELOW = "demo_dwd.dwd_item_below_df"
T_RISK = "demo_dwd.dwd_item_risk_df"
T_PHYSICAL = "demo_dwd.dwd_item_physical_df"
T_UNMAPPED = "demo_dwd.dwd_item_unmapped_df"
T_MULTI = "demo_dwd.dwd_item_multi_df"

SCHEMA_TABLES = {
    ITEM: ["row_id", "proj_id", "item_id", "contract_no", "other_id", "item_amt", "dt"],
    FACT: ["proj_id", "item_id", "contract_no", "other_id", "amt", "dt"],
    RATE: ["proj_id", "rate", "dt"],
    T_COARSE: ["proj_id", "item_id", "item_amt", "proj_amt", "proj_name"],
    T_FULL: ["proj_id", "item_id", "pair_amt"],
    T_SURROGATE: ["row_id", "contract_no", "contract_amt"],
    T_BELOW: ["proj_id", "amt"],
    T_RISK: ["proj_id", "item_id", "raw_amt"],
    T_PHYSICAL: ["proj_id", "item_id", "rate"],
    T_UNMAPPED: ["proj_id", "item_id", "other_amt"],
    T_MULTI: ["proj_id", "contract_no", "item_id", "some_amt"],
}
# (grain columns, measure columns) of each document
DOCUMENTS = {
    T_COARSE: (["proj_id", "item_id"], {"item_amt", "proj_amt"}),
    T_FULL: (["proj_id", "item_id"], {"pair_amt"}),
    T_SURROGATE: (["row_id"], {"contract_amt"}),
    T_BELOW: (["proj_id"], {"amt"}),
    T_RISK: (["proj_id", "item_id"], {"raw_amt"}),
    T_PHYSICAL: (["proj_id", "item_id"], {"rate"}),
    T_UNMAPPED: (["proj_id", "item_id"], {"other_amt"}),
    T_MULTI: (["proj_id", "contract_no", "item_id"], {"some_amt"}),
}

TASKS = {
    "coarse": f"""
INSERT OVERWRITE TABLE {T_COARSE}
SELECT d.proj_id, d.item_id, d.item_amt, s.proj_amt, s.proj_name
FROM {ITEM} d
LEFT JOIN (SELECT proj_id, SUM(amt) AS proj_amt, MAX(other_id) AS proj_name
           FROM {FACT} GROUP BY proj_id) s
  ON d.proj_id = s.proj_id""",
    "full": f"""
INSERT OVERWRITE TABLE {T_FULL}
SELECT d.proj_id, d.item_id, s.pair_amt
FROM {ITEM} d
LEFT JOIN (SELECT proj_id, item_id, SUM(amt) AS pair_amt FROM {FACT} GROUP BY proj_id, item_id) s
  ON d.proj_id = s.proj_id AND d.item_id = s.item_id""",
    "surrogate": f"""
INSERT OVERWRITE TABLE {T_SURROGATE}
SELECT d.row_id, d.contract_no, s.contract_amt
FROM {ITEM} d
LEFT JOIN (SELECT contract_no, SUM(amt) AS contract_amt FROM {FACT} GROUP BY contract_no) s
  ON d.contract_no = s.contract_no""",
    "below": f"""
INSERT OVERWRITE TABLE {T_BELOW}
SELECT d.proj_id, SUM(f.amt) AS amt
FROM {ITEM} d
JOIN {FACT} f ON d.other_id = f.other_id
GROUP BY d.proj_id""",
    "risk": f"""
INSERT OVERWRITE TABLE {T_RISK}
SELECT d.proj_id, d.item_id, s.raw_amt
FROM {ITEM} d
LEFT JOIN (SELECT proj_id, amt AS raw_amt FROM {FACT}) s
  ON d.proj_id = s.proj_id""",
    "physical": f"""
INSERT OVERWRITE TABLE {T_PHYSICAL}
SELECT d.proj_id, d.item_id, r.rate
FROM {ITEM} d
LEFT JOIN {RATE} r ON d.proj_id = r.proj_id""",
    "unmapped": f"""
INSERT OVERWRITE TABLE {T_UNMAPPED}
SELECT d.proj_id, d.item_id, s.other_amt
FROM {ITEM} d
LEFT JOIN (SELECT other_id, SUM(amt) AS other_amt FROM {FACT} GROUP BY other_id) s
  ON d.other_id = s.other_id""",
    "multi": f"""
INSERT OVERWRITE TABLE {T_MULTI}
SELECT d.proj_id, d.contract_no, d.item_id, s.some_amt
FROM {ITEM} d
LEFT JOIN (SELECT proj_id, SUM(amt) AS some_amt FROM {FACT} GROUP BY proj_id) s
  ON d.proj_id = s.proj_id;
INSERT INTO TABLE {T_MULTI}
SELECT d.proj_id, d.contract_no, d.item_id, s.some_amt
FROM {ITEM} d
LEFT JOIN (SELECT contract_no, SUM(amt) AS some_amt FROM {FACT} GROUP BY contract_no) s
  ON d.contract_no = s.contract_no""",
}


def _schema() -> dict:
    return {"tables": [
        {"table_name": name, "table_desc": name, "is_partition": "0", "schema": [
            {"columnName": column, "columnType": "string", "columnComment": column,
             "columnIndex": index, "isPartition": 0}
            for index, column in enumerate(columns)
        ]}
        for name, columns in SCHEMA_TABLES.items()
    ]}


def _document(table: str) -> dict:
    grain, measures = DOCUMENTS[table]
    document = copy.deepcopy(read_json(EXAMPLE))
    document["table"] = table
    document["columns"] = [
        {
            "column": column, "meaning": column,
            "category": "measure" if column in measures else (
                "identifier" if column in grain else "descriptive"),
            "derivation": "直接取上游列。", "sources": ["sql"], "confidence": "high",
        }
        for column in SCHEMA_TABLES[table]
    ]
    document["summary"]["row"]["grain_columns"] = list(grain)
    return document


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("joined_in")
    for name, sql in TASKS.items():
        write_json(root / "tasks" / f"{name}.json", {"meta": {
            "task_id": f"task-{name}", "task_name": name, "task_type": "Spark SQL",
            "schedule_cycle": "day", "sql": sql,
        }})
    write_json(root / "schema_info.json", _schema())
    assert main([
        "parse", "--input-dir", str(root / "tasks"), "--schema", str(root / "schema_info.json"),
        "--out", str(root / "lineage"),
    ]) == 0
    for table in DOCUMENTS:
        write_json(root / "docs" / f"{table}.json", _document(table))
    return {"root": root, "lineage": root / "lineage", "docs": root / "docs"}


def _digest(corpus: dict, out: Path, *extra) -> tuple[dict, str]:
    assert main(["catalog", "digest", str(corpus["docs"]), "--out", str(out),
                 *[str(arg) for arg in extra]]) == 0
    return read_json(out / "digest.json"), (out / "digest.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built(corpus: dict, tmp_path_factory) -> tuple[dict, str]:
    return _digest(corpus, tmp_path_factory.mktemp("digest"), "--lineage", corpus["lineage"])


def _columns(digest: dict, table: str) -> dict[str, dict]:
    [entry] = [entry for entry in digest["tables"] if entry["table"] == table]
    return {
        column["column"]: column
        for key, value in entry.items()
        if key.endswith("_columns") and key != "technical_columns"
        for column in value
    }


def _joined(built, table: str, column: str):
    return _columns(built[0], table)[column].get("joined_in")


# ---------------------------------------------------------------- the fact


def test_a_measure_joined_in_by_a_coarser_key_names_the_join_and_its_keys(built) -> None:
    [hop] = _joined(built, T_COARSE, "proj_amt")
    assert hop["keys"] == ["proj_id"]
    assert hop["fan_out"] == "safe"
    assert hop["rule"].startswith("logic:ROOT:join")


def test_a_measure_read_from_the_driving_side_has_none(built) -> None:
    assert _joined(built, T_COARSE, "item_amt") is None


def test_a_column_that_is_not_a_measure_has_none(built) -> None:
    assert _joined(built, T_COARSE, "proj_name") is None


def test_keys_covering_the_grain_are_still_written(built) -> None:
    """The digest does not compare; the keys are given whatever they cover."""
    [hop] = _joined(built, T_FULL, "pair_amt")
    assert sorted(hop["keys"]) == ["item_id", "proj_id"]


def test_a_key_outside_the_grain_is_written_as_this_tables_column(built) -> None:
    [hop] = _joined(built, T_SURROGATE, "contract_amt")
    assert hop["keys"] == ["contract_no"]


def test_a_join_below_an_aggregate_is_not_listed(built) -> None:
    assert _joined(built, T_BELOW, "amt") is None


def test_a_key_that_reaches_no_column_of_this_table_writes_nothing(built) -> None:
    assert _joined(built, T_UNMAPPED, "other_amt") is None


def test_a_join_that_may_multiply_rows_is_written_with_its_status(built) -> None:
    [hop] = _joined(built, T_RISK, "raw_amt")
    assert hop["keys"] == ["proj_id"]
    assert hop["fan_out"] in ("risk", "unknown")


def test_a_physical_right_side_is_written_unknown(built) -> None:
    [hop] = _joined(built, T_PHYSICAL, "rate")
    assert hop["keys"] == ["proj_id"]
    assert hop["fan_out"] == "unknown"


def test_each_statement_writing_the_column_adds_its_own_entry(built) -> None:
    hops = _joined(built, T_MULTI, "some_amt")
    assert [hop["keys"] for hop in hops] == [["proj_id"], ["contract_no"]]
    assert len({hop["source"] for hop in hops}) == 2
    assert all("/stmt:" in hop["source"] for hop in hops)


def test_the_markdown_says_it_under_the_joined_inputs(built) -> None:
    [hop] = _joined(built, T_COARSE, "proj_amt")
    assert f"  - proj_amt: joined in through {hop['rule']} on proj_id (fan-out: safe)" in built[1]


def test_without_the_lineage_there_is_no_such_key(corpus, tmp_path, built) -> None:
    plain, text = _digest(corpus, tmp_path)
    assert all("joined_in" not in column
               for entry in plain["tables"] for column in _columns(plain, entry["table"]).values())
    assert "joined in through" not in text
