---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_grouped_dedup_join"
target_table: "mart.metric_by_segment"
stmt_kind: "INSERT_OVERWRITE"
lineage_digest: "4e323ab37f990b59"
---

# 任务语义描述 mart.metric_by_segment

## 1. 任务概览

- 目标表：`mart.metric_by_segment`（表注释：注释未知）（元数据事实）
- 语句类型：INSERT_OVERWRITE；静态分区 dt = `20260101`（SQL事实）
- 目标表元数据来源：target_ddl（元数据事实）
- 结构摘要：ROOT 不直接读取物理表；关联 1 个上游（1 个去重）；输出 6 列。（结构推断；证据 scope_profile）

共 3 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `dim.segment_dim` | 注释未知 | 去重来源（dedup_source） | 3 / 3 | 完整 | `cte:latest_dim` |
| `ods.events_a` | 注释未知 | 主表（driving） | 2 / 2 | 完整 | `union:events_norm:b01` |
| `ods.events_b` | 注释未知 | 主表（driving） | 2 / 2 | 完整 | `union:events_norm:b02` |

## 2. 输出表形态与粒度

- 形态：过滤投影型（filtered_projection）（结构推断；证据 ROOT）
- 粒度：一行对应一组 `cte:agg.segment`、`cte:agg.band`（物理来源：`ods.events_a.segment`、`ods.events_b.seg_code`、`ods.events_a.amount`、`ods.events_b.amount`）（依据 GROUP BY 键，basis=group_by，经 `cte:ranked` → `cte:joined` 穿透）（结构推断；证据 logic:cte:agg:group_by:001）
- 键：目标表列 `segment`、`band`——由 GROUP BY 键保证输出内唯一（分区内）（key_confidence=proven）（结构推断）
- 分区列：`dt`；分区列不计入候选键（元数据事实）
- 行数放大风险：
  - `cte:joined` 中的 LEFT_OUTER JOIN `cte:latest_dim`：安全（safe）——右侧 row_number 按 segment 分区并以 = 1 过滤（logic:cte:joined:join:001）（结构推断；证据 logic:cte:joined:join:001）

## 3. 加工链路

共 9 个阶段，按拓扑序逐个展开。

### 阶段 1：latest_dim（`cte:latest_dim`，角色 dedup）

- 直接输入：`dim.segment_dim`（SQL事实）
- 直接读取物理表：`dim.segment_dim`（SQL事实）
- 动作：
  - 窗口（意图 keep_latest_per_group）：按 segment 分组，按 updated_at 降序编号（rn）；cte:joined 以 rn = 1 消费，即每组保留最新一条（结构推断；证据 logic:cte:latest_dim:window:001, logic:cte:joined:join:001）
- 输出：3 列（`segment`、`segment_name`、`rn`）（SQL事实）

### 阶段 2：events_norm:b01（`union:events_norm:b01`，角色 union_branch）

- 直接输入：`ods.events_a`（SQL事实）
- 直接读取物理表：`ods.events_a`（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：3 列（`segment`、`amount`、`branch_tag`）（SQL事实）

### 阶段 3：events_norm:b02（`union:events_norm:b02`，角色 union_branch）

- 直接输入：`ods.events_b`（SQL事实）
- 直接读取物理表：`ods.events_b`（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：3 列（`segment`、`amount`、`branch_tag`）（SQL事实）

### 阶段 4：events_norm（`union:events_norm`，角色 union）

- 直接输入：`union:events_norm:b01`、`union:events_norm:b02`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 上游物理表（来源边界）：`ods.events_a`、`ods.events_b`（SQL事实）
- 动作：
  - 合并：合并 2 个分支（来自 ods.events_a、ods.events_b）（SQL事实；证据 union:events_norm）
- 输出：3 列（`segment`、`amount`、`branch_tag`）（SQL事实）

### 阶段 5：events_norm（`cte:events_norm`，角色 transform）

- 直接输入：`union:events_norm`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：3 列（`segment`、`amount`、`branch_tag`）（SQL事实）

### 阶段 6：agg（`cte:agg`，角色 aggregate）

- 直接输入：`cte:events_norm`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：
  - 聚合：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 分组聚合：SUM(amount)、COUNT(1)（SQL事实；证据 logic:cte:agg:group_by:001）
  - 条件派生：派生 band：amount >= 100 → 'HIGH'；否则 'LOW'（SQL事实；证据 logic:cte:agg:case_when:001）
- 输出：4 列（`segment`、`band`、`total`、`cnt`）（SQL事实）

### 阶段 7：joined（`cte:joined`，角色 join）

- 直接输入：`cte:agg`、`cte:latest_dim`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 上游物理表（来源边界）：`dim.segment_dim`、`ods.events_a`、`ods.events_b`（SQL事实）
- 动作：
  - 关联：LEFT_OUTER 关联 cte:latest_dim，键 segment，附加条件 `d`.`rn` = 1，右侧无匹配时保留左行，右侧字段为空（SQL事实；证据 logic:cte:joined:join:001）
- 输出：5 列（`segment`、`band`、`total`、`cnt`、`segment_name`）（SQL事实）

### 阶段 8：ranked（`cte:ranked`，角色 dedup）

- 直接输入：`cte:joined`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：
  - 窗口（意图 running_aggregate）：按 band 分组，计算 SUM（band_total）；组内累计聚合（结构推断；证据 logic:cte:ranked:window:001）
- 输出：6 列（`segment`、`band`、`total`、`cnt`、`segment_name`、`band_total`）（SQL事实）

### 阶段 9：ROOT（`ROOT`，角色 pass_through）

- 直接输入：`cte:ranked`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：6 列（`segment`、`band`、`total`、`cnt`、`band_total`、`segment_name`）（SQL事实）

## 4. 规则清单

共 2 条规则（CASE 分支 1 条、连接条件 1 条）；条件为 SQL 原文，字段注释为元数据事实。

| 规则 | 类型 | 阶段 | 条件 | 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rule:001 | CASE 分支（case_branch） | `cte:agg` | `amount >= 100 → 'HIGH'；否则 'LOW'` | `cte:events_norm.amount`（scope 内部列） | — | — | `logic:cte:agg:case_when:001` |
| rule:002 | 连接条件（join_condition） | `cte:joined` | `` `a`.`segment` = `d`.`segment` AND `d`.`rn` = 1 `` | `ods.events_a.segment`（注释未知）、`dim.segment_dim.segment`（注释未知）、`ods.events_b.seg_code`（注释未知）、`dim.segment_dim.updated_at`（注释未知）（经生成列）、`cte:agg.segment`（scope 内部列）、`cte:latest_dim.segment`（scope 内部列）、`cte:latest_dim.rn`（scope 内部列） | — | — | `logic:cte:joined:join:001` |

## 5. 字段语义

共 6 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.metric_by_segment.segment` | Segment code：直接取自 ods.events_a.segment（注释未知）、ods.events_b.seg_code（注释未知） | candidate_key | — | ✓ |
| 2 | `mart.metric_by_segment.band` | Amount band：amount >= 100 → 'HIGH'；否则 'LOW'；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知） | candidate_key | — | ✓ |
| 3 | `mart.metric_by_segment.total` | Summed amount：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知） | measure | SUM(amount)；未在聚合路径上发现日期过滤 | ✓ |
| 4 | `mart.metric_by_segment.cnt` | Row count：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：COUNT(1) | measure | COUNT(1)；未在聚合路径上发现日期过滤 | ✓ |
| 5 | `mart.metric_by_segment.band_total` | Band level total：amount >= 100 → 'HIGH'；否则 'LOW'，再按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)，再窗口函数 SUM(total)；按 band 分组；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知） | conditional_label | SUM(amount)；未在聚合路径上发现日期过滤 | ✓ |
| 6 | `mart.metric_by_segment.segment_name` | Segment display name：直接取自 dim.segment_dim.segment_name（注释未知）（关联未命中时为空） | attribute | — | ✓ |

### 字段 mart.metric_by_segment.segment

- 语义：Segment code：直接取自 ods.events_a.segment（注释未知）、ods.events_b.seg_code（注释未知）
- 目标注释：Segment code（元数据事实）
- 类型：string（元数据事实）
- 来源：`ods.events_a.segment`（注释未知）、`ods.events_b.seg_code`（注释未知）（SQL事实）
- 结构角色：candidate_key（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 第 1–2/8 步：各分支直接透传（经 `union:events_norm:b01`、`union:events_norm:b02`）；粒度=preserved（SQL事实）
  - 步骤 3/8 @ `union:events_norm`（union）：合并 2 个分支（来自 union:events_norm:b01.segment、union:events_norm:b02.segment）；粒度=preserved（SQL事实）
  - 第 4–8/8 步：直接透传（经 `cte:events_norm` → `cte:agg` → `cte:joined` → `cte:ranked` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `ranked`.`segment` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.metric_by_segment.band

- 语义：Amount band：amount >= 100 → 'HIGH'；否则 'LOW'；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知）
- 取值：'HIGH'（待确认）、'LOW'（待确认）（该列取值已被 SQL 证明封闭）（SQL事实；证据 rule:001）
- 目标注释：Amount band（元数据事实）
- 类型：string（元数据事实）
- 来源：`ods.events_a.amount`（注释未知）、`ods.events_b.amount`（注释未知）（SQL事实）
- 结构角色：candidate_key（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 第 1–2/8 步：各分支直接透传（经 `union:events_norm:b01`、`union:events_norm:b02`）；粒度=preserved（SQL事实）
  - 步骤 3/8 @ `union:events_norm`（union）：合并 2 个分支（来自 union:events_norm:b01.amount、union:events_norm:b02.amount）；粒度=preserved（SQL事实）
  - 步骤 4/8 @ `cte:events_norm`（union）：合并 1 个分支（来自 union:events_norm.amount）；粒度=preserved（SQL事实）
  - 步骤 5/8 @ `cte:agg`（case_when）：amount >= 100 → 'HIGH'；否则 'LOW'；粒度=preserved（SQL事实）
  - 第 6–8/8 步：直接透传（经 `cte:joined` → `cte:ranked` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `ranked`.`band` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

### 字段 mart.metric_by_segment.total

- 语义：Summed amount：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知）
- 口径：
  - 统计对象：`ods.events_a`、`ods.events_b` 的记录（聚合于 `cte:agg`）
  - 时间范围：未在聚合路径上发现日期过滤
  - 纳入条件：无
  - 聚合：按 segment、band 汇总 SUM(amount)（分组键落目标列 `segment`、`band`）
  - 单位/类型：decimal(18,2)；单位未知
  - 空值：无可证明的关联致空，未见缺失回填
  - 更新频率：未知（任务元信息未提供）
- 目标注释：Summed amount（元数据事实）
- 类型：decimal(18,2)（元数据事实）
- 来源：`ods.events_a.amount`（注释未知）、`ods.events_b.amount`（注释未知）（SQL事实）
- 结构角色：measure（末步变换 DIRECT）（结构推断；证据 mc:003）
- 加工步骤：
  - 第 1–2/8 步：各分支直接透传（经 `union:events_norm:b01`、`union:events_norm:b02`）；粒度=preserved（SQL事实）
  - 步骤 3/8 @ `union:events_norm`（union）：合并 2 个分支（来自 union:events_norm:b01.amount、union:events_norm:b02.amount）；粒度=preserved（SQL事实）
  - 步骤 4/8 @ `cte:events_norm`（union）：合并 1 个分支（来自 union:events_norm.amount）；粒度=preserved（SQL事实）
  - 步骤 5/8 @ `cte:agg`（aggregate）：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)；粒度=changed（SQL事实）
  - 第 6–8/8 步：直接透传（经 `cte:joined` → `cte:ranked` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `ranked`.`total` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:003（SQL事实）

### 字段 mart.metric_by_segment.cnt

- 语义：Row count：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：COUNT(1)
- 口径：
  - 统计对象：`ods.events_a`、`ods.events_b` 的记录（聚合于 `cte:agg`）
  - 时间范围：未在聚合路径上发现日期过滤
  - 纳入条件：无
  - 聚合：按 segment、band 汇总 COUNT(1)（分组键落目标列 `segment`、`band`）
  - 单位/类型：bigint；笔数（来自函数）
  - 空值：无可证明的关联致空，未见缺失回填
  - 更新频率：未知（任务元信息未提供）
- 目标注释：Row count（元数据事实）
- 类型：bigint（元数据事实）
- 来源：无物理来源（SQL事实）
- 结构角色：measure（末步变换 DIRECT）（结构推断；证据 mc:004）
- 加工步骤：
  - 步骤 1/4 @ `cte:agg`（aggregate）：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：COUNT(1)；粒度=changed（SQL事实）
  - 第 2–4/4 步：直接透传（经 `cte:joined` → `cte:ranked` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `ranked`.`cnt` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:004（SQL事实）

### 字段 mart.metric_by_segment.band_total

- 语义：Band level total：amount >= 100 → 'HIGH'；否则 'LOW'，再按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)，再窗口函数 SUM(total)；按 band 分组；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知）
- 口径：
  - 统计对象：`ods.events_a`、`ods.events_b` 的记录（聚合于 `cte:agg`）
  - 时间范围：未在聚合路径上发现日期过滤
  - 纳入条件：无
  - 聚合：按 segment、band 汇总 SUM(amount)（分组键落目标列 `segment`、`band`）
  - 单位/类型：decimal(18,2)；单位未知
  - 空值：无可证明的关联致空，未见缺失回填
  - 更新频率：未知（任务元信息未提供）
- 目标注释：Band level total（元数据事实）
- 类型：decimal(18,2)（元数据事实）
- 来源：`ods.events_a.amount`（注释未知）、`ods.events_b.amount`（注释未知）、`ods.events_a.amount`（注释未知）、`ods.events_b.amount`（注释未知）（SQL事实）
- 结构角色：conditional_label（末步变换 DIRECT）（结构推断；证据 mc:005）
- 加工步骤：
  - 第 1–2/10 步：各分支直接透传（经 `union:events_norm:b01`、`union:events_norm:b02`）；粒度=preserved（SQL事实）
  - 步骤 3/10 @ `union:events_norm`（union）：合并 2 个分支（来自 union:events_norm:b01.amount、union:events_norm:b02.amount）；粒度=preserved（SQL事实）
  - 步骤 4/10 @ `cte:events_norm`（union）：合并 1 个分支（来自 union:events_norm.amount）；粒度=preserved（SQL事实）
  - 步骤 5/10 @ `cte:agg`（case_when）：amount >= 100 → 'HIGH'；否则 'LOW'；粒度=preserved（SQL事实）
  - 步骤 6/10 @ `cte:joined`（direct_projection）：直接投影自 cte:agg.band；粒度=preserved（SQL事实）
  - 步骤 7/10 @ `cte:agg`（aggregate）：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)；粒度=changed（SQL事实）
  - 步骤 8/10 @ `cte:joined`（direct_projection）：直接投影自 cte:agg.total；粒度=preserved（SQL事实）
  - 步骤 9/10 @ `cte:ranked`（window）：窗口函数 SUM(total)；按 band 分组；粒度=preserved（SQL事实）
  - 步骤 10/10 @ `ROOT`（direct_projection）：直接投影自 cte:ranked.band_total；粒度=preserved（SQL事实）
- 最终表达式：`` `ranked`.`band_total` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:005（SQL事实）

### 字段 mart.metric_by_segment.segment_name

- 语义：Segment display name：直接取自 dim.segment_dim.segment_name（注释未知）（关联未命中时为空）
- 目标注释：Segment display name（元数据事实）
- 类型：string（元数据事实）
- 来源：`dim.segment_dim.segment_name`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:006）
- 加工步骤：
  - 第 1–4/4 步：直接透传（经 `cte:latest_dim` → `cte:joined` → `cte:ranked` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `ranked`.`segment_name` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:006（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 3/3 完整；目标表列注释可用（来源 target_ddl）（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：1 条（filter_in_join_on_clause 1；语义提示见 `scope-lineage render` 生成的 warnings.md）（SQL事实）
- 目标列绑定：status=applied、method=ddl_position（按 DDL 位置绑定，目标表 DDL 变更会导致列错位）（元数据事实）
- 本文档的结构推断项：14 项（按 semantic.json 路径：fields[].structural_role 6、stages[].actions[].intent 2、output_shape.candidate_keys 1、output_shape.fan_out_risks[] 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
