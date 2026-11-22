"""Audit 2.5: a digest failure says why in a field, not only in its wording.

``report_flags`` (what ``semantic render --validation`` reads) told ``no_packet`` from
``packet_stale`` by whether the message began with "no packet". A report written by a
version that worded it differently would be misread. The failure now carries
``reason_code`` (``no_packet`` / ``stale``); a report without it, written before the field
existed, is still read by the old prefix.
"""

from __future__ import annotations

from scope_lineage.semantics.checks_context import check_digest, missing_packet
from scope_lineage.semantics.validate import report_flags


def _report(*items: dict) -> dict:
    return {"tables": [{"table": "s.t", "schema_errors": [], "failures": list(items)}]}


def _digest_failure(message: str, **extra) -> dict:
    return {"check": "digest", "status": "fail", "at": "packet_digest", "message": message,
            "number": 8, **extra}


def test_a_missing_packet_carries_its_reason_code() -> None:
    assert missing_packet({"table": "s.t"})["reason_code"] == "no_packet"


def test_a_stale_digest_carries_its_reason_code() -> None:
    [item] = check_digest({"packet_digest": "a" * 16}, {"packet_digest": "b" * 16})

    assert item["status"] == "fail"
    assert item["reason_code"] == "stale"


def test_report_flags_read_the_reason_code_not_the_wording() -> None:
    reworded = _report(_digest_failure("packet missing for s.t", reason_code="no_packet"))
    stale = _report(_digest_failure("no packet-level match", reason_code="stale"))

    assert report_flags(reworded) == {"s.t": ["no_packet"]}
    assert report_flags(stale) == {"s.t": ["packet_stale"]}


def test_sentinel_a_report_without_reason_code_falls_back_to_the_prefix() -> None:
    assert report_flags(_report(_digest_failure("no packet for s.t: ..."))) == {"s.t": ["no_packet"]}
    assert report_flags(_report(_digest_failure("stale: ..."))) == {"s.t": ["packet_stale"]}


def test_sentinel_a_passing_digest_has_no_reason_code() -> None:
    [item] = check_digest({"packet_digest": "a" * 16}, {"packet_digest": "a" * 16})

    assert "reason_code" not in item
