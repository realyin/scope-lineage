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
| catalog 前缀配置 | 否 | `target_table`、`source_tables`、物理字段来源中的表身份 | 默认保留 SQL 中的完整 catalog 表名。 |

输入越完整，Core 能证明的字段事实越多；但元数据不会覆盖 SQL 事实。例如 Schema 可以说明表有哪些列，不能替代 SQL 中实际使用的 JOIN、过滤和表达式。

多个来源可以按权威顺序组合：

~~~bash
scope-lineage parse \
  --input-dir exported_tasks \
  --schema rich-table-metadata \
  --schema-fallback schema_info.csv \
  --out /tmp/lineage
~~~

`--schema-fallback` 可重复。它只补充权威 `--schema` 中缺失的表；同表字段定义冲突时不会静默
合并或覆盖 DDL 顺序，v2 会在 `diagnostics.json.metadata_coverage.metadata_conflicts` 中记录。

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

## catalog 前缀配置

Spark/Hive 环境可能用三段表名 `catalog.database.table`。Core 默认保留完整名称，因为无法仅凭
三段结构安全判断第一段究竟是 catalog，还是业务命名的一部分。

如果确认以下两种写法表示同一张物理表：

```text
warehouse_catalog.ods.customer_base
ods.customer_base
```

可以在本次命令中声明允许剥离的首段 catalog：

```bash
scope-lineage parse \
  --input-dir exported_tasks \
  --catalog-prefixes warehouse_catalog,spark_catalog \
  --out /tmp/lineage
```

固定部署环境或 Python API 调用可以使用环境变量：

```bash
export SCOPE_LINEAGE_CATALOG_PREFIXES="warehouse_catalog,spark_catalog"
```

配置优先级和行为如下：

| 配置 | 行为 |
| --- | --- |
| 传入 `--catalog-prefixes` | 使用命令行逗号分隔列表，并覆盖环境变量。 |
| 未传命令行参数，但设置环境变量 | 使用 `SCOPE_LINEAGE_CATALOG_PREFIXES`。 |
| 两者均未设置 | 不剥离任何 catalog，保留 SQL 中的完整表名。 |
| 显式传入空字符串 | 使用空列表，即本次运行不剥离 catalog。 |

例如配置 `warehouse_catalog` 后，`lineage.json` 中的表身份会统一为：

```json
{
  "source_tables": ["ods.customer_base"],
  "end_to_end_lineage": [
    {
      "physical_sources": [
        {"table": "ods.customer_base", "column": "customer_id"}
      ]
    }
  ]
}
```

注意：

- 只配置确认属于 catalog 的首段名称，不要配置 `ods`、`dwd` 等 database 名；
- 同一批输出必须使用同一策略，否则同一物理表可能产生两个身份；
- 这是部署/批次级解析策略，不是某个 SQL 任务的业务属性，因此不放进任务 JSON；
- Schema 和目标表元数据仍可以填写完整表名，但它们不会替代本配置来决定 Lineage 中是否保留 catalog。

## 源表 Schema 元数据

`--schema` 接收一个 JSON/CSV 文件，也可以接收一个包含富 JSON 的目录，用于源字段解析、
`SELECT *` 展开，以及字段类型和注释补全。推荐使用带字段序号和 DDL 的富 JSON；CSV 仅作为
兼容候补。

### 推荐：带 Schema 和 DDL 的 JSON

每张表一份 JSON；传目录时会读取目录中的表元数据文件并按版本时间选择每张表的最新版本：

```json
{
  "table_name": "ods.customer_base",
  "full_table_name": "spark_catalog.ods.customer_base",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnComment": "Synthetic customer identifier",
      "columnIndex": 0,
      "isPartition": 0
    },
    {
      "columnName": "customer_name",
      "columnType": "string",
      "columnComment": "Synthetic display name",
      "columnIndex": 1,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE spark_catalog.ods.customer_base (customer_id BIGINT, customer_name STRING) USING iceberg",
  "query_time": "2026-08-14 10:00:00",
  "data_source": "catalog_api"
}
```

源表顺序按以下层级确定：

1. `ddl` 能成功解析时，DDL 字段顺序优先；
2. 没有 DDL 时，按 `schema[].columnIndex` 排序，序号必须从 0 开始且连续；
3. 富 JSON 的结构无效时直接报元数据错误，不会静默退回猜测顺序。

`--schema` 还兼容聚合式轻量 JSON。它没有显式字段序号或 DDL，`columns[]` 数组顺序就是字段
顺序：

```json
{
  "tables": [
    {
      "table_name": "ods.customer_base",
      "columns": [
        {"name": "customer_id", "type": "bigint"},
        {"name": "customer_name", "type": "string"}
      ]
    }
  ]
}
```

字段 value 至少需要 `name`；`type` 和 `comment` 可选。Schema 中的 table key 应使用 SQL
可解析的完整表名，例如 `ods.customer_base`。轻量 JSON 还兼容下面的简写：

```json
{
  "ods.customer_base": [
    {"name": "customer_id", "type": "bigint"},
    {"name": "customer_name", "type": "string"}
  ]
}
```

完整富 JSON 多表示例见
[`examples/metadata/schema_info.json`](../../examples/metadata/schema_info.json)。

### 候补：CSV

兼容 CSV 表头：

```csv
table_name,column_name,column_type,column_comment
ods.customer_base,customer_id,bigint,Synthetic customer identifier
ods.customer_base,customer_name,string,Synthetic display name
```

`type`/`data_type`/`column_type` 和 `comment`/`column_comment` 是兼容别名。同一张表在 CSV
中的行序会被当作字段顺序，所以它仍能展开 `SELECT *`；但 CSV 没有显式 `columnIndex`，也没有
DDL 交叉校验。只有导出端能够保证行序时才应依赖这一能力。

富 JSON 的结构与 `--target-ddl-metadata` 相同，所以同一个包含全部表元数据的目录可以同时传给
两个参数。`--schema` 将其中的表作为源字段候选；`--target-ddl-metadata` 只对当前 SQL 的目标表
执行权威位置绑定。

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

目标结构的优先级如下：

1. `ddl` 能成功解析时，以 DDL 中的字段顺序和分区定义为权威事实；
2. `schema[]` 按字段名与 DDL 交叉校验，并补充类型、注释和显式位置；
3. 没有 DDL 时，按 `schema[].columnIndex` 排序，序号必须从 0 开始且连续；
4. CSV 不支持目标表权威绑定，只能作为源表 `--schema` 的候补格式。

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
