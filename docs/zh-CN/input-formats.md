[English](../en/input-formats.md) | 中文

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
同一个任务目录：各写语句作为 `statement_lineage` 的 `stmt:NNN` 条目记录在一份 lineage.json 中。

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
- `meta.upstream_tasks`、`meta.downstream_tasks`，写入 `lineage.json.task_dependencies`；
- `meta.task_id`、`meta.task_name`、`meta.project_name`（缺失时 `meta.project_code`）、`meta.owner`、
  `meta.schedule`、`meta.schedule_cycle`、`meta.description`、`meta.expect_date`，以中立键名写入
  `lineage.json.task_meta`（契约 2.0 顶层），值全部转成字符串、空白转 `null`；
  `meta.upstream_tasks`、`meta.downstream_tasks` 另以任务名数组写入同一个 `task_meta`（B4，去重保序，
  空列表不发布），与写入 `task_dependencies` 的是同一份登记，只是那里保留完整记录。

**`meta.owner_email` 按名排除，不进入任何产物。** 它是个人联系方式，对数据没有解释力，而产物会在系统之间
流转；需要联系人时请回到任务系统。未列出的 `meta` 键（如 `instance_id`、`project_dir`）同样被忽略，
导出方加字段不会连带加宽契约。完整键表见 [task-lineage-v2.md](task-lineage-v2.md)。

`.sql` 输入没有 `meta`，产物里因此**没有** `task_meta` 键——缺席表示没有输入提供元信息，而不是这个任务
没有负责人或调度。

`meta.description` 是其中唯一的自由文本，人写它的方式和写注释一样，**默认按与 SQL 注释同一套规则做联系方式遮蔽**：
邮箱替换为 `<email>`、手机号替换为 `<phone>`、身份证号替换为 `<id>`，句子其余部分原样保留；其余各项是导出方产出的
标识、名称和调度表达式，不做改写。`--schema` / `--target-ddl-metadata` 读进来的列注释与表级文字走同一套遮蔽
（E1）——列注释同样是人写的自由文本。`parse --no-redact-comments` 同时关闭 description、元数据注释与 SQL 注释的
遮蔽，`parse --strip-comments` 只丢弃 SQL 注释、不影响 `task_meta` 与元数据注释。遮蔽是形态匹配，不保证穷尽——细则见
[lineage-json.md](lineage-json.md) §18.3。

最终采用的任务名也会成为输出目录的一个组件。任务名可以含空格和 Unicode，但绝对路径、`.`、
`..`、NUL、`/`、`\` 会被拒绝，不会被当成路径解释。依赖证据里的 `source_file` 在单文件模式下
只记录输入文件名，在目录模式下记录相对 `--input-dir` 的 POSIX 风格路径，绝不会写入调用方的
本机绝对路径。

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

若导出目录有意混放其他 JSON，应显式筛选，不要让非任务文件拖成批次失败，也不要猜它的结构：

```bash
scope-lineage parse \
  --input-dir exported_tasks \
  --include-glob '*_info.json' \
  --exclude-glob '*_archived_info.json' \
  --out /tmp/lineage
```

两个 glob 参数都可重复，只对 `--input-dir` 生效。不传时仍递归处理全部 `*.json`，保留“错误可见”
的默认行为。

`--input-dir` 本身也可重复：一份语料分散在多棵树下时，一次运行全部读入。

```bash
scope-lineage parse \
  --input-dir exported_tasks/domain_a \
  --input-dir exported_tasks/domain_b \
  --out /tmp/lineage
```

各目录按给出的顺序遍历；同一个文件被多个目录同时命中（父目录与其子目录、或同一棵树的两种写法）
只解析一次，归属第一个命中它的目录。glob 对每个目录分别生效。每个文件的相对父目录是相对**它
自己那个** `--input-dir` 算的，`task_dependencies[].source_file` 也一样——所以两棵树里同名的相对
路径仍然会按输出冲突处理，而不是静默覆盖。

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
  "table_alias": "Customer base table",
  "table_desc": "Synthetic customer master detail",
  "buzi_domain": "Customer",
  "project_name": "Customer profile",
  "owner_name": "demo_owner",
  "data_level": "ODS",
  "is_partition": 1,
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

表级键也会被读取，归一化成 `table_metadata`（`table_name_cn`、`table_desc`、`domain`、
`domain_path`、`project`、`project_code`、`owner`、`table_label_layer`、`physical_type`、
`is_partitioned`），随契约的 `related_metadata.*.table_metadata` 输出，并支撑 semantic 的
输入表注释与表卡的"这张表是什么"。键名中立：`table_alias`/`table_comment`/`comment` 都可以给
出中文表名，`buzi_domain`/`domain` 都可以给出业务域。含 `@` 的值（邮箱，例如 `tbl_pic`）在加载
时被丢弃，时间戳与质量率不进表级事实。完整键表见
[`lineage.json` §12.2](lineage-json.md#122-related_metadata)。

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

## 元数据补丁（metadata-patch/1）

`--metadata-patch` 接收一份**人工确认过的**注释补丁（可重复，后面的文件覆盖前面的）。它是
待确认清单的回写终点：业务方答了"这个字段是什么意思"，而团队又写不进数仓的 catalog 时，
答案落在这份本地文件里，而不是丢失在一份 markdown 里。**它不修改任何源元数据文件。**

```json
{
  "doc_format": "metadata-patch/1",
  "tables": {
    "mart.order_daily": {
      "table_name_cn": "订单日汇总",
      "table_desc": "每个渠道每天一行",
      "confirmed_by": "owner",
      "date": "2026-09-19"
    }
  },
  "columns": {
    "mart.order_daily.pay_status": {
      "comment": "支付状态",
      "confirmed_by": "owner",
      "date": "2026-09-19"
    }
  }
}
```

| Key | Value | 用途 |
| --- | --- | --- |
| `doc_format` | `metadata-patch/1` | 可省略；写了就必须是这个值，否则退出码 2。 |
| `tables` | `{"db.table": {…}}` | 表级事实，键名与富 JSON 元数据同一套（`table_name_cn`、`table_desc`、`domain` …），并进 `table_metadata`。 |
| `columns` | `{"db.table.column": {…}}` | 列注释；只认三段式的键，`表.列` 两段式不收（无法区分表名与列名，猜错就是把注释写到别处）。 |
| `confirmed_by` / `date` | string | 谁在哪天确认的；原样保留在补丁文件里，供复核。 |

规则：

- **补丁优先**：同一列同时有 schema 注释与补丁注释时，产物里是补丁的那条；
- **只改注释，不改结构**：补丁不带类型、不增列——列宽是数仓的事实，`SELECT *` 靠它展开；
- **带标记**：被写过的列多 `comment_source: "patch"`，被写过的表多 `table_metadata.patch_applied: true`；
- **注释同样遮蔽**：补丁里的列注释与 `table_name_cn` / `table_desc` 在读入时就过一遍与 schema 注释相同的遮蔽（`<email>` / `<phone>` / `<id>`），`parse --no-redact-comments` 一并关掉；
- **表名匹配**与 schema 一致：大小写不敏感，`catalog.db.table` 与 `db.table` 是同一张表；
- **没命中的键只报告不报错**：运行结束打印 `unmatched=N` 并列出键，拼错的键不会被静默吞掉；
- 文件不存在、不是合法 JSON、顶层不是对象、或 `doc_format` 是别的值时退出码为 2。

`describe --metadata-patch` 接收同一份文件，对已经写好的 `lineage.json` 在内存里做同样的覆盖
再派生视图——不重跑 parse 也能看到答案落地，磁盘上的产物不会被改写。两条路径产出同一份
`semantic.json`（含 `lineage_digest`）。回写文件怎么从画像生成，见
[术语与值域字典](glossary-doc.md)。

## 列样例值（samples/1）

`scope-lineage tables --samples` 接一份**别人导出的**列样例值，Core 自己永远不连数据库取数。
一份表头为 `table,column,value[,count]` 的 CSV、一个装着这种 CSV 的目录，或一份 `samples/1`
JSON 都可以：

```csv
table,column,value,count
mart.customer_daily,country_code,US,30
mart.customer_daily,country_code,JP,20
```

```json
{
  "doc_format": "samples/1",
  "samples": [
    {"table": "mart.customer_daily", "column": "country_code", "values": ["US", "JP"]}
  ]
}
```

| Key | Value | 用途 |
| --- | --- | --- |
| `table` | `db.table` 或全限定名 | 按表卡的规则匹配：取最后两段、忽略大小写。 |
| `column` | 列名 | 忽略大小写；表或列在语料里不存在时进 `samples_applied.unmatched[]`。 |
| `value` | 任意标量 | 去首尾空白后脱敏、超过 64 字符截断；空值跳过。 |
| `count` | 整数，可省 | 给了就按它从大到小排；整列都没给就按文件顺序。 |

规则：

- **一定脱敏**：邮箱、手机／国际号码、身份证号按形状掩码，与 SQL 注释同一套规则，**没有关掉
  它的开关**——样例值是本工具见过的最容易带个人信息的输入；
- **每列最多 N 个不同的值**：默认 5，`--samples-top` 可改；
- **没命中的键只报告不报错**：运行结束打印 `samples_unmatched=N` 并列出 `表.列`；
- 文件不存在、CSV 表头不对、JSON 不是 `samples/1`、`count` 不是整数时退出码为 2。

产物里对应 `columns[].samples[]`、`coverage.columns_sampled` 与顶层 `samples_applied`，
详见[表卡文档](tables-doc.md)。

## 失败策略

默认情况下，任一输入读取失败或任一语句 `parse_status=failed` 都返回非零退出码。已经成功解析
的其他输入仍会写盘，便于定位批量任务中的局部问题。只有调用方明确接受部分结果时才传入
`--allow-partial`；该选项不会把失败状态改成成功，也不会删除诊断。

## 输入错误与血缘不确定性的区别

- 文件不存在、JSON 无法读取、`meta.sql` 为空：输入错误，CLI 返回失败；
- SQL 语法无法形成支持的写表语句：`parse_status=failed`；
- SQL 可以解析但缺 Schema、alias 或唯一字段来源：可能仍有 Lineage 产物，同时通过 warning、`trace_complete=false` 或 fact gap 表达不确定性；
- `--allow-partial` 只决定批量命令是否因局部失败返回非零，不会提高任何血缘事实的可信度。
