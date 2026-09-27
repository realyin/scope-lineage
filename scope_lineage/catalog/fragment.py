"""``catalog-fragment/1``: one group's additions to a catalog, as ``catalog merge`` reads them.

A fragment is what one drafting pass over a group of tables produces: the attributes
it found (keyed by the concept they belong to), the code sets, identifiers, constraints
and terms they need, and one representation per table with every column bound. Each
item has exactly the shape of the catalog file it lands in -- the schema's item
definitions are copies of the catalog schemas', kept equal by a test -- so a merge
moves items, it never translates them.
"""

from __future__ import annotations

from .model import Finding
from .structure import schema_findings

FRAGMENT_FORMAT = "catalog-fragment/1"
FRAGMENT_SCHEMA = "catalog-fragment"

# Where each fragment list lands: the catalog file kind, and the kind's name in reports.
TOP_LEVEL = (
    ("code_sets", "code_set"),
    ("identifiers", "identifier"),
    ("constraints", "constraint"),
    ("terms", "term"),
)


def check_fragment(data, file: str) -> list[Finding]:
    """Every schema violation in one fragment, one finding each, in document order."""
    return schema_findings(FRAGMENT_SCHEMA, data, file)
