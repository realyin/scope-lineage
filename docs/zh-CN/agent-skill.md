[English](../en/agent-skill.md) | 中文

# AI agent 技能：让 agent 直接用上血缘能力

仓库自带一个 agent 中立的技能，位于 [`skills/scope-lineage/`](../../skills/scope-lineage/)。
它把"用好这个工具"所需的三类知识固化成文件，任何能读 markdown、能跑 shell 的 AI 编码
agent 都能执行：

1. **元数据接线**——`--schema` / `--schema-fallback` / `--target-ddl-metadata` 各喂什么，
   漏传哪个会静默降级（`SELECT *` 不展开、投影绑错列）；
2. **产物阅读法**——"字段怎么算出来的"读哪个 JSON 路径、"谁依赖这张表"怎么反查；
3. **诚实度规则**——`trace_complete`、事实缺口、`AMBIGUOUS` 必须随答案呈现，不许把猜测
   说成事实。

配套脚本 `scripts/query.py`（纯标准库）做定向提取。血缘产物可能很大，agent 永远不该把
整个文件读进上下文：

```bash
python3 skills/scope-lineage/scripts/query.py summary <产物目录>            # 任务概览
python3 skills/scope-lineage/scripts/query.py chain  db.table.column <目录>  # 字段加工链
python3 skills/scope-lineage/scripts/query.py impact db.table[.col] <根目录> # 影响分析
python3 skills/scope-lineage/scripts/query.py trace  db.table[.col] <根目录> \
    [--upstream N] [--downstream N]                                          # 跨任务上下游追溯
python3 skills/scope-lineage/scripts/query.py concept-impact <概念 id | 名> \
    --ontology <本体目录>/ontology.json --lineage <根目录> \
    [--depth N] [--attribute 属性名] [--json]                                # 概念级影响分析
```

这五个子命令对人也好用——不装任何 agent 也可以直接跑。
`chain` 默认限制表达式输出长度；确实需要完整表达式时再加 `--expanded`。扫描任务集合时，
脚本只保留当前产物，不会把全部已解析文档累积在内存里。`trace` 首次运行会在产物根目录
生成 `.scope-lineage-index.json` 路由索引，之后按文件指纹增量刷新；索引只是可丢弃的
缓存，产物始终是唯一事实源。`concept-impact` 是其中唯一一个还要读 `ontology.json`
（`ontology-json/2`）的子命令：它按 id / 完整名 / 唯一前缀定位概念，打印这个概念的表现表
（含 role）与概念关系（type、cardinality、tier），再用与 `trace` 同一套语料下游机制列出每张
表现表的下游任务（按任务去重，注明读的是哪张表、第几跳）；`--attribute` 把答案收窄到该属性
`sources[]` 的源列，并只保留 JOIN 列包含该属性的概念关系。前缀撞上多个概念时列出候选并退出
2，本体缺失 / 版本过旧 / 概念或属性不存在同样是一句话加退出码 2。

技能的工作流清单里还有一条不走 `query.py` 的：问"这个任务在做什么 / 这个字段什么含义"时，先跑 `scope-lineage describe --lineage <产物目录>` 生成 `semantic.json` / `semantic.md` 语义骨架，整读 `semantic.md` 回答；要业务画像时再按 `references/semantic-profile-prompt.md` 生成两个文件。`business_profile.md` 是给读者的：三件套——任务语义卡（≤ 1 页、业务语言、正文不挂来源标签）、字段字典（覆盖全部输出字段，指标附 7 行口径卡）、待确认清单（≤ 5 条，业务方几分钟答完）——后面只跟一个短附录：A 已确认项 / B 备查项与待填取值 / C 风险边界，三节合计 ≤ 正文字数的 1/3。`business_profile.check.md` 是写作方的质检记录：输入文件校验、来源标签与证据、结构推断项、自洽性检查与生成自检，一项都不能省，但不再占读者的篇幅。

技能还带一个写回脚本 `scripts/confirmations.py`（同样纯标准库）：业务方把答案填在
`business_profile.md` 每条待确认项的 `- 答案：` 行之后，

```
python3 skills/scope-lineage/scripts/confirmations.py apply <画像文件> --by <名字>
```

按每条的「回写目标」分流——`术语` / `值域` 合并进 `glossary.overrides.json`，
`字段注释` / `表注释` 合并进 `metadata-patch.json`（`--dry-run` 只打印）。`值域` 还认
**家族键** `值域:*.<列>=<值>`：一张码表被复制到三张以上的表时，业务方只答一次，答案写回
每一张观察到该取值的表。再跑一次
`glossary --overrides` 与 `describe --glossary --metadata-patch`，这些项在下一轮画像里
就从「待确认」变成已确认的事实，清单随每一轮变短。

问"这批任务讲的是什么、它们之间是什么关系"时走另一条：跑 `scope-lineage ontology --lineage <语料> --out <目录>`，先读 `<目录>/ontology.md` 的「本体总览」，再顺着概念表里的链接读 `<目录>/concepts/<文件>.md` 看它由哪些表表现，然后读 `<目录>/tables/<表>.md` 的本体五节（表级 ER 与表清单在 `<目录>/appendix.md` 里——那是证据，不是模型）；`hypothesis` 与 `conflict` 必须原样标 `[待确认]` 呈现，答完的项按 `references/ontology-review-prompt.md` 回写 `ontology.overrides.json`，下一轮升为 `confirmed`。

## 安装

**Claude Code**：

```
/plugin marketplace add realyin/scope-lineage
```

然后安装 `scope-lineage` 插件。之后提到血缘、字段来源、加工步骤、影响分析、mapping
文档的对话会自动触发技能。

**Codex（原生 Skill 安装，推荐）**：Codex 有自己的 Agent Skills 机制，技能目录格式
与本仓库的完全一致，即插即用。git 是分发渠道（`pip install` 有意**不**携带技能文件
——它们被排除在 PyPI 发行物之外）：

```bash
git clone https://github.com/realyin/scope-lineage ~/tools/scope-lineage
ln -s ~/tools/scope-lineage/skills/scope-lineage ~/.codex/skills/scope-lineage
```

- **用户级** `~/.codex/skills/`：所有项目通用，推荐；**项目级** `.codex/skills/`：只对
  当前项目生效。装进技能目录后，Codex 按 SKILL.md 的 description 自动触发，和 Claude
  Code 的体验一致。
- 更新：`git -C ~/tools/scope-lineage pull`，软链自动跟随；若你的 agent 版本不跟随
  软链，改为复制目录、更新时重新复制。
- Core CLI 的升级仍走 `pip install --upgrade scope-lineage`，两条通道独立，技能的
  自检会在版本过旧时提示升级。

**没有技能机制的 agent（兜底）**：先按上面 clone，然后在其规则文件（项目级
`AGENTS.md` 或全局等价物）加一行：

> SQL 血缘、字段加工、影响分析、mapping 文档相关问题，先读
> `~/tools/scope-lineage/skills/scope-lineage/SKILL.md` 并遵循它。

技能内部的相对路径（`scripts/query.py`、`references/...`）以 SKILL.md 自身所在目录为
基准解析，所以**被分析的项目里不需要有这些文件**——你在任何数仓项目里提问都能用。
技能内容不依赖任何 agent 专有机制，各家 agent 读到的是同一份指引。

## 团队私有元数据配置

真实语料的 schema / DDL 元数据路径属于团队私有信息，**不进技能本体**。约定放在本地
文件 `~/.scope-lineage/defaults.json`：

```json
{
  "schema": "/path/to/rich-json-metadata-dir",
  "schema_fallback": ["/path/to/fallback-schema.csv"],
  "target_ddl_metadata": "/path/to/target-ddl-dir",
  "catalog_prefixes": "warehouse_catalog,spark_catalog"
}
```

`catalog_prefixes` 可选，不确定首段是不是 catalog 就别写。

技能在每次解析前查找该文件并把键翻译成对应 flag；文件不存在且在解析真实任务时，
技能会先询问元数据位置而不是裸解析（裸解析会静默降级，见
`skills/scope-lineage/references/metadata-inputs.md`）。

## 版本要求

需要 scope-lineage ≥ 0.2.0。技能自检用 `scope-lineage --version`（0.2.1 起提供；
0.2.0 用 `python3 -c "import importlib.metadata as m; print(m.version('scope-lineage'))"`
兜底）。旧版本会静默产出已移除的逐语句格式——`query.py` 遇到这类产物会明确提示，
但解析本身已经浪费了。
