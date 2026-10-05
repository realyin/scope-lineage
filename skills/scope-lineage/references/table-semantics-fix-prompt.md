# 按审读意见修订提示词（table-semantics-fix@2）

输入：一张表的审读意见、现有 `table-semantics/1` 文档、材料包 `packet.md`。

1. 逐条处理「高」「中」发现：先在材料包里核实；成立就按「应改成什么」修改对应字段，必要时同步 `summary.what` / `row` / `watch` / `good_for` / `not_for` / 相关列；不成立的跳过并说明理由。「低」能顺手改就改。审读要求提问时可以新增或补充 `questions`，但最多 5 条：先合并相关的问题，再删影响最小的，不许超过。只在兄弟表材料包里出现的表，只能作为注明「据 <兄弟表> 的材料」的线索提及，不写成本材料包支持的推荐。
2. 改完把整份文档从头读一遍：新改的地方不能与页面其他地方（取数说明、适用/不适用、一行是什么、相关列、要注意）矛盾，有就一并改齐；推断的结论标「推断」或待确认；不得与已确认事实矛盾。
3. `generator.prompt` 在原值后加 `+review`；其余格式不变（`table-semantics/1`）。
4. 跑 `scope-lineage semantic validate`，只修失败项，最多 2 轮；仍失败的在 `summary.watch` 说明。
5. 不要改审读文件：`semantic status` 看到文档摘要与审读的 `reviewed_doc_digest` 不同、且文档重新通过校验，就算修订完成。
   查这一张表：文档放回 `<run>/docs/<db.table>.json` 后运行 `scope-lineage semantic status <run> --only <db.table>`，这一行应当是 `fixed`。要看两个摘要时加 `--json -`（`-` 表示把 JSON 打到标准输出），读 `tables[0].doc_digest` 与 `tables[0].review.reviewed_doc_digest`。在隔离目录里自查时加 `--docs <隔离目录>`，并且一定要带 `--only`，否则其余表在那个目录里没有文档，会显示成 `packet`。
