"""What the owner already confirmed, laid beside the comments and columns of a packet.

Two answers can reach a packet besides the metadata and the lineage: a comment written
back through a reviewed ``metadata-patch/1`` file, and a value meaning written into the
corpus glossary (``glossary-json/1`` ``values[].meaning``). Both are somebody's word, not
a reading of the corpus, so the writer must take them as they stand -- never guess the
meaning again, never ask for it again. The command line applies the patch to every
comment before the packet is built; this module only says which comments the packet
shows came from it (``comment_source: "patch"``) and which values of a column already
carry a confirmed meaning (``confirmed_values``).

Both keys appear only when there is something to say, so a packet built without either
input is byte for byte the packet built before they existed.
"""

from __future__ import annotations

from typing import Mapping

from ..redaction import redact
from ..render.glossary_values import same_table
from .names import bare_table

PATCH = "patch"


class Confirmed:
    """The glossary's confirmed values and the patch's comments, indexed for lookup.

    ``glossary`` is a ``glossary-json/1`` document; ``patched`` is the patch as plain
    data, ``{"tables": {db.table: [comment texts]}, "columns": {db.table.column: text}}``.
    A comment is marked only when it IS the patch's answer: a table whose patch gave a
    description but kept the schema's name shows the schema's name, and says nothing.
    """

    def __init__(self, glossary: Mapping | None = None, patched: Mapping | None = None):
        self._values: dict[str, list[tuple[str, Mapping]]] = {}
        for entry in (glossary or {}).get("values") or []:
            meaning = entry.get("meaning") or {}
            if entry.get("logical") or not meaning.get("text"):
                continue
            owner, _, column = str(entry.get("column_ref") or "").rpartition(".")
            name = str(entry.get("column") or column).lower()
            self._values.setdefault(name, []).append((owner.lower(), entry))
        patched = patched or {}
        self._tables = {
            bare_table(table): {redact(text) for text in texts if text}
            for table, texts in (patched.get("tables") or {}).items()
        }
        self._columns = {
            str(reference).lower(): redact(text)
            for reference, text in (patched.get("columns") or {}).items()
            if text
        }

    def table_source(self, table: str, comment) -> dict:
        """``{"comment_source": "patch"}`` when the table comment shown is the patch's."""
        patched = comment and comment in self._tables.get(table, ())
        return {"comment_source": PATCH} if patched else {}

    def column_source(self, table: str, column: str, comment) -> dict:
        """``{"comment_source": "patch"}`` when the column comment shown is the patch's."""
        answer = self._columns.get(f"{table}.{column}".lower())
        return {"comment_source": PATCH} if comment and comment == answer else {}

    def values(self, table: str, column: str) -> dict:
        """``{"confirmed_values": [...]}`` for one column, in glossary order; else ``{}``.

        The glossary names a table as the corpus spelt it (a catalog prefix included),
        so the table matches by dotted suffix and the column by name, ignoring case.
        """
        found: dict[str, dict] = {}
        for owner, entry in self._values.get(str(column).lower(), []):
            value = str(entry.get("value"))
            if value in found or not same_table(owner, table):
                continue
            meaning = entry["meaning"]
            # Who confirmed it stays in the dictionary: a packet never carries a person.
            found[value] = {"value": value, "meaning": redact(meaning["text"])}
        return {"confirmed_values": list(found.values())} if found else {}
