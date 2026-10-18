---
name: scope-lineage-ontology
description: >-
  Run the scope-lineage procedure that turns a batch of Spark/Hive task JSON plus table
  schema into table semantics, task semantics and a business ontology catalog: an
  orchestrator loop over references/runbook.md S0–S13 with independent write / review / fix
  sub-agents, a progress script that says which step is current, and an omission check on
  the built catalog. Use this skill whenever someone hands over a task directory and a
  schema directory and asks for 任务语义 / 表语义 / 业务本体 / 本体目录 / 概念 / 实体关系 /
  "这批表是什么意思" / "生成本体", or asks to run, resume or check such a run — even if they do
  not name the tool. For lineage questions about single columns or tables (字段来源、影响分析、
  mapping 文档) use the scope-lineage skill instead.
---

# 从任务和表 Schema 生成表语义与业务本体

这个 Skill 只做一件事：带你把一批任务 JSON 和表 Schema 按固定流程做成**表语义页**和**业务本体目录**。
流程的细节全在操作手册里；这里告诉你怎么进入、怎么一步一步走、哪些规则不能省。

## 0. 先认清两条路

| 你要的 | 走哪条路 |
| --- | --- |
| 业务语义、业务本体：一张表是什么意思、有哪些业务概念、概念之间什么关系 | **本 Skill 的流程**（S0–S13） |
| 一份语料的快速结构扫描：哪些表共用哪些键 | 只跑 `scope-lineage ontology`，得到的是**键折叠候选** |

**只跑 `parse` → `tables` / `glossary` → `describe` → `ontology` 就交差，是这里最常见的错误。**
那样得到的概念名取自键列词根（`cust`、`acct` 这类英文缩写，甚至元数据残值 `nan`），大多数表只是临时概念，不是业务本体。

## 1. 找到工具目录 `TOOL`

`TOOL` 是这个 Skill 所在的 scope-lineage 仓库根目录（里面有 `skills/`、`docs/`、`pyproject.toml`）。
本文件是 `<TOOL>/skills/scope-lineage-ontology/SKILL.md`；装成软链接时，先取真实路径：

```bash
python3 -c 'import os,sys; print(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))))' <本 SKILL.md 的路径>
```

下文的路径都以 `$TOOL` 开头。要读的只有三份：

| 文件 | 什么时候读 |
| --- | --- |
| `$TOOL/skills/scope-lineage/references/runbook.md` | 开始前读第 0 节；之后每一步只读那一步的小节 |
| `$TOOL/skills/scope-lineage/references/runbook-templates.md` | 不用读：派子代理时用 `fill` 从它生成提示词 |
| `$TOOL/docs/zh-CN/task-to-ontology.md` | 想看全流程一览表时 |

## 2. 开始前问清楚四件事

缺哪一件都先问人，不要猜：

1. 任务 JSON 目录、表 Schema 目录（还有目标表 DDL 目录的话也要）。
2. 运行目录放哪里（新建，不复用旧的）。
3. 范围：**默认先做小样**，最多 5 张表、1 组。人点名的表优先。
4. 人已经拍板的决定（例如「某列就是某编号」「某对象要建成独立概念」）。有就写进 `$RUN/owner_decisions.md`，
   S10 起草时原样交给起草者。

## 3. 主循环

照手册第 0 节写好 `$RUN/env.sh`、做完 S0 之后，**每一轮都是这四步，直到进度脚本说「完成」**：

1. **看当前步**：

   ```bash
   . "$RUN/env.sh" && python3 "$TOOL/skills/scope-lineage/scripts/next_step.py" "$RUN"
   ```

   它只读文件，打印 S0–S13 的进度清单、当前步和原因；表语义阶段还按手册附录 A 列出每张表的下一步和模板。
   它说「刷新状态」时，照它打印的命令刷新 `status.json`，再跑一次。
2. **读手册那一步的小节**：只读当前步，照「前提检查 → 命令 → 产出与自检 → 完成判据」做。前提不满足就停在这一步。
3. **贴出完成判据的输出**：把这一步完成判据要求的命令输出原样贴出来。判据不成立，不要往下走；照「常见失败与处理」做。
4. **记账**：`note "<步骤> <做了什么> <结果>"`，然后回到第 1 步。

每次 Bash 调用都要先 `. "$RUN/env.sh"`：`sl`、`fill`、`load_tables`、`note` 是它定义的函数，调用之间不会保留。
用到表清单的命令前先 `load_tables`。

## 4. 不能省的规则

1. **写作和审读是两次独立调用。** 审读员只读材料包和文档，不看写作者的推理。不要自己写完自己审。
2. **低级问题不修。** 审读的高 + 中 = 0 的表就是 `fixed`；只有首审有高级问题的表复审一次。
3. **通过与否看命令输出，不看感觉。** 进度脚本说「做完」只表示文件在了，内容对不对由每步的完成判据决定。
4. **S10g 必须跑漏做检查** `catalog_check.py`（带 `--digest` 和 `--changes`）。末行不是 `0 finding(s)` 就按手册 S10g 返工，
   或在 `catalog_changes.md` 逐条写不补的理由；digest 的每条 filter / dedup / derive 规则要么有约束承接，要么有一行
   `<库.表>#rN skip: <理由>`。
5. **人的决定要推到底。** 「某列就是某编号」意味着那张事件表要把它指向的概念列为参与者；「某对象建成概念」意味着
   旁边的名称、描述列要挂到那个概念上。
6. **不改 `docs/` 里的表语义文档**：只有写作和修订子代理改它们。编排者不手改，也不只改 `packet_digest` 让校验通过。

## 5. 角色和模型

手册里的角色是提示词文件，不绑定具体模型：

| 角色 | 步骤 | 档位 | 只有一种模型时 |
| --- | --- | --- | --- |
| 写作、修订 | S4、S7 | 次一档强 | 同一个模型可以，但每次开新会话，只给提示词 |
| 审读、复审 | S6、S8 | 最强 | 新会话；做两遍，取两份审读的并集 |
| 目录起草、片段 | S10c、S10d | 次一档强 | 不要降到更弱的模型；靠 S10g 的漏做检查兜底 |
| 作答 | S11 | 便宜 | 任意 |
| 判分 | S11 | 最强 | 新会话 |

**派子代理**：用 `fill <模板> <输出文件> KEY=值 …` 生成提示词（手册每一步写了要用的 `fill` 命令），`exit=0` 才能发。
把文件交给一个新的子代理：任务只写一句「用 Read 完整读 `<文件绝对路径>`，照里面的要求做」。
没有子代理能力的环境，就开一个新会话，把这个文件交给它。同时在跑的子代理不超过 5 个。

## 6. 子代理回报后，编排者要做的

- 照手册那一步的「产出与自检」逐张核对，不要只信子代理的回报。
- 修订（T4）回报后，把回复里「逐条处理」「未改的低级发现」两段原样存进 `reviews/<表>.fixlog.txt`（手册 S7）。
- 子代理写文件被拦截、回报「文件在 `$SCRATCH/…`」时，由你 `cp` 到运行目录。
- 子代理中途停了、报额度用完：不算一轮，按 `$SCRATCH/prompts/` 里的同一份提示词重派。

## 7. 怎么看出走偏了

| 现象 | 说明 | 怎么办 |
| --- | --- | --- |
| 运行目录里只有 `ontology.json`，没有 `packets/`、`docs/`、`reviews/` | 走了键折叠的路 | 回到 S0 |
| 概念名是 `cust`、`acct` 这类英文词根，或 `nan` | 同上 | 回到 S0 |
| 有 `docs/` 没有 `reviews/` | 漏了独立审读 | 回到 S6 |
| 进度脚本的当前步和你以为的不一样 | 以脚本为准 | 从脚本说的那一步的前提检查开始 |
| `catalog_check.txt` 有 `empty_concept`、`missing_participant`、`unabsorbed_rule`、`state_without_states` 等 | 目录漏做 | 手册 S10g 的返工 |

## 8. 交付

进度脚本说当前是 S13 时，照手册 S13 写 `RESULT.md`：做了哪些表、校验与审读的数字、目录的计数、`catalog_check` 的结果、
给人的待确认清单（来自账本和 `merge_report.txt` 的 `note` 行），以及工具和流程的问题清单。
