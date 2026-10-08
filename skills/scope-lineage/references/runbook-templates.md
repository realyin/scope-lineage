# runbook 模板：编排者检查清单、子代理提示词 T1–T8、账本与交付报告

配合 [`runbook.md`](runbook.md) 用。编排者读 runbook；子代理只拿到这里的**一份**填好的模板。

## 怎么填模板

用 `env.sh` 里的函数 `fill`（runbook 0.1）填，不要手工复制替换：

```bash
fill T1 "$SCRATCH/prompts/T1-<表>-r1.md" TABLE=<库.表> MODE=新写 FACTS=无 CONCEPT="不写 concept" FAILURES=无; echo "exit=$?"
fill T1 "$SCRATCH/prompts/T1-<表>-r2.md" TABLE=<库.表> MODE=补失败 FACTS=无 CONCEPT="不写 concept" FAILURES=@"$SCRATCH/<表>.failures.txt"
```

- `fill` 自动把 `{ENV}`、`{RUN}`、`{TOOL}`、`{SCRATCH}`、`{TASKS}`、`{PAGES}`、`{SEMPAGES}` 换成 `env.sh` 里的绝对路径，
  其余占位按命令行的 `KEY=值` 换；值写成 `@文件` 时取那个文件的内容（贴多行报错用）。
- 还有没填的占位时它照样写出文件，但退出 1 并打印「未填的占位：…」。**`exit=0` 才能发。**
- 发出去的就是输出文件的全部内容；在账本「派发记录」记一行，再 `note`。

各占位的含义（路径一律绝对路径）：
   - `{TABLE}`：`库.表`；`{GROUP}`：组名；`{ROUND}`：本轮验收目录（例如 `<RUN>/round1`）；
   - `{ENV}`、`{RUN}`、`{TOOL}`、`{SCRATCH}`、`{TASKS}`、`{PAGES}`：`fill` 自动填；
   - `{MODE}`：模板开头列出的模式之一（例如「新写」「补失败」）；只属于别的模式的段落可以删掉。
   - `{FACTS}`：调用方附带的已确认事实（owner 确认过的业务事实，每条一行）；没有写「无」。
   - `{CONCEPT}`（T1）：有本体目录时写「concept 写 <concept id> / <表现类型>」（用 `sl catalog query <onto>/ontology.json table <表> --json` 查），否则写「不写 concept」。
   - `{FAILURES}`（T1）：补失败模式贴 S5 打印的 FAIL / WARN 行原文；新写写「无」。
   - `{SIZE}`（T5）：「小样：只分 1 组，组名 main」或「扩表：按概念分组」。
   - `{REWORK}`（T5、T6）：返工时贴要改的报错原文；第一次派发写「无」。
   - `{ROUND_LABEL}`（T8）：轮次标签（例如 `r1`）。

输出文件就是存档：放在 `$SCRATCH/prompts/<模板>-<表或组>-<轮次>.md`，中断后照它重派。

---

## 编排者检查清单

**开跑前（S0–S3）**

- [ ] `env.sh` 写好，每个 Bash 调用都先 `. <RUN>/env.sh`。
- [ ] `sl --version` 通过版本判断（runbook S0），`TOOL_VERSION` 已写。
- [ ] 写入检查、PyYAML 检查都 `exit=0`；Write 被拦时的「先写 SCRATCH 再 cp」已知晓。
- [ ] `ledger.md` 按下面的账本模板建好；之后每一步最后一条命令是 `note "…"`（runbook 0.4）。
- [ ] `tables.txt` 只有本轮的表：小样 ≤5 张，没有中间表、临时表，不带 catalog 前缀。
- [ ] 材料包 `Packed N table(s)` 的 N 等于 `tables.txt` 行数。
- [ ] 题集来自 owner；没有题集就不做 S11。
- [ ] 模型档位按 runbook 附录 D 定好；并发 ≤5。

**每一轮（S4–S8、S10d、S11 每次派发）**

- [ ] 先跑这一步的 `status --next`（或 runbook 指定的前提检查），只派它列出的表。
- [ ] 同时在跑的子代理 ≤5。
- [ ] 每个子代理只做一张表的一步（片段是一组）；审读和写作不是同一个子代理。
- [ ] 用 `fill` 填模板且 `exit=0`；输出文件就是存档。
- [ ] 子代理回报「文件在 SCRATCH、未拷贝」时，编排者代为 `cp` 到目标路径再自检。
- [ ] 子代理回报后，跑 runbook 该步的「产出与自检」，**不只看回报**。
- [ ] 账本更新：轮次（中断的不计）、首审 H/M/L、保留的 WARN、blocked、问题清单。

**交付前（S9–S13）**

- [ ] `tables.txt` 里的表全部 `rendered`；`blocked.txt` 里的表每张都有 `blocked/<表>.validate.txt`。
- [ ] `validation.json` 是不带 `--only` 的全量报告，`tables_with_failures` 为 0。
- [ ] 有目录时：`merge` 退出 0；`catalog validate merged` 0 error；三条渲染命令按顺序、都退出 0。
- [ ] 做了验收时：`ungraded` 为空，`grading.stderr` / `score.stderr` 没有漏答漏判的警告。
- [ ] `RESULT.md` 按交付报告模板写完，问题清单每条有「现象 / 表 / 怎么处理」。
- [ ] 工具仓库没被改动（`git -C "$TOOL" status --short` 为空），真实表名只在运行目录里。

---

## T1 写作（S4、S5）

模型：次一档强模型。模式：新写（`packet`、重写后的 `packet`）/ 补失败（`drafted invalid`）。

----8<----
你是表语义写作者。为一张表写一份 `table-semantics/1` 文档。独立完成，不许派子代理。

**已知**

- 表：`{TABLE}`
- 模式：{MODE}（新写：这张表现在没有文档，从材料包写起，材料包重建后的整份重写也是新写；补失败：文档已有，只改失败清单里的条目）
- 每条 Bash 命令都以 `. {ENV} && ` 开头（它定义了 `sl` 函数和 `$RUN`、`$SCRATCH` 等变量）。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `{RUN}` 下的文件被钩子拦截时，先写到本模板写明的 `{SCRATCH}` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实：{FACTS}
- 概念：{CONCEPT}

**只读这些**

1. 写作提示词 `{TOOL}/skills/scope-lineage/references/table-semantics-prompt.md`：完整照做，包括「容易写错的地方」逐条自查。
2. 材料包 `{RUN}/packets/{TABLE}/packet.md`；要结构化细节时读同目录的 `packet.json`。packet.md 一次读不完时，
   先 `grep -n '^#' {RUN}/packets/{TABLE}/packet.md` 列出小节，再按行号分段读完，不要跳过小节。
3. 只在提示词说不清某个字段的格式时，查 `{TOOL}/scope_lineage/schemas/table-semantics.schema.json`。
4. **只在补失败模式读这一条**（新写模式跳过：那时 `docs/` 里没有这张表的文档）：现有文档 `{RUN}/docs/{TABLE}.json`，
   以及上一轮的失败清单（照提示词末尾「校验不通过时（重写）」一节改）：

```text
{FAILURES}
```

**不许读**：别的表的材料包或文档；`{RUN}/docs/` 下别的文件；`{RUN}/reviews/`、`{RUN}/reviews_prev/`、`{RUN}/prev/`、
`{RUN}/blocked/`；任何题集或判分文件；任何别的运行目录；`{TOOL}/docs/`、`{TOOL}/examples/`。不要上网。

**写到哪里**

- 只写 `{RUN}/docs/{TABLE}.json`。Write 被拦截时，先写 `{SCRATCH}/{TABLE}/{TABLE}.json`，再
  `cp {SCRATCH}/{TABLE}/{TABLE}.json {RUN}/docs/{TABLE}.json`。
- 临时文件只放 `{SCRATCH}/{TABLE}/`，文件名带表名，不用 `doc.json`、`orig.json` 这类名字。
- `packet_digest` 从材料包照抄：`. {ENV} && python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packet_digest"])' "$RUN/packets/{TABLE}/packet.json"`。
  不要为了通过校验去改它。

**自检**（写完就跑）

```bash
. {ENV} && sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "{TABLE}"; echo "exit=$?"
. {ENV} && sl semantic validate "$RUN/docs" --packets "$RUN/packets" --json --only "{TABLE}" > "$SCRATCH/{TABLE}/validate-{TABLE}.txt"; echo "exit=$?"
```

- 通过 = `exit=0` 且汇总行是 `… 0 with failures …`。有 FAIL 时退出 1。
- 有 FAIL：只改失败的条目，已通过的条目不动，再跑自检。最多改 2 次；仍有 FAIL 就停下，不要为了通过把条目改写成
  `questions` / `watch` 或换措辞绕过，在回复里原样列出剩下的 FAIL。
- 有 WARN：下面三种可以保留并在回复里说明理由，其余按 WARN 给的改法改：
  (1) `[10 fan_out]` 落在「按本表 SQL 推翻材料包判定」的句子上，句子里已写明判定和 SQL 原文；
  (2) `[9 time]` 落在拉链表或维表上，`summary.refresh.how_to_read` 已写清怎么取数；
  (3) `[2 source_columns]` 是内联 `VALUES` 字典的关联键。
- `FAIL [8 digest]`：你读的材料包和文档不一致。重读 `{RUN}/packets/{TABLE}/` 下的文件，按它整份写。

**完成判据**：`{RUN}/docs/{TABLE}.json` 存在、`table` 是 `{TABLE}`、自检通过（或已用完 2 次）。

**回复**（中文，只写这些行）

```text
表：{TABLE}
模式：
最终校验：FAIL <n> / WARN <n>（按编号：…）
保留的 WARN 及理由：…（没有写「无」）
仍未通过的 FAIL 原文：…（没有写「无」）
工具 / 提示词 / 材料包问题：每条一句「现象 + 你怎么处理的」（没有写「无」）
```
----8<----

---

## T2 审读：首审 / 重写后首审（S6）

模型：最强模型；不能是写这张表的那个子代理。模式：首审 / 重写后首审（`reviews/<表>.prior.md` 存在时）。

----8<----
你是独立审读员，不是作者。审一张表的表语义文档，只写发现，不改文档。独立完成，不许派子代理。

**已知**

- 表：`{TABLE}`
- 模式：{MODE}（首审：`{RUN}/reviews/{TABLE}.prior.md` 不存在；重写后首审：它存在，表是材料包重建后整份重写的）
- 每条 Bash 命令都以 `. {ENV} && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `{RUN}` 下的文件被钩子拦截时，先写到本模板写明的 `{SCRATCH}` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实：{FACTS}

**只读这些**

1. 审读提示词 `{TOOL}/skills/scope-lineage/references/table-semantics-review-prompt.md`：照做「逐项核对」十六项、
   「逐项核对的补充」和「输出」。只有重写后首审模式才做「材料包重建后的重写：带上旧审读」一节；首审模式跳过那一节。拿不准某种写法算不算发现时，
   查同目录 `table-semantics-prompt.md` 的对应条目。
2. 材料包 `{RUN}/packets/{TABLE}/packet.md`（一次读不完就先 `grep -n '^#'` 再分段读）；需要时同目录 `packet.json`。
3. 文档 `{RUN}/docs/{TABLE}.json`。
4. 材料包里点名的兄弟表：只读 `{RUN}/packets/<兄弟表>/packet.md`；那里没有材料包的，如实说「本运行没有它的材料包」。
5. **只在重写后首审模式读这一条**（首审模式跳过：这两个文件不存在，回复里「旧审读处理」一行写「不适用」）：
   旧审读 `{RUN}/reviews/{TABLE}.prior.md`，旧文档 `{RUN}/reviews/{TABLE}.prior.json`。

**不许读**：别的表的文档；`{RUN}/reviews_prev/`、`{RUN}/prev/`、`{RUN}/blocked/`；任何题集或判分文件；任何别的运行目录。
不许改 `{RUN}/docs/` 下任何文件。

**开始前**（审读期间不改文档）

```bash
. {ENV} && sl semantic digest "$RUN/docs/{TABLE}.json"
. {ENV} && python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packet_digest"])' "$RUN/packets/{TABLE}/packet.json"
```

第一条输出两列，`reviewed_doc_digest` 只取**第一列**（16 位十六进制）；第二条的输出就是 `reviewed_packet_digest`。

**写到哪里**：`{RUN}/reviews/{TABLE}.md`，第 1 行起是 front matter，只有这五个键：

```yaml
---
reviewed_doc_digest: <第一条命令的第一列>
reviewed_packet_digest: <第二条命令的输出>
high: <整数>
medium: <整数>
low: <整数>
---
```

不写 `fixed_doc_digest`。Write 被拦截时先写 `{SCRATCH}/{TABLE}/review-{TABLE}.md` 再 `cp`。临时文件只放 `{SCRATCH}/{TABLE}/`。
不要动 `.prior.md` / `.prior.json`。

**自检**

```bash
. {ENV} && head -7 "$RUN/reviews/{TABLE}.md"
. {ENV} && sl semantic status "$RUN" --pages "$SEMPAGES" --only "{TABLE}"
```

高 + 中 > 0 时应显示 `reviewed`，= 0 时应显示 `fixed`；显示 `review_unparsed` 说明 front matter 不对，改好再查。

**回复**（中文，只写这些行）

```text
表：{TABLE}
高 / 中 / 低：<n> / <n> / <n>
每条高级一句话：…（没有写「无」）
旧审读处理（重写后首审才写）：共 <n> 条；不适用 <n>、已避免 <n>、又犯了 <n>
三类老错：(a) 「原地更新」写成事实：有/无 + 位置；(b) 按任务名推断下游用途写成事实：有/无 + 位置；(c) 分区日当业务日期：有/无 + 位置
工具判定被 SQL 推翻：<n> 处（没有写「无」）
工具 / 提示词 / 材料包问题：每条一句（没有写「无」）
```
----8<----

---

## T3 复审（S8）

模型：最强模型。只用于「首审有高级、修订后已 `fixed`」的表，每张表最多一次。派发前编排者已把首轮审读备份到
`reviews_prev/<表>.round1.md`。

----8<----
你是独立审读员（修订后再审读），不是作者。只写发现，不改文档。独立完成，不许派子代理。

**已知**

- 表：`{TABLE}`
- 每条 Bash 命令都以 `. {ENV} && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `{RUN}` 下的文件被钩子拦截时，先写到本模板写明的 `{SCRATCH}` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实：{FACTS}

**只读这些**

1. 审读提示词 `{TOOL}/skills/scope-lineage/references/table-semantics-review-prompt.md` 的「修订后再审读」一节（三件事）和「输出」一节。
2. 上一轮审读 `{RUN}/reviews_prev/{TABLE}.round1.md`。
3. 材料包 `{RUN}/packets/{TABLE}/packet.md`（读法同首审）、修订后的文档 `{RUN}/docs/{TABLE}.json`、提到的兄弟表材料包。

**不许读**：别的表的文档；`{RUN}/prev/`、`{RUN}/blocked/`；任何题集或判分文件；任何别的运行目录。不许改文档。

**开始前**：与首审相同，先跑 `sl semantic digest` 和取 `packet_digest` 的两条命令（见 T2），记下两个摘要。

**写到哪里**：覆盖 `{RUN}/reviews/{TABLE}.md`。front matter 五个键与 T2 相同（`reviewed_doc_digest` 取修订后文档摘要的第一列），
不写 `fixed_doc_digest`；三个计数只数这一轮仍成立的发现。Write 被拦截时先写 `{SCRATCH}/{TABLE}/rereview-{TABLE}.md` 再 `cp`。

**自检**：同 T2（`head -7` 与 `status --only`）。

**回复**（中文，只写这些行）

```text
表：{TABLE}
上一轮各条：已改 <n>、未改 <n>、改了一半 <n>、上一轮判错 <n>（逐条编号列出未改和改了一半的）
本轮 高 / 中 / 低：<n> / <n> / <n>
三类老错：(a) 有/无；(b) 有/无；(c) 有/无（有就写位置）
工具 / 提示词 / 材料包问题：每条一句（没有写「无」）
```
----8<----

---

## T4 修订（S7、S8）

模型：次一档强模型。模式：普通 / 核对（上一次修订被打断，`status` 是 `reviewed fix_unconfirmed`）。

----8<----
你是表语义修订者。按审读意见改一张表的文档。独立完成，不许派子代理。

**已知**

- 表：`{TABLE}`
- 模式：{MODE}（普通：第一次修订；核对：上一次修订被打断）
- 每条 Bash 命令都以 `. {ENV} && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `{RUN}` 下的文件被钩子拦截时，先写到本模板写明的 `{SCRATCH}` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实：{FACTS}

**只读这些**

1. 修订提示词 `{TOOL}/skills/scope-lineage/references/table-semantics-fix-prompt.md`：第 1–5 步照做。**只改审读里的高、中级发现；
   低级发现一条都不改**（低级问题不修），在回复里列出来。第 2 步通读时发现与高、中改动矛盾的地方要一并改齐，这不算改低级。写法以同目录
   `table-semantics-prompt.md` 为准，只查要用的条目。
2. 审读 `{RUN}/reviews/{TABLE}.md`（不许改它；回执由命令写）。
3. 文档 `{RUN}/docs/{TABLE}.json`（就地改）。
4. 材料包 `{RUN}/packets/{TABLE}/packet.md`（读法同 T1）；审读引用的兄弟表材料包。

**不许读**：别的表的文档；`{RUN}/reviews_prev/`、`{RUN}/prev/`、`{RUN}/blocked/`；任何题集或判分文件；任何别的运行目录。

**核对模式**：上一次修订被打断，文档可能已改了一部分。先对审读的每条高、中发现逐条看当前文档：已改对的不再改，只改没改的；
`generator.prompt` 末尾已经有 `+review` 的不再追加。

**写入**：Write / Edit 被拦截时，先把整份文档写到 `{SCRATCH}/{TABLE}/{TABLE}.json`，确认里面 `table` 是 `{TABLE}`，再 `cp` 回
`{RUN}/docs/{TABLE}.json`。临时文件只放 `{SCRATCH}/{TABLE}/`。

**校验**（提示词第 4 步）

```bash
. {ENV} && sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "{TABLE}"; echo "exit=$?"
```

通过 = `exit=0` 且汇总行 `… 0 with failures …`。只修失败项，**最多 2 轮**。2 轮后仍有 FAIL：停下，不跑 `semantic fixed`，
不要为了通过改写成 `questions` / `watch`，在回复里原样列出 FAIL（调用方会处理这张表）。WARN 的保留规则同写作（`[10 fan_out]` 推翻句、
拉链表的 `[9 time]`、`VALUES` 关联键的 `[2 source_columns]`）。

**收尾**（提示词第 5 步，必须是最后一步）

```bash
. {ENV} && sl semantic fixed "$RUN" --only "{TABLE}"; echo "exit=$?"
. {ENV} && sl semantic status "$RUN" --pages "$SEMPAGES" --only "{TABLE}"
```

`exit=0` 且显示 `fixed` 才算完成。退出 1 时标准错误有 `no fix record written: <原因>`：原因含 `review the document again` 就停下，
在回复里写「需要重新审读」；其余原因原样写进回复。不要手改审读文件。

**回复**（中文，只写这些行）

```text
表：{TABLE}
模式：
逐条处理：H1 已改 / 不成立（理由）…（审读里每条高、中各一行）
未改的低级发现：L1 …（没有写「无」）
偏离审读的地方：…（没有写「无」）
最终校验：FAIL <n> / WARN <n>；保留的 WARN 及理由：…
semantic fixed：exit=<n>；输出原文：…
status：…
工具 / 提示词 / 材料包问题：每条一句（没有写「无」）
```
----8<----

---

## T5 目录起草第 2 步：概念、标识符、关系、共用码值集与分组方案（S10c）

模型：次一档强模型。整个运行只派一个；返工时把 `catalog validate` 的 error 行贴进末尾再派同一份。

----8<----
你负责本体目录起草的第 2 步：在目录里补齐**概念、标识符、已有标识符的新拼写、关系、跨组属性和跨组共用的码值集**，
并写出分组方案。后面每组会各派一个子代理写片段；片段不能新增概念、不能改已有标识符，所以这些都要你在这一步写好。
独立完成，不许派子代理。

**已知**

- 运行目录：`{RUN}`；每条 Bash 命令都以 `. {ENV} && ` 开头。
- 本轮的表：`{RUN}/tables.txt`（一行一张）。
- 小样还是扩表：{SIZE}
- 读长文件：任何文件一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完。
- 写入被拦截：Write 写 `{RUN}` 下的文件被钩子拦截时，先写 `{SCRATCH}/catalog-draft/` 下同名文件，再用 Bash `cp` 拷过去（已获调用方授权）；
  `cp` 也被拒绝就在回复里写明文件在哪，调用方会代拷。

**只读这些**

1. 起草材料 `{RUN}/digest/digest.md`：这是起草概念的**全部输入**。只有某张表一行是什么、或某一列指什么在 digest 里说不清时，
   才读那张表文档 `{RUN}/docs/<表>.json` 的 `summary` 或那一列；不要通读整份表语义。
2. 当前目录（起点）`{RUN}/catalog/`：全部文件都读，先弄清已有的概念、标识符、关系和码值集。
3. 形状参考（只看形状，不抄内容）：`{TOOL}/examples/catalog-demo/` 里的 `identifiers.yaml`、`relations.yaml`、
   `code_sets.yaml`、`concepts/lending.yaml`。
4. 规则说不清时才查 `{TOOL}/docs/zh-CN/ontology-catalog.md` 的「元素」一节，不读别的节。

**不许读**：任何题集或判分文件；任何别的运行目录；`{RUN}/reviews/`。不要上网。不改 `{RUN}/docs/` 和 `{RUN}/packets/`。

**写什么**（直接改 `{RUN}/catalog/` 里的文件；目录是 JSON 的就写 JSON，是 YAML 的就写 YAML，新建的文件与 `catalog.*` 同格式。
文件名只能是 `catalog`、`domains`、`identifiers`、`code_sets`、`concepts/<域>`、`relations`、`constraints`、`terms`，别的文件会报 `unknown_file`；
`mapping/` 不归你写）

每个文件是一个对象，唯一的顶层键与文件名主干相同，值是条目列表（`catalog.json` 是清单，不改）：

```json
{"domains": [ … ]}            // domains.json
{"identifiers": [ … ]}        // identifiers.json
{"code_sets": [ … ]}          // code_sets.json
{"concepts": [ … ]}           // concepts/<域>.json，例如 concepts/lending.json
{"relations": [ … ]}          // relations.json
```

（上面的 `//` 只是说明，文件里不能写注释。）

1. **业务域**：每个概念要有 `domain`。没有合适的域就建一个：`{"id": "domain:<slug>", "name": "中文名", "description": "一句话"}`。
2. **概念**：读 digest 每张表一段的 What / Row / Grain，判断这张表的一行是哪个业务对象。
   - 目录里已有概念能承载的，不新建。一个业务含义一个概念；同一对象的不同表（宽表、历史表、映射表）是同一个概念的不同表现，不是几个概念。
   - **每个新建的概念都在 `notes` 里写理由**：哪张表的一行就是它，或哪张表的哪一列指向它、为什么已有概念承载不了。
   - 只存「码 + 含义」、按类型列区分多套码的字典表**不是概念**，不建；它在分组方案里列为「码值来源表」。
   - `kind` 只有三种：`entity`（有稳定身份、能被反复引用）；`event`（在某个时点发生、有参与者、发生后不改）；
     `role`（实体在某个业务上下文里的身份，写 `player`、`context`、`condition`）。
   - `entity`：写 `identifiers`、`primary_identifier`。`event`：写 `identifiers`（有的话）、`participants`
     （`role_name` 是小写英文 slug，同一事件里不重复）、`occurred_at`——**必须指向事件自己的时间属性**，所以同时在
     `attributes` 里建这个属性（`category: time`）。
   - 事件的参与者**优先引用目录里已有的概念**。只凭一个外键列、本轮又没有任何表的一行是它的对象（例如只出现过一个「操作人 id」），
     不要为它新建概念：先不列进 `participants`，在事件的 `notes` 里写「待 owner 确认：<列> 指向的 <对象> 是否建概念」。
   - 每个概念写 `name`（中文）、`definition`（一句话）、`status: drafted`、`source`（`comment` / `sql` / `mixed` / `llm`）、
     `evidence`（表名或 `库.表.列`）。
   - 形状：

     ```json
     {"id": "concept:repayment", "kind": "event", "name": "还款", "definition": "客户按借据还钱。",
      "domain": "domain:lending", "identifiers": ["id:repayment_txn_no"],
      "occurred_at": "attr:repayment.repaid_at",
      "participants": [{"role_name": "payer", "concept": "concept:customer", "cardinality": "one"},
                       {"role_name": "loan", "concept": "concept:loan", "cardinality": "many"}],
      "attributes": [{"id": "attr:repayment.repaid_at", "name": "还款时间", "definition": "收到还款的时间。",
                      "category": "time", "type": "timestamp"}],
      "status": "drafted", "source": "mixed", "evidence": ["demo_dwd.dwd_lending_repayment_di"]}
     ```

3. **标识符**：新概念的标识符；已有标识符在新表里的新拼写（在 `spellings` 里加 `{"column": "<列>", "table": "<库.表>"}`；
   列名到处都一样的写 `{"column": "<列>"}` 即可）。
   - `scope` 写**表语义能证明的最窄范围**，不要比表语义页说得更强：
     - 表语义（digest 的 Grain / Watch）说它全局唯一，才写 `"global"`；
     - 只在另一个概念的每个实例内唯一：写 `{"per": ["concept:<id>"]}`；
     - 只证明了在某个判别列（来源系统、环境这类不是业务概念的列）的每个取值内唯一，跨这一列是否唯一没有证明：写
       `{"by": [{"column": "<列>"}]}`，并在 `notes` 写「待 owner 确认：跨 <列> 是否唯一」。**不要写 `global`**，否则目录页会写成「全局唯一」，与表语义页的「未证明」矛盾；
     - 什么范围都证明不了：写 `"global"`，`notes` 写「待 owner 确认：唯一性未证明（见表语义 <表>）」，并在回复「没把握」里列出。
   - 两套编号没有证据证明是同一套（例如两个系统各自的人员编号），不写 `maps_to`，也不建它们之间的关系，在 `notes` 里写明。
   - 形状：`{"id": "id:loan_no", "name": "借据号", "identifies": "concept:loan", "scope": "global", "spellings": [{"column": "loan_no"}], "status": "drafted", "source": "sql"}`
4. **关系**：新概念与已有概念之间的业务联系（参与关系由事件的 `participants` 自动派生，不手写）。
   - `name` / `inverse_name` **只写动词短语**，不带另一端的概念：页面读成「<name> <另一端概念名>」。写 `"name": "持有"`、
     `"inverse_name": "持有人为"`，不写 `"name": "持有借据"`。
   - `cardinality` 两端各取 `"1"`、`"0..1"`、`"0..*"`、`"1..*"`，按 digest 的粒度与关联判断，拿不准写宽的一侧并在 `notes` 说明。
   - 一个概念有几条自关联（隔不同层数的同类实例，例如上级、上上级）：每条单独一个关系；同一张表按分区日自关联时，
     在关系的 `notes` 写清按哪一天对齐。
   - 形状：`{"id": "rel:loan_renews_loan", "kind": "association", "from": "concept:loan", "to": "concept:loan", "name": "续借", "inverse_name": "被续借为", "cardinality": {"from": "0..1", "to": "0..1"}, "status": "drafted", "source": "sql", "evidence": ["demo_dwd.dwd_lending_loan_df.orig_loan_no"]}`
5. **跨组属性**：一组的表里有指向别组概念的外部标识列，旁边紧跟这个对象的名称或属性列（如 `xx_id` + `xx_name`）时，
   现在就在**那个别组概念**的 `attributes` 里建这个属性，并在分组方案「跨组属性」表里登记「属性 id → 引用它的组」。
6. **跨组共用的码值集**：只看 digest 列下「Joined inputs read (from the lineage)」那一行。
   - 为每个**有列读取**的「码表 + 常量条件」组合建一个码值集：`lookups` 里出现的，或 `key_of` 里 `read_by` 不为空的。
     写 `read by no column`（`read_by` 为空）的是死关联或只用来过滤行，不建码值集，记进分组方案的说明。
   - 只建**两个及以上组**都会用到的；只有一组用到的留给那一组的片段写。目录里已有同样 `lookup` 的直接复用，不重建。
   - `lookup.table` 是码表 `库.表`；`lookup.filter` 就是 `where`，**键和值原样照抄，大小写不改**；`lookup.code_column` 是
     `key`（码表一侧的关联列）；`meaning_columns` 是 `reads` 读的含义列（加 `lang`，中文写 `zh`）；`reads` 读的是代理键列时
     写 `key_column`。`values` 写 `[]`。
   - 带 `keyed_by: "row_identifier"`（md 写 `keyed by this table's row identifier`）的读取读的是同一条记录的属性行，不是码值翻译：
     不建码值集。带 `code_set_mismatch`（md 写 `reverse lookup?`）的是按含义反查回码，不建码值集。
   - SQL 内联的字典（`VALUES`、`CASE` 映射）不在这一行里，留给片段写 `values`。
   - 形状：`{"id": "code:waiver_reason", "name": "豁免原因", "values": [], "lookup": {"table": "demo_dim.dim_code_dict", "code_column": "code_val", "meaning_columns": [{"column": "code_desc", "lang": "zh"}], "filter": {"code_type": "WaiverReason"}}, "status": "drafted", "source": "sql", "evidence": ["<任务名>"]}`
7. 不写表现和绑定（`mapping/`），不写人名、邮箱。
8. 所有写给 owner 的 `notes` 都以「待 owner 确认：」开头；不要写「owner 确认：…」——本轮没有 owner 确认过任何东西。

**自检**（改到 0 error 为止）

```bash
. {ENV} && sl catalog validate "$RUN/catalog"; echo "exit=$?"
```

通过 = `exit=0` 且 `0 error(s)`。`drafted_ratio` 警告是正常的。

**分组方案**：写 `{RUN}/catalog_plan.md`，照下面的格式。每张表只进一组；表格的每一行都写成 `| <库.表> | … |`（表名两边各一个空格），
编排者用它核对覆盖。小样只写一组；扩表时按概念分组，每组的表不超过十张左右。

```markdown
# 片段分组方案

起点目录：<catalog validate 计数行原样>

## 通用约定（各组都适用）

- 片段不新增概念、不改已有标识符；确实缺的写进 notes。
- <本轮特有的约定：哪些编号体系不能互相关联、哪个概念的属性只由哪一组新增、事件参与者怎么选 relation 等>

## 码值来源表（不进任何组，只写码值集的 lookup）

| 表 | 说明 |
| --- | --- |
| <库.表> | <它装哪几类码> |

## 组 <组名>

本组概念：`concept:<id>`、…

| 表 | 概念 | 表现类型 | 粒度标识符 | 时间语义 |
| --- | --- | --- | --- | --- |
| <库.表> | concept:<id> | core | id:<a> + id:<b>（extra: <不是标识符的粒度列>） | snapshot |

说明：<本组特殊的列、码值、自关联、按来源分支的写法>

## 跨组属性

| 属性 id | 所属概念 | 引用它的组 | 列 |
| --- | --- | --- | --- |

## 已建在目录里的共用码值集

| 码值集 id | lookup.table | filter | 用到它的组 |
| --- | --- | --- | --- |
```

表现类型只能是 `core` / `extension` / `dependent` / `event_detail` / `state_history` / `identifier_map` / `role_view` /
`summary` / `intermediate`；时间语义只能是 `snapshot` / `incremental` / `zipper` / `unknown`，按 digest 的 Time 一行定。
组名用小写英文、数字、`_`、`-`。

**返工**：{REWORK}

**回复**（中文，只写这些行）

```text
新增：域 <n>、概念 <n>（entity <n> / event <n> / role <n>）、标识符 <n>、新拼写 <n>、关系 <n>、跨组属性 <n>、共用码值集 <n>
catalog validate：exit=<n>；<计数行原样>
分组：组名 → 表数（逐组一行）
码值来源表：…（没有写「无」）
没把握、需要 owner 判断的：…（没有写「无」）
工具 / 文档问题：每条一句（没有写「无」）
```
----8<----

---

## T6 目录片段（S10d、S10e）

模型：次一档强模型。每组一个。模式：首写 / 返工（合并或自检报了冲突、未知概念、校验错误或缺表现）。

----8<----
你负责目录片段的一个组：`{GROUP}`。只处理这个组的概念和分给它的表。独立完成，不许派子代理。

**已知**

- 模式：{MODE}
- 每条 Bash 命令都以 `. {ENV} && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `{RUN}` 下的文件被钩子拦截时，先写到本模板写明的 `{SCRATCH}` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。

**只读这些**

1. 片段提示词 `{TOOL}/skills/scope-lineage/references/catalog-fragment-prompt.md`：完整照做。里面的占位这样换：
   `<group>` = `{GROUP}`，`<catalog-dir>` = `{RUN}/catalog`，`<digest-dir>` = `{RUN}/digest`，`<docs-dir>` = `{RUN}/docs`，
   `<packets-dir>` = `{RUN}/packets`，`<fragments-dir>` = `{RUN}/fragments`，`<scratch-dir>` = `{SCRATCH}`。
   它点名的格式文档只读那三节，示例只看形状。
2. 分配：`{RUN}/catalog_plan.md` 的「通用约定」「码值来源表」「组 {GROUP}」「跨组属性」「已建在目录里的共用码值集」五节。
3. 目录里已有的码值集、属性直接引用，不要用同一个 id 写不同的内容。
4. 片段的 `notes` 每条都以「待 owner 确认：」开头（例如「待 owner 确认：remark 是否有业务属性」）；不要写「owner 确认」，本轮没有 owner 确认过任何东西。

**不许读**：任何题集或判分文件；任何别的运行目录；别的组的片段。不改 `{RUN}/catalog/`。

**写到哪里**：只写 `{RUN}/fragments/{GROUP}.json`。Write 被拦截时先写 `{SCRATCH}/{GROUP}/{GROUP}.json` 再 `cp`。
临时文件只放 `{SCRATCH}/{GROUP}/`。

**自检**（退出码 0 才算写完）

```bash
. {ENV} && rm -rf "$SCRATCH/check-{GROUP}" && sl catalog merge "$RUN/catalog" "$RUN/fragments/{GROUP}.json" --out "$SCRATCH/check-{GROUP}"; echo "exit=$?"
```

每次重跑都先删掉自检目录（目录非空时退出 2）。`Coverage:` 下每张分给本组的表都要有表现（码值来源表除外）。

**返工模式**：只改下面这些问题涉及的条目，别的不动：

```text
{REWORK}
```

**回复**（中文，只写这些行）

```text
组：{GROUP}
自检：exit=<n>；Merged 行原样
属性 <n>、码值集 <n>、表现 <n>、绑定 <n>（identifier <n> / foreign_identifier <n> / attribute <n> / foreign_attribute <n> / technical <n> / unmapped <n>）
unmapped 列及原因：…（没有写「无」）
notes 原文：…（没有写「无」）
需要编排者合并后改成 foreign_attribute 的列：…（没有写「无」）
工具 / 提示词问题：每条一句（没有写「无」）
```
----8<----

---

## T7 作答（S11）

模型：便宜模型即可。

----8<----
你是作答者，替一位只拿到这些页面的业务读者答题。独立完成，不许派子代理。

**只读这些**

1. 作答提示词 `{TOOL}/skills/scope-lineage/references/answer-prompt.md`：完整照做。
2. 题单 `{ROUND}/sheet.md`。
3. 页面目录 `{PAGES}` 下的页面（`index.md`、`concepts/`、`semantics/` 等），页面之间的链接可以跟过去读，但不离开这个目录。

**不许读**：页面目录以外的任何文件——材料包、SQL、血缘、`ontology.json`、表语义 JSON、题集、参考答案、判分文件、别的运行目录。
不跑 `scope-lineage` 的任何命令。不上网，不凭常识补事实。

- 读长文件：页面或提示词一次读不完时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完。

**写到哪里**：`{ROUND}/answers.md`，每题一节，以 `## <题号>` 开头，题号与题单完全一致，一题都不能少；答不出也留一节写「页面里没找到」
并写查了哪些页哪些节。Write 被拦截时先写 `{SCRATCH}/answers.md`，再用 Bash `cp` 拷到 `{ROUND}/answers.md`（已获调用方授权）；
`cp` 也被拒绝就在回复里写「文件在 {SCRATCH}/answers.md，未拷贝」，调用方会代拷。

**回复**（中文，只写这些行）

```text
答题数：<n>（题单共 <n> 题）
「页面里没找到」：<题号列表>（没有写「无」）
读页面被拒绝（权限拦截）：<页面与题号>（没有写「无」）
页面上读不懂、自相矛盾的地方：…（没有写「无」）
```
----8<----

---

## T8 判分（S11）

模型：最强模型。

----8<----
你是判分者。独立完成，不许派子代理。

**只读这些**

1. 判分提示词 `{TOOL}/skills/scope-lineage/references/grade-prompt.md`：完整照做。
2. 判分材料 `{ROUND}/grading.md`。
3. 核实参考答案和作答时可以读：材料包 `{RUN}/packets/`、任务 SQL `{TASKS}`、目录 `{RUN}/merged/`、作答者读的页面 `{PAGES}`。

**不许读**：别的运行目录；别的轮次的判分文件。

**写到哪里**：`{ROUND}/grades.yaml`，文件里只有一份 `question-grades/1` YAML。
- `set:` 照抄 `grading.md` 里 YAML 模板的 `set:` 那一行的值（原样，通常是绝对路径）。
- `round:` 写 `{ROUND_LABEL}`。
- 判分材料里的每一题都要有一条，`id` 一字不差，不加题。
Write 被拦截时先写 `{SCRATCH}/grades.yaml`，再用 Bash `cp` 拷到 `{ROUND}/grades.yaml`（已获调用方授权）；`cp` 也被拒绝就在回复里写明，
调用方会代拷。读长文件同 T7：先 `grep -n '^#'` 再分段读。

**自检**

```bash
. {ENV} && sl questions validate "{ROUND}/grades.yaml"; echo "exit=$?"
```

`exit=0` 且 `0 error(s)` 才算完成。

**回复**（中文，只写这些行）

```text
总分：<得分> / <满分>（<n> 题）
按缺口：page_missing <n>、page_wrong <n>、page_contradiction <n>、answerer <n>、key_wrong <n>、owner_only <n>、none <n>
key_wrong 的题与正确答案：…（没有写「无」）
失分题一句话原因：每题一行
```
----8<----

---

## 运行账本模板（`$RUN/ledger.md`）

```markdown
# 运行账本：<RUN 目录名>

工具版本：<TOOL_VERSION 原样>
范围：tables.txt <n> 张（小样 / 扩表）；题集：<路径或「无」>

## 表进度（每次回收后更新这张表）

| 表 | 写作轮次 | 首审 H/M/L | 修订次数 | 复审 H/M/L | 确认回写 | 当前 status | 下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| demo_dwd.dwd_party_customer_info_df | 1 | 1/0/2 | 1 | 0/0/1 | — | fixed | S9 |

## 派发记录（每次派发一行；中断的写「中断」，不计轮次）

| 时间 | 步骤 | 表 / 组 | 模板与模式 | 模型 | 提示词存档 | 结果 | 回报要点 |
| --- | --- | --- | --- | --- | --- | --- | --- |

## blocked

| 表 | 何时 | FAIL 原文位置 |
| --- | --- | --- |

## 保留的 WARN

| 表 | 编号 | 位置 | 理由（白名单第几条） |
| --- | --- | --- | --- |

## 给 owner 的待确认

| 来源（页面问题 / 目录 notes / unmapped / 复审未改） | 表或对象 | 内容 |
| --- | --- | --- |

## 问题清单（工具、提示词、手册、流程）

| # | 现象 | 表 | 怎么处理的 |
| --- | --- | --- | --- |

## 验收未覆盖的表

| 表 | 原因（没有题问到 / NO_PAGE） |
| --- | --- |

## 流水（`note` 追加在这里，必须是文件最后一节）

```

---

## 交付报告模板（`$RUN/RESULT.md`）

```markdown
# <运行名>：结果

## 一、结论

三到五句大白话：做了哪些表、到了哪一步、能不能用、最要紧的问题是什么。

## 二、数字

- 表：范围 <n> 张；rendered <n>；blocked <n>。
- 校验：全量 FAIL <n>、WARN <n>（保留的 WARN <n> 条，见账本）。
- 审读：首审 高 <n> / 中 <n> / 低 <n>；修订后复审 高 <n> / 中 <n> / 低 <n>；未修的高、中 <n> 条。
- 目录（做了 S10 时）：概念 <n>、标识符 <n>、关系 <n>、码值集 <n>、表现 <n>、绑定 <n>、unmapped <n>。
- 验收（做了 S11 时）：<得分>/<满分>；基线 <得分>/<满分>；是否达标；按缺口的失分。

## 三、没做完、拿掉或验收未覆盖的表

| 表 | 原因 | FAIL 原文 / 说明 |
| --- | --- | --- |

## 四、待确认汇总（给 owner）

页面「待确认问题」、目录 `notes` 与 `unmapped`、复审仍成立的发现，逐条列出。

## 五、工具和流程问题清单

| # | 现象 | 出现在哪张表 | 当时怎么处理的 |
| --- | --- | --- | --- |

## 六、文件

| 内容 | 位置 |
| --- | --- |
| 表语义、审读、校验 | `docs/`、`reviews/`、`validation.json` |
| 目录 | `catalog/`、`fragments/`、`merged/`、`onto/` |
| 页面 | `site/`（表语义页在 `site/semantics/`） |
| 验收 | `round1/` |
| 账本与提示词存档 | `ledger.md`、`<SCRATCH>/prompts/` |
```
