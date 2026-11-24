你是表语义修订者。按审读意见改一张表的文档。独立完成，不许派子代理。

**已知**

- 表：`demo_x.t`
- 模式：首修（首修：这份审读的第一次修订；核对：上一次修订被打断，或 owner 刚确认了行粒度、列含义或码值，或刚回写了平台查询的观测）
- 每条 Bash 命令都以 `. /RUN/env.sh && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `/RUN` 下的文件被钩子拦截时，先写到本模板写明的 `/SCRATCH` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实（owner 确认过的，用法见下面「已确认事实」一节；没有时是「无」）：

```text
无
```

**只读这些**

1. 修订提示词 `/SKILL/references/table-semantics-fix-prompt.md`：第 1–5 步照做。**只改审读里的高、中级发现；
   低级发现一条都不改**（低级问题不修），在回复里列出来。第 2 步通读时发现与高、中改动矛盾的地方要一并改齐，这不算改低级。写法以同目录
   `table-semantics-prompt.md` 为准，只查要用的条目。
2. 审读 `/RUN/reviews/demo_x.t.md`（不许改它；回执由命令写）。
3. 文档 `/RUN/docs/demo_x.t.json`（就地改）。
4. 材料包 `/RUN/packets/demo_x.t/packet.md`（读法同 T1）；审读引用的兄弟表材料包。

**不许读**：别的表的文档；`/RUN/reviews_prev/`、`/RUN/prev/`、`/RUN/blocked/`；任何题集或判分文件；任何别的运行目录。

**已确认事实**（上面写「无」就跳过这一节）：照写作提示词「已确认的业务事实」一节采用，逐项做到：

- 三种槽位照原值写：行粒度列、是否唯一、列含义、码值含义写进对应字段，不改写、不加后缀或旁注，`sources` 带 `confirmed`；
  确认了行粒度列或是否唯一、没确认来源时，`grain_source` 写 `declared`，不写 `inferred`。`sources` 里的 `confirmed` 只给这三种槽位（行粒度、列含义、码值）。
- 确认了行粒度列或是否唯一时（粒度列就是文档的 `summary.row.grain_columns`；事实里可能只有「是否唯一」一行）：
  `summary.row.text` 按确认的粒度重写一行是什么；`note` 以「已确认 …」开头；这些列不再写「候选键（推断）」「未证明唯一」「待确认」；
  `unique: no` 时写明同一粒度键可能有多行、计数要先去重，材料包没说为什么就写「原因未说明」，不要编原因；
  `what`、`good_for`、`how_to_read` 里说一行是什么的句子跟着改齐。
- 已回答的问题：由回答得出的句子写进相关条目的文字，句末标「（已确认）」，这个条目的 `sources` 不因它加 `confirmed`；
  回答只用于它说的那个对象；不再就它提问。
- 不从确认推出材料里没有的事实（「按 (a, b) 唯一」≠「同一 a 有多个 b」）。确认与 SQL 有张力时两说并列（「已确认 X；SQL 显示 Y」），
  不删有 SQL 依据的句子；「放大」的条件句照原样保留。
- 以「观测：」开头的行是平台查询的结果，不是 owner 的话，也不是定义：照写作提示词「观测事实」一节写（带查询、分区、执行日期；
  不写裸「唯一」、不写 `proven`；关联句用那一节给的句式，一句一条关联），对应条目的 `sources` 不因它加 `confirmed`；
  只在观测里出现的值不当码值，要列就写 `unconfirmed: true` 并提问。`grain_source: observed`、`row.observed`、`observed_values`、
  `observed_inputs` 由工具写，你不写也不改。
- 按这一节改正文，算第 2 步的改齐，不算改低级。

**核对模式**：上一次修订被打断，文档可能已改了一部分。先对审读的每条高、中发现逐条看当前文档：已改对的不再改，只改没改的；
`generator.prompt` 末尾已经有 `+review` 的不再追加。
owner 刚确认了行粒度、列含义或码值时（或刚回写了观测），这些槽位已由工具写好，审读的发现多半已改过：这一轮只按上一节改正文，而且只改这些地方——
`summary.row` 的 `text` / `note` / `watch`、`summary.watch`、`questions`、`what` / `good_for` / `not_for` / `how_to_read` 里说粒度的句子、
相关列的 `watch`，以及 `rules[].text` / `rules[].watch` 里说这条关联会不会放大行数的句子（可以改，不是非改不可）。不改列的 `meaning`、`code_values`、`rules[].sql`。

**写入**：Write / Edit 被拦截时，先把整份文档写到 `/SCRATCH/demo_x.t/demo_x.t.json`，确认里面 `table` 是 `demo_x.t`，再 `cp` 回
`/RUN/docs/demo_x.t.json`。临时文件只放 `/SCRATCH/demo_x.t/`。

**校验**（提示词第 4 步）

```bash
. /RUN/env.sh && sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "demo_x.t"; echo "exit=$?"
```

通过 = `exit=0` 且汇总行 `… 0 with failures …`。只修失败项，**最多 2 轮**。2 轮后仍有 FAIL：停下，不跑 `semantic fixed`，
不要为了通过改写成 `questions` / `watch`，在回复里原样列出 FAIL（调用方会处理这张表）。WARN 的保留规则同写作（`[10 fan_out]` 推翻句、
拉链表、维表或整分区重算而日期过滤只是从上游挑一个版本的表的 `[9 time]`、`VALUES` 关联键的 `[2 source_columns]`）。

**收尾**（提示词第 5 步，必须是最后一步）

```bash
. /RUN/env.sh && sl semantic confirm "$RUN/docs" --confirmations "$RUN/confirmations" --reviews "$RUN/reviews" --require-asked --only "demo_x.t"; echo "exit=$?"
. /RUN/env.sh && sl semantic fixed "$RUN" --only "demo_x.t"; echo "exit=$?"
. /RUN/env.sh && sl semantic status "$RUN" --pages "$SEMPAGES" --only "demo_x.t"
```

第一条把 owner 的确认重放进文档（没有确认时什么都不改），回执因此记的是重放后的文档；它打印的 `unmatched:` 行、或退出 2 时的报错，
原样写进回复，照常跑后两条。`exit=0` 且显示 `fixed` 才算完成。退出 1 时标准错误有 `no fix record written: <原因>`：原因含 `review the document again` 就停下，
在回复里写「需要重新审读」；其余原因原样写进回复。不要手改审读文件。

**回复**（中文，只写这些行）。「逐条处理」「未改的低级发现」两段会被调用方原样存进这张表的修订记录，下一次重写时脚本按行读：
标题单独一行；下面每条单独一行，以审读里的编号开头（编号照审读原样，例如 `H1`、`M2`），后面紧跟「已改」「不成立」或「未改」，
再写冒号和一句话。一行只写一条，不要把几条写在同一行。

```text
表：demo_x.t
模式：
逐条处理：
H1 已改：<改了哪些字段>
M1 不成立：<理由>
（审读里每条高、中各一行）
未改的低级发现：
L1 未改：<一句话>
（没有低级发现写「无」）
偏离审读的地方：…（没有写「无」）
按确认改的正文：<字段路径>…；未改的写原句和理由（已确认事实是「无」时写「无」）
最终校验：FAIL <n> / WARN <n>；保留的 WARN 及理由：…
semantic confirm：exit=<n>；unmatched 行原文：…（没有写「无」）
semantic fixed：exit=<n>；输出原文：…
status：…
工具 / 提示词 / 材料包问题：每条一句（没有写「无」）
```
