# Core 输入格式

Scope Lineage Core 接收 SQL 内容以及两类可选元数据。它不会连接调度平台或元数据平台；调用方
负责导出文件，Core 负责将文件规范化后解析成版本化事实。

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

## 失败策略

默认情况下，任一输入读取失败或任一语句 `parse_status=failed` 都返回非零退出码。已经成功解析
的其他输入仍会写盘，便于定位批量任务中的局部问题。只有调用方明确接受部分结果时才传入
`--allow-partial`；该选项不会把失败状态改成成功，也不会删除诊断。
