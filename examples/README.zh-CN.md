# 示例说明

这里的文件都是合成数据，但输入结构和当前生产语料保持一致。示例分成三类：

```text
examples/
├── sql/                    # 直接交给 Core 的 Spark SQL 文件
├── tasks/                  # 调度平台导出的 task JSON（支持递归目录）
├── metadata/
    ├── schema_info.json    # 推荐：字段序号、DDL、类型和注释
    ├── schema_info.csv     # 候补：按行序读取的兼容格式
    └── target_tables/      # 每张目标表一份 DDL/Schema JSON
└── sample_data/            # 仅用于讲解样例逻辑的合成 CSV，Core 不读取行数据
```

## 覆盖场景

| 示例 | 主要语法与血缘问题 |
| --- | --- |
| `sql/customer_profile_daily.sql` | 多 CTE、JOIN、窗口函数、CASE、聚合、静态分区 |
| `sql/order_channel_metrics.sql` | UNION ALL、多来源归一、聚合、条件指标 |
| `sql/customer_profile_merge.sql` | MERGE、匹配更新、非匹配插入 |
| `sql/select_star_with_schema.sql` | 依赖 Schema 的 `SELECT *` 展开 |
| `sql/multi_statement_publish.sql` | 一个任务内的多条写表语句 |
| `sql/subscription_account_snapshot.sql` | 19 张源表、20 个 JOIN、多层子查询、条件聚合、窗口函数和 112 个目标字段的复杂脱敏样例 |
| `tasks/**/*.json` | 真实 `meta/query_time/data_source` 包装、任务依赖和目录批量输入 |

## 运行

解析一个裸 SQL：

```bash
scope-lineage parse \
  --sql-file examples/sql/customer_profile_daily.sql \
  --schema examples/metadata/schema_info.json \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/sql
```

解析一个调度任务 JSON：

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.json \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/task
```

递归解析整个任务目录：

```bash
scope-lineage parse \
  --input-dir examples/tasks \
  --schema examples/metadata/schema_info.json \
  --schema-fallback examples/metadata/subscription_account_snapshot/source_tables \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/corpus
```

解析复杂的订阅计费账户快照样例：

```bash
scope-lineage parse \
  --task-file examples/tasks/subscription/subscription_account_snapshot.json \
  --schema examples/metadata/subscription_account_snapshot/source_tables \
  --schema-fallback examples/metadata/target_tables/demo_mart.subscription_account_snapshot_metadata.json \
  --target-ddl-metadata examples/metadata/target_tables/demo_mart.subscription_account_snapshot_metadata.json \
  --contract-version 2.0 \
  --out /tmp/scope-lineage/subscription-account
```

对应的合成行数据位于 `examples/sample_data/subscription_account_snapshot/`。它们用于
后续文档解释费用分类、两级聚合和最终指标计算，不是 Core 静态解析的运行时输入。

任务 JSON 中与解析直接相关的字段是 `meta.task_name`、`meta.sql`、
`meta.upstream_tasks` 和 `meta.downstream_tasks`。其余字段保留在示例中，是为了准确表达真实上游
导出格式；Core 不把负责人、调度周期等平台属性复制进 `lineage.json`。

所有公开资产都是完全合成，或经过结构保真脱敏后的演示内容；不包含真实表名、字段名、行数据、
人员、邮箱、项目或本地路径。
