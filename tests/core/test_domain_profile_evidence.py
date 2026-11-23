"""``domain-profile evidence``: what a corpus says about its table-name suffixes, and the
comment material a writer drafts a ``domain-profile/1`` from.

The tool reports observations and never concludes ``full``: a suffix read one partition
at a time may be a full snapshot or a day's increment, and only a person can tell
(USAGE「一、表名后缀」). The corpora are synthetic (``domain_profile_corpora``).
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.cli import main
from scope_lineage.semantics import profile_evidence as pe

from .domain_profile_corpora import Corpora, suffix


@pytest.fixture(scope="module")
def corpora(tmp_path_factory) -> Corpora:
    return Corpora(tmp_path_factory.mktemp("domain_profile_evidence"))


# ------------------------------------------------------------------ suffix rules


def test_a_increments_with_no_write_in_the_corpus_are_pending_without_a_lean(corpora):
    """review-1's counter-example A as written: no statement writes the increments."""
    item = suffix(corpora.evidence("A"), "di")
    assert item["observation"] == "single_partition_reads"
    assert (item["suggestion"], item["lean"]) == ("pending", None)
    assert "没有写入" in item["pending_reason"]


def test_a2_increments_passed_on_through_the_partition_are_never_full(corpora):
    item = suffix(corpora.evidence("A2"), "di")
    assert item["suggestion"] == "pending"
    assert item["suggestion"] != "full"


def test_a3_a_window_on_the_write_side_takes_the_lean_away(corpora):
    item = suffix(corpora.evidence("A3"), "di")
    assert (item["suggestion"], item["lean"]) == ("pending", None)
    assert item["writes"]["window_filtered"] == 3
    assert "窗口" in item["pending_reason"]


def test_a4_dynamic_partition_increments_are_never_full(corpora):
    item = suffix(corpora.evidence("A4"), "di")
    assert item["suggestion"] == "pending"
    assert item["writes"]["dynamic"] == 3


def test_b_multi_equality_counts_in_the_denominator_only(corpora):
    item = suffix(corpora.evidence("B"), "df")
    assert item["reads"]["multi_equality"] == 6
    assert item["observation"] == "mixed"
    assert item["suggestion"] is None


def test_c_a_partition_column_no_rule_names_is_read_from_the_metadata(corpora):
    item = suffix(corpora.evidence("C"), "df")
    assert item["reads"]["equality"] == 6
    assert item["read_shapes"]["equality"] == ["分区列 = 常量"]


def test_d_unpartitioned_reads_make_no_suggestion(corpora):
    evidence = corpora.evidence("D")
    item = suffix(evidence, "info")
    assert item["reads"] == {"equality": 0, "multi_equality": 0, "range": 0,
                             "unconditioned": 0, "unpartitioned": 6}
    assert all(entry["suggestion"] is None for entry in evidence["suffixes"])


def test_e1_a_name_without_an_underscore_has_no_suffix(corpora):
    evidence = corpora.evidence("E")
    assert all(entry["suffix"] != "users" for entry in evidence["suffixes"])
    assert pe.suffix_of("app.users") is None


def test_e2_a_digits_only_suffix_counts(corpora):
    assert suffix(corpora.evidence("E"), "2024")["tables"] == 1


def test_e3_one_table_spelt_in_two_cases_is_one_table(corpora):
    item = suffix(corpora.evidence("E"), "list")
    assert (item["tables"], item["reads"]["unpartitioned"]) == (1, 2)


def test_f_a_snapshot_read_one_partition_at_a_time_leans_full(corpora):
    item = suffix(corpora.evidence("F"), "df")
    assert (item["observation"], item["suggestion"], item["lean"]) == (
        "single_partition_reads", "pending", "full")


def test_f2_the_classic_merge_is_never_incremental(corpora):
    item = suffix(corpora.evidence("F2"), "df")
    assert item["suggestion"] == "pending"
    assert item["lean"] is None


def test_g_increments_read_by_range_are_incremental(corpora):
    item = suffix(corpora.evidence("G"), "di")
    assert (item["observation"], item["suggestion"], item["lean"]) == (
        "range_reads", "incremental", None)
    assert item["read_shapes"]["range"] == ["分区列 >= 常量 AND 分区列 <= 常量"]


def test_h_a_suffix_written_and_never_read_is_listed_apart(corpora):
    evidence = corpora.evidence("A")
    written = {item["suffix"]: item for item in evidence["write_only_suffixes"]}
    assert set(written) == {"1d", "rpt"}
    assert written["rpt"]["writes"]["statements"] == 3
    assert all(item["suffix"] not in written for item in evidence["suffixes"])


def test_i_unconditioned_reads_take_the_lean_away(corpora):
    item = suffix(corpora.evidence("I"), "df")
    assert item["reads"]["unconditioned"] == 3
    assert (item["suggestion"], item["lean"]) == ("pending", None)
    assert "分区条件" in item["pending_reason"]


def test_j_low_metadata_coverage_makes_no_suggestion(corpora):
    evidence = corpora.evidence("J")
    assert suffix(evidence, "di")["observation"] == "range_reads"
    assert all(item["suggestion"] is None for item in evidence["suffixes"])
    assert any("80%" in note for note in evidence["notes"])


# ------------------------------------------------------------------ thresholds


def _reads(**counts) -> dict:
    return {kind: counts.get(kind, 0) for kind in pe.READ_KINDS}


@pytest.mark.parametrize(("tables", "reads", "expected"), [
    (3, _reads(range=5), "range_reads"),
    (2, _reads(range=5), "too_few"),
    (3, _reads(range=4), "too_few"),
    (3, _reads(range=9, equality=1), "range_reads"),          # exactly 90%
    (3, _reads(range=8, equality=1, multi_equality=1), "mixed"),
    (3, _reads(equality=9, range=1), "single_partition_reads"),
    (3, _reads(equality=17, range=2), "mixed"),               # 89%
    (3, _reads(range=5, unconditioned=50), "range_reads"),    # unconditioned is outside
])
def test_observation_thresholds(tables, reads, expected):
    assert pe.observe(reads, tables) == expected


def test_five_reads_of_one_table_do_not_reach_the_threshold():
    assert pe.observe(_reads(range=5), 1) == "too_few"


def test_the_unconditioned_share_excludes_unpartitioned_reads():
    writes = {"statements": 1, "window_filtered": 0, "static": 1, "dynamic": 0}
    lean = pe.suggest("single_partition_reads", _reads(equality=9, unconditioned=1,
                                                         unpartitioned=50), writes)
    assert lean[:2] == ("pending", "full")                     # 1/10 = 10%
    over = pe.suggest("single_partition_reads", _reads(equality=8, unconditioned=1), writes)
    assert over[:2] == ("pending", None)                       # 1/9 > 10%


def test_the_tool_never_suggests_full():
    writes = {"statements": 9, "window_filtered": 0, "static": 9, "dynamic": 0}
    for observation in pe.OBSERVATIONS:
        suggestion, lean, _ = pe.suggest(observation, _reads(equality=100), writes)
        assert suggestion != "full"
        assert lean in (None, "full")


# ------------------------------------------------------------------ the command


def test_evidence_without_schema_is_a_usage_error(corpora, tmp_path, capsys):
    with pytest.raises(SystemExit) as raised:
        main(["domain-profile", "evidence", "--lineage", str(corpora.lineage("A")),
              "--out", str(tmp_path / "e")])
    assert raised.value.code == 2


def test_an_unreadable_lineage_exits_2(tmp_path, corpora):
    code = main(["domain-profile", "evidence", "--lineage", str(tmp_path / "missing"),
                 "--schema", str(corpora.schema("A")), "--out", str(tmp_path / "e")])
    assert code == 2


def test_the_summary_line(corpora, tmp_path, capsys):
    code = main(["domain-profile", "evidence", "--lineage", str(corpora.lineage("G")),
                 "--schema", str(corpora.schema("G")), "--out", str(tmp_path / "e")])
    assert code == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("Evidence for 12 corpus table(s), 12 found in metadata (100%): ")
    assert "1 incremental, 0 pending," in line
    assert "(truncated 0)" in line


def test_the_same_input_writes_the_same_bytes(corpora, tmp_path):
    outs = []
    for name in ("one", "two"):
        out = tmp_path / name
        assert main(["domain-profile", "evidence", "--lineage", str(corpora.lineage("F")),
                     "--schema", str(corpora.schema("F")), "--out", str(out)]) == 0
        outs.append(out)
    for file in ("evidence.json", "evidence.md"):
        assert (outs[0] / file).read_bytes() == (outs[1] / file).read_bytes()


def test_the_evidence_records_its_inputs_and_rules(corpora):
    evidence = corpora.evidence("G")
    assert evidence["doc_format"] == "domain-profile-evidence/1"
    assert evidence["suffix_rules"] == pe.SUFFIX_RULES
    assert len(evidence["inputs"]["lineage_digest"]) == 64
    assert not evidence["inputs"]["lineage"].startswith("/")


# ------------------------------------------------------------------ material


def test_comments_come_from_the_metadata_first(corpora):
    evidence = corpora.evidence("G")
    columns = {item["comment"]: item for item in evidence["qualifier_material"]["columns"]}
    assert columns["订单金额"]["numeric"] is True
    assert columns["订单金额"]["from"] == "schema"
    # numeric columns lead
    first = evidence["qualifier_material"]["columns"][0]
    assert first["numeric"] is True


def test_comments_fall_back_to_the_lineage(corpora, tmp_path):
    """G parsed with every table's metadata, read against J's three: the other tables'
    comments are the ones the parse carried into the lineage."""
    out = tmp_path / "e"
    assert main(["domain-profile", "evidence", "--lineage", str(corpora.lineage("G")),
                 "--schema", str(corpora.schema("J")), "--out", str(out)]) == 0
    evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    tables = {item["source"]: item for item in evidence["qualifier_material"]["tables"]}
    assert tables["dwd.o_a_di"]["from"] == "schema"
    assert tables["ads.r_a_x"]["from"] == "lineage"
    assert evidence["coverage"] == {"tables": 12, "found": 3}


def test_concept_material(corpora):
    evidence = corpora.evidence("G")
    tokens = {item["token"]: item["count"] for item in evidence["concept_material"]["table_tokens"]}
    assert tokens["di"] == 3 and tokens["dwd"] == 3
    keys = {item["comment"] for item in evidence["concept_material"]["key_comments"]}
    assert keys == {"订单编号"}
    assert evidence["builtin"]["qualifier_terms"]
    assert set(evidence["builtin"]["concept_words"]) == {
        "event", "entity", "summary", "measure_suffixes", "filter_words"}


def _material_evidence(columns: list[dict], key_comments: int = 0) -> dict:
    return {
        "doc_format": pe.EVIDENCE_FORMAT, "inputs": {}, "suffix_rules": pe.SUFFIX_RULES,
        "coverage": {"tables": 1, "found": 1}, "suffixes": [], "write_only_suffixes": [],
        "qualifier_material": {"columns": columns, "tables": []},
        "concept_material": {
            "table_tokens": [], "table_comments": [],
            "key_comments": [{"comment": f"k{i}", "count": 1, "source": f"d.t{i}.k", "from": "schema"}
                             for i in range(key_comments)],
        },
        "builtin": {"qualifier_terms": [], "concept_words": {}}, "notes": [],
    }


def _column(i: int, *, numeric: bool, count: int = 1) -> dict:
    return {"comment": f"c{i}", "count": count, "numeric": numeric,
            "source": f"d.t.c{i}", "from": "schema"}


def test_the_markdown_truncates_and_says_by_how_much():
    # Qualifier material keeps up to 1200 entries; concept material up to 400.
    evidence = _material_evidence([_column(i, numeric=False) for i in range(1250)], key_comments=450)
    text = pe.render_evidence_markdown(evidence)
    assert "另有 50 条未列出，见 evidence.json" in text
    assert pe.truncated_count(evidence) == 100


def test_qualifier_material_up_to_the_limit_is_not_truncated():
    evidence = _material_evidence([_column(i, numeric=False) for i in range(1200)])
    text = pe.render_evidence_markdown(evidence)
    assert "未列出" not in text
    assert pe.truncated_count(evidence) == 0


def test_numeric_columns_are_kept_before_more_frequent_others():
    # Qualifiers are mostly written on measure columns: a rare numeric column's comment
    # survives truncation ahead of frequent non-numeric ones.
    columns = [_column(i, numeric=False, count=5) for i in range(1200)]
    columns.append(_column(9999, numeric=True, count=1))
    text = pe.render_evidence_markdown(_material_evidence(columns))
    assert "c9999" in text
    assert "另有 1 条未列出" in text


def _window_filtered(tmp_path, read_condition: str, *, source_known: bool) -> int:
    """``window_filtered`` of one write reading ``ods.o_src_di`` under ``read_condition``."""
    def column(name, index, partition=0):
        return {"columnName": name, "columnType": "string", "columnComment": name,
                "columnIndex": index, "isPartition": partition}

    tables = [{"table_name": "dwd.o_out_di", "table_desc": "out", "is_partition": 1,
               "schema": [column("id", 0), column("dt", 1, partition=1)]}]
    if source_known:
        tables.append({"table_name": "ods.o_src_di", "table_desc": "src", "is_partition": 1,
                       "schema": [column("id", 0), column("biz_date", 1),
                                  column("status", 2), column("dt", 3, partition=1)]})
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "w.json").write_text(json.dumps({"meta": {"task_name": "w", "sql": (
        "INSERT OVERWRITE TABLE dwd.o_out_di PARTITION (dt = '${dt}') "
        f"SELECT s.id FROM ods.o_src_di s WHERE {read_condition} AND s.status = 1")}}),
        encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"tables": tables}), encoding="utf-8")
    assert main(["parse", "--input-dir", str(tasks), "--schema", str(schema),
                 "--out", str(tmp_path / "lineage")]) == 0
    assert main(["domain-profile", "evidence", "--lineage", str(tmp_path / "lineage"),
                 "--schema", str(schema), "--out", str(tmp_path / "evidence")]) == 0
    evidence = json.loads((tmp_path / "evidence" / "evidence.json").read_text(encoding="utf-8"))
    return suffix(evidence, "di")["writes"]["window_filtered"]


def test_a_parameter_equality_on_an_input_without_metadata_is_no_window_filter(tmp_path):
    """Without metadata the tool cannot tell ``s.dt = '${dt}'`` reads a partition; it is a
    ``parameter_equality``, not a business-date window, so it filters no write."""
    assert _window_filtered(tmp_path, "s.dt = '${dt}'", source_known=False) == 0


def test_a_parameter_equality_on_a_described_input_stays_a_window(tmp_path):
    assert _window_filtered(tmp_path, "s.biz_date = '${dt}'", source_known=True) == 1


def test_small_suffixes_without_partition_reads_fold_into_one_line(corpora, tmp_path):
    out = tmp_path / "e"
    assert main(["domain-profile", "evidence", "--lineage", str(corpora.lineage("E")),
                 "--schema", str(corpora.schema("E")), "--out", str(out)]) == 0
    text = (out / "evidence.md").read_text(encoding="utf-8")
    assert "`2024`" in text and "`list`" in text
    json.loads((out / "evidence.json").read_text(encoding="utf-8"))
