"""A6: sample values on a table card, from a supplied file and never from a database.

Core does not connect to a warehouse, so the one thing a card could never say is "what
does a value of this column look like". A team that can export a few values per column
can hand them over as a file; these tests pin what happens to that file on the way to
the card:

1. **The file is data, not truth.** Every value is trimmed, redacted and cut to length
   before it is published -- a samples file is the most PII-prone input the tool ever
   reads, and there is no flag that turns the masking off;
2. **A row that matches nothing is reported**, never dropped: a typo in a hand-made
   export is exactly what its author cannot see;
3. **A corpus with no samples file builds the same bytes it always did** -- the keys
   appear only when somebody supplied values for them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.column_samples import (
    ColumnSamplesError,
    load_column_samples,
)
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    build_table_cards,
    render_table_card_markdown,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "contact", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "contact", "dt"],
}

PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, country_code, contact FROM ods.customer_base "
    "GROUP BY customer_id, country_code, contact"
)

CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_rollup "
    "SELECT country_code, count(1) AS n FROM mart.customer_daily "
    "WHERE dt = '20250101' GROUP BY country_code"
)


def _profiles() -> list[dict]:
    return [
        build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA)))
        for task, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL))
    ]


def _cards(samples=None) -> dict:
    return build_table_cards(_profiles(), artifact_root="corpus", samples=samples)


def _column(cards: dict, table: str, column: str) -> dict:
    card = next(item for item in cards["tables"] if item["table"] == table)
    return next(item for item in card["columns"] if item["name"] == column)


def _card(cards: dict, table: str) -> dict:
    return next(item for item in cards["tables"] if item["table"] == table)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


COUNTED_CSV = (
    "table,column,value,count\n"
    "mart.customer_daily,country_code,CN,10\n"
    "mart.customer_daily,country_code,US,30\n"
    "mart.customer_daily,country_code,JP,20\n"
)


# ------------------------------------------------------------------------ the file


def test_counts_order_the_values_most_frequent_first(tmp_path: Path) -> None:
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", COUNTED_CSV)))

    cards = _cards(samples)

    assert _column(cards, "mart.customer_daily", "country_code")["samples"] == [
        "US",
        "JP",
        "CN",
    ]


def test_without_counts_the_file_order_is_the_published_order(tmp_path: Path) -> None:
    text = (
        "table,column,value\n"
        "mart.customer_daily,country_code,CN\n"
        "mart.customer_daily,country_code,US\n"
        "mart.customer_daily,country_code,CN\n"
    )
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", text)))

    cards = _cards(samples)

    # distinct values only: the repeated CN keeps its first position rather than
    # occupying two of the five slots
    assert _column(cards, "mart.customer_daily", "country_code")["samples"] == ["CN", "US"]


def test_a_directory_of_csvs_is_read_as_one_file(tmp_path: Path) -> None:
    directory = tmp_path / "samples"
    _write(directory / "a.csv", COUNTED_CSV)
    _write(
        directory / "b.csv",
        "table,column,value\nmart.customer_daily,customer_id,C-001\n",
    )

    cards = _cards(load_column_samples(str(directory)))

    assert _column(cards, "mart.customer_daily", "country_code")["samples"][0] == "US"
    assert _column(cards, "mart.customer_daily", "customer_id")["samples"] == ["C-001"]


def test_the_json_form_carries_the_values_in_order(tmp_path: Path) -> None:
    document = {
        "doc_format": "samples/1",
        "samples": [
            {
                "table": "mart.customer_daily",
                "column": "country_code",
                "values": ["CN", "US", "JP"],
            }
        ],
    }
    path = _write(tmp_path / "samples.json", json.dumps(document, ensure_ascii=False))

    cards = _cards(load_column_samples(str(path)))

    assert _column(cards, "mart.customer_daily", "country_code")["samples"] == [
        "CN",
        "US",
        "JP",
    ]


def test_a_file_of_an_unknown_shape_is_an_error_not_a_traceback(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "wrong.csv", "db,col,val\nmart.customer_daily,a,b\n")
    json_path = _write(tmp_path / "wrong.json", json.dumps({"rows": []}))

    with pytest.raises(ColumnSamplesError) as csv_error:
        load_column_samples(str(csv_path))
    with pytest.raises(ColumnSamplesError) as json_error:
        load_column_samples(str(json_path))
    with pytest.raises(ColumnSamplesError) as missing:
        load_column_samples(str(tmp_path / "nope.csv"))

    assert "table,column,value" in str(csv_error.value)
    assert "samples/1" in str(json_error.value)
    assert "does not exist" in str(missing.value)


def test_the_table_name_is_matched_the_way_the_cards_normalize_it(tmp_path: Path) -> None:
    text = (
        "table,column,value\n"
        "spark_catalog.MART.customer_daily,COUNTRY_CODE,CN\n"
    )
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", text)))

    cards = _cards(samples)

    # the card's table is `mart.customer_daily`; a fully qualified, differently cased
    # spelling of the same table is the same table here too
    assert _column(cards, "mart.customer_daily", "country_code")["samples"] == ["CN"]
    assert cards["samples_applied"]["unmatched"] == []


# -------------------------------------------------------------------- what is published


def test_contact_shapes_are_masked_before_a_value_is_published(tmp_path: Path) -> None:
    text = (
        "table,column,value\n"
        "mart.customer_daily,contact,someone@example.com\n"
        "mart.customer_daily,contact,13800138000\n"
        "mart.customer_daily,contact,  CN  \n"
    )
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", text)))

    values = _column(_cards(samples), "mart.customer_daily", "contact")["samples"]

    assert values == ["<email>", "<phone>", "CN"]


def test_a_long_value_is_cut_rather_than_published_whole(tmp_path: Path) -> None:
    long_value = "A" * 80
    text = f"table,column,value\nmart.customer_daily,country_code,{long_value}\n"
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", text)))

    value = _column(_cards(samples), "mart.customer_daily", "country_code")["samples"][0]

    assert value == "A" * 64 + "…"


def test_at_most_top_values_per_column_are_published(tmp_path: Path) -> None:
    rows = "".join(
        f"mart.customer_daily,country_code,V{index},{index}\n" for index in range(1, 9)
    )
    path = _write(tmp_path / "samples.csv", "table,column,value,count\n" + rows)

    default = load_column_samples(str(path))
    narrow = load_column_samples(str(path), top=2)

    assert len(_column(_cards(default), "mart.customer_daily", "country_code")["samples"]) == 5
    assert _column(_cards(narrow), "mart.customer_daily", "country_code")["samples"] == [
        "V8",
        "V7",
    ]


def test_coverage_counts_the_columns_that_got_values(tmp_path: Path) -> None:
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", COUNTED_CSV)))

    cards = _cards(samples)

    assert _card(cards, "mart.customer_daily")["coverage"]["columns_sampled"] == 1
    assert _card(cards, "ods.customer_base")["coverage"]["columns_sampled"] == 0


def test_a_row_that_matches_nothing_is_reported_rather_than_dropped(tmp_path: Path) -> None:
    text = (
        "table,column,value\n"
        "mart.customer_daily,country_code,CN\n"
        "mart.no_such_table,country_code,CN\n"
        "mart.customer_daily,no_such_column,CN\n"
    )
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", text)))

    cards = _cards(samples)

    assert cards["samples_applied"]["unmatched"] == [
        "mart.customer_daily.no_such_column",
        "mart.no_such_table.country_code",
    ]
    assert cards["samples_applied"]["columns_sampled"] == 1


# ------------------------------------------------------------------------- renderings


def test_the_card_markdown_shows_the_values_in_the_column_table(tmp_path: Path) -> None:
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", COUNTED_CSV)))

    rendered = render_table_card_markdown(_card(_cards(samples), "mart.customer_daily"))

    assert "| 样例值 |" in rendered
    assert "`'US'`、`'JP'`、`'CN'`" in rendered


def test_a_card_built_without_samples_is_the_document_it_always_was() -> None:
    cards = _cards()
    card = _card(cards, "mart.customer_daily")

    assert "samples_applied" not in cards
    assert all("samples" not in column for column in card["columns"])
    assert "columns_sampled" not in card["coverage"]
    assert "样例值" not in render_table_card_markdown(card)


def test_the_ontology_attribute_carries_the_card_s_samples(tmp_path: Path) -> None:
    samples = load_column_samples(str(_write(tmp_path / "samples.csv", COUNTED_CSV)))
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL))
    ]

    ontology = build_ontology(
        documents, tables=_cards(samples), artifact_root="corpus"
    )

    entity = next(
        item for item in ontology["entities"] if item["id"] == "mart.customer_daily"
    )
    attributes = {item["column"]: item for item in entity["attributes"]}
    assert attributes["country_code"]["samples"] == ["US", "JP", "CN"]
    assert "samples" not in attributes["customer_id"]


# -------------------------------------------------------------------------------- CLI


def _corpus(root: Path) -> Path:
    for name, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL)):
        write_statement_documents(parse_scope_lineage(sql, name, schema=SCHEMA), root / name)
    return root


def test_tables_reads_the_samples_file_and_reports_what_missed(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    text = COUNTED_CSV + "mart.no_such_table,country_code,CN\n"
    path = _write(tmp_path / "samples.csv", text)

    code = main(
        ["tables", "--lineage", str(corpus), "--out", str(out), "--samples", str(path)]
    )

    assert code == 0
    cards = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert _column(cards, "mart.customer_daily", "country_code")["samples"][0] == "US"
    assert cards["samples_applied"]["unmatched"] == ["mart.no_such_table.country_code"]
    assert "samples_unmatched=1" in capsys.readouterr().out
    assert "样例值" in (out / "tables" / "mart.customer_daily.md").read_text(
        encoding="utf-8"
    )


def test_samples_top_limits_what_the_cli_publishes(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    path = _write(tmp_path / "samples.csv", COUNTED_CSV)

    code = main(
        [
            "tables",
            "--lineage",
            str(corpus),
            "--out",
            str(out),
            "--samples",
            str(path),
            "--samples-top",
            "1",
        ]
    )

    assert code == 0
    cards = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert _column(cards, "mart.customer_daily", "country_code")["samples"] == ["US"]


def test_an_unreadable_samples_file_stops_the_run_with_a_message(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    path = _write(tmp_path / "wrong.csv", "db,col\nmart.customer_daily,a\n")

    code = main(
        ["tables", "--lineage", str(corpus), "--out", str(out), "--samples", str(path)]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "table,column,value" in captured.err
    assert "Traceback" not in captured.err
