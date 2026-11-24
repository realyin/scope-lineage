"""The small text rules every table-semantics module shares.

A table is named ``db.table`` everywhere in this package, whatever catalog prefix the
script or the schema spelt it with; a column reference is ``db.table.column``; a SQL
fragment is compared in one normalized form, and a question's text in a folded one. And
a packet is scrubbed of owners and email addresses on its way out, whatever its inputs
carried.
"""

from __future__ import annotations

import re
import unicodedata

from ..redaction import mask_emails

# Keys that name a person. Dropped wherever they appear in a packet: the lineage contract
# carries `task_meta.owner`, the semantic profile `target_table_owner` and `inputs[].owner`,
# and a schema export may add any of the others.
OWNER_KEYS = frozenset({"owner", "owner_name", "owner_email", "target_table_owner", "tbl_pic"})


def bare_table(name: object) -> str:
    """``db.table`` in lower case: a leading catalog and identifier quotes dropped."""
    parts = [part.strip("`") for part in str(name or "").strip().split(".") if part]
    return ".".join(parts[-2:]).lower()


def bare_column(reference: object) -> str:
    """``db.table.column`` in lower case, from a three- or four-part reference."""
    parts = [part.strip("`") for part in str(reference or "").strip().split(".") if part]
    return ".".join(parts[-3:]).lower()


def folded_text(text: object) -> str:
    """NFKC with whitespace folded: what two spellings of one question's text are compared
    by -- the question a person answered and the question a document holds now, or a new
    answer and the one already there. Never stored.

    Letter case is kept: ``Y`` and ``y`` may be two different code values, so a question
    whose case changed may ask something else. The catalog's search and its grouping of
    pending definitions fold case as well (``render.catalog_search``,
    ``render.catalog_pending``): they find and group related texts, this one decides that
    two texts are the same question.
    """
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).split())


def scrub(value):
    """``value`` with every owner key removed and every email address masked."""
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if key not in OWNER_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return mask_emails(value)
    return value


_QUALIFIER = re.compile(r"\b[a-z_][a-z0-9_]*\.(?=[a-z_$])")
# A comment, or a quoted string (single or double, backslash escapes). Only the string is
# protected; a comment is matched so an apostrophe in ``-- it's`` opens no string.
_COMMENT_OR_STRING = re.compile(
    r"""(--[^\n]*|/\*.*?\*/)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""", re.DOTALL
)
_LEADING_KEYWORD = re.compile(r"^\s*(?:where|and|or|on|having)\b", re.IGNORECASE)


def strip_leading_keyword(text: object) -> str:
    """``WHERE x = 1`` -> ``x = 1``: a quoted fragment without its clause keyword."""
    return _LEADING_KEYWORD.sub("", str(text or ""))


def normalize_sql(text: object) -> str:
    """One comparable spelling of a SQL fragment.

    Lower case, no identifier quotes, no table qualifiers, no whitespace, ``!=`` as
    ``<>``, and a leading ``WHERE``/``AND``/``ON`` dropped -- so the rendered
    ```latest`.`rn` = 1`` of the lineage, the ``WHERE rn = 1`` a writer quotes and the
    script's own ``latest.rn=1`` are one string.

    A string literal is data, not a qualified name: ``x = 'p.q'`` keeps its ``'p.q'``, so a
    quote that rewrote the literal to ``'q'`` is not the same fragment. Check 5 compares
    the qualifiers this form drops separately (:func:`.sql_forms.qualifiers`).
    """
    result = strip_leading_keyword(text).lower().replace("`", "")
    result = _outside_strings(result, lambda piece: _QUALIFIER.sub("", piece))
    return re.sub(r"\s+", "", result).replace("!=", "<>")


def _outside_strings(text: str, rewrite) -> str:
    """``text`` with ``rewrite`` applied to everything but its string literals."""
    pieces, at = [], 0
    for match in _COMMENT_OR_STRING.finditer(text):
        if match.group(2) is None:
            continue
        pieces += [rewrite(text[at:match.start()]), match.group(2)]
        at = match.end()
    return "".join(pieces) + rewrite(text[at:])
