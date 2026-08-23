def test_cli_reports_its_version(capsys):
    import pytest
    from scope_lineage.cli import main
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.strip().split(".")[0].isdigit() or "scope-lineage" in out
