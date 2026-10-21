"""The skill carries what a run needs without the tool repository.

A pip-installed ``scope-lineage`` brings the package and its JSON Schemas, not ``docs/``
or ``examples/``; the skill is often installed apart from it. The runbook used to send the
S0 PyYAML check and the catalog drafter (T5) to ``$TOOL/examples/catalog-demo/`` and
``$TOOL/docs/zh-CN/ontology-catalog.md`` -- paths such a machine does not have. The skill
now bundles both, and these tests keep the copies identical to their sources.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = ROOT / "skills" / "scope-lineage" / "references"


def _files(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def test_the_bundled_catalog_demo_is_the_examples_one() -> None:
    assert _files(REFS / "catalog-demo") == _files(ROOT / "examples" / "catalog-demo")


def test_the_bundled_fragment_example_is_the_examples_one() -> None:
    assert _files(REFS / "catalog-fragments") == {
        "disbursement.json": (ROOT / "examples" / "catalog-fragments" / "disbursement.json").read_bytes()
    }


def test_the_bundled_catalog_elements_are_the_docs_sections() -> None:
    docs = (ROOT / "docs" / "zh-CN" / "ontology-catalog.md").read_text(encoding="utf-8")

    def section(head: str, following: str) -> str:
        return docs[docs.index(f"\n## {head}\n") + 1: docs.index(f"\n## {following}\n") + 1]

    expected = section("元素", "校验") + "\n" + section("起草：`catalog digest` 与 `catalog merge`", "安全地写 YAML")
    bundled = (REFS / "catalog-elements.md").read_text(encoding="utf-8")

    assert bundled.split("-->\n\n", 1)[1] == expected


def test_no_template_points_into_the_tool_repository() -> None:
    text = (REFS / "runbook-templates.md").read_text(encoding="utf-8")
    body = text.split("----8<----", 1)[1]

    assert "{TOOL}/" not in body
