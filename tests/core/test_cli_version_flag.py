def test_cli_reports_its_version(capsys):
    import pytest
    from scope_lineage.cli import main
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.strip().split(".")[0].isdigit() or "scope-lineage" in out


def test_cli_version_names_the_parser_and_the_code_it_runs(capsys):
    """A reproduction needs more than the package version, which a source checkout's
    install metadata can leave stale: the sqlglot it ran on and which code it was."""
    import pytest
    import sqlglot
    from scope_lineage.cli import main
    from scope_lineage.corpus_cache import _code_digest
    with pytest.raises(SystemExit):
        main(["--version"])
    out = capsys.readouterr().out
    assert f"sqlglot {sqlglot.__version__}" in out
    assert f"source {_code_digest()[:12]}" in out
