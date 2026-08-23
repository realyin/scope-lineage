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

**Codex 及其他 agent**：这些 agent 没有插件机制，git 是唯一分发渠道（`pip install`
有意**不**携带技能文件——它们被排除在 PyPI 发行物之外）。三步：

1. 把仓库 clone 到一个固定位置（和你日常工作的项目无关）：

   ```bash
   git clone https://github.com/realyin/scope-lineage ~/tools/scope-lineage
   ```

2. 在 agent 的规则文件里加一行。项目级 `AGENTS.md` 只对当前项目生效；建议写进全局
   规则文件（Codex 为 `~/.codex/AGENTS.md`），所有项目通用：

   > SQL 血缘、字段加工、影响分析、mapping 文档相关问题，先读
   > `~/tools/scope-lineage/skills/scope-lineage/SKILL.md` 并遵循它。

   路径换成你实际的 clone 位置。技能内部的相对路径（`scripts/query.py`、
   `references/...`）以 SKILL.md 自身所在目录为基准解析，所以**被分析的项目里不需要
   有这些文件**——你在任何数仓项目里提问都能用。

3. 更新技能：`git -C ~/tools/scope-lineage pull`（Core CLI 的升级仍走
   `pip install --upgrade scope-lineage`，两条通道独立，技能的自检会在版本过旧时提示
   升级）。

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
