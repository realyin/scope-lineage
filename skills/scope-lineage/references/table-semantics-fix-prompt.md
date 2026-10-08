# 按审读意见修订提示词（table-semantics-fix@6）

输入：一张表的审读意见、现有 `table-semantics/1` 文档、材料包 `packet.md`。

1. 逐条处理「高」「中」发现：先在材料包里核实；成立就按「应改成什么」修改对应字段，必要时同步 `summary.what` / `row` / `watch` / `good_for` / `not_for` / 相关列；不成立的跳过并说明理由。「低」能顺手改就改。审读要求提问时可以新增或补充 `questions`，但最多 5 条：先合并相关的问题，再删影响最小的，不许超过。只在兄弟表材料包里出现的表，只能作为注明「据 <兄弟表> 的材料」的线索提及，不写成本材料包支持的推荐。审读按第 16 项判定材料包的「行数放大」「粒度 / 键」被 SQL 推翻（原文出自本表任务 SQL）时，照改：按 SQL 写，并注明「材料包标 <判定>，SQL 证明 <事实>（原文）」。审读据兄弟表材料，要求把关联写成「不放大」或移出放大名单的，不照改：按写作提示词写成推断（保留点名，注明「据 <兄弟表> 的材料」，写明推断不成立时会怎样）；审读同一条里其余成立的部分照改，并在回复里说明偏离了哪一处。
2. 改完把整份文档从头读一遍：新改的地方不能与页面其他地方（取数说明、适用/不适用、一行是什么、相关列、要注意）矛盾，有就一并改齐；推断的结论标「推断」或待确认；不得与已确认事实矛盾。
3. `generator.prompt` 在原值后加 `+review`；其余格式不变（`table-semantics/1`）。
4. 跑 `scope-lineage semantic validate`，只修失败项，最多 2 轮。2 轮后仍有失败就停下：不做第 5 步，不要为了通过把条目改写成 `questions` / `watch` 或换措辞绕过，把仍失败的条目原样告诉调用方（这张表交 owner 处理）。第 10 项（`fan_out`）对上一步按 SQL 推翻材料包判定（原文出自本表任务 SQL）的句子报 WARN 时，保留原句，不要为了消掉 WARN 改措辞：句子里已写明 SQL 原文和材料包的判定，WARN 不挡收尾。
5. 收尾（必须是最后一步；前面任何一步没做完都不要做这一步）：把文档放回 `<run>/docs/<db.table>.json`（放回前确认文件里的 `table` 等于 `<db.table>`），然后运行 `scope-lineage semantic fixed <run> --only <db.table>`。它先校验文档，再在审读文件的 front matter 里写入修订回执 `fixed_doc_digest`；退出码非 0 时什么都没写，按它给的原因处理：文档校验不通过，说明第 4 步没有收住，同样停下告诉调用方，不再回到第 4 步；审读没有 `reviewed_packet_digest`、或审读读的是另一版材料包，就停下，告诉调用方这张表要重新审读，不要自己补键。
   之后运行 `scope-lineage semantic status <run> --only <db.table>`，这一行应当是 `fixed`。要看摘要时加 `--json -`（`-` 表示把 JSON 打到标准输出），读 `tables[0].doc_digest`、`tables[0].review.reviewed_doc_digest` 与 `tables[0].review.fixed_doc_digest`。在隔离目录里自查时加 `--docs <隔离目录>`（隔离目录用带表名的子目录，例如 `<scratch>/<db.table>/`，不要几张表共用一个目录或一个文件名），并且一定要带 `--only`，否则其余表在那个目录里没有文档，会显示成 `packet`。
   不要手改审读文件：回执只由 `semantic fixed` 写。修订被打断、没走到这一步时，`status` 会把这张表标成 `fix_unconfirmed`，`--next fix` 会重新派发它。
