"""One ``ontology-json/3`` document, indexed the ways its pages and its queries ask.

``catalog render`` and ``catalog query`` both read the built document and nothing else --
never the catalog directory -- so they share this one index over it: objects by id, the
representations of each concept, the bindings of each attribute or identifier, and the
evidence ``catalog build --lineage/--tables`` attached (empty when there is none). The
Chinese labels live here too, so a page and a query name a kind the same way.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

ONTOLOGY_FORMAT = "ontology-json/3"

KIND_TEXT = {"entity": "实体", "event": "事件", "role": "角色"}
STATUS_TEXT = {"drafted": "草拟", "confirmed": "已确认", "deprecated": "已废弃"}
REPRESENTATION_KINDS = (
    ("core", "核心"),
    ("extension", "扩展"),
    ("dependent", "从属"),
    ("event_detail", "事件明细"),
    ("state_history", "状态历史"),
    ("identifier_map", "标识映射"),
    ("role_view", "角色视图"),
    ("summary", "汇总"),
    ("intermediate", "中间"),
)
TIME_TEXT = {"snapshot": "快照", "incremental": "增量", "zipper": "拉链", "unknown": "未知"}
GRAIN_SOURCE_TEXT = {"declared": "声明", "inferred": "推断", "proven": "已证明"}
CATEGORIES = (("descriptive", "描述"), ("state", "状态"), ("measure", "度量"), ("time", "时间"))
RELATION_KIND_TEXT = {
    "association": "关联",
    "composition": "组成",
    "generalization": "泛化",
    "derivation": "派生",
    "participation": "参与",
}
CONSTRAINT_KINDS = (
    ("unique", "唯一"),
    ("cardinality", "基数"),
    ("mandatory", "必填"),
    ("value_domain", "值域"),
    ("referential", "引用"),
    ("temporal", "时间"),
    ("state_transition", "状态迁移"),
    ("derivation", "派生"),
    ("business_rule", "业务规则"),
)
STRENGTH_TEXT = {"hard": "硬", "soft": "软"}
BINDING_TEXT = {
    "attribute": "属性",
    "identifier": "标识符",
    "foreign_identifier": "外部标识符",
    "foreign_attribute": "冗余属性",
    "technical": "技术列",
    "unmapped": "未映射",
}
CONFIDENCE_TEXT = {"proven": "已证明", "candidate": "候选", "none": "无"}
IDENTIFYING_BINDINGS = ("identifier", "foreign_identifier")
MAPPING_TEXT = {
    "one_to_one": "一对一",
    "one_to_many": "一对多",
    "many_to_one": "多对一",
    "many_to_many": "多对多",
}
TABLE_STATUS_TEXT = {"active": "在用", "deprecated": "已废弃"}
UNCONFIRMED = "待确认"
# Column names a snapshot table partitions by, and the words naming a zipper's window ends.
PARTITION_COLUMNS = ("dt", "ds", "pt", "p_date", "stat_date", "snapshot_date", "biz_date")
WINDOW_START = ("start", "begin", "eff", "effective", "from")
WINDOW_END = ("end", "expire", "exp", "expiry", "to")


def catalog_table_name(name) -> str:
    """The ``db.table`` a spelling names: its last two dotted segments.

    The catalog names every table ``db.table``; a corpus or a reader may spell the same
    table ``catalog.db.table``. Both the evidence merge and ``catalog query`` match on this.
    """
    return ".".join(str(name or "").split(".")[-2:])


def concept_slug(concept_id: str) -> str:
    """``concept:fee_waiver`` -> ``fee_waiver``: the page's file stem."""
    return str(concept_id).split(":", 1)[-1]


def concept_filename(concept_id: str) -> str:
    return f"{concept_slug(concept_id)}.md"


def is_unconfirmed(value: Mapping) -> bool:
    """A code value whose meaning is still a guess: flagged, empty, or starting 待确认."""
    meaning = str(value.get("meaning") or "").strip()
    return bool(value.get("unconfirmed")) or not meaning or meaning.startswith(UNCONFIRMED)


def unconfirmed_guess(value: Mapping) -> str:
    """What the catalog guesses an unconfirmed value means, without the 待确认 marker."""
    meaning = str(value.get("meaning") or "").strip()
    if meaning.startswith(UNCONFIRMED):
        meaning = meaning[len(UNCONFIRMED) :].lstrip("：:，,、 ")
    return meaning


def code_value_text(value: Mapping) -> str:
    """``1=normal``, or ``9（含义待确认：guess）`` when the meaning is not confirmed."""
    if not is_unconfirmed(value):
        return f"{value['value']}={value['meaning']}"
    guess = unconfirmed_guess(value)
    return f"{value['value']}（含义待确认{'：' + guess if guess else ''}）"


def usage_hint(rep: Mapping) -> Optional[str]:
    """How to read the table given its time semantics, or None when there is nothing to say.

    A snapshot table holds the whole population once per partition, so summing across
    partitions counts every row again; a zipper table holds one row per validity window.
    """
    columns = [str(binding["column"]) for binding in rep.get("bindings") or []]
    if rep.get("time") == "snapshot":
        partition = next((c for c in columns if c in PARTITION_COLUMNS), "dt")
        return f"按单个 {partition} 分区取数"
    if rep.get("time") == "zipper":
        start = next((c for c in columns if _names_window(c, WINDOW_START)), "开始日")
        end = next((c for c in columns if _names_window(c, WINDOW_END)), "结束日")
        return f"按有效期窗口取数（{start} ≤ 查询日 < {end}，端点开闭以表口径为准）"
    return None


def time_text(rep: Mapping) -> str:
    """``快照；按单个 dt 分区取数``: the time semantics and how to read the table by them."""
    hint = usage_hint(rep)
    return f"{TIME_TEXT[rep['time']]}；{hint}" if hint else TIME_TEXT[rep["time"]]


def _names_window(column: str, words: tuple) -> bool:
    return any(part in words for part in column.casefold().split("_"))


def status_text(obj: Mapping) -> str:
    """``已确认（owner）``: the status, and where it came from when that is known."""
    status = STATUS_TEXT.get(str(obj.get("status")), str(obj.get("status")))
    return f"{status}（{obj['source']}）" if obj.get("source") else status


class CatalogView:
    """Read-only lookups over one built document."""

    def __init__(self, document: Mapping, semantic_pages: Optional[Mapping] = None) -> None:
        self.document = document
        # ``db.table -> link`` to its table-semantics page, relative to concepts/ (render only).
        self._semantic_pages = {
            catalog_table_name(table).lower(): link
            for table, link in (semantic_pages or {}).items()
        }
        self.concepts = {c["id"]: c for c in document.get("concepts") or []}
        self.attributes = {
            a["id"]: (a, c) for c in self.concepts.values() for a in c.get("attributes") or []
        }
        self.identifiers = {i["id"]: i for i in document.get("identifiers") or []}
        self.code_sets = {s["id"]: s for s in document.get("code_sets") or []}
        self.domains = {d["id"]: d for d in document.get("domains") or []}
        self.relations = {r["id"]: r for r in document.get("relations") or []}
        self.constraints = list(document.get("constraints") or [])
        self.terms = list(document.get("terms") or [])
        self.representations = {r["table"]: r for r in document.get("representations") or []}
        self.bindings_by_ref: dict[str, list] = {}
        for rep in self.representations.values():
            for binding in rep["bindings"]:
                if binding.get("ref"):
                    self.bindings_by_ref.setdefault(binding["ref"], []).append((rep, binding))
        evidence = document.get("evidence") or {}
        self.has_evidence = bool(evidence)
        self.evidence_inputs = evidence.get("inputs") or {}
        self._rep_evidence = evidence.get("representations") or {}
        self._binding_evidence = evidence.get("bindings") or {}
        self._relation_evidence = evidence.get("relations") or {}

    # ------------------------------------------------------------------ names

    def name(self, object_id: str) -> str:
        """The display name of any id, or the id itself when it names nothing."""
        for index in (
            self.concepts,
            self.identifiers,
            self.code_sets,
            self.domains,
            self.relations,
        ):
            if object_id in index:
                return str(index[object_id].get("name") or object_id)
        if object_id in self.attributes:
            return str(self.attributes[object_id][0]["name"])
        return str(object_id)

    def state_name(self, reference: str) -> str:
        """``concept:customer#verified`` -> ``已认证`` (the state's name), else the text."""
        concept_id, _, value = str(reference).partition("#")
        states = (self.concepts.get(concept_id) or {}).get("states") or {}
        for item in states.get("values") or []:
            if item["value"] == value:
                return str(item["name"])
        return str(reference)

    # -------------------------------------------------------------- concepts

    def representations_of(self, concept_id: str) -> list[dict]:
        return [r for r in self.representations.values() if r["concept"] == concept_id]

    def identifiers_of(self, concept_id: str) -> list[dict]:
        """Listed on the concept first (in its order), then any that declare it."""
        listed = list((self.concepts.get(concept_id) or {}).get("identifiers") or [])
        declared = [i for i, obj in self.identifiers.items() if obj["identifies"] == concept_id]
        ordered = listed + [i for i in declared if i not in listed]
        return [self.identifiers[i] for i in ordered if i in self.identifiers]

    def relations_of(self, concept_id: str) -> list[dict]:
        return [r for r in self.relations.values() if concept_id in (r["from"], r["to"])]

    def self_relations_of(self, concept_id) -> list[dict]:
        """Relations from the concept to itself (a loan renews a loan)."""
        return [r for r in self.relations_of(concept_id) if r["from"] == r["to"]]

    def self_reference_columns(self, concept_id: str) -> list[str]:
        """``db.table.column`` of every column holding another instance of the concept."""
        return [
            f"{rep['table']}.{binding['column']}"
            for identifier in self.identifiers_of(concept_id)
            for rep, binding in self.bindings_of(identifier["id"])
            if binding.get("self_reference")
        ]

    def foreign_attribute_bindings(self) -> list[tuple[dict, list[dict]]]:
        """``(representation, its foreign_attribute bindings)`` for every table with any."""
        found = []
        for table in sorted(self.representations):
            rep = self.representations[table]
            bindings = [b for b in rep["bindings"] if b["to"] == "foreign_attribute"]
            if bindings:
                found.append((rep, bindings))
        return found

    def carriers_of(self, concept_id: str) -> list[tuple[dict, list[dict]]]:
        """``(representation, its bindings)`` for every table, of any concept, that binds one
        of the concept's identifiers as ``identifier`` or ``foreign_identifier``."""
        own = {identifier["id"] for identifier in self.identifiers_of(concept_id)}
        found = []
        for table in sorted(self.representations):
            rep = self.representations[table]
            bindings = [
                b
                for b in rep["bindings"]
                if b["to"] in IDENTIFYING_BINDINGS and b.get("ref") in own
            ]
            if bindings:
                found.append((rep, bindings))
        return found

    def carried_together(self, relation: Mapping) -> list[str]:
        """The tables holding both ends of a relation: what the catalog alone says about
        where it lives, shown when no JOIN in the corpus backs it.

        A table holds a concept when it represents it or binds one of its identifiers (a
        role's are its player's); for a relation from a concept to itself, only a table
        with a column naming another instance (``self_reference``) holds both ends.
        """
        source, target = relation["from"], relation["to"]
        if source == target:
            own = {i["id"] for i in self.identifiers_of(source)}
            return [
                rep["table"]
                for rep, bindings in self.carriers_of(source)
                if any(b.get("self_reference") and b["ref"] in own for b in bindings)
            ]
        return [
            table
            for table in sorted(self.representations)
            if self._holds(table, source) and self._holds(table, target)
        ]

    def _holds(self, table: str, concept_id: str) -> bool:
        rep = self.representations[table]
        if rep["concept"] == concept_id:
            return True
        keys = {i["id"] for i in self.identifiers_of(concept_id)}
        player = (self.concepts.get(concept_id) or {}).get("player")
        if not keys and player:
            keys = {i["id"] for i in self.identifiers_of(player)}
        return any(
            b["to"] in IDENTIFYING_BINDINGS and b.get("ref") in keys for b in rep["bindings"]
        )

    def unconfirmed_codes(self) -> list[tuple[dict, list[dict]]]:
        """``(code set, its values whose meaning is not confirmed)`` for every set with any."""
        found = []
        for code_set_id in sorted(self.code_sets):
            code_set = self.code_sets[code_set_id]
            values = [v for v in code_set["values"] if is_unconfirmed(v)]
            if values:
                found.append((code_set, values))
        return found

    def attributes_coded_by(self, code_set_id: str) -> list[dict]:
        return [a for a, _ in self.attributes.values() if a.get("code_set") == code_set_id]

    def roles_played_by(self, concept_id: str) -> list[dict]:
        return [c for c in self.concepts.values() if c.get("player") == concept_id]

    def bindings_of(self, ref: str) -> list[tuple[dict, dict]]:
        return list(self.bindings_by_ref.get(ref) or [])

    def constraints_on(self, concept_id: str) -> list[dict]:
        """Constraints on the concept, its attributes, identifiers and relations."""
        concept = self.concepts.get(concept_id) or {}
        targets = {concept_id}
        targets |= {a["id"] for a in concept.get("attributes") or []}
        targets |= {i["id"] for i in self.identifiers_of(concept_id)}
        targets |= {r["id"] for r in self.relations_of(concept_id)}
        order = [kind for kind, _ in CONSTRAINT_KINDS]
        found = [c for c in self.constraints if c["on"] in targets]
        return sorted(found, key=lambda c: (order.index(c["kind"]), c["id"]))

    # -------------------------------------------------------------- evidence

    def rep_evidence(self, table: str) -> dict:
        return dict(self._rep_evidence.get(table) or {})

    def binding_evidence(self, table: str, column: str) -> dict:
        return dict(self._binding_evidence.get(f"{table}.{column}") or {})

    def relation_joins(self, relation_id: str) -> Optional[dict]:
        """``{count, samples}`` when the build checked this relation, else None."""
        entry = self._relation_evidence.get(relation_id)
        return dict(entry["joins"]) if entry else None

    def semantic_page(self, table: str) -> Optional[str]:
        """The link to the table's ``semantic render`` page, when ``--semantics`` gave one."""
        return self._semantic_pages.get(catalog_table_name(table).lower())

    def lineage_checked(self) -> bool:
        return "lineage" in self.evidence_inputs
