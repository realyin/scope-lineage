"""The domain-profile writer prompt states check 12's word rule exactly as the code applies it.

The writer has to judge whether a qualifier it found will ever match downstream; the
prompt therefore spells out the characters that make a Chinese term count as a word. If
those sets change in `checks_documented`, the prompt must change with them, or drafts
start citing comments that no longer match.
"""

from __future__ import annotations

from pathlib import Path

from scope_lineage.semantics import checks_documented

PROMPT = (
    Path(__file__).resolve().parents[2]
    / "skills/scope-lineage-ontology/references/domain-profile-prompt.md"
)


def test_the_prompt_names_the_characters_before_a_qualifier():
    assert f"「{checks_documented._QUALIFIER_BEFORE}」" in PROMPT.read_text(encoding="utf-8")


def test_the_prompt_names_the_characters_after_a_qualifier():
    assert f"「{checks_documented._QUALIFIER_AFTER}」" in PROMPT.read_text(encoding="utf-8")
