# 按审读意见修订提示词（table-semantics-fix@1）

输入：一张表的审读意见、现有 `table-semantics/1` 文档、材料包 `packet.md`。

1. 逐条处理「高」「中」发现：先在材料包里核实；成立就按「应改成什么」修改对应字段，必要时同步 `summary.what` / `row` / `watch` / `good_for` / `not_for` / 相关列；不成立的跳过并说明理由。「低」能顺手改就改。
2. 改完把整份文档从头读一遍：新改的地方不能与页面其他地方（取数说明、适用/不适用、一行是什么、相关列、要注意）矛盾，有就一并改齐；推断的结论标「推断」或待确认；不得与已确认事实矛盾。
3. `generator.prompt` 在原值后加 `+review`；其余格式不变（`table-semantics/1`）。
4. 跑 `scope-lineage semantic validate`，只修失败项，最多 2 轮；仍失败的在 `summary.watch` 说明。
