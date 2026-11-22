"""The international-phone and ID-number shapes of ``scope_lineage.redaction``.

The international rule used to have no boundary on either side, so a time-zone offset
followed by a partition date (``UTC+8 20260802``), an amount written with a plus sign
and the head of a 20-digit key were all masked as ``<phone>`` -- the last one leaving a
truncated ``<phone>890`` behind. The rule now refuses three concrete shapes instead of
judging the character before the ``+``:

* a run of digits that continues after the number (``(?!\\d)``), so an over-long key is
  one run and is left whole;
* a number part that is exactly an 8-digit ``YYYYMMDD`` date;
* fewer than 9 digits in country code and number together.

Judging the character before the ``+`` was tried and refused: it stopped masking real
numbers glued to an ASCII label (``tel+86…``, ``contact_+86…``). The project errs toward
masking too much, so every positive below is a shape that must stay masked.

The two narrow shapes this rule deliberately lets through (owner decision D8) are pinned
as well: 8 digits or fewer in total, and a number part that reads as a real date.

Every number here is invented.
"""

from __future__ import annotations

from datetime import date

import pytest

from scope_lineage.redaction import redact


MASKED = [
    "联系 +86 13800000000",
    "联系+86-13900000000",
    "电话+8613700000000",
    "tel:+1 2025550123",
    "+1-4155550100 值班",
    "(+44 2079460000)",
    "+852 61000000",
    "+81 9000000000",
    "+49 15100000000",
    "+61 491570156",
    "+33 612345678",
    "+65 81234567",
    "+886 912345678",
    "+7 9161234567",
    # an ASCII label glued to the plus sign is still a real number
    "phone+8613800000000",
    "tel+8613800000000",
    "Mobile+8613800000000",
    "contact_+8613800000000",
    "wx_id+8613800000000",
    "tel+86 13800000000",
    "tel+86-13800000000",
    "tel+1 2025550123",
    "Tel+12025550123",
    "whatsapp+447911123456",
    # nine digits in total is the lower bound and is masked
    "+298 212345",
    "+376 312345",
    "+35312345678",
    "id=1+8613800000000",
    "++8613800000000",
]

LEFT_ALONE = [
    "T+1 20260802 数据",
    "UTC+8 20260802",
    "GMT+08 20260802",
    "日期 +1 20260802",
    "同比 +12 20260802",
    "偏移量 +100 20260801",
    "金额 +1000000",
    "+12345678901234567890",
    "col+100000000000000000",
    "+1 2026",
    "C++ 20230101",
]


@pytest.mark.parametrize("text", MASKED)
def test_an_international_number_is_masked(text: str) -> None:
    redacted = redact(text)
    assert "<phone>" in redacted
    # the whole number goes, never a head or a tail of it
    assert not any(ch.isdigit() for ch in redacted.split("<phone>")[-1][:1])


@pytest.mark.parametrize("text", LEFT_ALONE)
def test_a_date_an_offset_or_a_long_key_is_not_a_phone(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        # deliberately over-masked, toward privacy: the number part is not an 8-digit date
        "T+3 2026080212",
        "东八区+8 2026080212",
        "增长 +25 1234567 户",
        "x = y +123456789",
        "+10000000000 行",
    ],
)
def test_the_rule_still_masks_toward_privacy_when_the_shape_fits(text: str) -> None:
    assert "<phone>" in redact(text)


@pytest.mark.parametrize(
    "text",
    [
        # D8 (1): eight digits or fewer in total are not masked
        "a+1 2345678",
        "版本 v1+2 2026080",
        # D8 (2): a number part that is exactly a real YYYYMMDD date is not masked
        "+852 20120315",
        "+86 20231215",
    ],
)
def test_the_two_shapes_d8_lets_through(text: str) -> None:
    assert redact(text) == text


# ------------------------------------------------------------------ ID number birth year


@pytest.mark.parametrize(
    "text",
    [
        "证 110101000101011234",  # born in year 0001
        "证 110101999912311239",  # born in year 9999
        "证 110101189912311234",  # born before 1900
        f"证 110101{date.today().year + 1}01011234",  # born next year
    ],
)
def test_an_18_digit_run_whose_birth_year_is_impossible_is_not_an_id(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "证 110105199003071234",
        "证 110101190001011234",  # 1900 is the lower bound
        f"证 110101{date.today().year}01011234",  # the current year is the upper bound
        "旧证 110101900307821",  # the 15-digit form is always 19xx
    ],
)
def test_an_id_number_with_a_possible_birth_year_is_still_masked(text: str) -> None:
    assert redact(text).endswith("<id>")
