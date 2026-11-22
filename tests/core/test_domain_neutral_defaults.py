"""WP11: the package ships no business-domain vocabulary and no warehouse naming rule.

Three places used to carry them as built-in defaults:

* check 12's qualifier list held two lending / payment words, and matched every term as
  a substring -- 「纳税人识别号」 was read as a comment qualified by 「税」;
* check 9 read a table-name suffix (``_df`` / ``_full`` / ``_snapshot``) as proof that each
  partition holds a full copy, so one ``fail`` rested on a naming convention alone;
* the concept layer's word votes, measure suffixes and filter words held lending
  lifecycle words.

The defaults now keep only generic terms (税 / 增值税 / 手续费 / 测试, matched as words),
the suffix convention is off unless a caller turns it on, and every domain word comes
from a ``domain-profile/1`` file the caller passes (``--domain-profile``). All names
here are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.domain_profile import (
    DOC_FORMAT,
    DomainProfile,
    DomainProfileError,
    load_domain_profile,
    parse_domain_profile,
)
from scope_lineage.render import concepts as concepts_module
from scope_lineage.render.concepts import (
    CONCEPT_EVENT,
    JUNK_FILTER,
    JUNK_MEASURE,
    JUNK_PERIOD,
    concept_words,
)
from scope_lineage.semantics.checks_context import check_time
from scope_lineage.semantics.checks_documented import (
    QUALIFIER_TERMS,
    check_documented_meaning,
    qualifier_hits,
)
from scope_lineage.semantics.packet_facts import input_time_facts

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PROFILE = ROOT / "examples" / "domain-profile" / "domain-profile.json"

# ------------------------------------------------------------------ check 12 qualifiers


def test_the_default_qualifier_list_holds_only_generic_terms() -> None:
    assert QUALIFIER_TERMS == ("增值税", "税", "手续费", "测试")


@pytest.mark.parametrize("comment", [
    "纳税人识别号",          # 纳税人 is the taxpayer, not a tax-qualified amount
    "税务登记号",            # an identifier
    "测试结果编码",          # the result of a test, not test data
    "税号",                  # the tax number, an identifier
    "the tax id",          # latin is never a substring hit of a Chinese term
])
def test_a_term_inside_a_longer_word_is_no_qualifier(comment: str) -> None:
    assert qualifier_hits(comment, QUALIFIER_TERMS) == []


@pytest.mark.parametrize(("comment", "term"), [
    ("含税金额", "税"),
    ("交易金额（税）", "税"),
    ("税前收入", "税"),
    ("不含税价", "税"),
    ("手续费金额", "手续费"),
    ("核心系统客户注册表（含测试客户）", "测试"),
    ("增值税发票客户", "增值税"),
    ("签约税后收入", "税"),       # a noun before the term does not hide it
    ("所得税税率", "税"),
    ("含税总金额", "税"),
    ("实际_当年签约剔税额", "税"),
])
def test_a_term_standing_as_a_qualifier_still_counts(comment: str, term: str) -> None:
    assert qualifier_hits(comment, QUALIFIER_TERMS) == [term]


def test_a_latin_term_from_a_profile_matches_as_a_whole_word() -> None:
    terms = QUALIFIER_TERMS + ("gross",)
    assert qualifier_hits("Gross amount", terms) == ["gross"]
    assert qualifier_hits("grossing up", terms) == []


def _qualifier_case(comment: str) -> tuple[dict, dict]:
    """A one-column document and a packet whose one source column carries ``comment``."""
    packet = {
        "tasks": [{"sql": "INSERT OVERWRITE TABLE db.t SELECT a FROM db.s"}],
        "target": {"comment": "", "columns": [{"name": "a", "comment": ""}]},
        "inputs": [{"table": "db.s", "comment": "", "driving": True,
                    "columns": [{"name": "a", "comment": comment, "used": True}]}],
        "lineage": {"columns": [{"column": "a", "producers": [{"sources": ["db.s.a"]}]}]},
    }
    document = {
        "summary": {"what": "", "upstream": []},
        "columns": [{"column": "a", "meaning": "编码", "derivation": ""}],
    }
    return document, packet


def _warnings(document: dict, packet: dict, terms=QUALIFIER_TERMS) -> list[dict]:
    return [r for r in check_documented_meaning(document, packet, terms) if r["status"] == "warn"]


def test_a_taxpayer_id_source_column_raises_no_qualifier_warning() -> None:
    document, packet = _qualifier_case("纳税人识别号")
    assert _warnings(document, packet) == []


def test_a_tax_inclusive_source_column_still_raises_the_warning() -> None:
    """The sentinel: the matcher change keeps the warning check 12 exists for."""
    document, packet = _qualifier_case("含税金额")
    (warning,) = _warnings(document, packet)
    assert "「税」" in warning["message"]


def test_a_domain_qualifier_is_raised_only_when_the_caller_lists_it() -> None:
    document, packet = _qualifier_case("冲正后的金额")
    assert _warnings(document, packet) == []
    (warning,) = _warnings(document, packet, QUALIFIER_TERMS + ("冲正",))
    assert "「冲正」" in warning["message"]


# ------------------------------------------------------------------ check 9 suffix rule

TABLE = "db.orders_full"
COLUMNS = [{"name": "dt", "type": "string", "partition": True}]
EQUALITY_READ = [{
    "kind": "filter", "partition_filter": True, "tables": [TABLE],
    "expression": "`o`.`dt` = '${bizdate}'", "statement_id": "stmt:001", "id": "p1",
    "columns": [f"{TABLE}.dt"],
}]
CONVENTION = {"full": ("df", "full", "snapshot"), "incremental": ("di", "inc")}


def test_a_suffix_alone_proves_nothing_without_a_configured_convention() -> None:
    facts = input_time_facts(TABLE, EQUALITY_READ, COLUMNS)
    assert (facts["name_convention"], facts["full_snapshot"]) == ("unknown", False)


def test_check_9_does_not_fail_on_a_table_name_suffix_by_default() -> None:
    facts = input_time_facts(TABLE, EQUALITY_READ, COLUMNS)
    packet = {"inputs": [{"table": TABLE, **facts}]}
    document = {"summary": {"refresh": {"time": "incremental"}}}
    assert [r["status"] for r in check_time(document, packet)] == ["pass"]


def test_a_configured_convention_still_reads_the_suffix() -> None:
    """The sentinel: a caller that turns the convention on keeps the old reading."""
    facts = input_time_facts(TABLE, EQUALITY_READ, COLUMNS, convention=CONVENTION)
    assert (facts["name_convention"], facts["full_snapshot"]) == ("full", True)
    increment = input_time_facts("db.orders_inc", [], COLUMNS, convention=CONVENTION)
    assert increment["name_convention"] == "incremental"


def test_the_check_9_failure_says_it_rests_on_the_name_convention() -> None:
    facts = input_time_facts(TABLE, EQUALITY_READ, COLUMNS, convention=CONVENTION)
    packet = {"inputs": [{"table": TABLE, **facts}]}
    document = {"summary": {"refresh": {"time": "incremental"}}}
    (problem,) = check_time(document, packet)
    assert problem["status"] == "fail"
    assert "表名约定" in problem["message"]


# ------------------------------------------------------------------ concept words


def test_no_lending_word_votes_or_ranks_by_default() -> None:
    assert concepts_module._word_votes("dwd.pay_x 回款") == []
    assert concepts_module._junk_reason("合同欠款") is None
    assert concepts_module._junk_reason("已到期合同") is None
    assert concepts_module._junk_reason("首期合同") is None


def test_the_generic_words_still_vote_and_rank() -> None:
    """The sentinel: what stays is the generic half of each list."""
    assert concepts_module._word_votes("dwd.order_x 交易流水") == [CONCEPT_EVENT]
    assert concepts_module._junk_reason("合同金额") == JUNK_MEASURE
    assert concepts_module._junk_reason("本月合同") == JUNK_PERIOD
    assert concepts_module._junk_reason("合同当日") == JUNK_FILTER


def test_caller_words_vote_and_rank_while_they_are_in_force() -> None:
    words = {"event": ["回款"], "measure_suffixes": ["欠款"], "filter_words": ["已到期"]}
    with concept_words(words):
        assert concepts_module._word_votes("dwd.pay_x 回款") == [CONCEPT_EVENT]
        assert concepts_module._junk_reason("合同欠款") == JUNK_MEASURE
        assert concepts_module._junk_reason("已到期合同") == JUNK_FILTER
    assert concepts_module._word_votes("dwd.pay_x 回款") == []


# ------------------------------------------------------------------ the profile file


def test_an_empty_profile_changes_nothing() -> None:
    profile = parse_domain_profile({"doc_format": DOC_FORMAT})
    assert profile == DomainProfile()
    assert profile.name_convention is None


def test_a_profile_reads_every_section() -> None:
    profile = parse_domain_profile({
        "doc_format": DOC_FORMAT,
        "qualifier_terms": ["gross"],
        "table_name_convention": {"full": ["DF"], "incremental": ["di"]},
        "concept_words": {"event": ["shipment"], "filter_words": ["expired"]},
    })
    assert profile.qualifier_terms == ("gross",)
    assert profile.name_convention == {"full": ("df",), "incremental": ("di",)}
    assert profile.concept_words == {"event": ("shipment",), "filter_words": ("expired",)}


@pytest.mark.parametrize(("document", "said"), [
    ({"doc_format": "other/1"}, "doc_format"),
    ({"doc_format": DOC_FORMAT, "qualifer_terms": []}, "qualifer_terms"),
    ({"doc_format": DOC_FORMAT, "qualifier_terms": "税"}, "qualifier_terms"),
    ({"doc_format": DOC_FORMAT, "qualifier_terms": [""]}, "qualifier_terms"),
    ({"doc_format": DOC_FORMAT, "table_name_convention": {"full": ["d f"]}}, "full"),
    ({"doc_format": DOC_FORMAT, "table_name_convention": {"monthly": ["mf"]}}, "monthly"),
    ({"doc_format": DOC_FORMAT, "concept_words": {"verb": ["x"]}}, "verb"),
    ([], "object"),
])
def test_a_malformed_profile_is_refused_with_the_field_named(document, said: str) -> None:
    with pytest.raises(DomainProfileError, match=said):
        parse_domain_profile(document)


def test_the_example_profile_loads_and_holds_no_lending_word() -> None:
    profile = load_domain_profile(EXAMPLE_PROFILE)
    assert profile.name_convention is not None
    from tests.architecture.test_domain_neutral_literals import DOMAIN_WORDS

    words = [*profile.qualifier_terms, *(w for ws in profile.concept_words.values() for w in ws)]
    assert not [word for word in words for banned in DOMAIN_WORDS if banned in word]


# ------------------------------------------------------------------ the CLI entries


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("argv", [
    ["semantic", "packet", "--lineage", "x", "--tasks", "x", "--out", "x"],
    ["semantic", "validate", "x", "--packets", "x"],
    ["ontology", "--lineage", "x", "--out", "x"],
])
def test_a_bad_profile_stops_each_command_with_exit_2(tmp_path: Path, argv, capsys) -> None:
    from scope_lineage.cli import main

    bad = _write(tmp_path / "p.json", {"doc_format": "nope/1"})
    assert main([*argv, "--domain-profile", str(bad)]) == 2
    assert "domain-profile" in capsys.readouterr().err


# ------------------------------------------------------------------ end to end


@pytest.fixture(scope="module")
def demo_lineage(tmp_path_factory) -> Path:
    from .catalog_demo import CORPUS
    from .table_semantics_demo import parse_corpus

    return parse_corpus(CORPUS, tmp_path_factory.mktemp("wp11") / "lineage")


def test_packing_without_a_profile_reads_no_suffix_and_check_9_stays_quiet(
    demo_lineage: Path, tmp_path: Path
) -> None:
    from .catalog_demo import CORPUS
    from .table_semantics_demo import example, pack, packet_of, run, write_json

    assert pack(CORPUS, demo_lineage, tmp_path / "plain", profile=None) == 0
    assert pack(CORPUS, demo_lineage, tmp_path / "named") == 0
    plain, named = packet_of(tmp_path / "plain"), packet_of(tmp_path / "named")
    assert [(i["name_convention"], i["full_snapshot"]) for i in plain["inputs"]] == [
        ("unknown", False)]
    assert [(i["name_convention"], i["full_snapshot"]) for i in named["inputs"]] == [
        ("full", True)]

    document = example()
    document["summary"]["refresh"]["time"] = "incremental"
    for name in ("plain", "named"):
        document["packet_digest"] = packet_of(tmp_path / name)["packet_digest"]
        write_json(tmp_path / f"docs-{name}" / "doc.json", document)
    assert run("semantic", "validate", tmp_path / "docs-plain", "--packets", tmp_path / "plain") == 0
    assert run("semantic", "validate", tmp_path / "docs-named", "--packets", tmp_path / "named") == 1


def test_validate_adds_the_profile_qualifiers(demo_lineage: Path, tmp_path: Path, capsys) -> None:
    from .catalog_demo import CORPUS
    from .table_semantics_demo import example, pack, packet_of, run, write_json

    packets = tmp_path / "packets"
    assert pack(CORPUS, demo_lineage, packets) == 0
    packet = packet_of(packets)
    packet["inputs"][0]["comment"] = "客户注册表（冲正后）"
    write_json(packets / packet["target"]["table"] / "packet.json", packet)
    write_json(tmp_path / "docs" / "doc.json",
               {**example(), "packet_digest": packet["packet_digest"]})
    profile = _write(tmp_path / "p.json", {"doc_format": DOC_FORMAT, "qualifier_terms": ["冲正"]})

    run("semantic", "validate", tmp_path / "docs", "--packets", packets, "--json")
    assert "「冲正」" not in capsys.readouterr().out
    run("semantic", "validate", tmp_path / "docs", "--packets", packets, "--json",
        "--domain-profile", profile)
    assert "「冲正」" in capsys.readouterr().out


def test_the_ontology_command_adds_the_profile_words(demo_lineage: Path, tmp_path: Path) -> None:
    from .table_semantics_demo import read_json, run

    profile = _write(tmp_path / "p.json", {
        "doc_format": DOC_FORMAT, "concept_words": {"event": ["borrowers"]}})

    def votes(out: Path, *extra) -> set:
        assert run("ontology", "--lineage", demo_lineage, "--out", out, "--format", "json",
                   "--no-cache", *extra) == 0
        return {
            (vote.get("table"), vote["vote"])
            for concept in read_json(out / "ontology.json")["concepts"]
            for vote in concept["kind_evidence"] if vote["signal"] == "word_hint"
        }

    plain = votes(tmp_path / "plain")
    worded = votes(tmp_path / "worded", "--domain-profile", profile)
    assert ("demo_dwd.dwd_lending_borrower_df", CONCEPT_EVENT) in worded - plain
