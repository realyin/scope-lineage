---
doc_format: "mapping-md/1"
schema_version: "1.0"
task_name: "golden_syntax_recovered"
target_table: "mart.recovered"
stmt_kind: "INSERT"
---

# 字段映射文档 mart.recovered

## 1. 概览

- 任务名：golden_syntax_recovered
- 目标：mart.recovered
- 语句类型：INSERT
- 解析状态：ok；语法状态：recovered
- 语法错误：2 条（详见 lineage.json 的 syntax_errors）
- 目标绑定：未做目标绑定（文档无 target_field_binding：MERGE、缺目标 DDL 或目录写入等场景）

## 2. 来源表

| 表 | 列数（元数据） | 元数据完整 |
| --- | --- | --- |
| ods.events | 1 | 是 |

## 3. 来源表关系

- 无 JOIN/UNION 关系

## 4. 字段映射总表

| # | 目标字段 | 加工类型 | 来源物理字段 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | id | DIRECT | ods.events.id | ✓ |

## 5. 加工步骤明细

### 字段 mart.recovered.id

- 来源字段：`ods.events.id`
- 加工路径：1 步；direct_projection
- 步骤 1/1：`ods.events.id` → `mart.recovered.id`；direct_projection；表达式：`` `id` ``
- 证据：mapping_chain_id=mc:001；chain=chain:ROOT:id:position:0

## 6. 加工逻辑汇总

### scope `ROOT`（root，角色 filter）

- 概要：读取 ods.events；按过滤条件保留记录
- 输入：ods.events；物理上游：ods.events
- 逻辑：join 0、filter 1、聚合 0、窗口 0、union 分支 0、distinct 否
  - 过滤：`` WHERE `events`.`id` > 0 ``

## 7. scope 结构图

```mermaid
flowchart LR
    n0["ROOT"]
    n1["ods.events"]
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
