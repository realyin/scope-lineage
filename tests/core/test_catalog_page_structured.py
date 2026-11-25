"""Structured page answers in the core: the overlay of three page targets, the page's slot
states and their marks in the context pack.

A browsing page may answer a question with a structured value as well as a sentence: the
row's grain (``summary.row``), a column's meaning (``column:<c>.meaning``) or one code
value (``column:<c>.code_values``, one ``{value, meaning}`` object). ``overlay_answers``
applies those three shapes and nothing else a page cannot produce; ``page_index`` takes a
second kind of key, ``(table, slot)``, whose state is ``{"written": False}``; and the pack
marks an overlaid slot ``written: false`` (the row) or ``unwritten`` (a column), in JSON
and in text. Without slot states nothing changes (``test_catalog_page_answers`` pins it).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.render.catalog_context import context_pack, page_index, render_context_text
from scope_lineage.semantics.schema import DOC_FORMAT, schema_errors

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
ONTOLOGY = FIXTURES / "catalog" / "ontology.json"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"
DOCUMENT_FILES = (
    ROOT / "examples" / "table-semantics" / f"{CUSTOMER}.json",
    FIXTURES / "table-semantics" / "documents" / f"{WAIVER}.json",
)
UNWRITTEN = "（页面填写，尚未写回）"


@pytest.fixture()
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


@pytest.fixture()
def semantics() -> dict:
    found = {}
    for path in DOCUMENT_FILES:
        doc = json.loads(path.read_text(encoding="utf-8"))
        found[doc["table"]] = doc
    # an inferred grain, so a page's row answer is one the overlay may apply
    found[CUSTOMER]["summary"]["row"]["grain_source"] = "inferred"
    return found


def _entry(target: str, value, table: str = CUSTOMER) -> dict:
    return {"table": table, "target": target, "value": value, "by": "demo-owner",
            "date": "2026-11-24"}


def _column(doc: dict, name: str) -> dict:
    return next(c for c in doc["columns"] if c["column"] == name)


# ------------------------------------------------------------ overlay


def test_the_overlay_applies_the_three_page_targets(semantics) -> None:
    before = copy.deepcopy(semantics)

    changed, refused = answers.overlay_answers(semantics, [
        _entry("summary.row", {"unique": "no", "grain_columns": ["customer_id", "dt"]}),
        _entry("column:etl_time.meaning", "装载批次时间"),
        _entry("column:gender_cd.code_values", {"value": "X", "meaning": "其他"}),
    ])

    assert refused == []
    doc = changed[CUSTOMER]
    assert doc["summary"]["row"]["unique"] == "no"
    assert doc["summary"]["row"]["grain_columns"] == ["customer_id", "dt"]
    assert doc["summary"]["row"]["grain_source"] == "declared"
    assert _column(doc, "etl_time")["meaning"] == "装载批次时间"
    codes = {c["value"]: c["meaning"] for c in _column(doc, "gender_cd")["code_values"]}
    assert codes == {"F": "女", "M": "男", "U": "未知", "X": "其他"}
    assert schema_errors(doc, DOC_FORMAT) == []
    assert changed[WAIVER] is semantics[WAIVER]
    assert semantics == before


@pytest.mark.parametrize("target, value", [
    ("summary.row", "一行一个客户"),
    ("summary.row", {"unique": "yes", "grain_columns": ["customer_id"], "grain_source": "proven"}),
    ("summary.row", {"unique": "yes"}),
    ("summary.row", {"note": "说明"}),
    ("column:gender_cd.code_values", [{"value": "X", "meaning": "其他"}]),
    ("column:gender_cd.code_values", {"value": "X", "meaning": "其他", "unconfirmed": True}),
    ("column:gender_cd.meaning", {"text": "性别"}),
    ("column:gender_cd.observed_values", {"query": "p1"}),
    ("summary.row.observed", {"query": "p1"}),
    ("input:demo_ods.ods_customer", {"query": "p1"}),
])
def test_the_overlay_refuses_a_shape_no_page_produces(semantics, target, value) -> None:
    changed, refused = answers.overlay_answers(semantics, [_entry(target, value)])

    assert refused == [{"table": CUSTOMER, "target": target, "reason": answers.ONLY_PAGE_TARGETS}]
    assert all(changed[name] is semantics[name] for name in semantics)


def test_indexed_refusals_name_the_entry_they_refuse(semantics) -> None:
    entries = [
        _entry("column:gender_cd.meaning", "性别码"),
        _entry("column:no_such_column.meaning", "不存在"),
        _entry("question:q1", "会。"),
        _entry("summary.row", "一行一个客户"),
        _entry("column:gender_cd.code_values", {"value": "X", "meaning": "其他"}, table="demo_dwd.gone"),
    ]

    _, plain = answers.overlay_answers(semantics, entries)
    _, indexed = answers.overlay_answers(semantics, entries, indexed=True)

    assert "index" not in json.dumps(plain)
    assert sorted(item["index"] for item in indexed) == [1, 3, 4]
    for item in indexed:
        assert (item["table"], item["target"]) == (entries[item["index"]]["table"],
                                                   entries[item["index"]]["target"])
    assert [{k: v for k, v in item.items() if k != "index"} for item in indexed] == plain


# ------------------------------------------------------------ page states


def test_page_index_takes_slot_keys() -> None:
    states = page_index({
        (CUSTOMER.upper(), "row"): {"written": False},
        (CUSTOMER, "column:gender_cd.meaning"): {"written": False},
        (CUSTOMER, "column:gender_cd.code_values:X"): {"written": False},
        (CUSTOMER, "q1"): {"written": False},
    })

    assert set(states) == {(CUSTOMER, "row"), (CUSTOMER, "column:gender_cd.meaning"),
                           (CUSTOMER, "column:gender_cd.code_values:X"), (CUSTOMER, "q1")}


@pytest.mark.parametrize("slot, state", [
    ("row", {"kind": "partial", "reason": "r", "by": "b", "date": "2026-11-24"}),
    ("column:gender_cd.meaning", {"written": True}),
    ("column:gender_cd.observed_values", {"written": False}),
    ("column:gender_cd", {"written": False}),
    ("column:gender_cd.code_values:", {"written": False}),
])
def test_page_index_refuses_a_slot_state_it_does_not_know(slot, state) -> None:
    with pytest.raises(ValueError):
        page_index({(CUSTOMER, slot): state})


# ------------------------------------------------------------ the pack


def _overlaid(semantics) -> dict:
    changed, refused = answers.overlay_answers(semantics, [
        _entry("summary.row", {"unique": "no", "grain_columns": ["customer_id", "dt"]}),
        _entry("column:gender_cd.meaning", "性别码"),
        _entry("column:gender_cd.code_values", {"value": "X", "meaning": "其他"}),
    ])
    assert refused == []
    return changed


STATES = {
    (CUSTOMER, "row"): {"written": False},
    (CUSTOMER, "column:gender_cd.meaning"): {"written": False},
    (CUSTOMER, "column:gender_cd.code_values:X"): {"written": False},
}


def test_the_pack_marks_the_overlaid_slots(document, semantics) -> None:
    overlaid = _overlaid(semantics)

    pack = context_pack(document, overlaid, tables=[CUSTOMER, WAIVER],
                        columns=[f"{CUSTOMER}.gender_cd"], page_states=STATES)

    tables = {t["table"]: t["semantics"] for t in pack["tables"]}
    assert tables[CUSTOMER]["row"]["written"] is False
    assert "written" not in tables[WAIVER]["row"]
    columns = {c["column"]: c for c in tables[CUSTOMER]["columns"]}
    assert columns["gender_cd"]["unwritten"] == ["meaning", "code_values:X"]
    assert "unwritten" not in columns["customer_id"]
    (column,) = pack["columns"]
    assert column["semantics"]["unwritten"] == ["meaning", "code_values:X"]
    assert column["semantics"]["meaning"] == "性别码"


def test_the_text_marks_the_overlaid_slots(document, semantics) -> None:
    overlaid = _overlaid(semantics)

    text = render_context_text(context_pack(document, overlaid, tables=[CUSTOMER],
                                            page_states=STATES)).splitlines()
    alone = render_context_text(context_pack(document, overlaid, columns=[f"{CUSTOMER}.gender_cd"],
                                             page_states=STATES)).splitlines()

    (row,) = [line for line in text if line.startswith("- 一行是：")]
    assert row.endswith(UNWRITTEN)
    (gender,) = [line for line in text if line.startswith("- gender_cd：")]
    assert gender.endswith("（页面填写，尚未写回：含义、码值 'X'）")
    assert not [line for line in text if line.startswith("- customer_id：") and UNWRITTEN[:-1] in line]
    (meaning,) = [line for line in alone if line.startswith("- 含义：")]
    assert meaning.endswith(UNWRITTEN)
    (codes,) = [line for line in alone if line.startswith("  - 码值：")]
    assert codes.endswith("（页面填写，尚未写回：码值 'X'）")


def test_without_slot_states_the_overlaid_pack_carries_no_mark(document, semantics) -> None:
    overlaid = _overlaid(semantics)

    pack = context_pack(document, overlaid, tables=[CUSTOMER], columns=[f"{CUSTOMER}.gender_cd"])

    assert "written" not in json.dumps(pack["tables"][0]["semantics"]["row"])
    assert "unwritten" not in json.dumps(pack, ensure_ascii=False)
    assert UNWRITTEN[1:-1] not in render_context_text(pack)


def test_the_answers_command_refuses_a_bad_slot_state(document, semantics) -> None:
    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.context(document, semantics, tables=[CUSTOMER],
                        page_states={(CUSTOMER, "row"): {"written": True}})
    assert raised.value.exit_code == 2


# ------------------------------------------------------------ replay is not atomic


def test_a_replay_applies_a_structured_entry_whose_question_was_rewritten(semantics) -> None:
    """A page record exports a structured entry and the ``question:`` entry that closes the
    question. ``semantic confirm`` has no groups: under ``--require-asked`` the question,
    rewritten since, leaves its entry unmatched while the structured entry -- addressed by
    column name, carrying no ``asked`` -- still applies. The page keeps the two together;
    the replay does not (the docs say so)."""
    from scope_lineage.semantics import apply_confirmations

    doc = semantics[CUSTOMER]
    doc["summary"]["questions"] = [
        {"id": "q1", "text": "装载时间是什么时间？（改写后）", "status": "open"}]
    entries = [
        _entry("column:etl_time.meaning", "装载批次时间"),
        {**_entry("question:q1", "列 etl_time 的含义：装载批次时间"), "asked": "装载时间是什么时间？"},
    ]

    result = apply_confirmations({CUSTOMER: doc}, entries, require_asked=True)

    assert [item["target"] for item in result.unmatched] == ["question:q1"]
    assert result.unmatched_at == [1]
    assert _column(result.documents[CUSTOMER], "etl_time")["meaning"] == "装载批次时间"
    assert result.documents[CUSTOMER]["summary"]["questions"][0]["status"] == "open"
