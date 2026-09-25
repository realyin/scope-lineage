"""The small text rules every table-semantics module shares.

A table is named ``db.table`` everywhere in this package, whatever catalog prefix the
script or the schema spelt it with; a column reference is ``db.table.column``; a SQL
fragment is compared in one normalized form. And a packet is scrubbed of owners and
email addresses on its way out, whatever its inputs carried.
"""

from __future__ import annotations

import re

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
_LEADING_KEYWORD = re.compile(r"^\s*(?:where|and|or|on|having)\b", re.IGNORECASE)


def normalize_sql(text: object) -> str:
    """One comparable spelling of a SQL fragment.

    Lower case, no identifier quotes, no table qualifiers, no whitespace, ``!=`` as
    ``<>``, and a leading ``WHERE``/``AND``/``ON`` dropped -- so the rendered
    ```latest`.`rn` = 1`` of the lineage, the ``WHERE rn = 1`` a writer quotes and the
    script's own ``latest.rn=1`` are one string.
    """
    result = _LEADING_KEYWORD.sub("", str(text or "")).lower().replace("`", "")
    result = _QUALIFIER.sub("", result)
    return re.sub(r"\s+", "", result).replace("!=", "<>")
