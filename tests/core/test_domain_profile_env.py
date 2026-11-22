"""5.3: ``SCOPE_LINEAGE_DOMAIN_PROFILE`` stands in for ``--domain-profile``.

A run calls ``semantic packet``, ``semantic validate`` and ``ontology`` many times, some of
them from subagent templates; a profile passed on one command and forgotten on the next
gives check 12 and the packet's ``name_convention`` two different readings in one run.
The environment variable is set once (the runbook's ``env.sh`` exports it) and every
command reads it when the flag is not given. The flag wins when both are given. All names
are synthetic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scope_lineage.cli_semantic import read_domain_profile
from scope_lineage.domain_profile import DOC_FORMAT, DOMAIN_PROFILE_ENV, DomainProfile

from .table_semantics_demo import CORPUS, DEMO_PROFILE, pack, packet_of, parse_corpus, run


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_variable_name() -> None:
    assert DOMAIN_PROFILE_ENV == "SCOPE_LINEAGE_DOMAIN_PROFILE"


# ------------------------------------------------------------------ read_domain_profile


def test_without_flag_or_variable_the_profile_is_empty(monkeypatch, capsys) -> None:
    monkeypatch.delenv(DOMAIN_PROFILE_ENV, raising=False)
    assert read_domain_profile(argparse.Namespace(domain_profile=None)) == DomainProfile()
    assert capsys.readouterr().err == ""


def test_an_empty_variable_counts_as_unset(monkeypatch) -> None:
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, "")
    assert read_domain_profile(argparse.Namespace(domain_profile=None)) == DomainProfile()


def test_the_variable_is_read_when_the_flag_is_absent(monkeypatch, tmp_path, capsys) -> None:
    profile = _write(tmp_path / "p.json", {"doc_format": DOC_FORMAT, "qualifier_terms": ["冲正"]})
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, str(profile))
    read = read_domain_profile(argparse.Namespace(domain_profile=None))
    assert read.qualifier_terms == ("冲正",)
    err = capsys.readouterr().err
    assert str(profile) in err and DOMAIN_PROFILE_ENV in err


def test_the_flag_wins_over_the_variable(monkeypatch, tmp_path, capsys) -> None:
    flag = _write(tmp_path / "flag.json", {"doc_format": DOC_FORMAT, "qualifier_terms": ["甲"]})
    env = _write(tmp_path / "env.json", {"doc_format": DOC_FORMAT, "qualifier_terms": ["乙"]})
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, str(env))
    read = read_domain_profile(argparse.Namespace(domain_profile=str(flag)))
    assert read.qualifier_terms == ("甲",)
    err = capsys.readouterr().err
    assert str(flag) in err and "--domain-profile" in err and str(env) not in err


def test_a_missing_file_named_by_the_variable_exits_2_naming_it(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, str(tmp_path / "absent.json"))
    assert read_domain_profile(argparse.Namespace(domain_profile=None)) == 2
    assert DOMAIN_PROFILE_ENV in capsys.readouterr().err


def test_a_malformed_file_named_by_the_variable_exits_2_naming_it(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, str(_write(tmp_path / "bad.json", {"doc_format": "nope/1"})))
    assert read_domain_profile(argparse.Namespace(domain_profile=None)) == 2
    assert DOMAIN_PROFILE_ENV in capsys.readouterr().err


# ------------------------------------------------------------------ the three commands


@pytest.mark.parametrize("argv", [
    ["semantic", "packet", "--lineage", "x", "--tasks", "x", "--out", "x"],
    ["semantic", "validate", "x", "--packets", "x"],
    ["ontology", "--lineage", "x", "--out", "x"],
])
def test_each_command_reads_the_variable(monkeypatch, tmp_path, argv, capsys) -> None:
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, str(_write(tmp_path / "bad.json", {"doc_format": "nope/1"})))
    assert run(*argv) == 2
    assert DOMAIN_PROFILE_ENV in capsys.readouterr().err


@pytest.fixture(scope="module")
def demo_lineage(tmp_path_factory) -> Path:
    return parse_corpus(CORPUS, tmp_path_factory.mktemp("env") / "lineage")


def test_packing_with_the_variable_equals_packing_with_the_flag(
    monkeypatch, demo_lineage: Path, tmp_path: Path
) -> None:
    monkeypatch.delenv(DOMAIN_PROFILE_ENV, raising=False)
    assert pack(CORPUS, demo_lineage, tmp_path / "flag") == 0
    monkeypatch.setenv(DOMAIN_PROFILE_ENV, str(DEMO_PROFILE))
    assert pack(CORPUS, demo_lineage, tmp_path / "env", profile=None) == 0
    flag, env = packet_of(tmp_path / "flag"), packet_of(tmp_path / "env")
    assert [i["name_convention"] for i in env["inputs"]] == ["full"]
    assert env["packet_digest"] == flag["packet_digest"]
