"""4.5-d: the SHACL and LinkML writers escape every control character.

Both escaped only ``\\``, ``"``, ``\\n`` and ``\\t``. A comment holding a carriage return
(``客户\\r编号``) went out raw: Turtle forbids a raw ``#xD`` inside a quoted string, so the
file was not valid Turtle, and a YAML reader folded the value to ``客户 编号``.
"""

from __future__ import annotations

import re

import pytest

from scope_lineage.render.ontology_export import _turtle_string, _yaml_scalar

yaml = pytest.importorskip("yaml")

TEXTS = ["客户\r编号", "a\r\nb", "x\x00y\x1fz\x7f", "tab\there", "quote\"back\\slash", "line\nbreak"]
#: Turtle's STRING_LITERAL_QUOTE: no raw ", \, LF or CR; and this writer emits no other C0.
TURTLE_STRING = re.compile(r'^"(?:[^"\\\x00-\x1f]|\\["\\nrtbf]|\\u[0-9A-F]{4})*"$')


@pytest.mark.parametrize("text", TEXTS)
def test_a_yaml_scalar_round_trips_exactly(text: str) -> None:
    written = _yaml_scalar(text)
    assert not re.search(r"[\x00-\x1f]", written)
    assert yaml.safe_load(f"k: {written}")["k"] == text


@pytest.mark.parametrize("text", TEXTS)
def test_a_turtle_string_holds_no_raw_control_character(text: str) -> None:
    written = _turtle_string(text)
    assert TURTLE_STRING.match(written), written


def test_plain_text_is_written_as_before() -> None:
    """Sentinel: nothing changes for text without control characters."""
    assert _yaml_scalar("客户编号") == '"客户编号"'
    assert _turtle_string("客户编号") == '"客户编号"'
    assert _yaml_scalar("a\nb") == '"a\\nb"'
    assert _turtle_string("a\tb") == '"a\\tb"'
