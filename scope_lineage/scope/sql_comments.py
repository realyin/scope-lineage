"""SQL comments, read once and normalized once.

sqlglot attaches a comment to the node it belongs to: a statement's leading block lands
on the statement node, ``AS cust_id -- 客户号`` on the ``Alias``, and a comment written
inside a predicate on the ``Column`` or ``Literal`` beside it. This module is the only
place that reads those attachments, so ``statement_comments``, an output's ``comments``
and a logic block's ``comments`` cannot normalize differently from each other.

Two collection routes, for two different shapes of evidence:

- :func:`subtree_comments` walks an AST node -- used for a statement header and for a
  projection, whose comment sits on a node the contract does not serialize;
- :func:`comments_in_sql` scans rendered SQL text -- used for a logic block, whose
  ``raw_expression`` is already that block's subtree printed *with* its comments. It is
  the same set of comments the walk would find, read where the block's own expression
  is, so a WHERE split into conjuncts cannot be handed its siblings' comments.

A comment is free text written by a person. Nothing here parses it, matches it against
identifiers, or treats it as a fact about the data -- it is carried as a quotation and
nothing else. It can also hold what its author never meant to publish, which is why
``parse --strip-comments`` exists and why the docs say what the default does.

Between "keep everything" and "keep nothing" there is a third position, and it is the
default: :func:`redact` masks the three contact shapes a comment most often carries --
an email address, a phone number, a mainland-China ID number -- while leaving the
sentence around them readable. It is *shape* matching over free text, so it is neither
exhaustive (an unusually written number survives) nor certain (a code that happens to
have the shape is masked anyway); ``--strip-comments`` remains the only complete switch.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable, Iterable

from sqlglot import exp


# Applied in this order, over the comment text only -- never over a SQL expression, where
# the same digits are data the statement operates on. Email first: its replacement carries
# no digits, so a phone-shaped run inside an address cannot be matched twice. The ID rule
# precedes both phone rules, and every numeric rule is fenced by digit lookarounds, so a
# longer run of digits (an 18-digit ID, a 20-digit transaction key) is judged as one run
# rather than having an 11-digit "phone" carved out of its middle.
#
# The address rule is bounded to the characters an address is actually written with
# rather than to "everything that is not a space". A comment is usually a Chinese
# sentence with no space around its punctuation, so an unbounded run would consume the
# words beside the address -- `联系 a@b.com（值班）` would publish `联系 <email>` and lose
# the note. Masking a person's address must not delete the author's sentence; an address
# written in characters this class does not cover is one of the cases the docs already
# say shape matching does not catch.
_ID_NUMBER = re.compile(r"(?<!\d)(?:\d{17}[0-9Xx]|\d{15})(?!\d)")


def _mask_id_number(match: re.Match[str]) -> str:
    """Mask a run of digits only when it has the *shape* of a mainland ID number.

    Length alone is not that shape. Warehouse comments are full of 15- and 18-digit
    runs that are order keys, bar codes and serial numbers, and masking ``123456789012345``
    as ``<id>`` deleted a value the author wrote down on purpose. An ID number carries a
    six-digit region code (which never starts with a zero) followed by a birth date --
    ``YYMMDD`` in the 15-digit form, which is always 19xx, and ``YYYYMMDD`` in the
    18-digit one -- and a date that does not exist is the cheap, decisive test.

    Still a shape and still not a certainty: a 15-digit code whose middle six digits do
    read as a date is masked anyway, and ``--strip-comments`` remains the only complete
    switch.
    """
    digits = match.group(0)
    birth = ("19" + digits[6:12]) if len(digits) == 15 else digits[6:14]
    if digits.startswith("0") or not _is_real_date(birth):
        return digits
    return "<id>"


def _is_real_date(text: str) -> bool:
    try:
        date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return False
    return True


_REDACTIONS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<email>"),
    (_ID_NUMBER, _mask_id_number),
    (re.compile(r"\+\d{1,3}[\s-]?\d{6,14}"), "<phone>"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "<phone>"),
)


def redact(text: object) -> str:
    """Mask contact-shaped runs in one comment, leaving the rest of the text alone.

    ``a@b.com`` becomes ``<email>``, a mainland-China mobile or an international number
    becomes ``<phone>``, an 18- or 15-digit ID number becomes ``<id>``. A date such as
    ``20260814``, an amount such as ``1000.50`` and a 15- or 18-digit serial number whose
    middle digits are not a real birth date are not contact shapes and are left as the
    author wrote them.
    """
    result = "" if text is None else str(text)
    for pattern, placeholder in _REDACTIONS:
        result = pattern.sub(placeholder, result)
    return result


def redact_comments(tree: exp.Expression | None) -> None:
    """Rewrite every comment of a tree in place, masking what :func:`redact` masks.

    In place and on the tree rather than on the collected lists, for the same reason
    :func:`strip_comments` is: a comment reaches an artifact twice -- once through the
    contract's ``comments`` keys and once inline inside a rendered ``raw_expression`` --
    and masking only the first would publish the address in the second. Replacing rather
    than deleting is what separates this from stripping: the sentence survives.

    Applied only to trees this package parsed itself; see :func:`strip_comments`.
    """
    if tree is None:
        return
    for node in tree.walk():
        comments = getattr(node, "comments", None)
        if comments:
            node.comments = [redact(item) for item in comments]


def normalize(raw: Iterable[object] | None) -> list[str]:
    """Trimmed, order-preserving comment text with adjacent repeats collapsed.

    Only *adjacent* repeats: the same note written over two different branches of a CASE
    is two facts about two branches, and collapsing them across the list would claim the
    author wrote it once.
    """
    collected: list[str] = []
    for item in raw or ():
        text = str(item).strip() if item is not None else ""
        if not text or (collected and collected[-1] == text):
            continue
        collected.append(text)
    return collected


def node_comments(node: object) -> list[str]:
    """The comments attached to exactly this node."""
    return normalize(getattr(node, "comments", None))


def subtree_comments(node: exp.Expression | None) -> list[str]:
    """This node's own comments first, then every descendant's in traversal order.

    The node's own come first deliberately: for a projection that node is the ``Alias``,
    and the comment a reader wrote next to the output name is the one that names the
    column -- a comment buried in the expression is context for it, not a replacement.
    """
    if node is None:
        return []
    collected = list(node_comments(node))
    for descendant in node.walk():
        if descendant is node:
            continue
        collected.extend(node_comments(descendant))
    return normalize(collected)


def comments_in_sql(text: object) -> list[str]:
    """Comments in a rendered SQL fragment, skipping quoted strings and identifiers.

    Written as a scan rather than a regex because ``WHERE note = '-- not a comment'`` is
    ordinary Spark SQL: a pattern that cannot see quoting publishes the author's data as
    the author's commentary.
    """
    source = str(text or "")
    collected: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char in ("'", '"', "`"):
            index = _end_of_quoted(source, index)
            continue
        if char == "/" and source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = length if end == -1 else end
            collected.append(source[index + 2:end])
            index = (end + 2) if end < length else length
            continue
        if char == "-" and source.startswith("--", index):
            end = _line_end(source, index)
            collected.append(source[index + 2:end])
            index = end
            continue
        index += 1
    return normalize(collected)


def strip_comments(tree: exp.Expression | None) -> None:
    """Drop every comment from a tree, in place.

    Applied to trees this package parsed itself, never to one a caller handed over: the
    flag removes facts from *our* artifacts, and silently emptying a caller's AST would
    remove them from theirs too.
    """
    if tree is None:
        return
    for node in tree.walk():
        if getattr(node, "comments", None):
            node.comments = None


def _end_of_quoted(source: str, start: int) -> int:
    """The index just past the quoted region opening at ``start``."""
    quote = source[start]
    index = start + 1
    length = len(source)
    while index < length:
        char = source[index]
        if char == "\\" and quote != "`":
            index += 2
            continue
        if char == quote:
            # A doubled quote is an escaped quote, not the end of the region.
            if index + 1 < length and source[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _line_end(source: str, start: int) -> int:
    newline = min(
        (position for position in (source.find("\n", start), source.find("\r", start))
         if position != -1),
        default=-1,
    )
    return len(source) if newline == -1 else newline


def script_header_comments(statements: Iterable[exp.Expression | None]) -> list[str]:
    """The opening comment block of a script, read off the statements before its first write.

    A task script usually opens with the lines that say what the job does, and that block
    is written above the session settings rather than above the INSERT. sqlglot attaches a
    statement's leading comments to that statement's node, so those lines land on the first
    ``SET`` -- a statement this tool does not model, whose comments therefore reached no
    artifact at all. Read here from the statements that run *before* the first modelled
    write, they can be published on that write and once at task level.

    Only each statement's own node is read, not its subtree: a ``CREATE TABLE IF NOT
    EXISTS`` preamble carries comments written inside its column list, and those describe a
    column, not the job.
    """
    collected: list[str] = []
    for statement in statements:
        if statement is None:
            continue
        collected.extend(node_comments(statement))
    return normalize(collected)


def merge_comments(*groups: Iterable[str]) -> list[str]:
    """Concatenate comment lists in order, publishing a repeated line once.

    Full deduplication rather than :func:`normalize`'s adjacent-only rule, because the
    groups are different *sources* for the same statement -- a script header hoisted onto
    the first write and that write's own header block. A line written in both places is one
    note the author wrote twice about the same statement, and publishing it twice would
    claim otherwise.
    """
    merged: list[str] = []
    for group in groups:
        for text in group:
            if text not in merged:
                merged.append(text)
    return merged
