你是独立审读员，不是作者。审一张表的表语义文档，只写发现，不改文档。独立完成，不许派子代理。

**已知**

- 表：`demo_x.t`
- 模式：首审（首审：`/RUN/reviews/demo_x.t.prior.md` 不存在；重写后首审：它存在，表是材料包重建后整份重写的）
- 每条 Bash 命令都以 `. /RUN/env.sh && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `/RUN` 下的文件被钩子拦截时，先写到本模板写明的 `/SCRATCH` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 调用方附带的已确认事实：无

**只读这些**

1. 审读提示词 `/SKILL/references/table-semantics-review-prompt.md`：照做「逐项核对」十六项、
   「逐项核对的补充」和「输出」（定级照「输出」一节的定级锚点）。只有重写后首审模式才做「材料包重建后的重写：带上旧审读」一节；首审模式跳过那一节。拿不准某种写法算不算发现时，
   查同目录 `table-semantics-prompt.md` 的对应条目。
2. 材料包 `/RUN/packets/demo_x.t/packet.md`（一次读不完就先 `grep -n '^#'` 再分段读）；需要时同目录 `packet.json`。
3. 文档 `/RUN/docs/demo_x.t.json`。
4. 材料包里点名的兄弟表：只读 `/RUN/packets/<兄弟表>/packet.md`；那里没有材料包的，如实说「本运行没有它的材料包」。
5. **只在重写后首审模式读这一条**（首审模式跳过：这两个文件不存在，回复里「旧审读处理」一行写「不适用」）：
   旧审读 `/RUN/reviews/demo_x.t.prior.md`，旧文档 `/RUN/reviews/demo_x.t.prior.json`。

**不许读**：别的表的文档；`/RUN/reviews_prev/`、`/RUN/prev/`、`/RUN/blocked/`；任何题集或判分文件；任何别的运行目录。
不许改 `/RUN/docs/` 下任何文件。

**开始前**（审读期间不改文档）

```bash
. /RUN/env.sh && sl semantic digest "$RUN/docs/demo_x.t.json"
. /RUN/env.sh && python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packet_digest"])' "$RUN/packets/demo_x.t/packet.json"
```

第一条输出两列，`reviewed_doc_digest` 只取**第一列**（16 位十六进制）；第二条的输出就是 `reviewed_packet_digest`。

**写到哪里**：`/RUN/reviews/demo_x.t.md`，第 1 行起是 front matter，只有这五个键：

```yaml
---
reviewed_doc_digest: <第一条命令的第一列>
reviewed_packet_digest: <第二条命令的输出>
high: <整数>
medium: <整数>
low: <整数>
---
```

不写 `fixed_doc_digest`。Write 被拦截时先写 `/SCRATCH/demo_x.t/review-demo_x.t.md` 再 `cp`。临时文件只放 `/SCRATCH/demo_x.t/`。
不要动 `.prior.md` / `.prior.json` / `.fixlog.txt`。正文的格式（发现的标题、四个小标题、处理结果表格的小节标题）照审读提示词
「输出」一节的硬格式写：下一次重写时，脚本按这个格式从你的审读里抽修正点。

**自检**

```bash
. /RUN/env.sh && head -7 "$RUN/reviews/demo_x.t.md"
. /RUN/env.sh && sl semantic status "$RUN" --pages "$SEMPAGES" --only "demo_x.t"
```

高 + 中 > 0 时应显示 `reviewed`，= 0 时应显示 `fixed`；显示 `review_unparsed` 说明 front matter 不对，改好再查。

**回复**（中文，只写这些行）

```text
表：demo_x.t
高 / 中 / 低：<n> / <n> / <n>
每条高级一句话：…（没有写「无」）
旧审读处理（重写后首审才写）：共 <n> 条；不适用 <n>、已避免 <n>、又犯了 <n>
三类老错：(a) 「原地更新」写成事实：有/无 + 位置；(b) 按任务名推断下游用途写成事实：有/无 + 位置；(c) 分区日当业务日期：有/无 + 位置
工具判定被 SQL 推翻：<n> 处（没有写「无」）
工具 / 提示词 / 材料包问题：每条一句（没有写「无」）
```
