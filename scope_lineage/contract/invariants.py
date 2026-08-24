"""Semantic consistency invariants across a lineage document's derivation layers.

`validate_cross_references` checks that every referenced id exists. This module checks
something referential validation cannot see: facts the contract derives through more
than one independent path must agree with each other. Trace completeness is computed
once by the field-mapping-chain collector and once by the end-to-end layer; physical
sources appear in ``end_to_end_lineage``, in ``root_source_fields``, in per-step
``expression_resolution``, and in ``source_tables``. Each layer can look individually
plausible while the conjunction is contradictory — a chain claiming
``trace_status=complete`` for a field ``end_to_end_lineage`` honestly reports as
ambiguous shipped exactly that way, and every per-layer test stayed green.

Every rule here is measured, not assumed: each one held with zero violations over the
full example/golden corpus at the time it was added, and the sweep against the
pre-fix tree reported exactly the known AMBIGUOUS defect and nothing else. The
architecture sweep (``tests/architecture/test_contract_invariants.py``) keeps the
whole corpus at zero violations, so every future defect of this class fails a test
the day it is introduced.
"""

from __future__ import annotations

from ..scope.scope_types import NON_PHYSICAL_SOURCE_SCOPES


def validate_contract_invariants(document: dict) -> list[str]:
    """Return cross-layer consistency violations (empty list = consistent).

    Accepts both contract shapes, like ``validate_cross_references``: a statement
    document ("1.0") is checked directly; a task document ("2.0") has each embedded
    statement document checked with its violations prefixed by the statement id.
    """
    if document.get("schema_version") == "2.0":
        errors: list[str] = []
        statement_lineage = document.get("statement_lineage") or {}
        if not isinstance(statement_lineage, dict):
            return ["statement_lineage must be an object"]
        for statement_id, nested in statement_lineage.items():
            if not isinstance(nested, dict):
                continue
            errors.extend(
                f"statement_lineage[{statement_id!r}]: {error}"
                for error in _validate_statement_invariants(nested)
            )
        return errors
    return _validate_statement_invariants(document)


def _validate_statement_invariants(document: dict) -> list[str]:
    errors: list[str] = []
    source_tables = {
        str(table) for table in document.get("source_tables") or [] if table
    }
    chains = [
        chain
        for chain in document.get("field_mapping_chains") or []
        if isinstance(chain, dict)
    ]
    e2e_entries = [
        entry
        for entry in document.get("end_to_end_lineage") or []
        if isinstance(entry, dict)
    ]

    for table in sorted(source_tables & NON_PHYSICAL_SOURCE_SCOPES):
        errors.append(f"source_tables lists sentinel {table!r} as a physical table")

    e2e_by_column: dict[str, list[dict]] = {}
    for entry in e2e_entries:
        e2e_by_column.setdefault(str(entry.get("column")), []).append(entry)

    for entry in e2e_entries:
        errors.extend(_e2e_entry_errors(entry, source_tables))

    chain_fields = set()
    for chain in chains:
        chain_fields.add(str(chain.get("target_field")))
        errors.extend(_chain_errors(chain, source_tables, e2e_by_column))

    for column, entries in e2e_by_column.items():
        if column not in chain_fields:
            errors.append(
                f"end_to_end_lineage[{column!r}] has no field_mapping_chain "
                "for the same column"
            )
    return errors


def _e2e_entry_errors(entry: dict, source_tables: set[str]) -> list[str]:
    errors: list[str] = []
    column = str(entry.get("column"))
    for source in entry.get("physical_sources") or []:
        if not isinstance(source, dict):
            continue
        table = str(source.get("table") or "")
        if table in NON_PHYSICAL_SOURCE_SCOPES:
            errors.append(
                f"end_to_end_lineage[{column!r}] physical_sources lists "
                f"sentinel {table!r} as a table"
            )
        elif table and table not in source_tables:
            errors.append(
                f"end_to_end_lineage[{column!r}] physical source table {table!r} "
                "not in source_tables"
            )
    if entry.get("ambiguities"):
        if entry.get("trace_complete") is not False:
            errors.append(
                f"end_to_end_lineage[{column!r}] carries ambiguities but "
                "trace_complete is not false"
            )
        reasons = [str(item) for item in entry.get("trace_incomplete_reasons") or []]
        if "ambiguous_unqualified" not in reasons:
            errors.append(
                f"end_to_end_lineage[{column!r}] carries ambiguities without an "
                "ambiguous_unqualified trace_incomplete_reason"
            )
    return errors


def _chain_errors(
    chain: dict,
    source_tables: set[str],
    e2e_by_column: dict[str, list[dict]],
) -> list[str]:
    errors: list[str] = []
    chain_id = str(chain.get("mapping_chain_id"))
    field = str(chain.get("target_field"))
    label = f"field_mapping_chains[{chain_id}] target_field={field!r}"
    trace_status = str(chain.get("trace_status"))
    chain_status = str(chain.get("chain_status"))
    reasons = [str(item) for item in chain.get("missing_reasons") or []]
    roots = [str(item) for item in chain.get("root_source_fields") or []]

    for sentinel in ("AMBIGUOUS", "UNKNOWN"):
        if trace_status == "complete" and any(
            root.startswith(f"{sentinel}.") for root in roots
        ):
            errors.append(
                f"{label}: {sentinel} root source but trace_status=complete "
                "(an unproven attribution published as a fact)"
            )

    if chain.get("name_is_generated") and (chain.get("final_output_fields") or []):
        errors.append(
            f"{label}: name_is_generated but final_output_fields is non-empty "
            "(a bound target column is a real name, not a generated placeholder)"
        )

    if trace_status == "complete":
        if reasons:
            errors.append(
                f"{label}: trace_status=complete but missing_reasons is non-empty "
                f"({reasons[:3]})"
            )
        if chain_status != "resolved":
            errors.append(
                f"{label}: trace_status=complete but chain_status={chain_status!r}"
            )
    elif trace_status == "incomplete":
        if chain_status == "resolved":
            errors.append(
                f"{label}: trace_status=incomplete but chain_status='resolved'"
            )
        if not reasons:
            errors.append(
                f"{label}: trace_status=incomplete without any missing_reasons"
            )

    for root in roots:
        table = _physical_table_of_root(root, source_tables)
        if table is not None and table not in source_tables:
            errors.append(
                f"{label}: root source table {table!r} not in source_tables"
            )

    for step in chain.get("ordered_steps") or []:
        if not isinstance(step, dict):
            continue
        resolution = step.get("expression_resolution") or {}
        for item in resolution.get("physical_source_fields") or []:
            if not isinstance(item, dict):
                continue
            table = str(item.get("table") or "")
            if table in NON_PHYSICAL_SOURCE_SCOPES:
                errors.append(
                    f"{label}: step expression_resolution lists sentinel "
                    f"{table!r} as a table"
                )
            elif table and table not in source_tables:
                errors.append(
                    f"{label}: step physical source table {table!r} "
                    "not in source_tables"
                )

    entries = e2e_by_column.get(field)
    if entries is None:
        errors.append(f"{label}: no end_to_end_lineage entry for the same column")
    else:
        all_complete = all(entry.get("trace_complete") for entry in entries)
        if trace_status == "complete" and not all_complete:
            errors.append(
                f"{label}: trace_status=complete but an end_to_end entry reports "
                "trace_complete=false for the same column"
            )
        if trace_status == "incomplete" and all_complete:
            errors.append(
                f"{label}: trace_status=incomplete but every end_to_end entry "
                "reports trace_complete=true for the same column"
            )
    return errors


def _physical_table_of_root(root: str, source_tables: set[str]) -> str | None:
    """Return the physical table a root-source field id names, or None.

    Root ids look like ``db.table.column`` (possibly catalog-qualified, possibly a
    struct path after the table). Sentinel roots (``AMBIGUOUS.x``, ``CONSTANT.'v'``)
    and scope roots (``cte:x.col``, ``ROOT.col``) are not tables. A root whose prefix
    matches a known source table is resolved to that table, so struct paths and
    catalog qualification never misread as unknown tables.
    """
    head = root.split(".", 1)[0]
    if head in NON_PHYSICAL_SOURCE_SCOPES or head == "ROOT":
        return None
    if ":" in root:
        return None
    for table in source_tables:
        if root.startswith(f"{table}."):
            return table
    if "." not in root:
        return None
    return root.rsplit(".", 1)[0]
