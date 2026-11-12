### "跨任务追溯上下游 N 层" — cross-task trace

```bash
python3 scripts/query.py trace [--upstream N] [--downstream N] <db.table[.column]> <artifacts-root>
```

Joins tasks by table name across the whole corpus and walks the lineage graph hop by
hop (default: one hop each direction). Each printed edge names the task and artifact
path that proves it; `no producing task in corpus` marks the physical boundary. Cycles
(e.g. MERGE self-references, mutually-fed tables) are reported once and not re-walked.
Under-qualified names (`db.table` for a recorded `catalog.db.table`) are resolved by
suffix and the resolution is printed. trace navigates; for the full per-field
derivation at any hop, follow up with `chain` on that task's artifact dir.

The first run builds a routing index at `<artifacts-root>/.scope-lineage-index.json`
and later runs refresh it incrementally by file fingerprint (stderr says
`built` / `reused` / `updated`). The index is a disposable cache — delete it to force a
full rebuild; artifacts remain the single source of truth.
