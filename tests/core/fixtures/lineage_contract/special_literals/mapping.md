---
doc_format: "mapping-md/1"
schema_version: "1.0"
task_name: "golden_special_literals"
target_table: "mart.flags"
stmt_kind: "INSERT"
---

# 字段映射文档 mart.flags

## 1. 概览

- 任务名：golden_special_literals
- 目标：mart.flags
- 语句类型：INSERT
- 解析状态：ok；语法状态：strict_ok
- 目标绑定：未做目标绑定（文档无 target_field_binding：MERGE、缺目标 DDL 或目录写入等场景）

## 2. 来源表

| 表 | 列数（元数据） | 元数据完整 |
| --- | --- | --- |
| ods.users | 1 | 是 |

## 3. 来源表关系

- 无 JOIN/UNION 关系

## 4. 字段映射总表

| # | 目标字段 | 加工类型 | 来源物理字段 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | flagged | CONDITIONAL | ods.users.name | ✓ |

## 5. 加工步骤明细

### 字段 mart.flags.flagged

- 来源字段：`ods.users.name`
- 加工路径：1 步；case_when
- 步骤 1/1：`ods.users.name` → `mart.flags.flagged`；case_when；表达式：`` CASE WHEN `name` = 'x；y → z|w' THEN 'a\nb' ELSE `name` END ``
- 证据：mapping_chain_id=mc:001；chain=chain:ROOT:flagged:position:0

## 6. 加工逻辑汇总

### scope `ROOT`（root，角色 transform）

- 概要：读取 ods.users；通过 CASE WHEN 派生字段
- 输入：ods.users；物理上游：ods.users
- 逻辑：join 0、filter 0、聚合 0、窗口 0、union 分支 0、distinct 否

## 7. scope 结构图

```mermaid
flowchart LR
    n0["ROOT"]
    n1["ods.users"]
    n1 --> n0
    classDef physical fill:#e8f0fe,stroke:#4a6fa5
    class n1 physical
```

## 8. 任务依赖

- 无声明的任务依赖

## 9. 不确定性与缺口

- 字段追溯：全部完整
- 缺口：无（diagnostics 未记录 lineage_fact_gaps）
- 解析警告：无
