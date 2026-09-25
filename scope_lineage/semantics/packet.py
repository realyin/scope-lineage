"""``semantic packet``: every fact a writer needs about one target table, in one place.

A packet is deterministic. It gathers, per table the corpus writes: the table's metadata
with its comments, each producing task with its SQL, the input tables' metadata, and the
lineage facts the semantic profile (``describe``'s builder, the old semantic card)
already derives -- column sources and derivations, rules, keys, neighbours. A model
writes ``table-semantics/1`` from it; ``semantic validate`` checks that document against
it; its ``packet_digest`` says whether a document was written against the facts as they
are now.

Everything leaving this module passes :func:`~.names.scrub`: no owner key, no email.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable, Iterable, Mapping, Optional

from . import packet_facts as facts
from .names import bare_table, scrub
from .packet_sections import inputs_section, lineage_section, target_section, tasks_section

PACKET_FORMAT = "table-semantics-packet/1"

MetadataLookup = Callable[[str], Optional[dict]]


class UnknownTables(ValueError):
    """``--only`` named a table the corpus does not write."""

    def __init__(self, names: list[str]):
        super().__init__(f"no table written by the corpus is named {', '.join(names)}")
        self.names = names


def build_packets(
    documents: Iterable[tuple[dict, Optional[dict]]],
    *,
    tasks: Iterable[dict] = (),
    metadata: MetadataLookup | None = None,
    cards: dict | None = None,
    only: Iterable[str] | None = None,
) -> list[dict]:
    """One packet per table the corpus writes (or per ``only`` table), sorted by name.

    ``documents`` are ``(lineage document, diagnostics or None)`` pairs; ``tasks`` the
    task JSON records ``{name, source_file, sql}``; ``metadata`` answers
    ``{comment, layer, domain, columns}`` for a ``db.table`` or None; ``cards`` a
    ``tables-json/1`` document, built from the corpus itself when not given.
    """
    profiles, cards = _profiles(list(documents), cards)
    produced = _produced_statements(profiles)
    corpus = _Corpus(cards, _TaskIndex(tasks), metadata or (lambda _table: None))
    return [_packet(table, produced[table], corpus) for table in _selected(produced, only)]


def packet_digest(packet: Mapping) -> str:
    """Sixteen hex digits over every fact in the packet but the digest itself."""
    body = {key: value for key, value in packet.items() if key != "packet_digest"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _profiles(documents: list, cards: dict | None) -> tuple[list[dict], dict]:
    """Every task's semantic profile, read with the corpus's table cards.

    Without ``--tables`` the cards are built from this corpus first -- the same two
    passes ``tables`` then ``describe --tables`` make -- so a packet always knows its
    downstream consumers and every JOIN another task proved unique.
    """
    from ..render.semantic_profile import build_semantic_profile
    from ..render.table_cards import apply_table_cards, build_table_cards

    if cards is None:
        cards = build_table_cards(build_semantic_profile(doc, diag) for doc, diag in documents)
    profiles = [
        apply_table_cards(build_semantic_profile(doc, diag, table_cards=cards), cards)
        for doc, diag in documents
    ]
    return profiles, cards


def _produced_statements(profiles: list[dict]) -> dict[str, list[tuple[str, dict]]]:
    """``db.table -> [(task, statement profile)]`` for every table a task finally writes."""
    produced: dict[str, list[tuple[str, dict]]] = {}
    for profile in profiles:
        # A bare 1.0 statement profile names its task inside, not above, its statement.
        task = str(profile.get("task_id") or (profile.get("task") or {}).get("task_name") or "")
        finals = {bare_table(name) for name in profile.get("produced_tables") or []}
        for statement in profile.get("statements") or [profile]:
            target = bare_table((statement.get("task") or {}).get("target_table"))
            if target and (target in finals or not finals):
                produced.setdefault(target, []).append((task, statement))
    return produced


def _selected(produced: dict, only: Iterable[str] | None) -> list[str]:
    if not only:
        return sorted(produced)
    wanted = list(dict.fromkeys(bare_table(name) for name in only))
    unknown = [name for name in wanted if name not in produced]
    if unknown:
        raise UnknownTables(unknown)
    return sorted(wanted)


class _TaskIndex:
    """Task JSON records, found by task name first and by source file second."""

    def __init__(self, records: Iterable[dict]):
        self.by_name: dict[str, dict] = {}
        self.by_file: dict[str, dict] = {}
        for record in records:
            self.by_name.setdefault(str(record.get("name")), record)
            self.by_file.setdefault(str(record.get("source_file")), record)

    def find(self, names: list, source_file) -> dict | None:
        for name in names:
            if name and str(name) in self.by_name:
                return self.by_name[str(name)]
        return self.by_file.get(str(source_file)) if source_file else None


class _Corpus:
    """What every packet reads besides its own statements."""

    def __init__(self, cards: dict, tasks: _TaskIndex, metadata: MetadataLookup):
        self.cards = list((cards or {}).get("tables") or [])
        self.tasks = tasks
        self.metadata = metadata

    def card(self, table: str) -> dict:
        for card in self.cards:
            if table in {bare_table(name) for name in [card.get("table"), *card.get("aliases", [])]}:
                return card
        return {}

    def tables_written_by(self, task: str) -> list[str]:
        return sorted({
            bare_table(card.get("table"))
            for card in self.cards
            for producer in card.get("produced_by") or []
            if producer.get("task") == task
        })


def _packet(table: str, statements: list[tuple[str, dict]], corpus: _Corpus) -> dict:
    rules = [rule for task, statement in statements for rule in facts.statement_rules(task, statement)]
    for index, rule in enumerate(rules, start=1):
        rule["id"] = f"p{index}"
    target = target_section(table, statements, corpus)
    packet = scrub({
        "doc_format": PACKET_FORMAT,
        "table": table,
        "packet_digest": "",
        "target": target,
        "tasks": tasks_section(statements, corpus),
        "inputs": inputs_section(statements, rules, corpus),
        "lineage": lineage_section(table, statements, rules, target, corpus),
    })
    packet["packet_digest"] = packet_digest(packet)
    return packet
