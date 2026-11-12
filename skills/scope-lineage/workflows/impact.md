### "谁依赖表 T / 列 C" — impact analysis

```bash
python3 scripts/query.py impact <db.table[.column]> <artifacts-root>
```

Requires artifacts to exist for the task corpus first (parse `--input-dir` once, reuse
the output). Reports every `target_table.column <- source` edge. "No consumers found"
across N docs is a real answer — report N so the user knows the search space.
