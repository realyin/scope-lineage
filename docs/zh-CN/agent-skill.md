# AI agent 技能：让 agent 直接用上血缘能力

仓库自带一个 agent 中立的技能，位于 [`skills/scope-lineage/`](../../skills/scope-lineage/)。
它把"用好这个工具"所需的三类知识固化成文件，任何能读 markdown、能跑 shell 的 AI 编码
agent 都能执行：

1. **元数据接线**——`--schema` / `--schema-fallback` / `--target-ddl-metadata` 各喂什么，
   漏传哪个会静默降级（`SELECT *` 不展开、投影绑错列）；
2. **产物阅读法**——"字段怎么算出来的"读哪个 JSON 路径、"谁依赖这张表"怎么反查；
3. **诚实度规则**——`trace_complete`、事实缺口、`AMBIGUOUS` 必须随答案呈现，不许把猜测
   说成事实。

配套脚本 `scripts/query.py`（纯标准库）做定向提取——真实任务的 lineage.json 可达 MB 级，
agent 永远不该把整个文件读进上下文：

```bash
python3 skills/scope-lineage/scripts/query.py summary <产物目录>            # 任务概览
python3 skills/scope-lineage/scripts/query.py chain  db.table.column <目录>  # 字段加工链
python3 skills/scope-lineage/scripts/query.py impact db.table[.col] <根目录> # 影响分析
```

这三个子命令对人也好用——不装任何 agent 也可以直接跑。

## 安装

**Claude Code**：

```
/plugin marketplace add realyin/scope-lineage
```

然后安装 `scope-lineage` 插件。之后提到血缘、字段来源、加工步骤、影响分析、mapping
文档的对话会自动触发技能。

**Codex 及其他 agent**：在你的 agent 规则文件（如 `AGENTS.md`）里加一行：

> SQL 血缘、字段加工、影响分析、mapping 文档相关问题，先读
> `skills/scope-lineage/SKILL.md` 并遵循它。

技能内容不依赖任何 agent 专有机制，各家 agent 读到的是同一份指引。

## 团队私有元数据配置

真实语料的 schema / DDL 元数据路径属于团队私有信息，**不进技能本体**。约定放在本地
文件 `~/.scope-lineage/defaults.json`：

```json
{
  "schema": "<rich-JSON 元数据目录>",
  "schema_fallback": ["<兜底 CSV>"],
  "target_ddl_metadata": "<目标表 DDL 目录>",
  "catalog_prefixes": "<可选，逗号分隔>"
}
```

技能在每次解析前查找该文件并把键翻译成对应 flag；文件不存在且在解析真实任务时，
技能会先询问元数据位置而不是裸解析（裸解析会静默降级，见
`skills/scope-lineage/references/metadata-inputs.md`）。

## 版本要求

需要 scope-lineage ≥ 0.2.0。技能自检用 `scope-lineage --version`（0.2.1 起提供；
0.2.0 用 `python3 -c "import importlib.metadata as m; print(m.version('scope-lineage'))"`
兜底）。旧版本会静默产出已移除的逐语句格式——`query.py` 遇到这类产物会明确提示，
但解析本身已经浪费了。
