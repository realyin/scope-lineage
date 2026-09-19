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
default: :func:`~scope_lineage.redaction.redact` masks the three contact shapes a comment
most often carries -- an email address, a phone number, a mainland-China ID number --
while leaving the sentence around them readable. The rule itself lives in
:mod:`scope_lineage.redaction`, because the same masking serves metadata and supplied
sample values, and it is re-exported here so a caller holding a comment still asks the
comment module for it. ``--strip-comments`` remains the only complete switch.
"""

from __future__ import annotations

from typing import Iterable

from sqlglot import exp

from ..redaction import redact


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
