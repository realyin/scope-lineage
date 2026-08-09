# Scope Lineage：面向 AI SQL 知识库的解析底座

中文 | [English](README.md)

Scope Lineage 是一个开源的 Spark/Hive SQL 静态解析工具。它的目标不是只画一张表血缘图，
而是把 SQL 任务转换成结构稳定、证据可追溯、可直接被 Agent、RAG、搜索和知识图谱消费的
事实层，为 AI 构建 SQL 任务知识库提供底层支撑。

很多系统把原始 SQL 或简单的“输入表 → 输出表”交给大模型。这样会丢失 CTE、子查询、
UNION 分支、字段表达式、过滤条件、聚合和解析不确定性。Scope Lineage 保留这些中间结构，
输出版本化的 `lineage.json` 与 `diagnostics.json`，让上层 AI 在可验证事实之上理解任务，
而不是直接猜测 SQL 含义。

> 当前仓库是首期开源的 Core 层：负责 SQL/任务输入、scope 解析、字段级血缘和诊断输出。
> 向量化、知识图谱存储、业务语义生成、数仓建模和重构建议属于上层能力，不包含在本仓库中。

## 它能做什么

- 面向 Spark/Hive 数仓 SQL，离线静态解析，不需要连接 Spark 集群或执行 SQL；
- 接收单个 `.sql`、真实调度任务 JSON，或递归任务目录；
- 支持 `INSERT INTO`、`INSERT OVERWRITE`、CTAS 和 `MERGE` 写表语句；
- 保留 CTE、子查询、JOIN、UNION/UNION ALL、聚合、窗口函数和中间 scope；
- 生成字段映射、表达式、物理源字段、端到端字段血缘和 scope 依赖图；
- 结合可选 Schema 元数据展开 `SELECT *`，补充字段类型和注释；
- 结合目标表 DDL/Schema 元数据，按权威字段顺序绑定 INSERT 投影；
- 从任务 JSON 保留声明的上下游任务依赖；
- 对无法解析、语法恢复、歧义引用和元数据缺失给出显式状态与诊断，不把猜测伪装成事实；
- 通过版本化 JSON Schema 和写盘前校验，为 AI 与其他下游提供稳定契约。

## 面向 AI 知识库的工作方式

```mermaid
flowchart LR
    A["SQL 文件 / 调度任务 JSON"] --> B["Scope Lineage Core"]
    M["Schema / 目标表 DDL 元数据"] --> B
    B --> L["lineage.json：可验证 SQL 事实"]
    B --> D["diagnostics.json：边界与不确定性"]
    L --> K["SQL 任务知识库"]
    D --> K
    K --> R["Agent / RAG / 搜索 / 知识图谱"]
```

Core 负责确定性解析和事实表达，不负责替用户选择向量数据库、图数据库或大模型。这样的边界使
同一份解析结果可以服务代码检索、任务问答、影响分析、治理审查和后续业务知识生成。

## 为什么还需要这个项目

开源生态已经有成熟能力，本项目并不宣称自己是第一个 SQL 解析器或血缘工具：

- [SQLGlot](https://github.com/tobymao/sqlglot) 是通用 SQL 解析、转译和优化引擎，也是本项目的底层依赖；
- [SQLLineage](https://sqllineage.readthedocs.io/) 提供通用表级和字段级 SQL 血缘；
- [OpenLineage](https://openlineage.io/docs/guides/spark/) 侧重从运行中的 Spark 作业采集标准化血缘事件；
- [DataHub](https://github.com/datahub-project/datahub/blob/master/docs/api/tutorials/lineage.md) 是完整元数据平台，也能从 SQL 推断字段血缘。

Scope Lineage 的差异化方向，是专注 Spark/Hive 离线任务，把中间 scope、字段变换、任务依赖、
元数据补全、端到端证据和解析诊断统一成面向 AI 知识库的版本化事实契约。根据目前可见的上述
项目官方定位，我们尚未发现一个与这一完整目标和输出边界完全相同的开源工具；这是项目要验证
和持续建设的方向，不是“没有其他 SQL 血缘方案”的绝对结论。

## 安装

当前版本从源码安装：

```bash
git clone https://github.com/realyin/sparksql-knowleage-parse.git
cd sparksql-knowleage-parse
python -m pip install -e ".[dev]"
```

项目包名为 `scope-lineage`，当前处于 `0.1.x` Alpha 阶段。

## 快速开始

### 1. 解析一个 SQL 文件

```bash
scope-lineage parse \
  --sql-file examples/sql/customer_profile_daily.sql \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

### 2. 解析真实格式的任务 JSON

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

任务导出格式与当前语料一致：

```json
{
  "meta": {
    "task_id": "demo-task-1002",
    "task_name": "customer_profile_daily",
    "input_tables": ["ods.customer_base", "dwd.order_detail"],
    "output_tables": ["mart.customer_profile_snapshot"],
    "upstream_tasks": [
      {"task_id": "demo-task-1001", "task_name": "order_detail_daily"}
    ],
    "downstream_tasks": [],
    "sql": "INSERT OVERWRITE TABLE ..."
  },
  "query_time": "2026-08-02 10:00:00",
  "data_source": "scheduler_api_demo"
}
```

完整示例保留了任务类型、项目、负责人、调度、描述、输入输出表、依赖、实例和时间等实际字段；
Core 当前只消费解析需要的任务名、SQL 和依赖信息。

### 3. 批量解析任务目录

```bash
scope-lineage parse \
  --input-dir examples/tasks \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage-corpus
```

目录会递归发现 `*.json`。嵌套目录结构会保留到输出目录中；一个任务包含多条支持的写表语句时，
每条语句分别生成产物。只有调用方明确接受失败输入或失败语句时，才使用 `--allow-partial`。

更多完整输入见 [examples/README.zh-CN.md](examples/README.zh-CN.md)，字段级说明见
[Core 输入格式](docs/zh-CN/input-formats.md)。

## 输入元数据

Schema 支持 CSV 或 JSON。实际 CSV 可以包含字段类型和注释：

```csv
table_name,column_name,column_type,column_comment
ods.customer_base,customer_id,bigint,Synthetic customer identifier
ods.customer_base,customer_name,string,Synthetic customer name
```

`--target-ddl-metadata` 接收单个 JSON 或目录；每份文件描述目标表名、字段顺序、分区、DDL 和元数据
版本。Schema 主要用于源字段解析和 `SELECT *` 展开，目标表元数据用于权威 INSERT 字段绑定，
两者用途不同。

## 输出

每条写表语句只生成两份 Core 产物：

```text
<output>/<task-id>/
├── lineage.json
└── diagnostics.json
```

`lineage.json` 包含：

- 任务、目标表、语句类型、分区和解析状态；
- 上下游任务依赖、源表和相关元数据；
- scope 图与每个 scope 的输入、输出、条件和变换；
- 字段映射链、物理源字段和端到端字段血缘；
- 精简诊断摘要。

`diagnostics.json` 包含完整告警、语法恢复信息、未解析引用和降级原因。AI 下游必须同时读取诊断，
不能把 `recovered`、歧义候选或缺失元数据当成已经证明的血缘事实。

## Python API

```python
from lineage_parser import parse_scope_lineage, to_lineage_dict, write_lineage

result = parse_scope_lineage(
    "INSERT INTO mart.user_ids SELECT id FROM ods.users",
    task_id="user_ids",
    schema={"ods.users": ["id"]},
)

document = to_lineage_dict(result)
write_lineage(result, "/tmp/scope-lineage/user_ids")
```

稳定公共面由 `lineage_parser.PUBLIC_CORE_API` 显式声明。下游应使用公共门面或读取 JSON 契约，
不要穿透导入内部实现模块。

## 契约与限制

两份输出当前要求 `schema_version: "1.0"` 并在写盘前校验。同一 major 版本内，消费者应容忍
新增可选字段；删除、改名或改变字段语义必须升级 major。

- [Lineage JSON 契约](docs/zh-CN/lineage-json.md)
- [Diagnostics JSON 契约](docs/zh-CN/diagnostics-json.md)
- [Core 输入格式](docs/zh-CN/input-formats.md)

当前限制：

- 只做静态分析，不判断 SQL 在真实 Spark 集群上能否成功执行；
- 独立 `UPDATE`/`DELETE` 不属于当前字段投影模型，`MERGE` 内的更新/插入分支受支持；
- 动态 SQL、模板展开和平台自定义语法可能需要调用方先预处理；
- 缺少 Schema 时，`SELECT *` 可能保留显式降级占位；
- Scope Lineage 提供知识库事实输入，但本身不是完整的知识库产品。

## 开发验证

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py
python -m ruff check lineage_parser tests
python -m build
python tests/architecture/verify_distribution.py dist/*
```

提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。所有测试和示例
必须使用合成数据，不得包含私有 SQL、内部标识符或本机路径。

## License

Apache License 2.0，见 [LICENSE](LICENSE)。
