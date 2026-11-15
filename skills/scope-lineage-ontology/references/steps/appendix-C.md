## 附录 C 报错与退出码速查

| 命令 | 现象（原文片段） | 退出码 | 处理 |
| --- | --- | --- | --- |
| 任意 | `no such file or directory: uv run …` | 127 | 用函数 `sl`（0.2 第 1 条） |
| 读 YAML 的命令 | 报缺 PyYAML | 2 | `--extra catalog`（S0） |
| `parse` | 摘要行 `failed` / `input_failed` 不为 0 | 0 或非 0 | S1 |
| `semantic packet` | `no table written by the corpus is named …` | 1 | S3：表名 |
| `semantic validate` | 汇总行 `N with failures`（N ≥ 1）；含第 8 项过期、没有材料包 | 1 | S5（工具早于 0.8.0 时退出 0，照样按汇总行判）；报告照常写出 |
| `semantic validate` | `FAIL [8 digest] … 材料包变了，按新材料包整份重写 …` | 1 | S4 重写准备，整份重写 |
| `semantic validate --only` | `--only: no document for …` | 1 | 附录 A |
| `semantic validate` | 目录或 `--packets` 不存在 | 2 | 路径写错 |
| `semantic status` | 有表过期或无效 | 0 | 正常；看阶段和标记 |
| `status` / `validate` / `catalog digest` / `semantic packet` | 一行空表名的 `no_packet`；`--only: no document for ` 或 `no table written by the corpus is named ` 后面是空的 | 0 / 1 | 漏了 `load_tables`（0.2 第 5 条） |
| 任意 | `sl: command not found`，或路径以 `/docs`、`/packets` 开头 | 127 / 2 | 漏了 `. <RUN>/env.sh`（0.1） |
| `fill` | `未填的占位：{…}`；`缺参数：…` | 1 | 补上那几个 `KEY=值` 再跑 |
| `fill` | `没有占位 {…}：模板选错了…`；`的 MODE 只能是：…` | 1 | 模板或模式选错了：按报错和本手册那一步的命令改，不要删参数硬过 |
| `fill` | `的前提文件不存在：…`；`要求这个文件不存在，它却存在：…`；`… 要写成 @文件` / `要写「无」` | 1 | 前一步没做完，或模板、模式选错了（例如该派修订却填了复审、重写漏了修正点清单）。回到对应的步骤 |
| `semantic status` | `--json - and --next without --out both want stdout` | 2 | `--next` 加 `--out "$RUN/next.json"` |
| `semantic fixed` | `the following arguments are required: --only` | 2 | 加 `--only <表>` |
| `semantic fixed` | `no fix record written: …` | 1 | S7 的原因表 |
| `semantic render` | 有文档不合 schema（`skipped` 不为 0） | 1 | S5 |
| `semantic render` / `catalog digest` | `warning: packet_stale …` / `warning: invalid …` / `warning: no_packet …`（点名表） | 0 | 回 S8，不要用这批输出 |
| `semantic render` / `catalog digest` | `--packets does not exist: …` | 2 | 路径写错 |
| `semantic confirm` | `unmatched` 不为 0 | 0 | S12 |
| `semantic confirm` | 确认文件格式不对；`--reviews` 与 `--out` 同给 | 2 | S12 |
| `catalog validate` | `N error(s)`（N ≥ 1） | 1 | S10a / S10c |
| `catalog digest` | `skipped` 不为 0，或 `--only` 的表没有文档 | 1 | S10b |
| `catalog merge` | `--out … is not empty` | 2 | 先 `rm -rf` 输出目录 |
| `catalog merge` | `conflict` / `unknown concept` / 校验 error | 1 | T6 返工 |
| `catalog build` | 校验 error，什么也没写 | 1 | S10f |
| `catalog render` | `--semantics directory does not exist` | 2 | 先 `semantic render`（S10g） |
| `questions sheet` 等 | `no question in the set has table/concept …` | 1 | 改用 `--ids` |
| `questions sheet` | `warning: no page under … for the table of …` | 0 | S11：去掉这些题 |
| `questions grading-sheet` | `warning: no answer for: …` | 0 | S11 |
| `questions score` | `warning: not graded …` | 0 | S11 |
| `questions score` | 判分文件有题集没有的题号 | 1 | T8 返工 |
| Read 工具 / Bash 输出 | 文件一次读不完或输出被截断（`packet.md`、提示词都可能） | — | 先 `grep -n '^#' <文件>` 列小节，再按行号分段读完（模板里已有） |
| Write 工具 | 写 `$RUN` 被钩子拦截 | — | 先写 `$SCRATCH` 再 `cp`；子代理 cp 也被拒时由编排者代拷（S4） |
| 子代理 | 429 / 额度用完 / 没回报 | — | 不计轮次；额度恢复后重跑 `status --next`，已完成的表自动跳过 |

