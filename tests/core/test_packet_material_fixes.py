"""Packet material a weaker writer copies as given (quality plan 2026-10-18, W1-W9).

Each test names its work item. Every name is synthetic.
"""

from __future__ import annotations

import re

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown


def _pack(sql: str, schema: dict, meta: dict | None = None) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=schema))
    (packet,) = build_packets([(document, None)], metadata=(meta or {}).get)
    return packet


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


# ------------------------------------------------------------------ W1 control characters

W1_SCHEMA = {"ods.src": ["k", "v"], "dw.out": ["k", "v"]}
W1_META = {
    "ods.src": {"columns": [
        {"name": "k", "type": "string", "comment": "键\x00"},
        {"name": "v", "type": "string", "comment": "值\x01\x1f\t说明"},
    ]},
}


def test_w1_packet_md_holds_no_c0_control_character_but_tab_and_newline() -> None:
    packet = _pack("INSERT OVERWRITE TABLE dw.out SELECT s.k, s.v FROM ods.src s",
                   W1_SCHEMA, W1_META)
    text = render_packet_markdown(packet)
    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text)
    assert "| 键 |" in text and "值\t说明" in text
