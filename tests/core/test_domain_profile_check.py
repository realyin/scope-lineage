"""``domain-profile check``: a draft holds only what its evidence, its reasons and a
person's confirmations support (USAGE「domain-profile check」)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.semantics import profile_check as pc

from .domain_profile_corpora import Corpora


def _evidence(**changes) -> dict:
    """A small evidence document: one incremental suffix, one pending, some material."""
    evidence = {
        "doc_format": "domain-profile-evidence/1",
        "inputs": {"lineage_digest": "0" * 64, "tool_version": pc.current_version()},
        "suffixes": [
            {"suffix": "inc", "suggestion": "incremental", "lean": None},
            {"suffix": "snap", "suggestion": "pending", "lean": "full"},
            {"suffix": "type", "suggestion": None, "lean": None},
        ],
        "write_only_suffixes": [],
        "qualifier_material": {
            "columns": [{"comment": "运费金额", "count": 1, "numeric": True,
                         "source": "d.t.c", "from": "schema"},
                        {"comment": "Coupon amount", "count": 1, "numeric": True,
                         "source": "d.t.k", "from": "schema"},
                        {"comment": "含税金额", "count": 1, "numeric": True,
                         "source": "d.t.x", "from": "schema"}],
            "tables": [{"comment": "门店下单流水", "count": 1, "source": "d.t", "from": "schema"}],
        },
        "concept_material": {
            "table_tokens": [{"token": "shop", "count": 1, "source": "d.shop_inc"}],
            "table_comments": [{"comment": "门店下单流水", "count": 1, "source": "d.t",
                                "from": "schema"}],
            "key_comments": [{"comment": "商品销量", "count": 1, "source": "d.t.g",
                              "from": "schema"}],
        },
        "builtin": {},
        "notes": [],
    }
    evidence.update(changes)
    return evidence


def _profile(**sections) -> dict:
    return {"doc_format": "domain-profile/1", **sections}


def _reasons(*written, pending=()) -> str:
    lines = ["# 理由", "", "## 已写入", ""]
    lines += [f"- `{key}` `{value}`：理由。依据：evidence" for key, value in written]
    lines += ["", "## 待确认", ""]
    lines += [f"- `{key}` `{value}`: 倾向全量，需要人确认" for key, value in pending]
    return "\n".join(lines) + "\n"


def _confirmed(*entries) -> dict:
    return {
        "doc_format": "domain-profile-confirmations/1",
        "confirmed_by": "owner",
        "confirmed_at": "2026-11-22",
        "entries": [dict(zip(("key", "value", "decision"), entry)) for entry in entries],
    }


def _check(profile, reasons, evidence=None, confirmed=None) -> pc.CheckResult:
    return pc.check_profile(profile, reasons, evidence or _evidence(), confirmed)


GOOD = _profile(
    qualifier_terms=["运费"],
    table_name_convention={"incremental": ["inc"]},
    concept_words={"event": ["下单"], "entity": ["SHOP"], "measure_suffixes": ["销量"],
                   "filter_words": ["门店"]},
)
GOOD_REASONS = _reasons(
    ("qualifier_terms", "运费"), ("table_name_convention.incremental", "inc"),
    ("concept_words.event", "下单"), ("concept_words.entity", "SHOP"),
    ("concept_words.measure_suffixes", "销量"), ("concept_words.filter_words", "门店"),
    pending=[("table_name_convention.full", "snap")],
)


def test_a_grounded_draft_passes():
    result = _check(GOOD, GOOD_REASONS)
    assert result.errors == []


def test_a_latin_word_matches_whole_and_in_any_case():
    """``SHOP`` in the draft, ``shop`` among the table-name words: the concept layer's rule."""
    assert _check(GOOD, GOOD_REASONS).errors == []


def test_an_unknown_key_is_a_format_error_reported_alone():
    result = _check({**GOOD, "extra": 1, "qualifier_terms": ["无依据"]}, GOOD_REASONS)
    assert len(result.errors) == 1
    assert "unknown key" in result.errors[0]


def test_a_suffix_without_a_suggestion_is_an_error():
    draft = _profile(table_name_convention={"incremental": ["type"]})
    result = _check(draft, _reasons(("table_name_convention.incremental", "type")))
    assert any("type" in error for error in result.errors)


def test_a_suffix_written_into_the_opposite_class_is_an_error():
    draft = _profile(table_name_convention={"full": ["inc"]})
    result = _check(draft, _reasons(("table_name_convention.full", "inc")))
    assert any("inc" in error for error in result.errors)


def test_full_is_never_grounded_by_the_evidence_alone():
    draft = _profile(table_name_convention={"full": ["snap"]})
    result = _check(draft, _reasons(("table_name_convention.full", "snap")))
    assert any("snap" in error for error in result.errors)


def test_a_qualifier_found_as_a_substring_only_has_no_ground():
    """「店」 sits inside 门店下单流水 but is no word of it under check 12's rule."""
    draft = _profile(qualifier_terms=["店"])
    result = _check(draft, _reasons(("qualifier_terms", "店")))
    assert result.errors and "店" in result.errors[0]


def test_a_latin_qualifier_matches_in_any_case():
    draft = _profile(qualifier_terms=["coupon"])
    assert _check(draft, _reasons(("qualifier_terms", "coupon"))).errors == []


def test_a_measure_suffix_only_in_the_middle_has_no_ground():
    draft = _profile(concept_words={"measure_suffixes": ["商品"]})
    result = _check(draft, _reasons(("concept_words.measure_suffixes", "商品")))
    assert result.errors


def test_an_entry_without_a_reason_line_is_an_error():
    result = _check(GOOD, _reasons(("qualifier_terms", "运费")))
    assert any("concept_words.event" in error for error in result.errors)


def test_reason_lines_take_either_colon_and_the_full_key_path():
    text = GOOD_REASONS.replace("：", ":")
    assert _check(GOOD, text).errors == []
    reasons = pc.parse_reasons(GOOD_REASONS)
    assert ("table_name_convention.full", "snap") in reasons.pending
    assert ("concept_words.entity", "SHOP") in reasons.written


def test_a_pending_line_is_no_reason_for_a_draft_entry():
    draft = _profile(qualifier_terms=["运费"])
    result = _check(draft, _reasons(pending=[("qualifier_terms", "运费")]))
    assert result.errors


# ------------------------------------------------------------------ confirmations


def test_an_accepted_suffix_passes_only_with_the_confirmations():
    draft = _profile(table_name_convention={"full": ["snap"], "incremental": ["inc"]})
    reasons = _reasons(("table_name_convention.full", "snap"),
                       ("table_name_convention.incremental", "inc"))
    assert _check(draft, reasons).errors
    confirmed = _confirmed(("table_name_convention.full", "snap", "accept"))
    assert _check(draft, reasons, confirmed=confirmed).errors == []


def test_a_rejected_entry_in_the_draft_is_an_error():
    confirmed = _confirmed(("qualifier_terms", "运费", "reject"))
    result = _check(GOOD, GOOD_REASONS, confirmed=confirmed)
    assert any("reject" in error for error in result.errors)


def test_an_accepted_word_still_needs_its_material():
    draft = _profile(qualifier_terms=["优惠券"])
    confirmed = _confirmed(("qualifier_terms", "优惠券", "accept"))
    result = _check(draft, _reasons(("qualifier_terms", "优惠券")), confirmed=confirmed)
    assert any("下游匹配不到" in error for error in result.errors)


def test_an_accepted_entry_missing_from_the_draft_is_an_error():
    confirmed = _confirmed(("table_name_convention.full", "snap", "accept"))
    result = _check(GOOD, GOOD_REASONS, confirmed=confirmed)
    assert any("snap" in error for error in result.errors)


def test_confirmations_with_an_unknown_key_are_an_error():
    confirmed = {**_confirmed(), "approved": True}
    result = _check(GOOD, GOOD_REASONS, confirmed=confirmed)
    assert any("approved" in error for error in result.errors)


@pytest.mark.parametrize("entry", [
    {"key": "qualifier_terms", "value": "运费", "decision": "maybe"},
    {"key": "table_name_convention.half", "value": "x", "decision": "accept"},
    {"key": "qualifier_terms", "value": "运费", "decision": "accept", "by": "x"},
])
def test_a_malformed_confirmation_entry_is_an_error(entry):
    confirmed = {**_confirmed(), "entries": [entry]}
    assert _check(GOOD, GOOD_REASONS, confirmed=confirmed).errors


# ------------------------------------------------------------------ hints


def test_a_suggested_suffix_left_out_is_a_hint_only():
    draft = _profile(qualifier_terms=["运费"])
    result = _check(draft, _reasons(("qualifier_terms", "运费")))
    assert result.errors == []
    assert any("inc" in hint for hint in result.hints)


def test_a_word_that_changes_no_hit_is_a_hint_only():
    """「税」 is built in and already hits 含税金额; 「含税」 adds no comment to the hits."""
    draft = _profile(qualifier_terms=["含税"])
    result = _check(draft, _reasons(("qualifier_terms", "含税")))
    assert result.errors == []
    assert any("含税" in hint for hint in result.hints)


def test_a_repeated_word_is_a_hint_only():
    draft = _profile(qualifier_terms=["运费", "运费"])
    result = _check(draft, _reasons(("qualifier_terms", "运费")))
    assert result.errors == []
    assert any("重复" in hint for hint in result.hints)


def test_a_changed_tool_version_is_a_hint():
    evidence = _evidence(inputs={"lineage_digest": "0" * 64, "tool_version": "0.0.0"})
    result = _check(GOOD, GOOD_REASONS, evidence=evidence)
    assert result.errors == []
    assert any("0.0.0" in hint for hint in result.hints)


# ------------------------------------------------------------------ the command


def _write(path: Path, value) -> str:
    path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                    encoding="utf-8")
    return str(path)


def _run(tmp_path, profile, reasons=GOOD_REASONS, evidence=None, *extra) -> int:
    return main([
        "domain-profile", "check",
        "--profile", _write(tmp_path / "draft.json", profile),
        "--reasons", _write(tmp_path / "reasons.md", reasons),
        "--evidence", _write(tmp_path / "evidence.json", evidence or _evidence()),
        *extra,
    ])


def test_the_command_exits_0_on_a_grounded_draft(tmp_path, capsys):
    assert _run(tmp_path, GOOD) == 0
    assert "0 error(s)" in capsys.readouterr().out


def test_the_command_exits_1_on_an_error(tmp_path, capsys):
    assert _run(tmp_path, _profile(qualifier_terms=["优惠券"]),
                _reasons(("qualifier_terms", "优惠券"))) == 1


def test_a_draft_that_is_not_json_exits_1(tmp_path):
    assert _run(tmp_path, "{not json") == 1


def test_a_missing_file_exits_2(tmp_path):
    code = main(["domain-profile", "check", "--profile", str(tmp_path / "none.json"),
                 "--reasons", _write(tmp_path / "r.md", GOOD_REASONS),
                 "--evidence", _write(tmp_path / "e.json", _evidence())])
    assert code == 2


def test_reasons_and_evidence_are_required_without_format_only(tmp_path):
    with pytest.raises(SystemExit) as raised:
        main(["domain-profile", "check", "--profile", _write(tmp_path / "p.json", GOOD)])
    assert raised.value.code == 2


def test_format_only_needs_only_the_profile(tmp_path):
    path = _write(tmp_path / "p.json", _profile(qualifier_terms=["没有依据也行"]))
    assert main(["domain-profile", "check", "--profile", path, "--format-only"]) == 0
    bad = _write(tmp_path / "bad.json", _profile(qualifier_terms="x"))
    assert main(["domain-profile", "check", "--profile", bad, "--format-only"]) == 1


def test_confirmed_file_is_read(tmp_path):
    draft = _profile(table_name_convention={"full": ["snap"]})
    reasons = _reasons(("table_name_convention.full", "snap"))
    confirmed = _write(tmp_path / "confirmed.json",
                       _confirmed(("table_name_convention.full", "snap", "accept")))
    assert _run(tmp_path, draft, reasons, None) == 1
    assert _run(tmp_path, draft, reasons, None, "--confirmed", confirmed) == 0


def test_a_changed_lineage_is_a_stale_hint(tmp_path, capsys):
    corpora = Corpora(tmp_path / "c")
    lineage = corpora.lineage("G")
    out = tmp_path / "e"
    assert main(["domain-profile", "evidence", "--lineage", str(lineage),
                 "--schema", str(corpora.schema("G")), "--out", str(out)]) == 0
    evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    draft = _profile(table_name_convention={"incremental": ["di"]})
    reasons = _reasons(("table_name_convention.incremental", "di"))
    capsys.readouterr()
    assert _run(tmp_path, draft, reasons, evidence, "--lineage", str(lineage)) == 0
    assert "过期" not in capsys.readouterr().out
    first = sorted(lineage.rglob("lineage.json"))[0]
    first.write_text(first.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert _run(tmp_path, draft, reasons, evidence, "--lineage", str(lineage)) == 0
    assert "过期" in capsys.readouterr().out


def test_parse_evidence_check_end_to_end(tmp_path):
    """parse -> evidence -> check on fixture F: the pending snapshot suffix stays out."""
    corpora = Corpora(tmp_path / "c")
    out = tmp_path / "e"
    assert main(["domain-profile", "evidence", "--lineage", str(corpora.lineage("F")),
                 "--schema", str(corpora.schema("F")), "--out", str(out)]) == 0
    evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    draft = _profile(qualifier_terms=["订单金额"])
    reasons = _reasons(("qualifier_terms", "订单金额"), pending=[("table_name_convention.full", "df")])
    assert _run(tmp_path, draft, reasons, evidence) == 0
    with_df = _profile(table_name_convention={"full": ["df"]})
    assert _run(tmp_path, with_df, _reasons(("table_name_convention.full", "df")), evidence) == 1
