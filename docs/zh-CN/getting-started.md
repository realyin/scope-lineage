# Scope Lineage 安装与使用指南

Scope Lineage 是一个离线的 Spark/Hive SQL 静态分析工具。它读取 SQL 和可选元数据，输出：

- `lineage.json`：表、scope、表达式、字段映射链和端到端字段血缘；
- `diagnostics.json`：解析 warning、统计数据和无法证明的事实缺口。

它不需要 Spark 集群、数据库连接或 LLM。运行环境需要 Python 3.9～3.12。

## 1. 安装

### 方式一：使用 pipx 安装 CLI（推荐）

如果本机已经安装 `pipx`：

```bash
pipx install scope-lineage
scope-lineage --help
```

`pipx` 会为命令行工具创建独立环境，避免与其他 Python 项目的依赖冲突。以后升级可以运行：

```bash
pipx upgrade scope-lineage
```

### 方式二：在虚拟环境中使用 pip

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install scope-lineage
scope-lineage --help
```

Windows PowerShell 激活虚拟环境的命令是：

```powershell
.venv\Scripts\Activate.ps1
```

## 2. 第一次解析

新建 `demo.sql`：

```sql
INSERT OVERWRITE TABLE mart.order_summary
SELECT
  customer_id,
  COUNT(*) AS order_count,
  SUM(amount) AS total_amount
FROM ods.orders
WHERE status = 'PAID'
GROUP BY customer_id;
```

运行：

```bash
scope-lineage parse \
  --sql-file demo.sql \
  --out ./scope-lineage-output
```

输出目录使用 SQL 文件名作为默认任务名：

```text
scope-lineage-output/
└── demo/
    ├── lineage.json
    └── diagnostics.json
```

可以直接格式化查看结果：

```bash
python -m json.tool scope-lineage-output/demo/lineage.json
python -m json.tool scope-lineage-output/demo/diagnostics.json
```

## 3. 选择输入方式

`parse` 命令必须且只能使用以下三种输入方式之一：

| 场景 | 参数 | 示例 |
| --- | --- | --- |
| 一个普通 SQL 文件 | `--sql-file` | `scope-lineage parse --sql-file task.sql --out ./output` |
| 一个调度平台导出的任务 JSON | `--task-file` | `scope-lineage parse --task-file task.json --out ./output` |
| 批量递归解析 JSON 目录 | `--input-dir` | `scope-lineage parse --input-dir tasks --out ./output` |

SQL 文件名是默认任务名，也可以显式覆盖：

```bash
scope-lineage parse \
  --sql-file task.sql \
  --task-name customer_profile_daily \
  --out ./output
```

`--task-name` 只适用于单个 SQL 或任务 JSON；批量目录模式会使用每份任务数据中的名称。一个文件
包含多条受支持的写表语句时，会分别写入 `<任务名>_0`、`<任务名>_1` 等目录。

任务 JSON 推荐把 SQL 和任务信息放在 `meta` 中：

```json
{
  "meta": {
    "task_id": "demo-1002",
    "task_name": "customer_profile_daily",
    "sql": "INSERT OVERWRITE TABLE mart.customer_profile SELECT customer_id FROM ods.customer_base",
    "upstream_tasks": [
      {"task_id": "demo-1001", "task_name": "customer_base_daily"}
    ],
    "downstream_tasks": []
  },
  "data_source": "scheduler_export"
}
```

任务依赖会写入 `lineage.json.task_dependencies`。完整字段约定见
[Core 输入格式](input-formats.md)。

## 4. 添加元数据，提高字段血缘完整度

不传元数据也能解析显式字段。遇到 `SELECT *`、目标字段位置绑定或需要类型和注释时，应补充
Schema 和目标表元数据。这是两类用途不同的输入：

| 输入 | 推荐格式 | 解决的问题 |
| --- | --- | --- |
| `--schema` | 含 `schema[]` 和可选 `ddl` 的 JSON 文件/目录；CSV 仅作候补 | 提供源表字段，按权威顺序展开 `SELECT *`，补充类型和注释。 |
| `--target-ddl-metadata` | 含 `schema[]` 和 `ddl` 的 JSON | 按权威目标表结构绑定 INSERT 投影，识别字段位置和分区。 |

### 源表 Schema：JSON 优先

新建 `ods.orders_metadata.json`。推荐同时提供 `schema[].columnIndex` 和 DDL：

```json
{
  "table_name": "ods.orders",
  "full_table_name": "spark_catalog.ods.orders",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnComment": "Synthetic customer identifier",
      "columnIndex": 0,
      "isPartition": 0
    },
    {
      "columnName": "amount",
      "columnType": "decimal(18,2)",
      "columnComment": "Synthetic order amount",
      "columnIndex": 1,
      "isPartition": 0
    },
    {
      "columnName": "status",
      "columnType": "string",
      "columnComment": "Synthetic order status",
      "columnIndex": 2,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE spark_catalog.ods.orders (customer_id BIGINT, amount DECIMAL(18,2), status STRING) USING iceberg",
  "query_time": "2026-08-14 10:00:00",
  "data_source": "catalog_api"
}
```

解析时传入：

```bash
scope-lineage parse \
  --sql-file demo.sql \
  --schema ods.orders_metadata.json \
  --out ./scope-lineage-output
```

`--schema` 也可以接收一个目录，目录中每张源表放一份这种 JSON。源表字段顺序的实际优先级是：

1. `ddl` 能成功解析时，以 DDL 字段顺序为准；
2. 没有 DDL 时，按 `schema[].columnIndex` 排序，序号必须从 0 开始且连续；
3. 兼容的轻量 JSON 没有 `columnIndex` 时，按 `columns[]` 数组顺序；
4. CSV 最后按文件行序处理。

CSV 是兼容候补格式。同一张表的文件行序会被当作字段顺序：

```csv
table_name,column_name,column_type,column_comment
ods.orders,customer_id,bigint,Synthetic customer identifier
ods.orders,amount,"decimal(18,2)",Synthetic order amount
ods.orders,status,string,Synthetic order status
```

CSV 没有显式 `columnIndex`，也没有 DDL 可用于交叉校验。如果导出端不能保证行序，就不要依赖
CSV 展开 `SELECT *`。

### 目标表 DDL/Schema：权威 JSON

`--target-ddl-metadata` 接收一个 JSON 文件或目录，用于提供目标表的权威字段名、顺序、类型和
分区信息。新建 `mart.order_summary_metadata.json`：

```json
{
  "table_name": "mart.order_summary",
  "full_table_name": "spark_catalog.mart.order_summary",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnComment": "Synthetic customer identifier",
      "columnIndex": 0,
      "isPartition": 0
    },
    {
      "columnName": "order_count",
      "columnType": "bigint",
      "columnComment": "Order count",
      "columnIndex": 1,
      "isPartition": 0
    },
    {
      "columnName": "total_amount",
      "columnType": "decimal(18,2)",
      "columnComment": "Total order amount",
      "columnIndex": 2,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE spark_catalog.mart.order_summary (customer_id BIGINT, order_count BIGINT, total_amount DECIMAL(18,2)) USING iceberg",
  "query_time": "2026-08-14 10:00:00",
  "data_source": "catalog_api"
}
```

解析时同时传入源表和目标表元数据：

```bash
scope-lineage parse \
  --sql-file demo.sql \
  --schema ods.orders_metadata.json \
  --target-ddl-metadata mart.order_summary_metadata.json \
  --out ./scope-lineage-output
```

目标结构的实际优先级是：

1. `ddl` 能成功解析时，以 DDL 中的字段顺序和分区定义为准；
2. `schema[]` 按字段名与 DDL 交叉校验，并提供类型、注释和 `columnIndex`；
3. 没有 DDL 时按 `schema[].columnIndex` 排序，序号必须从 0 开始且连续；
4. CSV 不能作为 `--target-ddl-metadata`，它只属于源表 `--schema` 的候补格式。

如果同一个富 JSON 目录包含全部源表和目标表，可以把该目录同时传给 `--schema` 和
`--target-ddl-metadata`；前者提供源字段展开，后者只对本次写入的目标表执行位置绑定。

目标元数据的 JSON 结构和版本选择规则见
[目标表 DDL/Schema 元数据](input-formats.md#目标表-ddlschema-元数据)。

克隆源码仓库后，也可以直接运行完整示例：

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.json \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

## 5. 如何读取结果

建议始终同时读取两份文件：

| 想回答的问题 | 主要字段 |
| --- | --- |
| 写入哪张表、读取哪些物理表？ | `target_table`、`source_tables` |
| CTE、子查询和 UNION 如何连接？ | `scope_graph`、`scopes` |
| JOIN、过滤、聚合和窗口在哪里发生？ | `scopes.*.logic_blocks` |
| 字段经过哪些 scope 和表达式？ | `field_mapping_chains` |
| 每个目标字段最终来自哪里？ | `end_to_end_lineage` |
| 结果是否完整、哪里仍有歧义？ | `trace_complete`、`missing_reasons`、`ambiguities` |
| 为什么某条事实无法确定？ | `diagnostics.json.lineage_fact_gaps` |

最基本的消费规则是：

1. 确认 `lineage.json.parse_status` 不是 `failed`；
2. 检查 `diagnostics.json.warnings` 和 `lineage_fact_gaps`；
3. 对字段级结论检查 `trace_complete`、`missing_reasons` 和 `ambiguities`；
4. 不要把恢复后的语法、候选来源或元数据缺口当成已经证明的事实。

完整字段说明见 [`lineage.json` 输出契约](lineage-json.md)和
[`diagnostics.json` 输出契约](diagnostics-json.md)。

## 6. 批量任务和失败策略

批量解析目录：

```bash
scope-lineage parse \
  --input-dir exported-tasks \
  --schema table-metadata \
  --target-ddl-metadata table-metadata \
  --out ./output
```

默认情况下，只要有一个输入读取失败，或有一条语句的 `parse_status=failed`，命令就返回非零退出
码；其他成功结果仍会写盘。只有调用方明确接受部分结果时才使用：

```bash
scope-lineage parse \
  --input-dir exported-tasks \
  --out ./output \
  --allow-partial
```

`--allow-partial` 只改变命令退出码，不会把失败结果改成成功，也不会隐藏诊断。

需要任务级 DELETE/TRUNCATE/UPDATE 和多语句最终状态时使用：

~~~bash
scope-lineage parse \
  --input-dir exported-tasks \
  --contract-version 2.0 \
  --quality-policy strict \
  --out ./output-v2
~~~

完整语义见 [Task Lineage 2.0](task-lineage-v2.md)。v1 和 v2 应写入不同目录。

## 7. catalog 前缀

三段表名默认完整保留。只有确认首段是可移除的 catalog 时才显式配置：

```bash
scope-lineage parse \
  --sql-file task.sql \
  --catalog-prefixes warehouse_catalog,spark_catalog \
  --out ./output
```

固定运行环境也可以设置：

```bash
export SCOPE_LINEAGE_CATALOG_PREFIXES="warehouse_catalog,spark_catalog"
```

命令行配置优先于环境变量。不要把 `ods`、`dwd` 等 database 名误配成 catalog。


### 集群的覆写模式与 Spark 默认不同时

`INSERT OVERWRITE TABLE t PARTITION(dt)`（分区规格不给值）删掉多少数据，
取决于 `spark.sql.sources.partitionOverwriteMode`：`static`（Spark 官方默认）删整表，
`dynamic` 只删本次实际写出的分区。脚本通常不设置它，本工具按 Spark 默认推断。

**若你们集群配的是 `dynamic`**（Spark Web UI 的 Environment 页可确认），
在 `--contract-version 2.0` 下传 `--partition-overwrite-mode dynamic`，
否则每一条不给分区取值的覆写——分区表日常写入的常见写法——效果判定方向都会相反。
脚本里的 `SET` 始终优先于该参数。

## 8. Python API

```python
from scope_lineage import parse_scope_lineage, to_lineage_dict, write_lineage

sql = "INSERT INTO mart.user_ids SELECT id FROM ods.users"

result = parse_scope_lineage(
    sql,
    task_name="user_ids",
    schema={"ods.users": ["id"]},
)

document = to_lineage_dict(result)
print(document["target_table"])

write_lineage(result, "./scope-lineage-output/user_ids")
```

`to_lineage_dict()` 适合内存消费，`write_lineage()` 会校验并写出两份契约文件。下游代码应通过
`scope_lineage` 公共门面调用，不要依赖内部模块路径。

任务级 API 为 `parse_task_lineage()` 和 `write_task_lineage()`。

## 9. 常见问题

### 安装后找不到 `scope-lineage`

- 使用虚拟环境安装时，先确认环境已经激活；
- 使用 `pipx` 时运行 `pipx ensurepath`，然后重新打开终端；
- 用 `python -m pip show scope-lineage` 确认安装到了当前 Python 环境。

### `SELECT *` 没有完整展开

为相关源表提供 `--schema`。没有 Schema 时，工具不会猜测星号代表哪些字段，而会在诊断中记录
缺口。

### 普通 `SELECT` 没有生成产物

Scope Lineage 面向离线写表任务。输入中需要有受支持的 `INSERT`、CTAS 或 `MERGE` 写表语句；
独立查询不会被当作发布任务生成 Lineage 产物。

### 如何查看全部参数

```bash
scope-lineage parse --help
```

## 下一步

- [文档导航与问题—字段索引](README.md)
- [完整输入格式](input-formats.md)
- [`lineage.json` 输出契约](lineage-json.md)
- [`diagnostics.json` 输出契约](diagnostics-json.md)
- [示例说明](../../examples/README.zh-CN.md)
