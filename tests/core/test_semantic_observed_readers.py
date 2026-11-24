"""The readers of a document whose grain a platform query observed.

An observation speaks of the partitions a query read on the day it ran; it is no
definition. Every reader of a table-semantics document -- the table page, ``catalog
digest``, the context pack, the catalog index -- says so wherever it would otherwise
say the table is unique: the grain is "counted without a duplicate in partition P (query
Q, run on D)", never 「唯一」 or 「全表唯一」 on its own. The context pack's row carries
``grain_source`` and the observation, so an agent reading the JSON can tell an observed
grain from a declared one. Observed values sit with the column, observed inputs with the
table's neighbours, each with its partition and date.

Without an observation every reader's output is what it was (the snapshot tests of each
reader keep that); here the fixture is the example document replayed with the W1a
observations, its note's own 「唯一」 taken out so only the readers' words are looked at.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.catalog.digest import digest_tables, render_digest_markdown
from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.semantics.page import render_semantic_pages

from .table_semantics_demo import DEMO_TABLE, example
from .test_semantic_observed import ALL, INPUT, _apply, _with_row

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
PARTITION = "dt=20261119"
RUN_ON = "2026-11-20"


@pytest.fixture(scope="module")
def observed() -> dict:
    document, _ = _apply(_with_row(grain_source="inferred", note="每天各有一份全量。"), *ALL)
    assert document["summary"]["row"]["grain_source"] == "observed"
    return document


@pytest.fixture(scope="module")
def ontology() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _says_where(text: str) -> None:
    assert PARTITION in text and RUN_ON in text and "观测" in text, text


# ------------------------------------------------------------------ the page


def test_the_page_never_says_unique_of_an_observed_grain(observed: dict) -> None:
    page = render_semantic_pages([observed])[f"{DEMO_TABLE}.md"]
    assert "唯一" not in page
    (row,) = [line for line in page.splitlines() if line.startswith("**一行是什么**")]
    _says_where(row)
    assert "按 (customer_id) 计数无重复" in row and "不是定义" in row


def test_the_page_shows_observed_values_with_the_column(observed: dict) -> None:
    page = render_semantic_pages([observed])[f"{DEMO_TABLE}.md"]
    (line,) = [line for line in page.splitlines() if line.startswith("| `gender_cd`")]
    _says_where(line)
    assert "X（10 行）" in line and "不是码值表" in line


def test_the_page_shows_observed_inputs_with_the_upstream(observed: dict) -> None:
    page = render_semantic_pages([observed])[f"{DEMO_TABLE}.md"]
    lines = [line for line in page.splitlines() if line.startswith("- 上游观测：")]
    assert len(lines) == 2
    for line in lines:
        _says_where(line)
        assert INPUT in line and "唯一" not in line
    assert "按 (cust_no) 计数无重复" in lines[0] and "别的分区" in lines[0]


def test_a_declared_grain_keeps_its_words_and_gains_the_observation(observed: dict) -> None:
    document = copy.deepcopy(observed)
    document["summary"]["row"]["grain_source"] = "declared"
    page = render_semantic_pages([document])[f"{DEMO_TABLE}.md"]
    (row,) = [line for line in page.splitlines() if line.startswith("**一行是什么**")]
    assert "来源为声明，全表唯一。" in row
    _says_where(row.split("全表唯一。", 1)[1])


# ------------------------------------------------------------------ the digest


def test_the_digest_states_an_observed_grain_as_an_observation(observed: dict) -> None:
    digest = digest_tables([observed])
    (entry,) = digest["tables"]
    assert entry["grain"]["source"] == "observed"
    assert entry["grain"]["observed"]["partition"] == {"column": "dt", "values": ["20261119"]}
    assert entry["grain"]["observed"]["on"] == RUN_ON
    (gender,) = [c for c in entry["descriptive_columns"] if c["column"] == "gender_cd"]
    assert gender["observed_values"]["values"][2] == {"value": "X", "count": 10}
    assert [item["columns"] for item in entry["observed_inputs"]] == [["cust_no"], ["verified_no"]]
    text = render_digest_markdown(digest)
    (grain,) = [line for line in text.splitlines() if line.startswith("- Grain:")]
    assert "unique" not in grain.lower() and "唯一" not in text
    assert "observed in dt=20261119 on 2026-11-20" in grain and "not a definition" in grain
    assert any(line.startswith("- Observed input: demo_ods.ods_core_customer_df")
               and "dt=20261119" in line for line in text.splitlines())
    (gender_line,) = [line for line in text.splitlines() if "gender_cd" in line]
    assert "[observed in dt=20261119 on 2026-11-20 (query probe_1, 120 rows" in gender_line
    assert "F x60, M x50, X x10, complete; absent U -- not a code list]" in gender_line


def test_an_empty_string_value_is_shown_as_one(observed: dict) -> None:
    from scope_lineage.catalog.digest import _observed_values_text
    from scope_lineage.observation_words import observed_values_text, values_text

    column = copy.deepcopy(next(c for c in observed["columns"] if c["column"] == "gender_cd"))
    value = column["observed_values"]
    value["values"] = [{"value": "", "count": 804}, {"value": "A", "count": 2}]
    value["absent"] = [""]
    said = values_text(value)
    assert said.startswith("出现 ''（空串）（804 行）、A（2 行）")
    assert "没有出现 ''（空串）" in said and "出现 （" not in said
    assert "''（空串）（804 行）" in observed_values_text(column)
    digested = _observed_values_text(value)
    assert "'' (empty string) x804, A x2" in digested and "absent '' (empty string)" in digested


# ------------------------------------------------------------------ the context pack


def test_the_context_pack_row_carries_the_grain_source_and_the_observation(
    observed: dict, ontology: dict
) -> None:
    pack = context_pack(ontology, {DEMO_TABLE: observed}, tables=[DEMO_TABLE])
    (table,) = pack["tables"]
    row = table["semantics"]["row"]
    assert row["grain_source"] == "observed"
    assert row["observed"]["partition"] == {"column": "dt", "values": ["20261119"]}
    assert row["observed"]["on"] == RUN_ON
    assert [item["columns"] for item in table["semantics"]["observed_inputs"]] == [
        ["cust_no"], ["verified_no"]]
    (gender,) = [c for c in table["semantics"]["columns"] if c["column"] == "gender_cd"]
    assert gender["observed_values"]["on"] == RUN_ON


@pytest.mark.parametrize("brief", [False, True])
def test_the_context_text_never_says_unique_of_an_observed_grain(
    observed: dict, ontology: dict, brief: bool
) -> None:
    text = render_context_text(context_pack(ontology, {DEMO_TABLE: observed},
                                            tables=[DEMO_TABLE], brief=brief))
    assert "唯一" not in text
    (row,) = [line for line in text.splitlines() if line.startswith("- 一行是：")]
    _says_where(row)
    inputs = [line for line in text.splitlines() if line.startswith("- 上游观测：")]
    assert len(inputs) == 2 and all(PARTITION in line for line in inputs)


def test_a_column_answer_carries_its_observed_values(observed: dict, ontology: dict) -> None:
    pack = context_pack(ontology, {DEMO_TABLE: observed}, columns=[f"{DEMO_TABLE}.gender_cd"])
    (column,) = pack["columns"]
    assert column["semantics"]["observed_values"]["partition"]["values"] == ["20261119"]
    (line,) = [line for line in render_context_text(pack).splitlines() if "观测取值" in line]
    _says_where(line)
    assert "不是码值表" in line


# ------------------------------------------------------------------ the catalog index


def test_the_index_says_an_observed_grain_has_no_duplicate_in_the_partition_read(
    observed: dict, ontology: dict
) -> None:
    index = render_catalog_pages(ontology, None, {DEMO_TABLE: observed})["index.md"]
    (row,) = [line for line in index.splitlines() if line.startswith(f"| `{DEMO_TABLE}`")]
    cells = [cell.strip() for cell in row.strip("|").split(" | ")]
    said = cells[3]
    assert "唯一" not in said
    assert said.startswith("无重复（观测") and PARTITION in said and RUN_ON in said


def test_without_observations_the_index_cell_is_unchanged(ontology: dict) -> None:
    index = render_catalog_pages(ontology, None, {DEMO_TABLE: example()})["index.md"]
    (row,) = [line for line in index.splitlines() if line.startswith(f"| `{DEMO_TABLE}`")]
    assert " | 已证明 | 唯一 | " in row
