# Core 输入格式

Scope Lineage Core 接收 SQL 内容以及两类可选元数据。它不会连接调度平台或元数据平台；调用方
负责导出文件，Core 负责将文件规范化后解析成版本化事实。

## 输入如何改变输出价值

| 输入 | 是否必须 | 主要影响的输出 | 不提供时的结果 |
| --- | --- | --- | --- |
| SQL 文本 | 是 | 全部 scope、逻辑块、表和字段血缘 | 无法解析。 |
| 任务 JSON 包装 | 否 | `task_id`、`task_dependencies`、批量输出路径 | 仍可解析 SQL，但没有调度任务依赖。 |
| 源表 Schema | 否 | `SELECT *` 展开、字段绑定、类型/注释、`related_metadata` | 显式列仍可解析；星号可能降级并产生 warning。 |
| 目标表 DDL/Schema | 否 | `target_field_binding`、最终目标字段名和位置 | 使用 INSERT 列表或 SQL 投影名，不宣称经过权威位置校正。 |

输入越完整，Core 能证明的字段事实越多；但元数据不会覆盖 SQL 事实。例如 Schema 可以说明表有哪些列，不能替代 SQL 中实际使用的 JOIN、过滤和表达式。

## SQL 输入

### 单个 SQL 文件

```bash
scope-lineage parse --sql-file task.sql --out /tmp/lineage
```

文件可以包含一条或多条语句。只有受支持的写表语句生成产物，多条写表语句使用
`<task-name>_0`、`<task-name>_1` 等独立目录。

### 单个任务 JSON

推荐使用当前调度平台导出结构：

```json
{
  "meta": {
    "task_id": "task-1002",
    "task_name": "customer_profile_daily",
    "task_type": "Spark SQL",
    "input_tables": ["ods.customer_base"],
    "output_tables": ["mart.customer_profile_snapshot"],
    "upstream_tasks": [
      {"task_id": "task-1001", "task_name": "customer_base_daily"}
    ],
    "downstream_tasks": [],
    "sql": "INSERT OVERWRITE TABLE ..."
  },
  "query_time": "2026-08-02 10:00:00",
  "data_source": "scheduler_api"
}
```

Core 当前消费：

- `meta.task_name`，缺失时依次使用 `meta.task_id` 和文件名；
- `meta.sql`，必须是非空字符串；
- `meta.upstream_tasks`、`meta.downstream_tasks`，写入 `lineage.json.task_dependencies`。

依赖对象会尽量规范化为以下 value：

| 输入 key | 输出位置 | 含义 |
| --- | --- | --- |
| `task_id` | `dependency.task_id` | 调度平台任务 ID。 |
| `task_name` | `dependency.task_name` | 任务显示名。 |
| `project_name` | `dependency.project_name` | 可选项目名。 |
| `task_group` | `dependency.task_group` | 可选任务组。 |
| 表名字段 | `dependency.dependency_table` | 依赖关联的表；字段名由输入适配器识别。 |
| 完整输入对象 | `dependency.raw_record` | 保留原记录，便于追溯，不用于替代规范化字段。 |

其他平台字段可以保留在输入中，但当前不会复制到 Core 输出。旧的顶层
`{"task_name": "...", "sql": "..."}` 格式仍受支持，但没有 `meta` 时不会产生声明式任务依赖。

### 任务目录

```bash
scope-lineage parse --input-dir exported_tasks --out /tmp/lineage
```

Core 递归读取目录内的 `*.json`，并保留源文件的相对父目录。两个输入若在同一相对目录使用相同
任务名，会被视为输出冲突，不会静默覆盖。

## Schema 元数据

`--schema` 接收一个 CSV 或 JSON 文件，用于源字段解析、`SELECT *` 展开，以及字段类型和注释
补全。

推荐 CSV 表头：

```csv
table_name,column_name,column_type,column_comment
ods.customer_base,customer_id,bigint,Synthetic customer identifier
```

`type`/`data_type`/`column_type` 和 `comment`/`column_comment` 是兼容别名。JSON 支持表到字段数组
的简单映射，也支持 `tables[].columns[]` 的详细结构，见
[`examples/metadata/schema_info.json`](../../examples/metadata/schema_info.json)。

Schema 中的 table key 应使用 SQL 可解析的完整表名，例如 `ods.customer_base`。字段 value 至少需要名称；类型和注释可选：

```json
{
  "ods.customer_base": [
    {"name": "customer_id", "type": "bigint", "comment": "Synthetic customer identifier"},
    {"name": "customer_name", "type": "string", "comment": "Synthetic display name"}
  ]
}
```

字段顺序用于 `SELECT *` 展开，因此应与源表实际 Schema 一致。

## 目标表 DDL/Schema 元数据

`--target-ddl-metadata` 接收一个 JSON 文件或目录。目录中每张目标表使用一份 JSON：

```json
{
  "table_name": "mart.customer_snapshot",
  "full_table_name": "spark_catalog.mart.customer_snapshot",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnIndex": 0,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE ...",
  "query_time": "2026-08-02 09:00:00",
  "data_source": "catalog_api"
}
```

DDL 与 Schema 的字段集合必须一致。存在同一表的多份元数据时，Core 使用 `query_time` 或
`ddl_update_time` 选择唯一最新版本；无法排序或结构冲突会明确失败。

关键 key/value：

| Key | Value | 用途 |
| --- | --- | --- |
| `table_name` | `database.table` | 与 SQL 目标表匹配的规范名称。 |
| `full_table_name` | catalog 完整表名 | 保留 catalog 信息并辅助匹配。 |
| `schema[]` | 字段对象数组 | 提供权威字段顺序、类型和分区标记。 |
| `schema[].columnName` | string | 最终目标字段名。 |
| `schema[].columnIndex` | integer | 从 0 开始的权威字段位置。 |
| `schema[].isPartition` | 0/1 或 boolean | 标记分区字段；静态分区不占 SELECT 投影位置。 |
| `ddl` | CREATE TABLE string | DDL 解析成功时优先作为字段权威来源。 |
| `query_time` / `ddl_update_time` | 可排序时间 | 多版本元数据选择依据。 |
| `data_source` | string | 元数据来源标识，便于追溯。 |

## 失败策略

默认情况下，任一输入读取失败或任一语句 `parse_status=failed` 都返回非零退出码。已经成功解析
的其他输入仍会写盘，便于定位批量任务中的局部问题。只有调用方明确接受部分结果时才传入
`--allow-partial`；该选项不会把失败状态改成成功，也不会删除诊断。

## 输入错误与血缘不确定性的区别

- 文件不存在、JSON 无法读取、`meta.sql` 为空：输入错误，CLI 返回失败；
- SQL 语法无法形成支持的写表语句：`parse_status=failed`；
- SQL 可以解析但缺 Schema、alias 或唯一字段来源：可能仍有 Lineage 产物，同时通过 warning、`trace_complete=false` 或 fact gap 表达不确定性；
- `--allow-partial` 只决定批量命令是否因局部失败返回非零，不会提高任何血缘事实的可信度。
