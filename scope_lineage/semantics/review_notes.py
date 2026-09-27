"""The front matter a review opens with: which document it read and how much it found.

A review is markdown a model writes (``table-semantics-review@1``). Its first lines are a
minimal YAML block that ``semantic status`` reads without a YAML library::

    ---
    reviewed_doc_digest: 04439862460b03d6
    high: 1
    medium: 2
    low: 0
    ---

``reviewed_doc_digest`` is the :func:`~.digests.document_digest` of the document as the
reviewer read it (``semantic digest <doc.json>`` prints it); ``high`` / ``medium`` /
``low`` count the findings by severity. Anything short of all four keys with a non-empty
digest and non-negative whole counts is no front matter at all.
"""

from __future__ import annotations

COUNT_KEYS = ("high", "medium", "low")
REVIEW_KEYS = ("reviewed_doc_digest", *COUNT_KEYS)


def parse_review(text: str) -> dict | None:
    """``{reviewed_doc_digest, high, medium, low}``, or None without complete front matter."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    fields = {}
    for line in lines[1:end]:
        key, colon, value = line.partition(":")
        if colon:
            fields[key.strip()] = value.strip().strip("\"'")
    return _review(fields)


def _review(fields: dict) -> dict | None:
    digest = fields.get("reviewed_doc_digest")
    if not digest:
        return None
    review: dict = {"reviewed_doc_digest": digest}
    for key in COUNT_KEYS:
        value = fields.get(key, "")
        if not (value.isascii() and value.isdigit()):
            return None
        review[key] = int(value)
    return review
