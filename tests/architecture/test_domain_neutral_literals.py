"""Keep business-domain vocabulary out of the package's string literals.

CONTRIBUTING: "Keep every layer domain-neutral ... business-domain rules ... belong in
downstream projects rather than this package." A word list is a rule: once a lending
word sits in a default tuple, every corpus is read as if it were a lending one. Domain
words reach the package as data a caller passes (``--domain-profile``), never as code.

The scan reads every string literal under ``scope_lineage/`` -- f-string parts included
-- and leaves docstrings out: a docstring documents behaviour with an example, it does
not drive any. ``#`` comments are not literals and are not read either.

``DOMAIN_WORDS`` lists only public, generic finance and lending words -- never a term
from a private corpus (those live in the private-surface scanner's secret list). A
literal that must keep one of them goes into ``EXEMPT`` with the reason it is not a
domain rule.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "scope_lineage"

# Chinese matches as a substring (the language writes no word boundaries); latin as a
# whole word, case-insensitively.
DOMAIN_WORDS = (
    "罚息", "冲正", "回款", "欠款", "已还", "未还", "已结清", "未结清", "首期", "逾期",
    "催收", "放款", "还款", "借款", "贷款", "授信", "核销", "展期", "借据", "坏账",
    "loan", "overdue", "repayment", "delinquency", "collateral", "borrower",
)

# ``(path relative to scope_lineage/, word) -> reason``. Empty today.
EXEMPT: dict[tuple[str, str], str] = {}

_CJK = re.compile(r"[一-鿿]")


def _docstrings(tree: ast.AST) -> set[int]:
    """The ids of the constant nodes that are docstrings."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                found.add(id(body[0].value))
    return found


def _hits(text: str) -> list[str]:
    lowered = text.lower()
    return [
        word for word in DOMAIN_WORDS
        if (word in text if _CJK.search(word) else re.search(rf"(?<![a-z0-9]){word}(?![a-z0-9])", lowered))
    ]


def collect_violations(package_root: Path = PACKAGE_ROOT) -> list[str]:
    violations = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in skip:
                continue
            for word in _hits(node.value):
                if (relative, word) not in EXEMPT:
                    violations.append(f"scope_lineage/{relative}:{node.lineno} literal holds {word!r}")
    return violations


def test_no_business_domain_word_in_a_package_literal() -> None:
    violations = collect_violations()
    assert not violations, (
        "domain words in package literals -- move them to a domain-profile/1 file the "
        "caller passes, or add an EXEMPT entry with the reason:\n" + "\n".join(violations)
    )


def test_every_exemption_still_matches_a_literal() -> None:
    """A stale exemption would silently allow the word back."""
    for (relative, word), reason in EXEMPT.items():
        assert reason.strip(), f"{relative}: exemption for {word!r} needs a reason"
        text = (PACKAGE_ROOT / relative).read_text(encoding="utf-8")
        assert word in text, f"{relative}: exemption for {word!r} no longer matches"


def _package(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "scope_lineage"
    root.mkdir()
    (root / "words.py").write_text(text, encoding="utf-8")
    return root


def test_a_word_in_a_default_tuple_is_caught(tmp_path: Path) -> None:
    root = _package(tmp_path, 'TERMS = ("税", "罚息")\nNOTE = f"x {1} overdue"\n')
    assert collect_violations(root) == [
        "scope_lineage/words.py:1 literal holds '罚息'",
        "scope_lineage/words.py:2 literal holds 'overdue'",
    ]


def test_docstrings_and_partial_latin_words_are_not_caught(tmp_path: Path) -> None:
    root = _package(tmp_path, '"""A 回款 example."""\n\ndef f():\n    """loan."""\n    return "loans_x"\n')
    assert collect_violations(root) == []
