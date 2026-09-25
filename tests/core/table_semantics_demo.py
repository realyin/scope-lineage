"""Shared helpers for the table-semantics tests: the demo corpus, its packets, the example.

The demo corpus (``examples/catalog-demo-corpus``) is parsed and packed exactly as the
docs tell a reader to, and the hand-written example document
(``examples/table-semantics/``) is validated against the packet of the table it
describes. Every failing fixture is that example with exactly one thing changed, so a
test names the one check it is about and a clean run of the example proves the fixture
broke nothing else.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from .catalog_demo import CORPUS

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "table-semantics"
DEMO_TABLE = "demo_dwd.dwd_party_customer_info_df"
EXAMPLE = EXAMPLES / f"{DEMO_TABLE}.json"
CONFIRMATIONS = EXAMPLES / "confirmations.json"


def run(*argv: str) -> int:
    from scope_lineage.cli import main

    return main([str(arg) for arg in argv])


def parse_corpus(corpus: Path, target: Path) -> Path:
    code = run(
        "parse", "--input-dir", corpus / "tasks",
        "--schema", corpus / "schema_info.json", "--out", target,
    )
    assert code == 0, "the corpus must parse"
    return target


def pack(corpus: Path, lineage: Path, out: Path, *extra: str) -> int:
    return run(
        "semantic", "packet", "--lineage", lineage, "--tasks", corpus / "tasks",
        "--schema", corpus / "schema_info.json", "--out", out, *extra,
    )


def demo_packets(work: Path) -> Path:
    """Parse and pack the demo corpus into ``work``; the packet directory."""
    lineage = parse_corpus(CORPUS, work / "lineage")
    assert pack(CORPUS, lineage, work / "packets") == 0
    return work / "packets"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def packet_of(packets: Path, table: str = DEMO_TABLE) -> dict:
    return read_json(packets / table / "packet.json")


def example(packets: Path | None = None) -> dict:
    """A fresh copy of the example; its digest set to the packet's when one is given.

    The digest pins how the installed sqlglot renders every expression, so the example is
    held to its *content* here and to its digest only by the stale-digest test.
    """
    document = copy.deepcopy(read_json(EXAMPLE))
    if packets is not None:
        document["packet_digest"] = packet_of(packets)["packet_digest"]
    return document


def copy_corpus(target: Path) -> Path:
    shutil.copytree(CORPUS, target)
    return target
