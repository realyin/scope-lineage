"""Whether the material supports a measure's unit: one rule for every reader.

The material is the table-semantics documents. The judgement is the attribute's, not a
column's: a measure attribute's unit is supported when any column bound to it has a
``unit`` in its table's document, not supported when its bound columns are described and
none has one, and cannot be judged when no document describes any of its bound columns
(including a measure bound to no column at all).

``catalog context`` marks a unit with it (``material_unit``) and ``catalog render
--docs`` counts with it on the index, so a column the context pack does not mark is
never counted as unsupported on the page, and the other way round.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, Optional

from .catalog_view import CatalogView, catalog_table_name

__all__ = [
    "SUPPORTED", "UNJUDGED", "UNSUPPORTED", "UnitSupport", "material_documents", "unit_support",
]

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNJUDGED = "unjudged"


class UnitSupport(NamedTuple):
    outcome: str  # SUPPORTED, UNSUPPORTED or UNJUDGED
    units: tuple[str, ...]  # the units the material gives, in the order first seen


def material_documents(semantics: Optional[Mapping[str, Mapping]]) -> dict[str, Mapping]:
    """``{db.table (lower case): document}``, the key ``unit_support`` looks a table up by."""
    return {catalog_table_name(name).lower(): doc for name, doc in (semantics or {}).items()}


def unit_support(
    view: CatalogView, attribute: Mapping, material: Mapping[str, Mapping]
) -> Optional[UnitSupport]:
    """The material's judgement of a measure attribute's unit; None for any other attribute.

    ``material`` is keyed as ``material_documents`` keys it.
    """
    if attribute.get("category") != "measure":
        return None
    described = False
    units: list[str] = []
    for rep, binding in view.bindings_of(attribute["id"]):
        document = material.get(rep["table"].lower()) or {}
        folded = binding["column"].casefold()
        for column in document.get("columns") or []:
            if str(column.get("column", "")).casefold() != folded:
                continue
            described = True
            given = str(column.get("unit") or "").strip()
            if given and given not in units:
                units.append(given)
    if not described:
        return UnitSupport(UNJUDGED, ())
    return UnitSupport(SUPPORTED if units else UNSUPPORTED, tuple(units))
