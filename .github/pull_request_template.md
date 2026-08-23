## Change

Describe the problem, the smallest implemented change, and its user-visible effect.

## Verification

- [ ] Focused tests cover the changed behavior and failure mode.
- [ ] `python -m pytest -q tests/core tests/architecture`
- [ ] `python -m ruff check scope_lineage tests`
- [ ] Public tree, commit messages, and this PR body pass the private-surface scan.
- [ ] User-facing contract documentation is updated in both English and Chinese when required.
- [ ] Golden changes, if any, were reviewed byte by byte and across the SQLGlot matrix.

Do not include private SQL, identifiers, local paths, corpus sizes, task-level measurements, or
other facts that describe non-public data. Put private verification evidence only in local
`dev-notes/verification/` and summarize conclusions here without absolute measurements.
