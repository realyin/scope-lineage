[English](../en/task-to-ontology.md) | 中文

# 从任务和表 Schema 到业务语义与本体：操作入口

> 手上有一批任务 JSON 和表 Schema，要的是**任务语义、表语义和业务本体**时，从这一页开始。
> 只跑 `parse` → `tables` / `glossary` → `describe` → `ontology` 就停，得到的是键折叠候选，不是业务本体：
> 概念名取自键列词根（`cust`、`acct` 这类英文缩写），大多数表只是临时概念。

## 先选路线

| 你要的 | 走哪条路 | 得到什么 |
| --- | --- | --- |
| 字段血缘、影响分析、mapping 文档 | `parse`，之后用 `scripts/query.py` 或 `render` | `lineage.json`、`mapping.md` |
| 一份语料的快速结构扫描：哪些表共用哪些键 | [端到端工作流](workflow.md)的五分钟路径，到 `ontology` 为止 | `ontology.json`：键折叠候选，不是业务本体 |
| 任务在做什么、一张表是什么意思、业务有哪些概念 | **本页的路线**：表语义，再到本体目录 | `docs/`、`site/semantics/`、`site/concepts/` |

## 全流程一览

操作手册是 [`runbook.md`](../../skills/scope-lineage/references/runbook.md)，下表是它的目录。
每一步在手册里都有七栏：目的、前提检查、命令、产出与自检、常见失败、完成判据、下一步。
不知道现在走到哪一步时，跑进度脚本 `next_step.py`（手册 0.6）：它只读运行目录，打印下表的进度清单和当前步。

| 步 | 做什么 | 谁做 | 主要产出 |
| --- | --- | --- | --- |
| S0 | 环境、版本、运行目录、账本 | 编排者 | `env.sh`、`ledger.md` |
| S1 | 血缘解析 | 编排者 | `artifacts/` |
| S2 | 表卡与术语 | 编排者 | `corpus/tables.json`、`corpus/glossary.json` |
| S3 | 选表与材料包 | 编排者 | `tables.txt`、`packets/` |
| S4 | 写作 | 子代理，每表一个 | `docs/<表>.json` |
| S5 | 校验与 blocked | 编排者 | 校验结论 |
| S6 | 审读 | 子代理，每表一个 | `reviews/<表>.md` |
| S7 | 修订 | 子代理，每表一个 | 改过的文档、修订回执 |
| S8 | 状态推进与复审 | 编排者和子代理 | 全部 `fixed` |
| S9 | 全量校验与渲染表语义页 | 编排者 | `site/semantics/` |
| S10 | 本体目录：起点、digest、起草、片段、合并、修正、构建渲染 | 编排者和子代理 | `catalog/`、`merged/`、`onto/`、`site/concepts/` |
| S11 | 回归验收 | 编排者和子代理 | `round1/score/` |
| S12 | 确认回写（可选） | 编排者 | 带确认的文档 |
| S13 | 交付 | 编排者 | `RESULT.md` |

## 三条不能省的规则

1. **写作和审读是两次独立调用。** 审读员只读材料包和文档，不读写作者的推理。写作者自查找不出自己的盲点。
2. **每一步是否通过，以完成判据里的命令输出为准**，不以自己的感觉为准。前提检查不满足或完成判据不成立，就停在这一步。
3. **先小样。** 最多 5 张表、1 组，验证流程和质量后再扩。

## 角色和模型档位

手册里的角色是提示词文件，不绑定具体模型。档位是相对的：

| 角色 | 步骤 | 档位 | 只有一种模型时 |
| --- | --- | --- | --- |
| 写作、修订 | S4、S7 | 次一档强 | 可以用同一个模型，但每次开新会话，只给提示词和材料包 |
| 审读、复审 | S6、S8 | 最强 | 新会话，只读材料包和文档；做两遍，取两份审读的并集 |
| 目录起草、片段 | S10 | 次一档强 | 不要降到更弱；起草完让更强的模型核对概念是否补全 |
| 作答 | S11 | 便宜 | 任意 |
| 判分 | S11 | 最强 | 新会话，不看作答者的推理 |

## 怎么开始

执行的 agent 用 [`scope-lineage-ontology`](../../skills/scope-lineage-ontology/SKILL.md) 这个 Skill。
装好之后（见 [AI agent 技能](agent-skill.md)），说清任务目录、表 Schema 目录和要做的事，它会自动加载；
没有 Skill 机制的 agent，把下面这段交给它，替换尖括号里的路径：

```text
目标：用 scope-lineage 从下面的任务和表 Schema 生成表语义和业务本体目录。
任务目录：<任务 JSON 目录>
表 Schema 目录：<表元数据目录>
运行目录：<新建的运行目录>
先完整读 <scope-lineage 仓库>/skills/scope-lineage-ontology/SKILL.md，照它做。
先做小样：最多 5 张表。
```

## 怎么看出走偏了

| 现象 | 说明 | 怎么办 |
| --- | --- | --- |
| 运行目录里只有 `ontology.json`，没有 `packets/`、`docs/`、`reviews/` | 走了键折叠路线，没做表语义 | 回到 S0，按手册重来 |
| 概念名是 `cust`、`acct` 这类英文词根，或 `nan` | 同上，名字取自键列词根 | 同上 |
| 有 `docs/`，没有 `reviews/` | 没有独立审读 | 回到 S6 |
| 概念页只有标识符、没有属性，或事件只有一两个参与者 | 目录起草不完整，`catalog validate` 查不出漏掉的内容 | 跑 S10g 的漏做检查 `catalog_check.py`，按它的发现退回 S10c、S10d 补全 |

## 下一步

- [`runbook.md`](../../skills/scope-lineage/references/runbook.md)：逐步操作手册。
- [表语义](table-semantics.md)：`semantic *` 的文档格式、校验和状态。
- [本体目录](ontology-catalog.md)：`catalog-yaml/1` 与 `ontology-json/3`。
- [端到端工作流](workflow.md)：键折叠路线和各产物的先后关系。
