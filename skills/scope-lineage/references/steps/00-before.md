## 0. 开跑前

### 0.1 变量块（`$RUN/env.sh`，用脚本生成）

`env.sh` 不用手写：跑 skill 自带的 `scripts/init_run.py`，它按参数写出 `<运行目录>/env.sh` 并把内容打印出来。
`<SKILL>` 是 skill 目录的绝对路径（里面有 `SKILL.md`、`references/`、`scripts/`）；路径全部写绝对路径，一律用正斜杠（Git Bash 会吞掉反斜杠）。

```bash
python3 <SKILL>/scripts/init_run.py \
  --run /abs/path/to/runs/run-20260101 \
  --scratch /abs/path/to/scratchpad/run-20260101 \
  --tasks /abs/path/to/tasks \
  --schema /abs/path/to/schema; echo "exit=$?"
```

| 参数 | 写进 `env.sh` 的变量 | 含义 |
| --- | --- | --- |
| `--run` | `RUN` | 运行目录（新建，不要复用别的运行目录）；脚本会建好它 |
| `--scratch` | `SCRATCH` | 临时目录，不放在 `RUN` 里面（放进去脚本退出 1） |
| `--tasks` | `TASKS` | 任务 JSON 目录（`parse --input-dir`） |
| `--schema` | `SCHEMA` | 表元数据：rich-JSON 目录或文件（`parse --schema`） |
| `--ddl` | `DDL` | 目标表 DDL 元数据；和 `SCHEMA` 是同一目录就写同一个值；没有就不写 |
| `--patch` | `PATCH` | owner 审过的 `metadata-patch.json`；没有就不写 |
| `--overrides` | `OVERRIDES` | owner 审过的 `glossary.overrides.json`；没有就不写 |
| `--questions` | `Q` | 回归题集（`question-set/1`）；没有就不写 |
| `--tool` | `TOOL` | 工具仓库根目录（里面有 `skills/` `docs/` `examples/` `pyproject.toml`）。不写时脚本自己判断：skill 在仓库里就是那个仓库；pip 安装、没有仓库就是空的 |

脚本还会建好账本 `<运行目录>/ledger.md`（已经有就不动它）。`env.sh` 里另外写好四样，不用给参数：

- `SKILL`：脚本自己所在的 skill 目录。
- `PAGES="$RUN/site"`（页面根目录：概念页、`index.md`）、`SEMPAGES="$RUN/site/semantics"`（表语义页目录）。
- 最后一行 `. "$SKILL/scripts/runlib.sh"`：它定义函数 `sl`（调用工具：`TOOL` 非空时 `uv run --project "$TOOL" --extra catalog scope-lineage`，
  为空时用已安装的 `scope-lineage`）、`fill`（填模板：模板写编号或名字，参数写 `KEY=值`，值写 `@文件` 表示取文件内容；用法见 `runbook-templates.md`「怎么填模板」）、
  `load_tables`（把 `tables.txt` 读进数组 `TABLES`，读到 0 张表就报错）、`note`（账本流水：每一步做完的最后一条命令，
  例：`note "S4 派 T1 demo_dwd.x 第1轮"`），以及变量 `SCHEMAS`（工具自带的 JSON Schema 目录）和 `set -o pipefail`。

`env.sh` 已经存在时脚本退出 1、不改它：要换某个路径就直接改那一行等号右边。Windows 上 `python3` 指向应用商店占位程序
（退出码 49、「Python was not found」）时，取消 `env.sh` 里 `# python3() { python "$@"; }` 那行的注释。

0.11.2 及更早的手册写出的 `env.sh`（函数直接写在文件里）续跑时，在它最后加一行 `. "$SKILL/scripts/runlib.sh"`。

每开一个新的 shell（Claude Code 里**每一次** Bash 调用都是新的 shell，变量和函数不会保留），第一条命令都是：

```bash
. /abs/path/to/runs/run-20260101/env.sh
```

下文的命令都假定已经执行过这一行。忘了这一行的症状：`sl: command not found` / `command not found: sl`，
或路径变成以 `/packets`、`/docs` 开头（变量是空的）。处理：补上这一行重跑，不要改路径。

### 0.2 七条调用规则

1. **只用函数 `sl` 调用工具**，不要写 `SL="uv run …"; $SL parse`：zsh 不会把变量拆成多个词，会报
   `no such file or directory: uv run …`（退出码 127）。
2. **`--extra catalog` 不能省**：读 `.yaml` 的命令（`catalog`、`questions`）没有它会以退出码 2 报缺 PyYAML。
3. **判断成功只看两样：退出码和本手册指定的摘要行 / JSON 键。**「输出看起来正常」不算。每条要判断的命令后面紧跟
   `echo "exit=$?"`。
4. **要判断退出码的命令不接管道。**`sl … | tail -3` 之后的 `$?` 是 `tail` 的。要看长输出就重定向到文件
   （`> "$SCRATCH/x.txt" 2>&1`），再读文件。
5. **表名列表一律用数组**：先 `load_tables`，命令里写 `"${TABLES[@]}"`。`--only` 一律放在命令**最后**（它会吞掉后面所有的词）。
   `TABLES` 和变量一样不跨 Bash 调用：**每个用到 `"${TABLES[@]}"` 的命令块都要先跑 `load_tables`**，它打印
   `tables=N`，N 是 0 时返回非 0。漏了的症状：`status` 打出一行空表名的 `no_packet`；`--only: no document for `
   或 `no table written by the corpus is named ` 后面什么都没有（退出 1）。处理：补 `load_tables` 重跑。
6. **路径一律绝对路径**，表名一律 `库.表`（不带 catalog 前缀，例如写 `demo_dwd.dwd_lending_loan_df`，
   不写 `spark_catalog.demo_dwd.dwd_lending_loan_df`）。
7. **遇到手册里没有的情况就停**：把命令、退出码、报错原文写进账本「问题清单」，交 owner；不要自己改工具、
   改提示词或改格式文档，也不要换一种「差不多」的命令绕过去。

### 0.3 小样原则

- 第一次跑（或换了工具版本、换了提示词）先跑**小样**：≤5 张表、目录只分 1 组、回归只用约 15 道题。
- 小样从 S0 走到 S11 全部达标后，才按 owner 的指示扩到更多表；扩表时从 S3 开始，同一个运行目录继续。
- 全量由 owner 指定的人或 agent 跑。没有 owner 明说「跑全量」，就只跑小样。
- 只重写了一部分表（例如材料包重建后重写了 5 张）时：`docs/` 里只放这几张表的文档，页面和目录也只从它们来
  （S10a 走 B）。不要把上一个运行目录的文档、`merged/` 或 `site/` 拿来一起渲染：旧目录里关于这几张表的说法
  （标识符范围、概念定义）不会跟着新文档变，页面会自相矛盾。owner 指定要把它们接回已有的完整目录时，S10a 走 C。

### 0.4 账本与恢复

- **每一步做完，最后一条命令是 `note "<步骤> <做了什么> <结果>"`**（往 `ledger.md` 末尾的「流水」追加一行）；
  派发、回收子代理时同时更新账本的表格。不更新账本，编排者自己被打断后就只能靠猜。
- **编排者自己被打断后**（会话中断、额度用完、重开会话），按这个顺序恢复，不要从头跑：
  1. `. <RUN>/env.sh`，读 `$RUN/ledger.md` 末尾的流水，看最后做完的是哪一步。
  2. 跑进度脚本（0.6），以它为准（账本和它不一致时以它为准，并记进问题清单）：

     ```bash
     python3 "$SKILL/scripts/next_step.py" "$RUN"
     ls "$SCRATCH/prompts" 2>&1
     ```

  3. 从它打印的「当前」那一步的「前提检查」重新开始（`status --next` 会跳过已完成的表）。当前步是 S11 时，
     再看它点名的那个验收目录（`round1/`、`round2/` …，每套题一个）里有什么，按下表找到 S11 的第几步：

     | 看到的情况 | 当前步 |
     | --- | --- |
     | `round1/` 只有 `sheet.md` | S11 第 1 步（作答） |
     | 有 `answers.md`，没有 `grading.md` 或 `grades.yaml` | S11 第 2、3 步 |
     | 有 `grades.yaml`，没有 `score/score.json` | S11 第 4 步 |

  4. 正在跑的子代理没有回报就算中断：不计轮次，按 `$SCRATCH/prompts/` 里的存档重派同一份提示词。

- 任何检查命令重跑之后，都**以最新一次的输出为准**：文件改过，报错条数和文字都可能变，不要拿旧的报错去处理。

