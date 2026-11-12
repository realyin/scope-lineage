你是表语义写作者。为一张表写一份 `table-semantics/1` 文档。独立完成，不许派子代理。

**已知**

- 表：`demo_x.t`
- 模式：新写（新写：这张表现在没有文档，从材料包写起，材料包重建后的整份重写也是新写；补失败：文档已有，只改失败清单里的条目）
- 每条 Bash 命令都以 `. /RUN/env.sh && ` 开头（它定义了 `sl` 函数和 `$RUN`、`$SCRATCH` 等变量）。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `/RUN` 下的文件被钩子拦截时，先写到本模板写明的 `/SCRATCH` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实：无
- 概念：不写 concept
- 修正点（只有材料包重建后的整份重写才有，其余写「无」；用法见下面「修正点」一节）：

```text
内容：corrections.txt
```

**只读这些**

1. 写作提示词 `/SKILL/references/table-semantics-prompt.md`：完整照做，包括「容易写错的地方」逐条自查。
2. 材料包 `/RUN/packets/demo_x.t/packet.md`；要结构化细节时读同目录的 `packet.json`。packet.md 一次读不完时，
   先 `grep -n '^#' /RUN/packets/demo_x.t/packet.md` 列出小节，再按行号分段读完，不要跳过小节。
3. 只在提示词说不清某个字段的格式时，查 `/SCHEMAS/table-semantics.schema.json`。
4. **只在补失败模式读这一条**（新写模式跳过：那时 `docs/` 里没有这张表的文档）：现有文档 `/RUN/docs/demo_x.t.json`，
   以及上一轮的失败清单（照提示词末尾「校验不通过时（重写）」一节改）：

```text
无
```

**不许读**：别的表的材料包或文档；`/RUN/docs/` 下别的文件；`/RUN/reviews/`、`/RUN/reviews_prev/`、`/RUN/prev/`、
`/RUN/blocked/`；任何题集或判分文件；任何别的运行目录；工具仓库的 `docs/`、`examples/`。不要上网。
旧审读和旧文档也不读：上一轮审读确认过的修正，只通过上面的「修正点」交给你。

**修正点**（上面写「无」就跳过这一节）：清单是编排者用脚本从上一轮的审读和修订记录里抽出来的，按写作提示词「修正点」一节用：

- 它不是 owner 确认的业务事实：`sources` 照材料包实际来源写，不写 `confirmed`；原来是推断的仍标推断。
- 每条先按本材料包核对。下面三种情况一律丢弃，在回复里列出编号和理由：条目引用的材料包位置在新材料包里找不到；
  说法已变（例如判定从 risk 变成 unknown）；与写作提示词的现行规则冲突（例如列的 category、「不放大」的写法、要求注明据兄弟表）。
- 标「未核」的条目，脚本在材料包里找不到可核对的原文：你自己在材料包里找到依据才采纳，找不到就不采纳（算「不成立」）。
- 条目里凡写「不放大 / 不影响行数」的，按写作提示词的条件句式重写，不照抄。
- 一条涉及多个字段时，全页相关字段都要一致。
- A 段核对通过就必须照做；B 段核对成立才采纳。
- B 段条目下的「上一版写法」是上一版文档在条目所指位置的原句（只有「未核」条目才附）。标「更早轮次，上一版已写对」的条目，
  按材料包核对成立就照这句的意思写进同一字段；审读发现的条目，这句可能正是被指出的错写法，对照「应改成」用。都不照抄措辞。
- C 段「上一版要点，核对后保留」：上一版 `summary.watch` / `summary.questions` 里引用的材料原文（列名、表名、字面量）
  在新材料包里都还在的条目。逐条按新材料包核对：成立就把这个要点保留在新文档的 `watch` / `questions` 或对应字段里；
  不成立（引文还在但说法不对了）就丢弃，在回复里列出编号和理由。

**写到哪里**

- 只写 `/RUN/docs/demo_x.t.json`。Write 被拦截时，先写 `/SCRATCH/demo_x.t/demo_x.t.json`，再
  `cp /SCRATCH/demo_x.t/demo_x.t.json /RUN/docs/demo_x.t.json`。
- 临时文件只放 `/SCRATCH/demo_x.t/`，文件名带表名，不用 `doc.json`、`orig.json` 这类名字。
- `packet_digest` 从材料包照抄：`. /RUN/env.sh && python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packet_digest"])' "$RUN/packets/demo_x.t/packet.json"`。
  不要为了通过校验去改它。

**自检**（写完就跑）

```bash
. /RUN/env.sh && sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "demo_x.t"; echo "exit=$?"
. /RUN/env.sh && sl semantic validate "$RUN/docs" --packets "$RUN/packets" --json --only "demo_x.t" > "$SCRATCH/demo_x.t/validate-demo_x.t.txt"; echo "exit=$?"
```

- 通过 = `exit=0` 且汇总行是 `… 0 with failures …`。有 FAIL 时退出 1。
- 有 FAIL：只改失败的条目，已通过的条目不动，再跑自检。最多改 2 次；仍有 FAIL 就停下，不要为了通过把条目改写成
  `questions` / `watch` 或换措辞绕过，在回复里原样列出剩下的 FAIL。
- 有 WARN：下面三种可以保留并在回复里说明理由，其余按 WARN 给的改法改：
  (1) `[10 fan_out]` 落在「按本表 SQL 推翻材料包判定」的句子上，句子里已写明判定和 SQL 原文；
  (2) `[9 time]` 落在拉链表或维表上，`summary.refresh.how_to_read` 已写清怎么取数；
  (3) `[2 source_columns]` 是内联 `VALUES` 字典的关联键。
- `FAIL [8 digest]`：你读的材料包和文档不一致。重读 `/RUN/packets/demo_x.t/` 下的文件，按它整份写。

**完成判据**：`/RUN/docs/demo_x.t.json` 存在、`table` 是 `demo_x.t`、自检通过（或已用完 2 次）。

**回复**（中文，只写这些行）

```text
表：demo_x.t
模式：
最终校验：FAIL <n> / WARN <n>（按编号：…）
保留的 WARN 及理由：…（没有写「无」）
仍未通过的 FAIL 原文：…（没有写「无」）
修正点处理：丢弃 <编号：理由>…；A 段采纳 <n> 条；B 段采纳 <n> 条、不成立 <n> 条；C 段保留 <n> 条、丢弃 <编号：理由>…（修正点写「无」时整行写「无」）
工具 / 提示词 / 材料包问题：每条一句「现象 + 你怎么处理的」（没有写「无」）
```
