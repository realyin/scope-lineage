# scope-lineage 分步操作手册（runbook）

这份手册写给**编排者**：用 scope-lineage 从 Spark/Hive SQL 任务生成表语义、本体目录和页面，并用问题集做回归验收。
照字面一步一步做，不需要读别的会话。

- 读法：从「0. 开跑前」读起，然后按 S0 → S13 的顺序做。每一步都有七栏：目的 / 前提检查 / 命令 / 产出与自检 /
  常见失败与处理 / 完成判据 / 下一步。前提检查不满足、或完成判据不成立，就停在这一步，不要往下走。
- 子代理（写作、审读、修订、目录起草、片段、作答、判分）由编排者派发。给子代理的话一律用
  [`runbook-templates.md`](runbook-templates.md) 里的填空模板 T1–T8，不要现写。子代理不读本手册。
- 本手册与 `SKILL.md` 或别的文档说法不一致时，以本手册为准，并把不一致记进账本的「问题清单」。
- 例子里的表名都是虚构的（`demo_dwd.dwd_party_customer_info_df` 等，取自仓库 `examples/`）。

---

## 0. 开跑前

### 0.1 变量块（写成 `$RUN/env.sh`）

把下面整块复制，只改等号右边，用 Write 工具（或编辑器）保存为 `<运行目录>/env.sh`。不要用 Bash 的
`cat <<EOF` 写它：不带引号的 `EOF` 会把 `$RUN`、`$@` 当场展开，写出来的文件就错了（非要用 heredoc 就写 `<<'EOF'`）。

```bash
# ===== scope-lineage 运行环境：只改等号右边，全部写绝对路径 =====
export TOOL=/abs/path/to/scope-lineage        # 工具仓库根目录（里面有 skills/ docs/ examples/ pyproject.toml）
export TASKS=/abs/path/to/tasks               # 任务 JSON 目录（parse --input-dir）
export SCHEMA=/abs/path/to/schema             # 表元数据：rich-JSON 目录或文件（parse --schema）
export DDL=                                   # 目标表 DDL 元数据；和 SCHEMA 是同一目录就写同一个值；没有就留空
export PATCH=                                 # owner 审过的 metadata-patch.json；没有就留空
export OVERRIDES=                             # owner 审过的 glossary.overrides.json；没有就留空
export RUN=/abs/path/to/runs/run-20260101     # 运行目录（新建，不要复用别的运行目录）
export SCRATCH=/abs/path/to/scratchpad/run-20260101   # 临时目录，不放在 RUN 里面
export Q=                                     # 回归题集（question-set/1）；没有就留空
export PAGES="$RUN/site"                      # 页面根目录（概念页、index.md）
export SEMPAGES="$RUN/site/semantics"         # 表语义页目录
sl() { uv run --project "$TOOL" --extra catalog scope-lineage "$@"; }
# 已经 pip 安装了 scope-lineage[catalog] 的机器，把上一行换成：sl() { scope-lineage "$@"; }
load_tables() {   # 把 tables.txt 读进数组 TABLES；读到 0 张表就报错
  TABLES=(); while IFS= read -r t; do [ -n "$t" ] && TABLES+=("$t"); done < "$RUN/tables.txt"
  echo "tables=${#TABLES[@]}"; [ "${#TABLES[@]}" -gt 0 ]
}
note() {         # 账本流水：每一步做完的最后一条命令，例：note "S4 派 T1 demo_dwd.x 第1轮"
  printf -- '- %s %s\n' "$(date '+%F %T')" "$*" >> "$RUN/ledger.md"
}
fill() {         # 填模板：fill T1 <输出文件> TABLE=库.表 MODE=新写 FACTS=无 …；值写 @文件 表示取文件内容
  python3 - "$@" <<'PY'
import os, re, sys
tid, out, pairs = sys.argv[1], sys.argv[2], sys.argv[3:]
src = open(os.path.join(os.environ["TOOL"], "skills/scope-lineage/references/runbook-templates.md"), encoding="utf-8").read()
m = re.search(r"^## " + re.escape(tid) + r" .*?^----8<----\n(.*?)^----8<----$", src, re.S | re.M)
if not m:
    sys.exit("没有模板 " + tid)
text = m.group(1)
vals = {k: os.environ.get(k, "") for k in ("RUN", "TOOL", "SCRATCH", "TASKS", "PAGES", "SEMPAGES")}
vals["ENV"] = os.path.join(os.environ["RUN"], "env.sh")
for pair in pairs:
    key, _, value = pair.partition("=")
    vals[key] = open(value[1:], encoding="utf-8").read().strip() if value.startswith("@") else value
for key, value in vals.items():
    if value:
        text = text.replace("{" + key + "}", value)
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, "w", encoding="utf-8").write(text)
left = sorted(set(re.findall(r"\{[A-Z_]+\}", text)))
print(out)
if left:
    sys.exit("未填的占位：" + " ".join(left))
PY
}
set -o pipefail
```

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

### 0.4 账本与恢复

- **每一步做完，最后一条命令是 `note "<步骤> <做了什么> <结果>"`**（往 `ledger.md` 末尾的「流水」追加一行）；
  派发、回收子代理时同时更新账本的表格。不更新账本，编排者自己被打断后就只能靠猜。
- **编排者自己被打断后**（会话中断、额度用完、重开会话），按这个顺序恢复，不要从头跑：
  1. `. <RUN>/env.sh`，读 `$RUN/ledger.md` 末尾的流水，看最后做完的是哪一步。
  2. 跑下面的进度检查，以它为准（账本和它不一致时以它为准，并记进问题清单）：

     ```bash
     load_tables
     sl semantic status "$RUN" --pages "$SEMPAGES" --only "${TABLES[@]}"
     ls "$RUN/catalog_plan.md" "$RUN/fragments" "$RUN/merge_report.txt" "$RUN/onto/ontology.json" "$PAGES/index.md" 2>&1
     ls "$RUN"/round*/ 2>&1
     ls "$SCRATCH/prompts" 2>&1
     ```

  3. 对照下表找到当前步，从那一步的「前提检查」重新开始（`status --next` 会跳过已完成的表）：

     | 看到的情况 | 当前步 |
     | --- | --- |
     | 有表不是 `fixed` / `rendered` | 按附录 A |
     | 全部 `rendered`，没有 `catalog_plan.md`（要做目录时） | S10a / S10b |
     | 有 `catalog_plan.md`，`fragments/` 缺组（对照分组方案的组名） | S10d |
     | 片段齐，没有 `merge_report.txt` 或 `merged/` | S10e |
     | 有 `merged/`，没有 `onto/ontology.json` 或 `$PAGES/index.md` | S10g |
     | `round1/` 只有 `sheet.md` | S11 第 1 步（作答） |
     | 有 `answers.md`，没有 `grading.md` 或 `grades.yaml` | S11 第 2、3 步 |
     | 有 `grades.yaml`，没有 `score/score.json` | S11 第 4 步 |

  4. 正在跑的子代理没有回报就算中断：不计轮次，按 `$SCRATCH/prompts/` 里的存档重派同一份提示词。

- 任何检查命令重跑之后，都**以最新一次的输出为准**：文件改过，报错条数和文字都可能变，不要拿旧的报错去处理。

### 0.5 主流程总览

| 步 | 做什么 | 谁做 | 主要产出 | 模板 |
| --- | --- | --- | --- | --- |
| S0 | 环境、版本、运行目录、账本 | 编排者 | `env.sh`、`TOOL_VERSION`、`ledger.md` | 账本模板 |
| S1 | 血缘解析 | 编排者 | `artifacts/` | — |
| S2 | 表卡与术语 | 编排者 | `corpus/tables.json`、`corpus/glossary.json` | — |
| S3 | 选表与材料包 | 编排者 | `tables.txt`、`packets/` | — |
| S4 | 写作 | 子代理（每表一个） | `docs/<表>.json` | T1 |
| S5 | 校验与 blocked | 编排者 | 校验结论、`blocked.txt` | T1（补失败） |
| S6 | 审读 | 子代理（每表一个） | `reviews/<表>.md` | T2 |
| S7 | 修订 | 子代理（每表一个） | 改过的文档 + 修订回执 | T4 |
| S8 | 状态推进与复审 | 编排者 + 子代理 | 全部 `fixed` | T3、T4 |
| S9 | 全量校验与渲染表语义页 | 编排者 | `validation.json`、`site/semantics/` | — |
| S10 | 本体目录（S10a–S10g） | 编排者 + 子代理 | `catalog/`、`fragments/`、`merged/`、`onto/`、`site/` | T5、T6 |
| S11 | 回归验收 | 编排者 + 子代理 | `round1/score/` | T7、T8 |
| S12 | 确认回写（可选） | 编排者 | 带确认的文档 | — |
| S13 | 交付 | 编排者 | `RESULT.md` | 交付报告模板 |

---

## S0 环境、版本与运行目录

**目的**：确认工具能跑、版本对、运行目录能写；建好目录树、`env.sh`、`TOOL_VERSION` 和账本。

**前提检查**

- `$TOOL/skills/scope-lineage/SKILL.md` 存在；`uv --version` 能运行（或机器上已装 `scope-lineage[catalog]`）。
- 运行目录 `$RUN` 不存在，或是空目录。不要在旧运行目录里开新一轮。

**命令**

```bash
mkdir -p /abs/path/to/runs/run-20260101 /abs/path/to/scratchpad/run-20260101
# 用 Write 工具把 0.1 的变量块写成 /abs/path/to/runs/run-20260101/env.sh，然后：
. /abs/path/to/runs/run-20260101/env.sh
sl --version; echo "exit=$?"
head -3 "$TOOL/CHANGELOG.md"
head -1 "$TOOL/skills/scope-lineage/references/table-semantics-prompt.md"
touch "$RUN/.write-test" && rm "$RUN/.write-test"; echo "exit=$?"
sl catalog validate "$TOOL/examples/catalog-demo" > "$SCRATCH/pyyaml-check.txt" 2>&1; echo "exit=$?"
mkdir -p "$RUN"/{artifacts,corpus,packets,docs,reviews,reviews_prev,prev/docs,blocked/docs,digest,catalog,fragments,confirmations}
mkdir -p "$SCRATCH/prompts"
sl --version > "$RUN/TOOL_VERSION"     # 第二次运行只为写进文件
git -C "$TOOL" log -1 --format='commit %h %cd' >> "$RUN/TOOL_VERSION"
```

然后按 `runbook-templates.md` 的「运行账本模板」建 `$RUN/ledger.md`。

**产出与自检**

- `sl --version` 打印 `scope-lineage X.Y.Z (sqlglot …, source …)`。版本判断：
  - `X.Y.Z` ≥ `0.8.0`：通过。
  - `X.Y.Z` 是 `0.7.x`，同时 `CHANGELOG.md` 第 3 行是 `## Unreleased`、提示词第 1 行含 `table-semantics-prompt@9`：
    这是仓库里的 0.8.0 候选，通过；在 `TOOL_VERSION` 末尾加一行 `candidate 0.8.0`。
  - 其他：不通过。
- 写入检查和 PyYAML 检查两个 `exit=0`。
- `$RUN/TOOL_VERSION`、`$RUN/ledger.md` 存在。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `no such file or directory: uv run …` | 127 | 用了字符串变量调用。改用 0.1 的函数 `sl` |
| `command not found: uv` | 127 | 装 uv，或 `pipx install 'scope-lineage[catalog]'` 后把 `sl` 换成 0.1 注释里的写法 |
| 版本低于 0.8.0 且不是候选 | — | 停下告诉 owner。不要自己 `pipx install` 覆盖，候选会被换掉 |
| PyYAML 检查报 `PyYAML` / `pip install 'scope-lineage[catalog]'` | 2 | `sl` 少了 `--extra catalog`，或安装时没带 `[catalog]` |
| `touch` 失败，或 Write 工具写 `$RUN` 被钩子拦截 | 非 0 | 先写 `$SCRATCH` 下同名文件，再用 `cp` 拷进 `$RUN`。这一条要写进每个子代理的说明（模板里已有） |
| 钩子提示「改用另一个路径」（例如 worktree 里的路径） | — | 运行目录的位置由 owner 指定。按上一行的 SCRATCH + `cp` 做；钩子连 `cp` 也拦、坚持要换路径时，停下问 owner，不要擅自把 `$RUN` 换到别处 |

**完成判据**：版本判断通过；两个检查 `exit=0`；`env.sh`、`TOOL_VERSION`、`ledger.md` 都在。

**下一步**：S1。

---

## S1 血缘解析

**目的**：把任务 SQL 解析成字段级血缘 `artifacts/`，后面所有步骤都读它。

**前提检查**

- 元数据怎么接，按顺序判断，第一条成立就用：
  1. owner（或任务说明）明确给了元数据目录：用它，**优先于** `defaults.json`；只给了一个目录时，`SCHEMA` 和 `DDL` 都写它；
  2. 有 `~/.scope-lineage/defaults.json`：`SCHEMA`、`DDL` 用它的 `schema`、`target_ddl_metadata`；
  3. 任务旁边自带表元数据目录：`SCHEMA` 和 `DDL` 都写这个目录；
  4. 都没有：停下，问 owner 元数据在哪。不要不带 `--schema` 裸跑（`SELECT *` 会展不开，列会绑错）。
  用了 1 而 `defaults.json` 也存在时，在账本记一笔「元数据用 owner 指定的目录」。
- `ls "$TASKS"` 能看到任务 JSON。

**命令**（`DDL` 非空用 A，留空用 B）

```bash
# A
sl parse --input-dir "$TASKS" --schema "$SCHEMA" --target-ddl-metadata "$DDL" --out "$RUN/artifacts"; echo "exit=$?"
# B
sl parse --input-dir "$TASKS" --schema "$SCHEMA" --out "$RUN/artifacts"; echo "exit=$?"
ls "$RUN/artifacts"
```

**产出与自检**

- 摘要行：`Parsed N statement(s) from M input(s) into … (tasks=…, modeled=…, failed=…, input_failed=…, partial_tasks=…, unsupported_mutations=…, root_gap_results=…, …)`。
  只看 `failed`、`input_failed`、`partial_tasks`、`root_gap_results` 四项；其余字段（`binding_fallbacks`、`recovered_syntax`、
  `binding_not_applicable` 等）不为 0 也不用处理。
- `$RUN/artifacts/<任务名>/lineage.json`，一个任务一个目录。目录名是**任务名**，不是表名。
- 看一个任务：`python3 "$TOOL/skills/scope-lineage/scripts/query.py" summary "$RUN/artifacts/<任务名>"`，
  输出里 `final tables:` 是这个任务写的表。

**常见失败与处理**

| 现象 | 处理 |
| --- | --- |
| 摘要行 `failed` / `input_failed` / `partial_tasks` / `root_gap_results` 不为 0 | 对每个有问题的任务跑上面的 `query.py summary`，按 `references/diagnostics.md` 判断原因；缺元数据就问 owner 要；其余记进账本「问题清单」。只要这些任务写的表不在本轮范围（S3），可以继续 |
| 退出码非 0、没有摘要行 | 原文记进问题清单，停下交 owner |

**完成判据**：`exit=0`，摘要行里 `failed=0 input_failed=0`；`partial_tasks`、`root_gap_results` 不为 0 的已逐个记进账本。

**下一步**：S2。

---

## S2 表卡与术语

**目的**：生成表卡 `tables.json`（材料包用它带上下游表的粒度与键）和术语词典 `glossary.json`（带上 owner 已确认的码值含义）。

**前提检查**：S1 完成。`OVERRIDES` 非空时，文件存在。

**命令**（`OVERRIDES` 非空用 B）

```bash
sl tables --lineage "$RUN/artifacts" --out "$RUN/corpus"; echo "exit=$?"
# A：没有 overrides
sl glossary --lineage "$RUN/artifacts" --out "$RUN/corpus"; echo "exit=$?"
# B：有 overrides
sl glossary --lineage "$RUN/artifacts" --out "$RUN/corpus" --overrides "$OVERRIDES"; echo "exit=$?"
```

**产出与自检**

- `$RUN/corpus/tables.json`、`tables.md`、`tables/`（每表一张卡）、`glossary.json`、`glossary.md`。
- 摘要行 `Carded N table(s) from M task(s) (…)`、`Collected … (overrides terms=…, values=…, blank=…, unmatched=…, rejected=…, ignored_fields=…, …)`。

**常见失败与处理**

| 现象 | 处理 |
| --- | --- |
| glossary 摘要行 `unmatched` / `rejected` / `ignored_fields` 不为 0 | overrides 里有拼错的键或缺 `basis` 的条目。把这几项原文记进问题清单交 owner，不要自己猜改 |

**完成判据**：两条命令 `exit=0`；用了 overrides 时 `unmatched=0 rejected=0 ignored_fields=0`。

**下一步**：S3。术语确认一轮（`glossary --template`、`references/glossary-review-prompt.md`）不在主流程里，owner 要求时另做，做完回到本步用 B 重跑。

---

## S3 选表与材料包

**目的**：定下本轮写表语义的表（`tables.txt`），为每张表生成材料包 `packets/<表>/packet.md`（写作、审读、修订只读它）。

**前提检查**：S2 完成。

**命令**

```bash
# 1. 列出语料里有生产任务的表（第 1 列表名，第 2 列写它的任务）
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); [print(t["table"]+"\t"+",".join(sorted({p["task"] for p in t["produced_by"]}))) for t in d["tables"] if t["produced_by"]]' "$RUN/corpus/tables.json" > "$RUN/candidates.tsv"; echo "exit=$?"
cat "$RUN/candidates.tsv"
# 2. 按下面的选表规则，用 Write 工具写 $RUN/tables.txt：一行一个 库.表，不带 catalog 前缀
# 3. 建材料包（PATCH 非空时在 --out 前加 --metadata-patch "$PATCH"）
load_tables; echo "n=${#TABLES[@]}"
sl semantic packet --lineage "$RUN/artifacts" --tasks "$TASKS" --schema "$SCHEMA" \
  --tables "$RUN/corpus/tables.json" --glossary "$RUN/corpus/glossary.json" \
  --out "$RUN/packets" --only "${TABLES[@]}"; echo "exit=$?"
sl semantic status "$RUN" --pages "$SEMPAGES" --only "${TABLES[@]}"; echo "exit=$?"
# 4. 每张表一个子代理私有临时目录
for t in "${TABLES[@]}"; do mkdir -p "$SCRATCH/$t"; done
```

选表规则（按顺序）：

1. owner 点名的表全部要；没点名时只取一个层、或一个业务概念的表。
2. 去掉中间表、临时表：表名含 `tmp_` / `temp_`，或表注释写「临时」「中间」的。它们写进本体会多出假概念。
3. 只存「码 + 含义」的码值字典表照样写表语义，S10 只给它写码值集的 `lookup`、不写表现。
4. 小样 ≤5 张（0.3）。
5. `candidates.tsv` 里带 catalog 前缀的表名（三段），写进 `tables.txt` 时去掉第一段。

**重建材料包**（换了工具版本、换了 `--glossary` / `--metadata-patch` 时）：先留底，再用同一条命令重建，再看哪些表变了：

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --json "$SCRATCH/status-before.json" --only "${TABLES[@]}"
# …重跑上面第 3 步的 semantic packet…
sl semantic status "$RUN" --pages "$SEMPAGES" --only "${TABLES[@]}"
```

显示 `drafted packet_stale` 的表要整份重写（S4 的重写准备）。

**产出与自检**

- 摘要行 `Packed N table(s) from M task(s) (…)`，`N` 等于 `tables.txt` 的行数；给了 `--metadata-patch` 时摘要行里
  `patch_unmatched=0`。
- 每张表有 `$RUN/packets/<表>/packet.md` 和 `packet.json`。
- `status` 里没有 `no_packet`，新表都是 `packet`。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `no table written by the corpus is named <表>` | 1 | 表名拼错，或写了 catalog 前缀，或这张表没有生产任务。对照 `candidates.tsv` 第 1 列改 `tables.txt` |
| `status` 显示 `no_packet` | 0 | 同上 |
| `patch_unmatched` 不为 0 | 0 | 补丁里有键没对上任何表或列，记进问题清单交 owner |

**完成判据**：`exit=0`；`N` = `tables.txt` 行数；`status` 里没有 `no_packet`。

**下一步**：S4。

---

## S4 写作（每张表一个子代理）

**目的**：每张表得到一份按材料包写的 `table-semantics/1` 文档 `$RUN/docs/<表>.json`。

**前提检查**

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --next draft --batch-size 5 --out "$RUN/next.json" --only "${TABLES[@]}"; echo "exit=$?"
cat "$RUN/next.json"
```

`batches` 里的表就是这一步要派的表。每张表按 `status` 的显示分三类：

| `status` 显示 | 类别 | 派发前要做 | 模板 |
| --- | --- | --- | --- |
| `packet` | 新写 | 无 | T1（新写） |
| `drafted packet_stale` | 重写 | 下面的「重写准备」三步 | T1（新写） |
| `drafted invalid` | 补失败 | 见 S5 | T1（补失败） |

**重写准备**（只对 `drafted packet_stale` 的表，每张表做一遍）：

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
[ -f "$RUN/reviews/$T.prior.md" ] && mv "$RUN/reviews/$T.prior.md" "$RUN/reviews/$T.prior.$(date +%Y%m%d%H%M).md"
[ -f "$RUN/reviews/$T.md" ] && mv "$RUN/reviews/$T.md" "$RUN/reviews/$T.prior.md"
cp "$RUN/docs/$T.json" "$RUN/reviews/$T.prior.json"
mv "$RUN/docs/$T.json" "$RUN/prev/docs/$T.json"
sl semantic status "$RUN" --pages "$SEMPAGES" --only "$T"
```

做完这张表显示 `packet`。旧审读（`.prior.md`）和旧文档（`.prior.json`）只在 S6 交给审读员，**不交给写作者**。

**命令**：每批同时派的子代理不超过 5 个。每张表用 T1 填空后派一个子代理，模型用次一档强模型（附录 D）：

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
fill T1 "$SCRATCH/prompts/T1-$T-r1.md" TABLE="$T" MODE=新写 FACTS=无 CONCEPT="不写 concept" FAILURES=无; echo "exit=$?"
```

`exit=0` 才能发（非 0 时它会列出没填的占位）。派发时两种做法等价，任选一种：把这个文件的内容原样粘贴作为子代理的任务；
或者任务只写一句「用 Read 工具完整读 `<这个文件的绝对路径>`，照里面的要求做，读不完就分段读」。不要改写、删减文件内容。在账本里给这张表记一行：
步骤「写作」、轮次、派发时间，然后 `note "S4 派 T1 $T 第1轮"`。

**写入被拦截**：子代理回报「文件在 `$SCRATCH/<表>/…`，cp 没做 / 被拒绝」时，由编排者代为拷贝，再做下面的自检：

```bash
cp "$SCRATCH/$T/$T.json" "$RUN/docs/$T.json"
```

审读文件（`reviews/`）、片段（`fragments/`）、作答和判分文件照同样的办法由编排者代拷。

**产出与自检**（子代理回报后，编排者对每张表做）

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("table", d["table"]); print("doc_packet", d["packet_digest"])' "$RUN/docs/$T.json"
python3 -c 'import json,sys; print("packet    ", json.load(open(sys.argv[1]))["packet_digest"])' "$RUN/packets/$T/packet.json"
sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "$T"; echo "exit=$?"
sl semantic status "$RUN" --pages "$SEMPAGES" --only "$T"
```

四项都要成立：`table` 等于 `$T`；`doc_packet` 等于 `packet`；validate `exit=0` 且汇总行是 `… 0 with failures …`；
`status` 显示 `valid`。

**常见失败与处理**

| 现象 | 处理 |
| --- | --- |
| 子代理没回报、报 429 / 额度用完、或中途停了 | 不算一轮。额度恢复后重跑本步的前提检查，`--next draft` 会再列出它，用同一模式重派 |
| `docs/` 里没有 `<表>.json`，或文件里 `table` 不是这张表 | 子代理写错位置。把文件改名放回 `docs/<文件里的 table>.json`，再看 `status`；查是哪个子代理写错的，记进问题清单 |
| `status` 显示 `doc_misfiled` | 同上 |
| validate 有 `FAIL` | 转 S5 |
| `doc_packet` 不等于 `packet` | 子代理读错了材料包，或抄错摘要。重派 T1（新写），计一轮 |

**绝对不要**：只把文档里的 `packet_digest` 改成新值来让 `[8 digest]` 通过。材料包变了的表必须由写作子代理按新材料包整份重写。
编排者自己也不改文档。

**完成判据**：本批每张表 `status` 都是 `valid`，或已转 S5。

**下一步**：本批全部 `valid` → S6；有 FAIL 的 → S5。

---

## S5 校验与 blocked

**目的**：对写作或修订后仍不通过校验的表，补一轮；两轮仍失败的表标为 **blocked**，不再派发。

**前提检查**：账本里这张表的「写作」或「修订」轮次（只数完成的，被中断的不算）。

**命令**

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "$T"; echo "exit=$?"
sl semantic validate "$RUN/docs" --packets "$RUN/packets" --json --only "$T" > "$SCRATCH/$T.validate.json"; echo "exit=$?"
python3 -c 'import json,sys; t=json.load(open(sys.argv[1]))["tables"][0]; [print(f["status"].upper(), f["number"], f["check"], f["at"], f["message"]) for f in t["failures"]]' "$SCRATCH/$T.validate.json"
```

有 FAIL 时退出码是 1（只有 WARN 是 0），报告照常打印。通过 = `exit=0` 且汇总行 `Validated … 0 with failures …`。

按轮次分流：

| 情况 | 处理 |
| --- | --- |
| 写作第 1 轮后有 FAIL | 用 T1（补失败模式）重派，把上面 python 打印的 FAIL 行原样贴进模板 |
| 写作第 2 轮后仍有 FAIL | 标 blocked（下面的命令） |
| 修订者回报「两轮后仍有 FAIL」，或 `semantic fixed` 报 `the document is invalid` | 标 blocked |
| 只有 WARN | 看 WARN 白名单。白名单里的可保留，记进账本；其余用 T1（补失败模式）交回，**WARN 不计轮次、不触发 blocked** |

第 8 项 `[8 digest]` 的 FAIL 表示材料包变了：不走补失败，回 S4 做「重写准备」后整份重写。

**WARN 白名单**（只有这三种可以保留；子代理回报里要写出保留理由）：

1. `[10 fan_out]` 的 WARN 落在「按本表 SQL 推翻材料包判定」的句子上，句子里已写明材料包的判定和 SQL 原文。
2. `[9 time]` 的 WARN（写 `snapshot`、写入按业务日期筛选）落在拉链表或维表上，且 `summary.refresh.how_to_read` 已写清怎么取数。
3. `[2 source_columns]` 的 WARN 是内联 `VALUES` 字典的关联键。

**标 blocked**（一张表做一遍）：

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
sl semantic validate "$RUN/docs" --packets "$RUN/packets" --only "$T" > "$RUN/blocked/$T.validate.txt" 2>&1
mv "$RUN/docs/$T.json" "$RUN/blocked/docs/$T.json"
[ -f "$RUN/reviews/$T.md" ] && mv "$RUN/reviews/$T.md" "$RUN/blocked/$T.review.md"
{ grep -v -x -F "$T" "$RUN/tables.txt" || true; } > "$SCRATCH/tables.txt.new" && mv "$SCRATCH/tables.txt.new" "$RUN/tables.txt"
echo "$T" >> "$RUN/blocked.txt"
cat "$RUN/blocked/$T.validate.txt"
```

blocked 的表：不再派写作或修订；不进渲染（S9）、不进目录（S10）、不进验收（S11）；交付报告（S13）里列出它的 FAIL 原文
（`blocked/<表>.validate.txt`），交 owner 决定。

**产出与自检**：`tables.txt` 里没有 blocked 的表；`blocked.txt` 里有；`docs/` 里没有它的文档。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `--only: no document for <表>` | 1 | `docs/` 里没有这张表的文档（被移走或从没写过）。看 `status` 再按附录 A 走 |
| validate 有 `FAIL` 却退出 0 | 0 | 工具早于 0.8.0。照样按汇总行判失败，在账本记一笔 |

**完成判据**：每张表要么 `valid`，要么在 `blocked.txt` 里。

**下一步**：S6。

---

## S6 审读（每张表一个子代理，最强模型）

**目的**：独立审读员对照材料包找出文档里的事实错误，写 `$RUN/reviews/<表>.md`（开头带 front matter）。

**前提检查**

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --next review --batch-size 5 --out "$RUN/next.json" --only "${TABLES[@]}"; echo "exit=$?"
cat "$RUN/next.json"
```

`batches` 里的表要审读。按 `status` 显示和文件选模式：

| 情况 | 派发前要做 | 模板 |
| --- | --- | --- |
| `valid`，`reviews/<表>.prior.md` 不存在（`ls "$RUN/reviews/$T.prior.md"` 报不存在） | 无 | T2（首审） |
| `valid`，`reviews/<表>.prior.md` 存在（重写后的首审） | 无 | T2（重写后首审：带 `.prior.md` 和 `.prior.json`） |
| `valid review_packet_stale` | 把旧审读移到 `reviews_prev/`（下面的命令） | T2（首审） |
| `valid review_stale` | 先查附录 A：是确认回写引起的就不审读，补跑 `semantic fixed`；否则同上 | T2（首审） |

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
mv "$RUN/reviews/$T.md" "$RUN/reviews_prev/$T.$(date +%Y%m%d%H%M).md"
```

**命令**：每张表用 T2 填空派一个子代理，**最强模型**，不能和写作是同一个子代理。每批不超过 5 个。账本记一行「审读」。

```bash
fill T2 "$SCRATCH/prompts/T2-$T.md" TABLE="$T" MODE=首审 FACTS=无; echo "exit=$?"     # 重写后首审写 MODE=重写后首审
```

**产出与自检**（子代理回报后）

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
head -8 "$RUN/reviews/$T.md"
sl semantic digest "$RUN/docs/$T.json"
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["packet_digest"])' "$RUN/packets/$T/packet.json"
sl semantic status "$RUN" --pages "$SEMPAGES" --only "$T"
```

- front matter 在第 1 行起，有 `reviewed_doc_digest`、`reviewed_packet_digest`、`high`、`medium`、`low` 五个键，没有 `fixed_doc_digest`。
- `reviewed_doc_digest` 等于 `semantic digest` 输出的**第一列**（16 位十六进制，不含后面的路径）。
- `reviewed_packet_digest` 等于 `packet.json` 的 `packet_digest`。
- `status`：高 + 中 > 0 时是 `reviewed`；= 0 时是 `fixed`。不能是 `review_unparsed`。
- 回报里有三类老错（「原地更新」写成事实、按任务名推断下游用途、分区日当业务日期）各「有 / 无」。

把首审的高、中、低条数记进账本「首审 H/M/L」一栏。**首审 H ≥ 1 的表，S8 要复审一次。**

**常见失败与处理**

| 现象 | 处理 |
| --- | --- |
| `status` 显示 `review_unparsed` | 审读文件没有完整 front matter。把它移到 `reviews_prev/<表>.unparsed.md`，重派 T2。不要手补 front matter |
| `reviewed_doc_digest` 抄成了整行（带路径），或与 digest 第一列不等 | 同上，重派 T2 |
| 审读员改了文档 | `status` 会变成 `valid review_stale`。把文档恢复不了就重派 T2，记进问题清单 |
| 子代理中断 / 429 | 不算一轮，重跑前提检查后重派 |

**完成判据**：本批每张表 `reviewed` 或 `fixed`，账本记了首审 H/M/L。

**下一步**：有 `reviewed` 的表 → S7；全部 `fixed` → S8。

---

## S7 修订（每张表一个子代理）

**目的**：按审读的高、中级发现改文档，最后由 `semantic fixed` 写修订回执，表变成 `fixed`。低级问题不派修订。

**前提检查**

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --next fix --batch-size 5 --out "$RUN/next.json" --only "${TABLES[@]}"; echo "exit=$?"
cat "$RUN/next.json"
```

| 情况 | 模板 |
| --- | --- |
| `reviewed`（审读有高 / 中，文档还没改） | T4（普通） |
| `reviewed fix_unconfirmed`，账本里这张表有一次被中断的修订 | T4（核对模式） |
| `reviewed fix_unconfirmed`，账本里这张表刚做过确认回写（S12） | 不派修订：`sl semantic fixed "$RUN" --only "$T"` |
| `reviewed fix_unconfirmed`，其他原因 | T4（核对模式），记进问题清单 |

**命令**：每张表用 T4 填空（`fill T4 "$SCRATCH/prompts/T4-$T-1.md" TABLE="$T" MODE=普通 FACTS=无`）派一个子代理，次一档强模型。
只修高、中级发现，低级的不改（模板里已写明）。修订者自己会在最后一步跑
`sl semantic fixed "$RUN" --only <表>`。账本记一行「修订」。

**产出与自检**

```bash
T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
sl semantic status "$RUN" --pages "$SEMPAGES" --only "$T"
grep -n 'fixed_doc_digest' "$RUN/reviews/$T.md"
```

`status` 显示 `fixed`；审读文件 front matter 里有 `fixed_doc_digest`。（S8 复审覆盖审读文件后，`fixed_doc_digest` 就没有了，
这是正常的：复审高 + 中 = 0 时 `status` 直接是 `fixed`。）

**常见失败与处理**（修订者回报的 `semantic fixed` 结果，或编排者重跑的结果；原因写在标准错误
`<表>: no fix record written: <原因>`）

| 原因原文 | 退出码 | 处理 |
| --- | --- | --- |
| `the document is invalid …` 或 `the document is packet_stale …` | 1 | 修订两轮后仍 FAIL：按 S5 标 blocked。`packet_stale`：材料包在修订期间重建过，回 S4 重写 |
| `the review names no reviewed_packet_digest …` 或 `the review read packet …: review the document again` | 1 | 审读要重做：按 S6 移走旧审读后重派 T2 |
| `the document is the version the review read: nothing was revised` | 1 | 修订者什么都没改（漏了 `generator.prompt` 加 `+review` 那一步）。重派 T4（核对模式） |
| `the review has no complete front matter` | 1 | 同 S6 的 `review_unparsed` |
| `the following arguments are required: --only` | 2 | 命令漏了 `--only <表>` |
| 修订者中断 / 429，`status` 是 `reviewed fix_unconfirmed` | 0 | 不算一轮。重派 T4（核对模式） |

**完成判据**：本批每张表 `fixed`，或已标 blocked、或已转回 S6。

**下一步**：S8。

---

## S8 状态推进与复审

**目的**：每轮收口：看所有表到了哪一步；对「首审有高级」的表复审一次；决定是否进入渲染。

**前提检查**：S4–S7 这一轮派出的子代理都已回报（或已记为中断）。

**命令**

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --json "$RUN/status.json" --only "${TABLES[@]}"; echo "exit=$?"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["summary"]["stages"]); [print(t["table"], t["stage"], " ".join(t["flags"])) for t in d["tables"]]' "$RUN/status.json"
```

把每张表的阶段和标记抄进账本，按附录 A 决定每张表的下一步。

**复审规则**（定死，不要自己加轮次）：

1. 只复审「账本里首审 H ≥ 1」且现在是 `fixed`、还没复审过的表。首审只有中、低级问题的表不复审。
2. 复审前先备份首轮审读：

   ```bash
   T=demo_dwd.dwd_party_customer_info_df   # 换成这张表
   cp "$RUN/reviews/$T.md" "$RUN/reviews_prev/$T.round1.md"
   ```

3. 用 T3 派复审（最强模型）：`fill T3 "$SCRATCH/prompts/T3-$T.md" TABLE="$T" FACTS=无`。复审员覆盖 `reviews/<表>.md`。回收检查同 S6。
4. 复审结果：高 + 中 = 0 → 表直接是 `fixed`，结束。高 + 中 > 0 → 表是 `reviewed` → 回 S7 用 T4 再修订一次 → `fixed` 后结束，
   **不再复审**；复审里仍成立的发现原文抄进账本「问题清单」。
5. 一张表最多：写作 2 轮、首审 1 次、修订 2 次、复审 1 次。

**停止条件**：`tables.txt` 里的每张表都是 `fixed`（或 `rendered`），需要复审的都复审过，其余表在 `blocked.txt` 里。

**常见失败与处理**

| 现象 | 处理 |
| --- | --- |
| 有表停在 `valid` / `reviewed` | 还没走完，按附录 A 回对应的步 |
| `doc_misfiled` | 见附录 A 最后一行 |
| 状态和账本对不上（例如账本说修订做完，`status` 是 `fix_unconfirmed`） | 以 `status` 为准，按附录 A 处理，并记进问题清单 |

**完成判据**：满足停止条件。

**下一步**：S9。

---

## S9 全量校验与渲染表语义页

**目的**：渲染前做一次全量校验写 `validation.json`，再把每张表渲染成页面 `$SEMPAGES/<表>.md`。

**前提检查**（闸门：两条都输出 `ALL_FIXED` / `FAILURES 0` 才能往下走）

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --json "$RUN/status.json" --only "${TABLES[@]}" > /dev/null; echo "exit=$?"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); bad=[t["table"]+" "+t["stage"] for t in d["tables"] if t["stage"] not in ("fixed","rendered")]; print("\n".join(bad) if bad else "ALL_FIXED")' "$RUN/status.json"
```

**命令**

```bash
sl semantic validate "$RUN/docs" --packets "$RUN/packets" --json > "$RUN/validation.json"; echo "exit=$?"
python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))["summary"]; print("FAILURES", s["tables_with_failures"], "SCHEMA_ERRORS", s["tables_with_schema_errors"], "DOCS", s["documents"])' "$RUN/validation.json"
rm -rf "$SEMPAGES"
sl semantic render "$RUN/docs" --out "$SEMPAGES" --validation "$RUN/validation.json" --packets "$RUN/packets" 2> "$SCRATCH/render.stderr"; echo "exit=$?"
cat "$SCRATCH/render.stderr"
sl semantic status "$RUN" --pages "$SEMPAGES" --only "${TABLES[@]}"
```

全量校验**不带 `--only`**（`docs/` 里只有本轮范围内的文档，blocked 的已移走）。带 `--only` 的输出不要写进 `validation.json`。
有 FAIL 时 validate 退出 1，但 `validation.json` 照常写出：先读它的 `FAILURES` 再判断。

**产出与自检**

- `FAILURES 0 SCHEMA_ERRORS 0`，`DOCS` 等于 `tables.txt` 行数。
- 摘要行 `Rendered N table page(s) and index.md (skipped=0) -> …`，`N` 等于 `tables.txt` 行数。
- `status` 全部 `rendered`。
- 读页面时的标记：✓ 已确认；⚠ 矛盾或风险；✗n 校验未通过（文末「校验」一节）；`值（含义待确认）` 只有值没有含义的码值。

**常见失败与处理**

| 现象 | 退出码 | 处理 |
| --- | --- | --- |
| 闸门打印了不是 `fixed` 的表 | — | 回 S8，不要渲染 |
| `FAILURES` 不为 0 | 1 | 某张表的文档在 S8 之后被改过。看 `validation.json` 里是哪张表，按附录 A 处理 |
| `DOCS` 多于 `tables.txt` 行数 | — | `docs/` 里有不在范围内的文档。用 `ls "$RUN/docs"` 对照，多出的移到 `$RUN/prev/docs/` |
| `render.stderr` 里有 `warning: packet_stale …`、`warning: invalid …` 或 `warning: no_packet …`（点名表） | 0 | 闸门漏了，这几张表的页面是旧的或错的。停下，回 S8 |
| `Rendered … (skipped=K)`，K 不为 0 | 1 | 有文档不合 schema，没有渲染。回 S5 |

**完成判据**：`FAILURES 0`；render `exit=0`；`status` 全部 `rendered`。

**下一步**：要做本体目录 → S10；不做 → S11（没有题集就 S13）。

---

## S10 本体目录

把表语义汇成本体目录（`catalog-yaml/1`），再渲染概念页并与表语义页互链。分七小步，顺序不能变。

### S10a 起点目录

**目的**：准备 `$RUN/catalog/`，确认它里面到底有什么。

**前提检查**：S9 完成。owner 说明了起点：「从某个旧目录开始」就用 A；**没说明就用 B（空目录）**，并在账本记一笔。

**命令**（二选一）

```bash
# A：从旧目录开始
cp -R /abs/path/to/old-catalog/. "$RUN/catalog/"
# B：从空目录开始（全 JSON 目录，不需要 PyYAML）
printf '{"doc_format": "catalog-yaml/1", "name": "run-20260101", "description": "drafted from table semantics"}\n' > "$RUN/catalog/catalog.json"
# 两种都跑
sl catalog validate "$RUN/catalog"; echo "exit=$?"
```

**产出与自检**：`Catalog <name> (catalog-yaml/1): 0 error(s), W warning(s)`；下一行的计数
`domains=… identifiers=… code_sets=… concepts=… attributes=… relations=… … representations=… bindings=…` 原样抄进账本。
别人说「旧目录里有绑定」而 `representations=0 bindings=0` 时，以计数为准，记进问题清单。

**常见失败与处理**：退出码 1（有 error）→ 旧目录本身不合格，交 owner；退出码 2 → 目录里没有 `catalog.yaml` / `catalog.json`，或是 YAML 而缺 PyYAML（见 S0）。

**完成判据**：`exit=0`，`0 error(s)`。

**下一步**：S10b。

### S10b 起草材料 digest

**目的**：把表语义浓缩成 `digest.md`（起草概念的全部输入），并标出目录还没覆盖的表和列。

**前提检查**：S9 的闸门成立（表全部 `fixed` / `rendered`）。

**命令**

```bash
load_tables
rm -rf "$RUN/digest"
sl catalog digest "$RUN/docs" --lineage "$RUN/artifacts" --schema "$SCHEMA" --catalog "$RUN/catalog" \
  --packets "$RUN/packets" --out "$RUN/digest" --only "${TABLES[@]}" 2> "$SCRATCH/digest.stderr"; echo "exit=$?"
cat "$SCRATCH/digest.stderr"
```

**产出与自检**

- `Digested N table(s) (skipped=0) -> …`，`N` 等于 `tables.txt` 行数。
- `catalog <name>: X table(s) without a representation, Y column(s) without a binding`。注意：`Y` 只数**已有表现**的表里没绑定的列，
  没有表现的表的列不计入，所以 `Y=0` 不代表列都绑好了。
- `$RUN/digest/digest.md`、`digest.json`。

**常见失败与处理**

| 现象 | 退出码 | 处理 |
| --- | --- | --- |
| `digest.stderr` 里有 `warning: packet_stale …` / `warning: invalid …` / `warning: no_packet …` | 0 | 点名的文档不该进目录。停下，回 S8 / S9 |
| `skipped` 不为 0 | 1 | 有文档不合 schema。回 S5 |
| `--only` 点名的表没有文档 | 1 | 表被 blocked 了却还在 `tables.txt`。按 S5 的 blocked 命令补做 |

**完成判据**：`exit=0`，`skipped=0`。

**下一步**：S10c。

### S10c 起草概念与分组方案（一个子代理）

**目的**：在 `$RUN/catalog/` 里补齐概念、标识符、拼写、关系、跨组属性和共用码值集，并写分组方案 `$RUN/catalog_plan.md`。
片段不能新增概念、不能改已有标识符，所以这些都要在这一步写好。

**前提检查**：S10b 完成。

**命令**：用 T5 填空派**一个**子代理（次一档强模型），只给 `digest.md`、当前目录和模板。小样时分组方案只写 1 组，组名用 `main`：

```bash
fill T5 "$SCRATCH/prompts/T5.md" SIZE="小样：只分 1 组，组名 main" REWORK=无; echo "exit=$?"
```

**产出与自检**

```bash
sl catalog validate "$RUN/catalog"; echo "exit=$?"
load_tables
for t in "${TABLES[@]}"; do printf '%s\t%s\n' "$(grep -c -F "| $t |" "$RUN/catalog_plan.md")" "$t"; done
```

- 目录 `exit=0`，`0 error(s)`。
- 每张表那一行的计数是 `1`（只进一组）；码值字典表是 `0`，并且列在分组方案的「码值来源表」一节。

**常见失败与处理**：validate 有 error → 返工，最多 2 次，仍不过交 owner。返工可以续用原来的子代理，也可以派一个新的：
用 `fill T5 … REWORK=@<报错文件>` 重新填一份（原提示词 + 这次的报错原文），新子代理照它改。某张表计数是 0 或 2 → 同样返工。
每次改完都重跑 `catalog validate`，**以最新一次输出为准**：文件改过之后同一个问题的报错文字可能变，不要拿旧报错去对。
`schema` 类 error 最常见的是概念类型写错了键（T5 里的必填 / 禁写表），例如事件没有 `participants`。

**完成判据**：目录 `0 error(s)`；分组方案覆盖每张表恰好一次。

**下一步**：S10d。

### S10d 片段（每组一个子代理）

**目的**：每组写一个 `catalog-fragment/1` 片段 `$RUN/fragments/<组名>.json`：属性、码值集、表现和每一列的绑定。

**前提检查**：S10c 完成；组名取自 `catalog_plan.md`。

**命令**：每组用 T6 填空（`fill T6 "$SCRATCH/prompts/T6-$G.md" GROUP="$G" MODE=首写 REWORK=无`）派一个子代理（次一档强模型），
每批不超过 5 个。回报后编排者重跑一次自检：

```bash
G=main   # 换成组名
rm -rf "$SCRATCH/check-$G"
sl catalog merge "$RUN/catalog" "$RUN/fragments/$G.json" --out "$SCRATCH/check-$G" > "$SCRATCH/check-$G.txt" 2>&1; echo "exit=$?"
grep -c -E '^Merged .* 0 conflict\(s\), 0 unknown concept\(s\)' "$SCRATCH/check-$G.txt"
grep -c -E '^Catalog .*: 0 error\(s\)' "$SCRATCH/check-$G.txt"
grep -E '^Coverage:|^  [a-z0-9_]+\.' "$SCRATCH/check-$G.txt"
```

**产出与自检**：`exit=0`；两个 `grep -c` 都打印 `1`；`Coverage: K table(s) in the fragments, K with a representation, U unmapped column(s)`
里两个 `K` 相等（每张分给本组的表都有表现），下面每张表一行。`U` 不为 0 时，那几列和原因抄进账本「给 owner 的待确认」，
不算失败。只 grep `unmapped` 这个词没有用：`0 unmapped column(s)` 也会被匹配。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `--out … is not empty; choose a new or empty directory` | 2 | 先 `rm -rf` 自检目录再跑 |
| `conflict` / `unknown_concept` / `error` 行 | 1 | T6 返工模式（`fill T6 … MODE=返工 REWORK=@<报错文件>`），续用原子代理或新派一个都行，最多 2 次；以最新一次自检输出为准 |
| 某张表没有表现 | 0 | 同上交回（码值字典表除外） |

**完成判据**：每组自检 `exit=0`。

**下一步**：S10e。

### S10e 合并

**目的**：把所有片段合进目录的一份拷贝 `$RUN/merged/`。

**命令**

```bash
rm -rf "$RUN/merged"
sl catalog merge "$RUN/catalog" "$RUN"/fragments/*.json --out "$RUN/merged" > "$RUN/merge_report.txt" 2>&1; echo "exit=$?"
grep -c -E '^Merged .* 0 conflict\(s\), 0 unknown concept\(s\)' "$RUN/merge_report.txt"
grep -c -E '^Catalog .*: 0 error\(s\)' "$RUN/merge_report.txt"
grep -E '^note|^Coverage:|^  [a-z0-9_]+\.' "$RUN/merge_report.txt"
```

**产出与自检**：`exit=0`；两个 `grep -c` 都打印 `1`；`Coverage:` 里两个表数相等（每张表都有表现，码值字典表本来就不在片段里）。

计数口径（不必对账，想核对时这样算）：`Merged … added attribute=A, …; U unchanged` 只数**片段新加**的条目；下面
`Catalog …` 的计数行（`attributes=N` 等）数的是**合并后整个目录**，包括 S10c 已经写进 `catalog/` 的条目（例如事件的时间属性）。
所以 `N = S10c 那次 catalog validate 的 attributes + A`，两者不相等是正常的。
`note` 行（片段的 `notes`，都以「待 owner 确认：」开头）和 `unmapped` 列抄进账本「给 owner 的待确认」。这些都**不是** owner 已确认的内容。

**常见失败与处理**：退出码 1 → 冲突或校验错误，结果已写出便于查看。不要手工挑一个：按冲突行里的组名，用 T6（返工模式）交回对应的组，
改完从 S10d 的自检重来。退出码 2 → `--out` 非空，先 `rm -rf "$RUN/merged"`。

**完成判据**：`exit=0`。

**下一步**：S10f。

### S10f 合并后的手工修正（编排者）

**目的**：处理片段 `notes` 里写明「合并后改成 `foreign_attribute`」的列，以及 owner 已确认的条目。

**规则**

- 只改 `$RUN/merged/` 里的文件，不改 `$RUN/catalog/`。每一处改动在 `$RUN/catalog_changes.md` 记一行（文件、对象、改前、改后、依据）。
  这份记录**不要**放进 `merged/`（目录里不认识的文件会报 `unknown_file`）。
- 改成 `foreign_attribute`：把绑定的 `to` 改成 `foreign_attribute`，`ref` 改成别组概念的属性 id，加 `via: <本表里绑成 foreign_identifier 的那一列>`。
  **先查目标在不在**：`grep -rn 'attr:<概念 slug>.<属性 slug>' "$RUN/merged/concepts"` 要能找到它的定义，并确认 `via` 那一列已绑成指向该概念标识符的
  `foreign_identifier`。目标概念或属性不存在、或没有这样的 `via` 列时**不改**（改了会引用不存在的对象），在账本「给 owner 的待确认」记
  「待 owner 确认：<表>.<列> 是否是 <对象> 的属性（目录里还没有这个概念 / 属性）」。
- owner 确认的条目：`status` 改成 `confirmed`，`source` 改成 `owner`。只认 owner 在对话里或确认文件里给出的回答；
  片段 `notes` 里写的「待 owner 确认」不是确认。
- 下一轮（扩表、再起草）的起点目录是这一份 `merged/`：S10a 用 A，旧目录写 `$RUN/merged`，新一轮在新的运行目录里做。

**命令**（改完）

```bash
sl catalog validate "$RUN/merged"; echo "exit=$?"
```

**完成判据**：`exit=0`，`0 error(s)`；没有要改的就直接通过。

**下一步**：S10g。

### S10g 构建与渲染（顺序不能变）

**目的**：构建 `ontology.json`，渲染互链的表语义页和概念页。

**命令**

```bash
rm -rf "$RUN/onto" "$PAGES"
sl catalog build "$RUN/merged" --out "$RUN/onto" --lineage "$RUN/artifacts" --tables "$RUN/corpus/tables.json"; echo "exit=$?"
sl semantic render "$RUN/docs" --out "$SEMPAGES" --validation "$RUN/validation.json" --ontology "$RUN/onto/ontology.json" --packets "$RUN/packets"; echo "exit=$?"
sl catalog render "$RUN/onto/ontology.json" --out "$PAGES" --semantics "$SEMPAGES"; echo "exit=$?"
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --only "${TABLES[@]}"
```

顺序：`build` → `semantic render --ontology` → `catalog render --semantics`。`build` 固定带 `--lineage` 和 `--tables`（页面上的证据靠它们）。

**产出与自检**：`Built ontology-json/3 from catalog …`（下一行 `evidence:` 的「N of M relation(s) backed by a JOIN」只是证据统计，小样里是 0 也不用处理）；`Rendered N table page(s) and index.md (skipped=0)`；
`Rendered N page(s) (C concept page(s)) -> …`；`$PAGES/concepts/`、`$PAGES/index.md`、`$SEMPAGES/<表>.md` 都在；`status` 全部 `rendered`。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `--semantics directory does not exist: …` | 2 | 顺序错了：先跑 `semantic render` 再跑 `catalog render` |
| `build` 有 error、什么也没写 | 1 | 回 S10f 修 `merged/`，或交 owner |
| render 打印 `warning: packet_stale …` / `invalid …` / `no_packet …` | 0 | 回 S8 |

**完成判据**：三条命令都 `exit=0`；`status` 全部 `rendered`。

**已知限制**（遇到时照做，不要去修工具）：

| 情况 | 怎么做 |
| --- | --- |
| 码值来自 SQL 内联字典（`VALUES` 列表、`CASE` 映射、`INLINE(ARRAY(STRUCT))`）；digest 不列出它们，关联条件也不会去筛这类常量表的行 | 片段里对照表语义（必要时读 SQL）写码值集的 `values`，`evidence` 写任务名，不写 `lookup` |
| 不带字符串常量的关联、拉链表的有效期列 | digest 不列出。按表语义和 `catalog-fragment-prompt.md` 的码值规则写 |
| 列注释与血缘矛盾（注释说是 A，SQL 取的是 B） | 以血缘为准，写进 `notes` 和待确认问题 |

**下一步**：S11（没有题集就 S13）。

---

## S11 回归验收

**目的**：用 owner 给的题集考页面：作答者只读页面答题，判分者对照参考答案和材料判 2 / 1 / 0，工具汇总。

**前提检查**

- `Q` 非空，`sl questions validate "$Q"` 退出 0、`0 error(s)`。题集只能来自 owner：**不要自己出题自己考**。
- 选这一轮的子集，写成数组，**sheet、grading-sheet、score 三条命令都用同一个 `SUB`**（漏一条就会混进没答的题）：

  ```bash
  SUB=(--ids Q01 Q02 Q03)                 # 或按表：SUB=(--only-table demo_dwd.dwd_party_customer_info_df)
  ```

- 题目问到的表都要有页面：

  ```bash
  ROUND="$RUN/round1"; mkdir -p "$ROUND"
  sl questions sheet "$Q" --pages "$PAGES" --out "$ROUND/sheet.md" "${SUB[@]}" 2> "$ROUND/sheet.stderr"; echo "exit=$?"
  cat "$ROUND/sheet.stderr"
  for t in $(grep -o '^- 表：`[^`]*`' "$ROUND/sheet.md" | sed 's/^- 表：`//; s/`$//' | sort -u); do
    if [ -f "$SEMPAGES/$t.md" ]; then echo "OK $t"; else echo "NO_PAGE $t"; fi
  done
  ls "$PAGES/concepts" | head -3
  ```

  `sheet.stderr` 里的 `warning: no page under … for the table of <题号> (<表>)` 与 `NO_PAGE` 是同一件事。
  反过来，有页面但这一轮**没有一道题问到**的表，在账本「给 owner 的待确认」和 `RESULT.md` 里记为「验收未覆盖」；
  不要自己出题补上。
  有 `NO_PAGE` 的：把问这张表的题从 `SUB` 里去掉（blocked 的表就属于这种），记进账本，重跑上面的 `sheet`。
  题单里有「概念」题时，`$PAGES/concepts/` 不能是空的。

**命令**

```bash
# 1. 作答：用 T7 派一个子代理（便宜模型），只给 $ROUND/sheet.md 和 $PAGES，写 $ROUND/answers.md
fill T7 "$SCRATCH/prompts/T7-round1.md" ROUND="$ROUND"; echo "exit=$?"
# 2. 判分材料
sl questions grading-sheet "$Q" --answers "$ROUND/answers.md" --out "$ROUND/grading.md" "${SUB[@]}" 2> "$ROUND/grading.stderr"; echo "exit=$?"
cat "$ROUND/grading.stderr"
# 3. 判分：用 T8 派一个子代理（最强模型），写 $ROUND/grades.yaml
fill T8 "$SCRATCH/prompts/T8-round1.md" ROUND="$ROUND" ROUND_LABEL=r1; echo "exit=$?"
sl questions validate "$ROUND/grades.yaml"; echo "exit=$?"
# 4. 汇总（有上一轮的 grades 时加 --previous <旧 grades.yaml>）
sl questions score "$ROUND/grades.yaml" --set "$Q" --out "$ROUND/score" "${SUB[@]}" 2> "$ROUND/score.stderr"; echo "exit=$?"
cat "$ROUND/score.stderr"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["total"]); print("ungraded", d["ungraded"]); [print(r["round"], r["total"]) for r in d["rounds"]]' "$ROUND/score/score.json"
# 5. 达标判断（带了 --previous 时；rounds 最后一项是本轮，前一项是基线）
python3 -c 'import json,sys; r=json.load(open(sys.argv[1]))["rounds"]; cur=r[-1]["total"]["points"]; base=r[-2]["total"]["points"] if len(r) > 1 else None; print("NO_BASELINE" if base is None else ("PASS" if cur >= base - 1 else "FAIL"), cur, base)' "$ROUND/score/score.json"
```

**产出与自检**

- `grading.stderr` 里没有 `no answer for`；`score.stderr` 里没有 `not graded`；`ungraded` 是 `[]`。
- `score.md` 的「按缺口」说失分在哪：`page_missing` / `page_wrong` / `page_contradiction` 是页面的问题，`answerer` 是作答，
  `key_wrong` 是参考答案（列在「参考答案待修正」），`owner_only` 交 owner。逐题抄进账本问题清单。
- 达标线：有基线（上一轮同一套题的 `grades.yaml`，用 `--previous` 带上；工具按同一个 `SUB` 对齐）时，本轮得分**不低于基线减 1 分**，
  上面第 5 步打印 `PASS`；没有基线（`NO_BASELINE`）时只报分数，由 owner 判断。不论是否达标，每道失分题都逐题记进账本。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `no question in the set has table/concept …` | 1 | `--only-table` 的表名在题集里没有（题目可能只写了 `concept:`）。改用 `--ids` |
| `PyYAML` 相关报错 | 2 | 见 S0 |
| `warning: no answer for: Q…` | 0 | 作答漏题或三条命令的 `SUB` 不一致。让作答者补齐，或核对 `SUB` |
| `warning: not graded (left out of the total): Q…` | 0 | 判分漏题或 `SUB` 不一致。交回判分者补齐 |
| `warning: no page under … for the table of …` | 0 | 同前提检查里的 `NO_PAGE` |
| `warning: --pages does not exist: …` | 0 | `PAGES` 写错，或还没渲染（S9 / S10g） |
| `questions validate grades.yaml` 报错 | 1 | 把错误行交回判分者改，不要自己改分 |
| 作答者回报某页被权限系统拒绝读取 | — | 记进问题清单；不换别的来源，照常判分 |
| 判分文件有题集没有的题号，`score` 拒绝汇总 | 1 | 交回判分者删掉多出的题 |

**完成判据**：`ungraded` 为空；有基线时达标（或已把未达标的失分逐题记进账本）。

**下一步**：owner 有回答要回写 → S12；否则 S13。

---

## S12 确认回写（可选）

**目的**：把 owner 对页面「待确认问题」的回答写回文档，下一次渲染带 ✓。

**前提检查**：owner 的回答已拿到。列出每张表的问题 id：

```bash
python3 -c 'import json,sys
for p in sys.argv[1:]:
    d = json.load(open(p))
    for q in d["summary"].get("questions", []):
        print(d["table"], q["id"], q.get("status"), q["text"])' "$RUN"/docs/*.json
```

**命令**：用 Write 工具写 `$RUN/confirmations/<日期>.json`（`semantic-confirmations/1`），每条一个回答：

```json
{
  "doc_format": "semantic-confirmations/1",
  "confirmations": [
    {"table": "demo_dwd.dwd_party_customer_info_df", "target": "question:q1",
     "value": "不会。注册系统只允许 F、M、U 三个值。", "by": "demo-reviewer", "date": "2026-01-01"}
  ]
}
```

`target` 只有四种写法：`question:<id>`（id 是上面列出的，例如 `q1`，不能只写 `question:`）、`column:<列>.meaning`、
`column:<列>.code_values`、`summary.row`。然后：

```bash
sl semantic confirm "$RUN/docs" --confirmations "$RUN/confirmations/20260101.json" --reviews "$RUN/reviews"; echo "exit=$?"
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --only "${TABLES[@]}"
```

**产出与自检**：`Applied N confirmation(s) to M table(s) (unmatched=0)`，之后每张被改的表一行 `<表>  fixed_doc_digest …`（回执移到了确认后的文档上）；
被确认的表显示 `fixed render_stale`。不要加 `--out`（`--out` 与 `--reviews` 同给退出 2，且就地确认才会移回执）。
在账本给这些表记一笔「确认回写」。

**常见失败与处理**

| 现象 | 退出码 | 处理 |
| --- | --- | --- |
| `unmatched` 不为 0 | 0 | 逐条把原因告诉 owner（表名、问题 id 或列名写错），改确认文件后重跑；不要默默丢掉 |
| 确认文件格式不对，或同时给了 `--out` 和 `--reviews` | 2 | 对照上面的 JSON 改；去掉 `--out` |
| 被确认的表显示 `reviewed fix_unconfirmed` 或 `valid review_stale` | 0 | 工具早于 0.8.0。跑 `sl semantic fixed "$RUN" --only <这些表>`，应变成 `fixed render_stale`；不要派修订或审读 |

**完成判据**：`unmatched=0`；被确认的表都是 `fixed render_stale`。

**下一步**：回 S9（全量校验与渲染），有目录时再做 S10g；目录里 owner 确认的条目按 S10f 改。

---

## S13 交付

**目的**：把结果和问题清单交给 owner。

**前提检查**：S9（和 S10、S11，如果做了）完成。

**命令**

```bash
load_tables
sl semantic status "$RUN" --pages "$SEMPAGES" --json "$RUN/status.json" --only "${TABLES[@]}" > /dev/null; echo "exit=$?"
python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))["summary"]; print(s["tables"], s["stages"])' "$RUN/status.json"
cat "$RUN/blocked.txt" 2>/dev/null
ls "$RUN"
```

然后按 `runbook-templates.md` 的「交付报告模板」写 `$RUN/RESULT.md`。

**产出与自检**：`RESULT.md` 写了数字、blocked 的表（带 FAIL 原文）、待确认汇总、问题清单。附录 B 列的文件都在。

**规则**

- 用大白话写，owner 不看别的文件也能看懂；给数字。
- **工具和流程问题清单**比结果本身更重要：每条写现象、哪张表、当时怎么处理的。
- 不改工具仓库的代码、文档、提示词；发现的问题只记录。
- 真实的表名、列名、码值只写在运行目录里，不写进工具仓库的提交、PR 或 issue。

**完成判据**：`RESULT.md` 写完，告诉 owner 它的路径。

**下一步**：结束。

---

## 附录 A 决策表：`status` 显示什么 → 下一步

先看账本，再看这张表。「账本」指 `$RUN/ledger.md` 里这张表的记录。

| `status` 显示 | 账本 / 文件情况 | 下一步 | 谁做 |
| --- | --- | --- | --- |
| `no_packet` | — | S3：核对 `tables.txt` 拼写（不带 catalog 前缀）后建材料包 | 编排者 |
| `packet` | 没写过，或写作被中断 | S4 新写 | T1 |
| `drafted packet_stale` | — | S4 重写准备 → T1 新写；之后首审带旧审读 | T1 → T2 |
| `drafted invalid` | 写作第 1 轮 | S5 补失败 | T1（补失败） |
| `drafted invalid` | 写作第 2 轮，或修订两轮后 | S5 标 blocked | 编排者 |
| `valid` | 没有 `.prior.md` | S6 首审 | T2 |
| `valid` | 有 `reviews/<表>.prior.md` | S6 重写后首审 | T2（带旧审读） |
| `valid review_packet_stale` | — | 旧审读移到 `reviews_prev/` → S6 首审 | T2 |
| `valid review_stale` | 刚做过确认回写 | `sl semantic fixed "$RUN" --only <表>` | 编排者 |
| `valid review_stale` | 其他 | 旧审读移到 `reviews_prev/` → S6 首审，记进问题清单 | T2 |
| `reviewed` | — | S7 修订 | T4 |
| `reviewed fix_unconfirmed` | 刚做过确认回写 | `sl semantic fixed "$RUN" --only <表>` | 编排者 |
| `reviewed fix_unconfirmed` | 修订被中断，或其他 | S7 核对模式 | T4（核对） |
| `reviewed review_unparsed` | — | 审读移到 `reviews_prev/<表>.unparsed.md` → S6 首审 | T2 |
| `fixed` | 首审 H ≥ 1，还没复审 | S8 复审（先备份首轮审读） | T3 |
| `fixed` | 其他 | 等其余表；全部 `fixed` 后 S9 | 编排者 |
| `fixed render_stale` | — | S9（有目录再 S10g） | 编排者 |
| `rendered` | — | 完成 | — |
| 任何阶段 + `doc_misfiled` | — | 停：用 S4 的 python 命令看每个 `docs/*.json` 的 `table`，把文件改名为 `docs/<table>.json`，同一张表只留一个文件；查是哪个子代理写错的 | 编排者 |
| （不出现在 `status`） | 在 `blocked.txt` | 不派任何子代理；S13 报告里列出 | — |

几条硬规则：

- 复审只在首审有高级时做一次；复审前备份到 `reviews_prev/<表>.round1.md`。
- 低级问题不修：高 + 中 = 0 的表就是 `fixed`，不派修订。
- 被中断的调用不计轮次；完成的写作 2 轮、修订 2 次仍有 FAIL 就 blocked。
- 「材料包变了」一律整份重写（重写准备三步），不允许只改 `packet_digest`。

## 附录 B 目录与文件约定

```text
$RUN/
  env.sh                     变量块（S0 写，之后只读）
  TOOL_VERSION               工具版本与提交号（S0）
  ledger.md                  编排者账本（每次派发、回收都更新）
  candidates.tsv             有生产任务的表（S3）
  tables.txt                 本轮范围内的表，一行一个 库.表（S3 写；blocked 时删行）
  blocked.txt                blocked 的表（S5）
  artifacts/<任务名>/         血缘 lineage.json（S1）
  corpus/                    tables.json、glossary.json（S2）
  packets/<表>/              packet.md、packet.json（S3；只由 semantic packet 写）
  docs/<表>.json             表语义（写作写、修订改、confirm 改；编排者不手改）
  reviews/<表>.md            当前审读（审读员写；fixed_doc_digest 只由 semantic fixed 写）
  reviews/<表>.prior.md      重写前的旧审读（S4 重写准备；只给重写后的首审）
  reviews/<表>.prior.json    重写前的旧文档（S4 重写准备；只给审读员，不给写作者）
  reviews_prev/<表>.round1.md   复审前备份的首轮审读（S8）
  reviews_prev/<表>.<时间>.md   其他被替换下来的审读（S6）
  prev/docs/<表>.json        重写前的旧文档（写作者看不到的位置）
  blocked/docs/<表>.json     blocked 的文档；blocked/<表>.validate.txt 是它的 FAIL 原文
  next.json  status.json     最近一次 --next / --json 的输出
  validation.json            全量校验报告（S9；只能由不带 --only 的 validate 写）
  digest/                    digest.md、digest.json（S10b）
  catalog/                   起点目录 + T5 的修改（S10a、S10c）
  catalog_plan.md            分组方案（S10c）
  fragments/<组名>.json       片段（S10d）
  merge_report.txt           合并输出（S10e）
  merged/                    合并后的目录；手工修正只改这里（S10f）
  catalog_changes.md         手工修正记录（不放进 merged/）
  onto/ontology.json         构建结果（S10g）
  site/                      概念页、index.md（catalog render）
  site/semantics/            表语义页（semantic render）
  round1/                    sheet.md、answers.md、grading.md、grades.yaml、score/（S11）
  confirmations/<日期>.json   owner 的回答（S12）
  RESULT.md                  交付报告（S13）
$SCRATCH/<表>/               该表子代理的私有临时目录（目录名含表名）
$SCRATCH/<组名>/、check-<组名>/  片段子代理的临时目录与自检目录
```

文件规则：

- 子代理的临时文件只放 `$SCRATCH/<表>/`（或 `$SCRATCH/<组名>/`），文件名带表名，不用 `doc.json`、`orig.json` 这类通用名。
  几个子代理共用一个 scratchpad，通用名会互相覆盖。
- 文件放回 `docs/<表>.json` 之前，先确认文件里的 `table` 就是 `<表>`。
- Write 工具写 `$RUN` 被钩子拦截时：先写 `$SCRATCH/<表>/` 下同名文件，再 `cp` 过去。
- `.prior.md`、`.prior.json`、`reviews_prev/`、`prev/` 里的文件 `status` 都不读；不要删，交付时留着。

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
| `fill` | `未填的占位：{…}` | 1 | 补上那几个 `KEY=值` 再跑 |
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

## 附录 D 成本与并发

- **并发**：同时在跑的子代理 ≤ 5。`--batch-size 5` 就是这个数。
- **模型档位**：

  | 步骤 | 档位 |
  | --- | --- |
  | 写作 T1、修订 T4、目录起草 T5、片段 T6 | 次一档强模型 |
  | 审读 T2、复审 T3、判分 T8 | 最强模型 |
  | 作答 T7 | 便宜模型即可 |

  审读和写作不能是同一个子代理、同一次调用。
- **低级问题不修**：高 + 中 = 0 的表不派修订；复审只在首审有高级时做一次。
- **子代理不通读格式文档**：写作者只读提示词和材料包；格式只在提示词说不清时查 schema。模板里已写明。
- **先小样**：≤5 张表、1 组、约 15 题（0.3）。
- **额度**：估算时按每次子代理调用约 10 万 token 计。撞到 429 后不要立刻重派一大批：等额度恢复，重跑当前步骤的 `status --next`，
  已经完成的表会自动跳过；被中断的修订显示 `fix_unconfirmed`，用 T4 核对模式重派。
- **一个子代理只做一张表的一步**（片段是一组），不再往下派子代理。
