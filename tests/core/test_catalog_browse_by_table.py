"""``catalog_browse`` and the index's 「用之前先看」 and 「按表看」: one computation, two readers.

The browse page shows the gap summary ``catalog render`` leads ``index.md`` with, and the
table list carries the by-table columns, both taken from the functions that write the
Markdown: every row and every cell below is compared with the rendered index for the same
inputs, so the page cannot count differently. The table list may be ordered by one
by-table column, over the whole filtered list; a table with no document sorts last
whichever way, its value being unknown, not 0. The table-semantics documents are the
ones invented for the demo in ``test_catalog_index_by_table``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.render.catalog_browse import (
    TABLE_SORTS,
    browse_index,
    browse_list,
    table_units,
)
from scope_lineage.render.catalog_context import context_pack, render_context_text

from .test_catalog_index_by_table import (
    ALL_TABLES,
    ANSWERING_USES,
    BY_TABLE,
    DOCS,
    HEADING,
    KEY_ROW,
    LOAN,
    PARTIAL,
    REPAYMENT,
    STRUCTURE_ONLY,
    UNIT_ROW,
    _by_table,
    _cells,
    _index,
    _section,
)

FIXTURES = Path(__file__).parent / "fixtures"
# the browse answers of the demo as they were before the by-table fields were added
BEFORE = FIXTURES / "catalog-browse-before.json"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads((FIXTURES / "catalog" / "ontology.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plain(document: dict) -> dict:
    """The demo without any evidence (so without lineage)."""
    changed = copy.deepcopy(document)
    changed.pop("evidence", None)
    return changed


def _summary_rows(page: str) -> list[tuple[str, str]]:
    rows = [line for line in _section(page, HEADING).splitlines() if line.startswith("| ")]
    return [tuple(_cells(row)) for row in rows[2:]]  # type: ignore[misc]


def _all_tables(document: dict, semantics, **request) -> list[dict]:
    return browse_list(document, "tables", semantics=semantics, limit=200, **request)["items"]


# ------------------------------------------------------------------ the home summary


@pytest.mark.parametrize("docs", [None, DOCS, PARTIAL, {}])
def test_the_home_summary_is_the_index_summary(document: dict, plain: dict, docs) -> None:
    for built in (document, plain):
        page = _index(built, docs)
        use_first = browse_index(built, docs)["use_first"]
        assert use_first["heading"] == HEADING.removeprefix("## ")
        assert use_first["notes"] == [STRUCTURE_ONLY, ANSWERING_USES]
        assert [(row["name"], row["value"]) for row in use_first["rows"]] == _summary_rows(page)


def test_without_documents_the_rows_needing_them_are_absent(document: dict) -> None:
    names = [row["name"] for row in browse_index(document)["use_first"]["rows"]]
    assert KEY_ROW not in names and UNIT_ROW not in names
    with_docs = [row["name"] for row in browse_index(document, DOCS)["use_first"]["rows"]]
    assert with_docs[-2:] == [KEY_ROW, UNIT_ROW]


# ------------------------------------------------------------------ the table list


@pytest.mark.parametrize("docs", [DOCS, PARTIAL])
def test_each_table_row_carries_the_index_cells(document: dict, plain: dict, docs) -> None:
    for built in (document, plain):
        rows = _by_table(_index(built, docs))
        answer = browse_list(built, "tables", semantics=docs, limit=200)
        columns = answer["by_table"]["columns"]
        assert [column["label"] for column in columns] == rows["head"][2:]
        assert len(answer["items"]) == len(ALL_TABLES)
        for item in answer["items"]:
            cells = [item["by_table"]["cells"][column["key"]] for column in columns]
            assert cells == rows[item["table"]][2:], item["table"]


def test_a_table_without_a_document_has_no_number_that_needs_one(document: dict) -> None:
    rows = {item["table"]: item["by_table"] for item in _all_tables(document, PARTIAL)}
    borrower = rows["demo_dwd.dwd_lending_borrower_df"]
    assert borrower["covered"] is False
    assert borrower["unique"] is None and borrower["unit_unsupported"] is None
    assert borrower["watch"] is None and borrower["watch_conflicts"] is None
    assert borrower["measures"] == 1 and borrower["unmapped"] == 0
    assert borrower["cells"]["unit_unsupported"] == "—"
    loan = rows[LOAN]
    assert loan["covered"] is True
    assert (loan["measures"], loan["unit_unsupported"], loan["watch"], loan["watch_conflicts"]) == (
        2, 1, 1, 0,
    )


def test_the_coverage_note_is_the_index_note(document: dict) -> None:
    partial = browse_list(document, "tables", semantics=PARTIAL)["by_table"]
    assert (partial["covered"], partial["tables"]) == (3, 9)
    assert partial["note"] in _section(_index(document, PARTIAL), BY_TABLE)
    assert browse_list(document, "tables", semantics=DOCS)["by_table"]["note"] is None


def test_without_lineage_there_is_no_key_column(plain: dict) -> None:
    answer = browse_list(plain, "tables", semantics=DOCS)
    keys = [column["key"] for column in answer["by_table"]["columns"]]
    assert "key_evidence" not in keys and "unique" not in keys
    assert "key_evidence" not in answer["items"][0]["by_table"]


def test_without_documents_the_list_has_no_by_table_fields(document: dict) -> None:
    answer = browse_list(document, "tables")
    assert "by_table" not in answer
    assert all("by_table" not in item for item in answer["items"])


# ------------------------------------------------------------------ ordering


def test_the_default_order_is_the_table_name(document: dict) -> None:
    assert [item["table"] for item in _all_tables(document, DOCS)] == sorted(ALL_TABLES)


@pytest.mark.parametrize("key", [key for key in TABLE_SORTS if key != "table"])
def test_a_sort_orders_the_whole_list_unknown_last(document: dict, key: str) -> None:
    rows = {item["table"]: item["by_table"][key] for item in _all_tables(document, PARTIAL)}
    for descending in (False, True):
        sort = ("-" if descending else "") + key
        known = sorted(
            (table for table in rows if rows[table] is not None),
            key=lambda table: ((-1 if descending else 1) * rows[table], table),
        )
        expected = known + sorted(table for table in rows if rows[table] is None)
        # page by page, two rows at a time: the order is the whole list's, not a page's
        paged = []
        for offset in range(0, len(rows), 2):
            page = browse_list(
                document, "tables", semantics=PARTIAL, sort=sort, offset=offset, limit=2
            )
            paged += [item["table"] for item in page["items"]]
        assert paged == expected, sort


def test_a_sort_applies_after_the_filters(document: dict) -> None:
    page = browse_list(document, "tables", semantics=DOCS, text="lending", sort="-measures")
    tables = [item["table"] for item in page["items"]]
    assert all("lending" in table for table in tables)
    assert tables[0] == LOAN and page["query"]["sort"] == "-measures"


def test_sorting_by_name_backwards_needs_no_documents(document: dict) -> None:
    tables = [item["table"] for item in _all_tables(document, None, sort="-table")]
    assert tables == sorted(ALL_TABLES, reverse=True)


@pytest.mark.parametrize(
    ("kind", "sort", "semantics", "says"),
    [
        ("tables", "score", DOCS, "sort must be one of"),
        ("tables", "--measures", DOCS, "sort must be one of"),
        ("tables", "measures", None, "needs the table-semantics documents"),
        ("concepts", "table", DOCS, "sort orders tables only"),
        ("metrics", "-measures", DOCS, "sort orders tables only"),
    ],
)
def test_a_sort_it_cannot_do_is_refused(document, kind, sort, semantics, says) -> None:
    with pytest.raises(ValueError, match=says):
        browse_list(document, kind, semantics=semantics, sort=sort)
    with pytest.raises(answers.CatalogAnswerError) as refused:
        answers.browse_list(document, kind, semantics, sort=sort)
    assert refused.value.exit_code == 2


# ------------------------------------------------------------------ nothing else changes


def _without_added(answer: dict) -> dict:
    stripped = copy.deepcopy(answer)
    stripped.pop("use_first", None)
    stripped.pop("by_table", None)
    if "query" in stripped:
        stripped["query"].pop("sort", None)
    for item in stripped.get("items") or []:
        item.pop("by_table", None)
    return stripped


@pytest.mark.parametrize("semantics", [None, DOCS])
def test_the_answers_are_as_before_apart_from_the_added_fields(document, semantics) -> None:
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    now = {
        "index": answers.browse_index(document, semantics).result,
        "tables": answers.browse_list(document, "tables", semantics, limit=200).result,
        "tables_page": answers.browse_list(
            document, "tables", semantics, offset=2, limit=3, text="dwd"
        ).result,
        "concepts": answers.browse_list(document, "concepts", semantics, limit=200).result,
        "metrics": answers.browse_list(document, "metrics", semantics, limit=200).result,
    }
    for name, answer in now.items():
        assert _without_added(answer) == before[name], name
    assert set(now["index"]) - set(before["index"]) == {"use_first"}
    assert now["concepts"]["query"]["sort"] is None


def test_a_document_object_changed_for_a_new_one_is_answered_anew(document: dict) -> None:
    first = browse_list(document, "tables", semantics=DOCS, limit=200)
    changed = copy.deepcopy(document)
    for rep in changed["representations"]:
        if rep["table"] == REPAYMENT:
            rep["bindings"].append({"column": "added_col", "to": "unmapped", "status": "drafted"})
    second = browse_list(changed, "tables", semantics=DOCS, limit=200)
    unmapped = {item["table"]: item["by_table"]["unmapped"] for item in second["items"]}
    assert unmapped[REPAYMENT] == 1
    assert browse_list(document, "tables", semantics=DOCS, limit=200) == first
    assert browse_index(changed, DOCS)["use_first"] != browse_index(document, DOCS)["use_first"]


# ------------------------------------------------------------------ units of a table


def test_a_tables_units_carry_the_context_packs_marks(document: dict) -> None:
    for docs in (DOCS, PARTIAL, None):
        for table in ALL_TABLES:
            answer = table_units(document, docs, table)
            assert answer["checked"] is (docs is not None)
            for column in answer["columns"]:
                pack = context_pack(document, docs, columns=[f"{table}.{column['column']}"])
                catalog = pack["columns"][0]["catalog"]
                assert column.get("unit") == catalog.get("unit")
                assert column.get("material_unit") == catalog.get("material_unit")
                assert column["text"] == _unit_text(pack)


def _unit_text(pack: dict):
    """What the pack's text prints after ``单位：`` for its one column; None for no line."""
    lines = [
        line.split("单位：", 1)[1] for line in render_context_text(pack).splitlines()
        if line.startswith("  - 单位：")
    ]
    assert len(lines) <= 1, lines
    return lines[0] if lines else None


def test_only_measures_and_columns_with_a_unit_are_listed(document: dict) -> None:
    answer = table_units(document, DOCS, LOAN)
    assert [column["column"] for column in answer["columns"]] == ["principal_amt", "penalty_amt"]
    penalty = answer["columns"][1]
    assert penalty["material_unit"] == {"given": False}
    assert table_units(document, DOCS, "nowhere.nothing")["in_catalog"] is False
    assert answers.table_units(document, DOCS, "nowhere.nothing").exit_code == 1
