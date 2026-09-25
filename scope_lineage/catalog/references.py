"""Stage two: every reference exists and points at the right kind of object.

Runs only on a catalog whose files all passed their schemas, so each rule may read the
fields its schema requires without guarding them. Every rule reports under its own name;
the names are the ones ``docs/*/ontology-catalog.md`` lists.
"""

from __future__ import annotations

from collections import Counter

from .index import Index, build_index
from .model import Catalog, Finding


class _Checks:
    def __init__(self, index: Index) -> None:
        self.index = index
        self.findings: list[Finding] = []

    def fail(self, rule: str, file: str, at, message: str) -> None:
        self.findings.append(Finding(rule, file, at, message))

    def expect(self, rule, file, at, ref, types, what: str, kinds=None) -> bool:
        """``ref`` must be one of ``types`` (and, for a concept, one of ``kinds``)."""
        ok = self.index.is_type(ref, *types)
        if ok and kinds is not None:
            ok = self.index.concept_kind(ref) in kinds
        if not ok:
            self.fail(rule, file, at, f"{ref!r} {_describe(self.index, ref)}; expected {what}")
        return ok


def _describe(index: Index, ref) -> str:
    entry = index.get(ref)
    if entry is None:
        return "does not exist"
    noun = index.concept_kind(ref) or entry.type.replace("_", " ")
    return f"is {'an' if noun[0] in 'aeiou' else 'a'} {noun}"


def check_references(catalog: Catalog) -> list[Finding]:
    index = build_index(catalog)
    checks = _Checks(index)
    for file, identifier in catalog.records("identifiers"):
        _identifier(checks, file, identifier)
    for file, code_set in catalog.records("code_sets"):
        _code_set(checks, file, code_set)
    for file, concept in catalog.records("concepts"):
        _concept(checks, file, concept)
    for file, relation in catalog.records("relations"):
        _relation(checks, file, relation)
    for file, constraint in catalog.records("constraints"):
        checks.expect(
            "constraint_on", file, constraint["id"], constraint["on"],
            ("concept", "attribute", "relation", "identifier"),
            "a concept, attribute, relation or identifier",
        )
    for file, term in catalog.records("terms"):
        if index.get(term["refers_to"]) is None:
            checks.fail("term_refers_to", file, term["term"], f"{term['refers_to']!r} does not exist")
    _representations(checks, catalog)
    _derived_ids(checks, catalog)
    return index.findings + checks.findings


# --- identifiers and code sets ---------------------------------------------------------


def _identifier(checks: _Checks, file: str, identifier: dict) -> None:
    at = identifier["id"]
    checks.expect(
        "identifier_identifies", file, at, identifier["identifies"],
        ("concept",), "an entity or an event", kinds=("entity", "event"),
    )
    scope = identifier["scope"]
    for concept in scope.get("per", []) if isinstance(scope, dict) else []:
        checks.expect("identifier_scope", file, at, concept, ("concept",), "a concept")
    arises = identifier.get("arises_when")
    if isinstance(arises, dict) and "state" in arises:
        _state_reference(checks, file, at, arises["state"])
    for mapping in identifier.get("maps_to") or []:
        checks.expect(
            "identifier_maps_to", file, at, mapping["identifier"], ("identifier",), "an identifier"
        )


def _state_reference(checks: _Checks, file: str, at: str, reference: str) -> None:
    concept_id, _, value = reference.partition("#")
    entry = checks.index.get(concept_id)
    states = entry.obj.get("states") if entry and entry.type == "concept" else None
    if states is None:
        checks.fail("identifier_state", file, at, f"{concept_id!r} is not a concept with states")
    elif value not in {str(v["value"]) for v in states["values"]}:
        checks.fail("identifier_state", file, at, f"{concept_id!r} has no state {value!r}")


def _code_set(checks: _Checks, file: str, code_set: dict) -> None:
    counts = Counter(str(value["value"]) for value in code_set["values"])
    for value, count in sorted(counts.items()):
        if count > 1:
            checks.fail(
                "duplicate_code_value", file, code_set["id"], f"value {value!r} is listed {count} times"
            )


# --- concepts --------------------------------------------------------------------------


def _concept(checks: _Checks, file: str, concept: dict) -> None:
    at = concept["id"]
    checks.expect("concept_domain", file, at, concept["domain"], ("domain",), "a domain")
    for identifier in concept.get("identifiers") or []:
        checks.expect("concept_identifier", file, at, identifier, ("identifier",), "an identifier")
    primary = concept.get("primary_identifier")
    if primary is not None and primary not in (concept.get("identifiers") or []):
        checks.fail("primary_identifier", file, at, f"{primary!r} is not in this concept's identifiers")
    if concept["kind"] == "role":
        _role(checks, file, concept)
    if concept["kind"] == "event":
        _event(checks, file, concept)
    if "states" in concept:
        _states(checks, file, concept)
    for attribute in concept.get("attributes") or []:
        if "code_set" in attribute:
            checks.expect(
                "attribute_code_set", file, attribute["id"], attribute["code_set"],
                ("code_set",), "a code set",
            )


def _role(checks: _Checks, file: str, role: dict) -> None:
    at = role["id"]
    checks.expect("role_player", file, at, role["player"], ("concept",), "an entity", kinds=("entity",))
    checks.expect("role_context", file, at, role["context"], ("domain",), "a domain")


def _event(checks: _Checks, file: str, event: dict) -> None:
    at = event["id"]
    for participant in event["participants"]:
        checks.expect(
            "event_participant", file, at, participant["concept"],
            ("concept",), "an entity or a role", kinds=("entity", "role"),
        )
    names = Counter(participant["role_name"] for participant in event["participants"])
    for name, count in sorted(names.items()):
        if count > 1:
            checks.fail("duplicate_role_name", file, at, f"role_name {name!r} is used {count} times")
    if event["occurred_at"] not in checks.index.attributes_of(at):
        checks.fail(
            "event_occurred_at", file, at,
            f"{event['occurred_at']!r} is not one of this event's own attributes",
        )


def _states(checks: _Checks, file: str, concept: dict) -> None:
    at, states = concept["id"], concept["states"]
    if states["attribute"] not in checks.index.attributes_of(at):
        checks.fail(
            "state_attribute", file, at,
            f"{states['attribute']!r} is not one of this concept's own attributes",
        )
    values = {str(value["value"]) for value in states["values"]}
    for transition in states.get("transitions") or []:
        checks.expect(
            "state_event", file, at, transition["event"], ("concept",), "an event", kinds=("event",)
        )
        for end in ("from", "to"):
            if str(transition[end]) not in values:
                checks.fail(
                    "state_value", file, at,
                    f"transition {end} {transition[end]!r} is not one of the states",
                )


def _relation(checks: _Checks, file: str, relation: dict) -> None:
    for end in ("from", "to"):
        checks.expect(
            "relation_endpoint", file, relation["id"], relation[end], ("concept",), "a concept"
        )


# --- mapping ---------------------------------------------------------------------------


def _representations(checks: _Checks, catalog: Catalog) -> None:
    seen: dict[str, str] = {}
    for file, representation in catalog.records("mapping"):
        table = representation["table"]
        if table in seen:
            checks.fail("duplicate_table", file, table, f"already represented in {seen[table]}")
            continue
        seen[table] = file
        _representation(checks, file, representation)


def _representation(checks: _Checks, file: str, representation: dict) -> None:
    table = representation["table"]
    concept_ok = checks.expect(
        "representation_concept", file, table, representation["concept"], ("concept",), "a concept"
    )
    for identifier in representation["grain"]["identifiers"]:
        checks.expect(
            "representation_grain", file, table, identifier, ("identifier",), "an identifier"
        )
    columns = Counter(binding["column"] for binding in representation["bindings"])
    for column, count in sorted(columns.items()):
        if count > 1:
            checks.fail("duplicate_column", file, f"{table}.{column}", f"bound {count} times")
    owners = checks.index.binding_owners(representation["concept"]) if concept_ok else None
    if owners is None:
        return  # no concept to judge the bindings against; reported above
    by_column = {b["column"]: b for b in reversed(representation["bindings"])}
    for binding in representation["bindings"]:
        at = f"{table}.{binding['column']}"
        _binding(checks, file, at, binding, owners, by_column)


def _binding(checks: _Checks, file: str, at: str, binding: dict, owners, by_column) -> None:
    to, ref = binding["to"], binding.get("ref")
    index = checks.index
    own_ids = set().union(*(index.identifiers_of(owner) for owner in owners))
    if to == "attribute":
        allowed = set().union(*(index.attributes_of(owner) for owner in owners))
        if ref not in allowed:
            checks.fail("binding_attribute", file, at, f"{ref!r} {_not_own(index, ref, 'attribute')}")
    elif to == "identifier" and ref not in own_ids:
        checks.fail("binding_identifier", file, at, f"{ref!r} {_not_own(index, ref, 'identifier')}")
    elif to == "foreign_identifier":
        _foreign_identifier(checks, file, at, ref, owners)
    elif to == "foreign_attribute":
        _foreign_attribute(checks, file, at, binding, owners, by_column)


def _foreign_identifier(checks: _Checks, file: str, at: str, ref, owners) -> None:
    """Another concept's identifier -- or this concept's own, when a relation links the
    concept to itself (a renewal loan's column naming the loan it renews)."""
    index = checks.index
    if not index.is_type(ref, "identifier"):
        message = f"{ref!r} {_describe(index, ref)}; expected an identifier"
        checks.fail("binding_foreign_identifier", file, at, message)
        return
    selves = [owner for owner in owners if ref in index.identifiers_of(owner)]
    if selves and not any(index.has_self_relation(owner) for owner in selves):
        checks.fail(
            "self_reference_without_relation", file, at,
            f"{ref!r} identifies this table's own concept, and no relation runs from "
            f"{selves[0]} to itself",
        )


def _foreign_attribute(checks: _Checks, file: str, at: str, binding: dict, owners, by_column) -> None:
    """Another concept's attribute, repeated on this row next to that concept's identifier."""
    index = checks.index
    ref, via = binding["ref"], binding["via"]
    owner = index.get(ref).owner if index.is_type(ref, "attribute") else None
    if owner is None or owner in owners:
        reason = "belongs to this table's own concept" if owner else _describe(index, ref)
        message = f"{ref!r} {reason}; expected another concept's attribute"
        checks.fail("binding_foreign_attribute", file, at, message)
        return
    reason = _via_problem(index, by_column.get(via), owner)
    if reason:
        checks.fail(
            "binding_foreign_attribute_via", file, at,
            f"via {via!r} {reason}; expected a column of this table bound as "
            f"foreign_identifier to an identifier of {owner}",
        )


def _via_problem(index: Index, target, owner: str):
    """Why the ``via`` column cannot name the instance of ``owner``, or None when it can."""
    if target is None:
        return "is not a column of this table"
    if target["to"] != "foreign_identifier":
        return f"is bound as {target['to']}"
    owners = index.binding_owners(owner) or (owner,)
    if target["ref"] not in set().union(*(index.identifiers_of(o) for o in owners)):
        return f"holds {target['ref']!r}, which does not identify {owner}"
    return None


def _not_own(index: Index, ref, what: str) -> str:
    if index.get(ref) is None:
        return "does not exist"
    return f"is not an {what} of the represented concept"


def _derived_ids(checks: _Checks, catalog: Catalog) -> None:
    """A participant becomes ``rel:<event>.<role_name>``; that id must be free."""
    for file, event in catalog.records("concepts"):
        for participant in event.get("participants") or []:
            derived = derived_relation_id(event["id"], participant["role_name"])
            entry = checks.index.get(derived)
            if entry is not None:
                checks.fail(
                    "duplicate_id", entry.file, derived,
                    f"also the id of the participation relation derived from {event['id']}",
                )


def derived_relation_id(event_id: str, role_name: str) -> str:
    return f"rel:{event_id.split(':', 1)[1]}.{role_name}"
