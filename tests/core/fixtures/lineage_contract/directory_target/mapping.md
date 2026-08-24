---
doc_format: "mapping-md/1"
schema_version: "1.0"
task_name: "golden_directory_target"
target_table: "directory:/warehouse/export/daily"
stmt_kind: "INSERT_OVERWRITE"
---

# 字段映射文档 （写入目录 /warehouse/export/daily）

## 1. 概览

- 任务名：golden_directory_target
- 目标：directory:/warehouse/export/daily
- 语句类型：INSERT_OVERWRITE
- 解析状态：ok；语法状态：strict_ok
- 目标绑定：未做（写入文件路径，没有可绑定的目标表）

## 2. 来源表

| 表 | 列数（元数据） | 元数据完整 |
| --- | --- | --- |
| ods.users | 2 | 是 |

## 3. 来源表关系

- 无 JOIN/UNION 关系

## 4. 字段映射总表

| # | 目标字段 | 加工类型 | 来源物理字段 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | user_id | DIRECT | ods.users.user_id | ✓ |
| 2 | user_name | DIRECT | ods.users.user_name | ✓ |

## 5. 加工步骤明细

### 字段 user_id（写入目录 /warehouse/export/daily）

- 来源字段：`ods.users.user_id`
- 加工路径：1 步；direct_projection
- 步骤 1/1：`ods.users.user_id` → `directory:/warehouse/export/daily.user_id`；direct_projection；粒度=preserved；表达式：`` `user_id` ``
- 证据：mapping_chain_id=mc:001；chain=chain:ROOT:user_id:position:0

### 字段 user_name（写入目录 /warehouse/export/daily）

- 来源字段：`ods.users.user_name`
- 加工路径：1 步；direct_projection
- 步骤 1/1：`ods.users.user_name` → `directory:/warehouse/export/daily.user_name`；direct_projection；粒度=preserved；表达式：`` `user_name` ``
- 证据：mapping_chain_id=mc:002；chain=chain:ROOT:user_name:position:1

## 6. 加工逻辑汇总

### scope `ROOT`（root，角色 pass_through）

- 概要：读取 ods.users
- 输入（均为物理表）：ods.users
- 逻辑：join 0、filter 0、聚合 0、窗口 0、union 分支 0、distinct 否

## 7. scope 结构图

- 图例：蓝底=物理表，灰底=scope

```mermaid
flowchart LR
    n0["ROOT"]
    n1["ods.users"]
    n1 --> n0
    classDef default fill:#f4f4f5,stroke:#6b7280,color:#111827
    classDef physical fill:#e8f0fe,stroke:#4a6fa5,color:#111827
    class n1 physical
```

## 8. 任务依赖

- 无声明的任务依赖

## 9. 不确定性与缺口

- 字段追溯：全部完整
- 缺口：无（diagnostics 未记录 lineage_fact_gaps）
- 解析警告：无
