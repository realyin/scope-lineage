---
doc_format: "mapping-md/1"
schema_version: "1.0"
task_name: "merge_contract"
target_table: "mart.customer_profile"
stmt_kind: "MERGE"
lineage_digest: "91ab5598676973ee"
---

# 字段映射文档 mart.customer_profile

## 1. 概览

- 任务名：merge_contract
- 目标：mart.customer_profile
- 语句类型：MERGE
- 解析状态：ok；语法状态：strict_ok
- 目标绑定：未做（MERGE 在绑定机制之外解析目标列）

## 2. 来源表

| 表 | 表列数（元数据） | 使用列数 | 元数据完整 |
| --- | --- | --- | --- |
| ods.customer_delta | 2 | 2 | 是 |

## 3. 来源表关系

- 无 JOIN/UNION 关系

## 4. 字段映射总表

| # | 目标字段 | 加工类型 | 来源物理字段 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | customer_name | DIRECT | ods.customer_delta.customer_name | ✓ |
| 2 | customer_id | DIRECT | ods.customer_delta.customer_id | ✓ |
| 3 | customer_name | DIRECT | ods.customer_delta.customer_name | ✓ |

## 5. 加工步骤明细

### 字段 mart.customer_profile.customer_name（merge:matched 分支 0）

- 来源字段：`ods.customer_delta.customer_name`
- 加工路径：2 步；direct_projection
- 步骤 1/2：`ods.customer_delta.customer_name` → `subq:source.customer_name`；direct_projection；粒度=preserved；表达式：`` `customer_name` ``
- 步骤 2/2：`subq:source.customer_name` → `mart.customer_profile.customer_name`；direct_projection；粒度=preserved；表达式：`` `customer_name` ``
- 证据：mapping_chain_id=mc:001；chain=chain:ROOT:customer_name:position:0

### 字段 mart.customer_profile.customer_id（merge:not_matched 分支 1）

- 来源字段：`ods.customer_delta.customer_id`
- 加工路径：2 步；direct_projection
- 步骤 1/2：`ods.customer_delta.customer_id` → `subq:source.customer_id`；direct_projection；粒度=preserved；表达式：`` `customer_id` ``
- 步骤 2/2：`subq:source.customer_id` → `mart.customer_profile.customer_id`；direct_projection；粒度=preserved；表达式：`` `customer_id` ``
- 证据：mapping_chain_id=mc:002；chain=chain:ROOT:customer_id:position:1

### 字段 mart.customer_profile.customer_name（merge:not_matched 分支 1）

- 来源字段：`ods.customer_delta.customer_name`
- 加工路径：2 步；direct_projection
- 步骤 1/2：`ods.customer_delta.customer_name` → `subq:source.customer_name`；direct_projection；粒度=preserved；表达式：`` `customer_name` ``
- 步骤 2/2：`subq:source.customer_name` → `mart.customer_profile.customer_name`；direct_projection；粒度=preserved；表达式：`` `customer_name` ``
- 证据：mapping_chain_id=mc:003；chain=chain:ROOT:customer_name:position:2

## 6. 加工逻辑汇总

### scope `ROOT`（root，角色 pass_through）

- 概要：基于 subq:source；上游可追溯至 ods.customer_delta
- 输入：subq:source；物理上游：ods.customer_delta
- 逻辑：join 0、filter 0、聚合 0、窗口 0、union 分支 0、distinct 否

## 7. scope 结构图

- 图例：蓝底=物理表，灰底=scope

```mermaid
flowchart LR
    n0["ROOT"]
    n1["ods.customer_delta"]
    n2["subq:source"]
    n1 --> n2
    n2 --> n0
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
