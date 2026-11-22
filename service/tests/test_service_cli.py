"""``scope-lineage-service``: refuses to start on inputs the catalog commands refuse."""

from __future__ import annotations

import pytest

from scope_lineage_service.cli import main


@pytest.mark.parametrize("mode", ["http", "mcp"])
def test_an_unreadable_ontology_stops_the_server_with_the_cli_exit_code(
    mode, tmp_path, capsys
) -> None:
    assert main([mode, str(tmp_path / "none.json")]) == 2
    assert "ontology path does not exist" in capsys.readouterr().err


def test_a_missing_semantics_directory_stops_the_server(inputs, tmp_path, capsys) -> None:
    code = main(["http", str(inputs["ontology"]), "--semantics", str(tmp_path / "none")])
    assert code == 2
    assert "--semantics directory does not exist" in capsys.readouterr().err
