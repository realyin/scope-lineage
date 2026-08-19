# Contributing

Thanks for considering a contribution.

Scope Lineage is intentionally conservative: lineage output should be
explainable, auditable, and explicit about uncertainty. Parser changes should
come with tests that cover both the parsed structure and the diagnostic behavior
when the SQL is ambiguous.

## Development

```bash
python -m pip install -e ".[dev]"     # editable install with pytest/jsonschema/build
python -m pytest -q tests/core
python -m pytest tests/core/test_lineage_contract_baseline.py -q
git diff --check                       # whitespace/conflict check after edits
```

Keep Core domain-neutral. Warehouse layer names, business-domain rules, report builders, and
modeling recommendations belong in downstream projects rather than this package.

## Pull Request Checklist

- Add or update tests for parser behavior.
- Add diagnostics tests when the behavior is uncertain or lossy.
- When you change an actively used output's structure/field meaning/evidence
  path, update the matching contract document under `docs/` in the same change.
- Keep examples synthetic and free of private table names, emails, or paths.

## SQL Fixtures

Do not add private production SQL to the public repository. If a real failure
requires a regression test, reduce it to a synthetic SQL statement that preserves
the parser shape but removes business names and private identifiers.
