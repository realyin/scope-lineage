# 示例说明

这里的文件都是合成数据，但输入结构和当前生产语料保持一致。示例分成三类：

```text
examples/
├── sql/                    # 直接交给 Core 的 Spark SQL 文件
├── tasks/                  # 调度平台导出的 task JSON（支持递归目录）
└── metadata/
    ├── schema_info.json    # 推荐：字段序号、DDL、类型和注释
    ├── schema_info.csv     # 候补：按行序读取的兼容格式
    └── target_tables/      # 每张目标表一份 DDL/Schema JSON
```

## 覆盖场景

| 示例 | 主要语法与血缘问题 |
| --- | --- |
| `sql/customer_profile_daily.sql` | 多 CTE、JOIN、窗口函数、CASE、聚合、静态分区 |
| `sql/order_channel_metrics.sql` | UNION ALL、多来源归一、聚合、条件指标 |
| `sql/customer_profile_merge.sql` | MERGE、匹配更新、非匹配插入 |
| `sql/select_star_with_schema.sql` | 依赖 Schema 的 `SELECT *` 展开 |
| `sql/multi_statement_publish.sql` | 一个任务内的多条写表语句 |
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
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/corpus
```

任务 JSON 中与解析直接相关的字段是 `meta.task_name`、`meta.sql`、
`meta.upstream_tasks` 和 `meta.downstream_tasks`。其余字段保留在示例中，是为了准确表达真实上游
导出格式；Core 不把负责人、调度周期等平台属性复制进 `lineage.json`。

所有表名、人员、邮箱、项目和 SQL 逻辑均为演示用途，不来自真实业务系统。
