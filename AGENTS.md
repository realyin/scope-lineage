# Repository Instructions

## Project

`scope-lineage` is an offline static analyzer that converts Spark/Hive SQL into two versioned JSON
artifacts: `lineage.json` and `diagnostics.json`. It uses SQLGlot with the `spark` dialect and does
not require a cluster, database connection, or LLM.

This repository contains the open-source Core only. Architecture tests refer to an internal
upper-layer/pipeline package, but that package is intentionally absent from this distribution.

## Working Rules

- Inspect the working tree before editing. Preserve unrelated changes and untracked files.
- Make the smallest change that solves the stated problem; avoid opportunistic refactors.
- Keep runtime code compatible with Python 3.9 through 3.12. Use
  `from __future__ import annotations` where modern type annotation syntax requires it.
- Treat parser output as facts, not guesses. Represent uncertainty or lossy recovery with a
  diagnostic or lineage fact gap and test both the structure and the diagnostic.
- Keep Core domain-neutral. Warehouse naming policies, business semantics, report generation, and
  modeling advice belong downstream.
- Do not change the public API, contract meaning, dependency bounds, or golden fixtures as a
  convenience. Such changes require focused tests, documentation, and an explicit rationale.
- Do not regenerate golden files blindly. Review every byte-level diff and treat unexpected output
  as a regression.
- Do not commit, merge, push, publish, or open a pull request unless the user explicitly requests it.
- Never add production SQL, real table names, internal identifiers, credentials, emails, or local
  paths to tests or fixtures. Reduce real failures to minimal synthetic examples.

## Setup and Validation

```bash
python -m pip install -e ".[dev]"

# Required test closure before claiming implementation work is complete
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py

# Focused checks
python -m pytest tests/core/test_lineage_contract_baseline.py -q
python -m pytest tests/core/test_parser_capability_matrix.py -q -k cte_window
python -m ruff check scope_lineage tests

# Verify wheel and source distribution contents
python -m build
python tests/architecture/verify_distribution.py dist/*
```

CLI smoke test, also used by CI against the installed wheel:

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

Run focused tests after each meaningful checkpoint, then run the full required closure before
completion. If packaging or CLI behavior changes, also run the distribution check and CLI smoke
test.

## Architecture

The execution path for one write statement is:

1. `scope_lineage/cli.py` resolves input files and metadata, applies catalog-prefix policy, calls
   Core, and writes only the two contract files.
2. `scope_lineage/scope/scope_builder.py` is the primary entry point. It splits scripts, recognizes
   supported write statements, qualifies the AST, traverses scopes, assigns stable scope IDs,
   synthesizes UNION/MERGE scopes where needed, and collects physical source tables.
3. `scope_lineage/scope/scope_resolver.py` resolves columns, joins, filters, UNION passthrough,
   fixed-point star expansion, and target-field binding.
4. `scope_lineage/scope/scope_facts.py` derives logic blocks, outputs, field usage, expression
   resolution, mapping chains, and lineage fact gaps. Some repeated passes intentionally converge
   to a fixed point; do not remove them without checking contract baselines.
5. `scope_lineage/contract/lineage.py` serializes output, derives scope profiles and end-to-end
   lineage, and validates schemas and cross-references before writing any file.

Shared scope helpers live in `scope_lineage/scope/_shared.py` and are re-exported through
`scope_builder` for compatibility. Metadata loaders live under `scope_lineage/metadata/`.

## Contract and Boundary Invariants

- `scope_lineage.PUBLIC_CORE_API` is the supported public facade. `__all__` must equal it, and all
  symbols in `tests/core/fixtures/public-api-required-symbols.json` must remain available. Adding a
  public symbol is a product decision.
- `tests/core/fixtures/lineage_contract/<case>/` contains byte-exact golden outputs. Baseline tests
  require byte equality and deterministic rendering across repeated runs.
- Core must not import upper layers. Published wheel and sdist archives must not contain `docs`,
  `tests`, `pipeline`, or other upper-layer source. Architecture allowlists are intentionally empty.
- Both output documents use `schema_version: "1.0"`. Within major version 1, only additive optional
  fields are compatible. Renaming, removing, or changing field meaning requires a new major version
  and matching schema and documentation updates.
- Reference documentation is in `docs/zh-CN/`. Any change to an output field's structure, meaning,
  or evidence path must update the corresponding contract documentation in the same change.

## SQLGlot Compatibility

The verified dependency range is `sqlglot>=30,<30.18`. SQLGlot optimizer scope shapes can change
between minor releases, especially for `MERGE`; do not rely on undocumented wrapper-root behavior
or traversal order.

When changing scope traversal or widening the SQLGlot range:

- Add a minimal synthetic regression for the affected statement shape.
- Test the oldest supported version, the previous verified version, and the proposed new version.
- Compare generated `lineage.json` and `diagnostics.json` bytes across versions where contract
  behavior is intended to remain stable.
- Verify stable scope IDs, physical source tables, `ROOT.raw_sql`, MERGE branch provenance, and
  diagnostics rather than checking only that parsing succeeds.

## Repository Conventions

- Fully qualified table names are preserved by default. Catalog prefixes are stripped only through
  the explicit `--catalog-prefixes` option or `SCOPE_LINEAGE_CATALOG_PREFIXES`; CLI configuration
  wins. This deployment policy must not be stored in task JSON.
- Comments around parser heuristics should explain why a rule exists and which failure it prevents.
  Preserve that context when modifying the code.
- Keep generated and local assistant state out of version control. `AGENTS.md` itself is repository
  documentation and should remain tracked.
