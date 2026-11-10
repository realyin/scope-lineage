### "这些页面能不能用 / 给页面打分" — 验收

表语义页和概念页写好后，用 owner 给的问题集（`question-set/1`）考页面：作答者只读页面答题，判分者对照参考答案和材料
判 2/1/0，`scope-lineage questions validate` / `sheet` / `grading-sheet` / `score` 做确定性的部分。**照
`references/runbook.md` 的 S11 做**，作答用 runbook-templates 的 T7（便宜模型即可），判分用 T8（最强模型）。不可违反的三条：

1. **作答与判分是两个独立子代理**：作答者只拿题单和页面目录，看不到题集、参考答案、材料包或 SQL。
2. **`sheet`、`grading-sheet`、`score` 带同一组 `--ids` / `--only-table`**，否则会混进没答、没判的题（只给警告、退出 0）。
3. **不自己出题自己考**；留出集只在收尾时跑一次。

读 YAML 题集要 `catalog` extra（PyYAML）。格式与命令见 `../../docs/zh-CN/questions.md`。
