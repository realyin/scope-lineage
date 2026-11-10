### "生成 mapping 文档" — render

```bash
scope-lineage render --lineage <artifacts-dir>    # writes mapping.md next to each lineage.json
```

Task documents render one section per statement. `--out <dir>` mirrors the tree
elsewhere; `--field`, `--sections`, `--expanded` narrow or expand the content. The
document is a derived view — every fact links back to lineage.json ids.
