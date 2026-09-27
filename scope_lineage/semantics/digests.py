"""The one digest every table-semantics file is compared by.

Sixteen hex digits of SHA-256 over canonical JSON (sorted keys, no whitespace, UTF-8), so
a digest names content, not layout: re-indenting a file or reordering its keys keeps it,
changing any value changes it. A packet's ``packet_digest`` is this over the packet
without the digest itself; a document's digest is this over the whole document -- what a
review's ``reviewed_doc_digest`` records and ``semantic status`` compares.
"""

from __future__ import annotations

import hashlib
import json


def canonical_digest(value) -> str:
    """Sixteen hex digits over the canonical JSON of ``value``."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def document_digest(document) -> str:
    """The digest of a whole ``table-semantics/1`` document, as a review records it."""
    return canonical_digest(document)
