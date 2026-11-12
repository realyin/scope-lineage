### "字段 X 是怎么加工出来的" — derivation chain

```bash
python3 scripts/query.py chain <db.table.column> <artifact-dir...>
```

Output shows the final-state sources, the step-by-step mapping chain (scope, step type,
transform, expression per step), the physical root columns, and a bounded expanded-expression
preview. Add `--expanded` only when the complete expression is needed. Present the steps in order
with their expressions; quote `trace_status` /
`trace_complete` verbatim. Structure of everything printed: `references/artifact-guide.md`.
