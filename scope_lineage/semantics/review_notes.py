"""The front matter a review opens with: what it read, how much it found, whether it was fixed.

A review is markdown a model writes (``table-semantics-review@5``). Its first lines are a
minimal YAML block that ``semantic status`` reads without a YAML library::

    ---
    reviewed_doc_digest: 04439862460b03d6
    reviewed_packet_digest: 8c1f0a2b3d4e5f60
    high: 1
    medium: 2
    low: 0
    ---

``reviewed_doc_digest`` is the :func:`~.digests.document_digest` of the document as the
reviewer read it (``semantic digest <doc.json>`` prints it); ``reviewed_packet_digest`` is
the ``packet_digest`` of the packet the reviewer read (copied from ``packet.md``);
``high`` / ``medium`` / ``low`` count the findings by severity. Anything short of the
digest and the three counts -- a non-empty digest, non-negative whole counts -- is no
front matter at all. ``reviewed_packet_digest`` is optional so that reviews written
before it existed still parse; ``semantic status`` treats such a review as one it cannot
tie to a packet.

``fixed_doc_digest`` is the fix record: the digest of the document a fix finished with.
Only ``semantic fixed`` writes it (:func:`with_fix_record`), so anything but sixteen
lower-case hex digits counts as no record. A new review overwrites the file and so drops
the record with it.
"""

from __future__ import annotations

import re

COUNT_KEYS = ("high", "medium", "low")
REVIEW_KEYS = ("reviewed_doc_digest", *COUNT_KEYS)
PACKET_KEY = "reviewed_packet_digest"
FIX_KEY = "fixed_doc_digest"

_DIGEST = re.compile(r"[0-9a-f]{16}")


def parse_review(text: str) -> dict | None:
    """``{reviewed_doc_digest, reviewed_packet_digest, fixed_doc_digest, high, medium, low}``.

    None without complete front matter; the two optional keys are None when absent (and
    the fix record when it is not a digest).
    """
    block = _front_matter(text)
    if block is None:
        return None
    lines, end = block
    fields = {}
    for line in lines[1:end]:
        key, colon, value = line.partition(":")
        if colon:
            fields[key.strip()] = value.strip().strip("\"'")
    return _review(fields)


def with_fix_record(text: str, digest: str) -> str:
    """``text`` with ``fixed_doc_digest: <digest>`` in its front matter, the rest untouched.

    An existing record is replaced in place; otherwise the line goes just before the
    closing ``---``, with the line ending the front matter already uses.
    """
    block = _front_matter(text)
    if block is None:
        raise ValueError("the review has no front matter")
    # Same line count as the parse: both split on the same boundaries.
    lines, end = text.splitlines(keepends=True), block[1]
    ending = "\r\n" if lines[0].endswith("\r\n") else "\n"
    record = f"{FIX_KEY}: {digest}{ending}"
    found = [i for i in range(1, end) if lines[i].partition(":")[0].strip() == FIX_KEY]
    if found:
        lines[found[0]] = record
    else:
        lines.insert(end, record)
    return "".join(lines)


def _front_matter(text: str) -> tuple[list[str], int] | None:
    """The lines of ``text`` and the index of the closing ``---``, or None."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    return lines, end


def _review(fields: dict) -> dict | None:
    digest = fields.get("reviewed_doc_digest")
    if not digest:
        return None
    fixed = fields.get(FIX_KEY)
    review: dict = {
        "reviewed_doc_digest": digest,
        PACKET_KEY: fields.get(PACKET_KEY) or None,
        FIX_KEY: fixed if fixed and _DIGEST.fullmatch(fixed) else None,
    }
    for key in COUNT_KEYS:
        value = fields.get(key, "")
        if not (value.isascii() and value.isdigit()):
            return None
        review[key] = int(value)
    return review
