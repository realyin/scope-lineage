"""The contact shapes masked out of free text, wherever that text came from.

A comment a person wrote, a table description exported from a catalog and a column's
sample values are three different inputs with one problem in common: the author may have
written down something they never meant to publish. The rule that masks it is a *text*
rule -- an email, a phone number, a mainland-China ID number -- with nothing SQL about
it, so it lives at the package root where every layer can reach it: the parser's comment
handling (``scope.sql_comments``), the metadata it carries alongside, and the supplied
sample values (``metadata.column_samples``), which are the most PII-prone input the tool
ever reads.

Between "keep everything" and "keep nothing" this is the third position, and it is the
default. It is *shape* matching over free text, so it is neither exhaustive (an unusually
written number survives) nor certain (a code that happens to have the shape is masked
anyway); ``parse --strip-comments`` remains the only complete switch for comments, and a
samples file is redacted with no switch at all.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable


# Applied in this order, over the comment text only -- never over a SQL expression, where
# the same digits are data the statement operates on. Email first: its replacement carries
# no digits, so a phone-shaped run inside an address cannot be matched twice. The ID rule
# precedes both phone rules, and every numeric rule ends with a digit lookahead (the ID
# and mainland rules are fenced on both sides), so a longer run of digits (an 18-digit ID,
# a 20-digit transaction key) is judged as one run rather than having an 11-digit "phone"
# carved out of its middle or a ``<phone>890`` tail left behind.
#
# The international rule is *not* fenced in front, on purpose: a real number is often
# glued to an ASCII label (``tel+86…``, ``contact_+86…``), and judging the character
# before the ``+`` stopped masking those. It refuses concrete shapes instead -- see
# :func:`_mask_intl_phone`.
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
    18-digit one -- and a date that does not exist is the cheap, decisive test. A date
    that exists but no living holder was born on (year 0001, year 9999) fails it too: the
    birth year must fall between 1900 and the current year. The 18th character is a
    check digit and is deliberately *not* verified -- a real number copied with one wrong
    digit must still be masked.

    Still a shape and still not a certainty: a 15-digit code whose middle six digits do
    read as a date is masked anyway, and ``--strip-comments`` remains the only complete
    switch.
    """
    digits = match.group(0)
    birth = ("19" + digits[6:12]) if len(digits) == 15 else digits[6:14]
    if digits.startswith("0") or not _is_real_date(birth):
        return digits
    if not 1900 <= int(birth[:4]) <= date.today().year:
        return digits
    return "<id>"


def _is_real_date(text: str) -> bool:
    try:
        date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return False
    return True


_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# A YYYYMMDD date in 1900-2099. A number part that is exactly this shape is far more often
# a partition date after an offset (``T+1 20260802``, ``UTC+8 20260802``) than a phone.
_DATE8 = r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)"
_INTL_PHONE = re.compile(r"\+(\d{1,3})([\s-]?)(?!" + _DATE8 + r")(\d{6,14})(?!\d)")


def _mask_intl_phone(match: re.Match[str]) -> str:
    """Mask a ``+``-prefixed number only when it has the shape of an E.164 number.

    The pattern already refuses two shapes: a digit run that continues past the number
    (an over-long key is one run and is kept whole) and a number part that is exactly an
    8-digit date. Here the country code and the number together must hold 9 to 15
    digits: fewer is an amount or an offset (``+1000000``, ``a+1 2345678``), more is not
    a phone number at all.

    Two narrow shapes are let through on purpose, and a real number of either shape is
    no longer masked: 8 digits or fewer in total (a few small countries), and a number
    part that happens to read as a real date (``+86 20231215``). The rule still masks
    toward privacy wherever the shape fits -- ``T+3 2026080212`` is masked, because a
    10-digit number part is not a date. A number written in groups (``+86 138 0000
    0000``) is not recognised, as before.
    """
    if 9 <= len(match.group(1)) + len(match.group(3)) <= 15:
        return "<phone>"
    return match.group(0)

_REDACTIONS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (_EMAIL, "<email>"),
    (_ID_NUMBER, _mask_id_number),
    (_INTL_PHONE, _mask_intl_phone),
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


def mask_emails(text: object) -> str:
    """Mask only the email shape, anywhere in ``text`` -- SQL included.

    :func:`redact` stays off SQL expressions because a digit run there is data the
    statement operates on. An email address is the one shape with no such excuse: a
    document that must never carry one (a table-semantics packet handed to a model) can
    run the whole text, SQL and all, through this without corrupting a number.
    """
    return _EMAIL.sub("<email>", "" if text is None else str(text))
