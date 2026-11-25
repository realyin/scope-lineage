## S9b 为待确认问题写平台查询（可选）

**目的**：S9 之后，派一个子代理把各表 open 的待确认问题拆成子问题，给数据能答的子问题各写一条只读 SELECT，存成
`$RUN/probes/question-probes.json`（`question-probes/1`），交给能在平台上执行查询的人。**工具从不执行 SQL，也不连接任何平台**：
`semantic probes check` 只读每条查询的语法树检查它。结果回来后按 S12 的「观测条目」在浏览页上贴回（或手写）成确认条目。

这一步可选：没有能执行查询的人、或 owner 不要，就跳过；进度脚本从不把它判成当前步，只在 `probes/` 里的查询比检查报告新时提示重跑检查。

**前提检查**：S9 做完（`validation.json` 在，`FAILURES 0`）；文档里有 open 的问题。列出它们：

```bash
python3 -c 'import json,sys
for p in sys.argv[1:]:
    d = json.load(open(p))
    for q in d["summary"].get("questions", []):
        if q.get("status") == "open": print(d["table"], q["id"], q["text"])' "$RUN"/docs/*.json
```

一行都没有就跳过这一步。owner 给了敏感列名单（一行一个列名或 `库.表.列`，`#` 起注释）时，放到 `$RUN/sensitive-columns.txt`：
检查命令自己找到它（在 `--packets` 旁边），不用加参数；没有名单时只拦文档里的标识类列及其来源列，报告里有一条警告。

**命令**

```bash
mkdir -p "$RUN/probes"
fill probes "$SCRATCH/prompts/T-probes-r1.md" MODE=首写 REWORK=无; echo "exit=$?"
```

`exit=0` 才派发（次一档强模型，一个子代理写全部表）。它回报之后检查：

```bash
sl semantic probes check "$RUN/probes/question-probes.json" --packets "$RUN/packets" --docs "$RUN/docs" > "$RUN/probes/check.txt"; echo "exit=$?"
cat "$RUN/probes/check.txt"
```

`exit=1`（有 FAIL）时把报告原样交回同一个模板的返工模式，最多两轮（同 S5：一次派发算一轮，子代理自己改几次不另计）：

```bash
fill probes "$SCRATCH/prompts/T-probes-r2.md" MODE=返工 REWORK=@"$RUN/probes/check.txt"; echo "exit=$?"
```

两轮后仍有 FAIL：把失败的项从文件里删掉（`items` 里整项删，同一子问题的其余项留着），重跑检查到 `exit=0`，在账本记下删掉的 id 和 FAIL 原文。
不要为了通过去改 `--docs`、名单或材料包。

**产出与自检**

- `$RUN/probes/question-probes.json`，`$RUN/probes/check.txt` 最后一行 `RESULT: PASS (0 failure(s), <n> warning(s))`。
- 警告逐条看：`engine` 没写、标了 `full_scan` 却每张表都带了分区条件、问题已回答、没有敏感列名单。能改的交回返工，其余记进账本。
- 每个 open 问题都有子问题（`class` 为 `data`、`human` 或 `corpus`）；`lands` 只出现在唯一性与取值清单两种形状上。

**交给执行查询的人**：把 `question-probes.json` 交出去，并说明：

1. 每条查询先把 `${…}` 占位符换成真实值（`placeholders` 里是示例），在 `engine` 写的引擎上执行（缺省 Spark：平台默认路由可能换引擎而失败）；
   `partitions` 里想要的分区还没有、`fallback` 是 `latest_available` 时，改用最近可用的分区并记下实际用的值。
2. 每条查询交回一个结果文件 `$RUN/probes/results/<id>.json`（`id` 是查询项的 id），键为
   `sql_id, status, run_on, bizdate, sql_executed, columns, rows, note`：`status` 为 `ok` 或失败原因，`run_on` 是执行日期 `YYYY-MM-DD`，
   `bizdate` 是实际读的分区值，`sql_executed` 是替换后的 SQL，`columns` 是输出列名，`rows` 是行的数组（每行一个数组）。
3. 不交明细、不交结果以外的数据。
4. **只换占位符**：除了把 `${…}` 换成真实值（和按 `fallback` 换分区值），不改写、不放宽任何查询——不删条件、不加大 `LIMIT`、不换表或列。
   查询跑不通就照第 5 条交回，由写作者改，不要自己改了再跑。
5. **报错原文照录**：执行失败时 `status` 写失败，`note` 原样贴平台的报错，不改写查询重跑。
6. **表名照文件写**：查询里的表名按 `question-probes.json` 里的写法用，不换库名、不加别名前缀；平台上确实叫别的名字时记进 `note`，不改 `sql_executed` 以外的东西。

结果回来后：带 `lands` 的项（唯一性、取值清单）在浏览页上贴回成观测（服务加 `--probes`，见 S12「观测条目」），不开页面时按那张表手写成观测确认条目；
其余项的结果只作一句话回答的依据，由 owner 在 S12 回答问题时引用（页面上贴回即带引用）。`status` 不是 `ok` 或 0 行的结果不写条目。

**常见失败与处理**

| 现象 | 退出码 | 处理 |
| --- | --- | --- |
| `fill` 报前提文件不存在：`validation.json` | 1 | S9 还没做完，回 S9 |
| `fill` 返工模式报前提文件不存在：`probes/question-probes.json` | 1 | 子代理没写出文件：看它的回复，首写模式重派 |
| 检查退出 2 | 2 | 文件读不了、`--packets` / `--docs` 不存在，或 `sensitive-columns.txt` 有一行不是列名：改名单或路径，不派子代理 |
| 报告里有 schema 错误（`schema_errors`），后面不再检查 | 1 | 文件不合 `question-probes/1`：报告交回返工 |
| C7 FAIL（问题原文已不是 `asked`） | 1 | 问题在写查询之后被改写过：交回返工，按现在的原文重拆 |
| `semantic probes check` 不认识（`invalid choice`） | 2 | 工具版本早于这条命令：跳过这一步，记进账本 |

**完成判据**：`check.txt` 最后一行 `RESULT: PASS`；查询文件已交给执行人（或在账本写明为什么不交）。

**下一步**：回到主流程，S10（不做目录就 S11）。查询结果回来后到 S12 写观测条目。
