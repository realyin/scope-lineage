---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_commented_insert"
target_table: "mart.channel_summary"
stmt_kind: "INSERT_OVERWRITE"
lineage_digest: "a631091cb58fc88a"
---

# 任务语义描述 mart.channel_summary

## 1. 任务概览

- 目标表：`mart.channel_summary`（表注释：注释未知）（元数据事实）
- 语句类型：INSERT_OVERWRITE；静态分区 dt = `${bizdate}`（SQL事实）
- 目标表元数据来源：无（元数据事实）
- 结构摘要：ROOT 直接读取 dim.channel、ods.channel_event；过滤 1 处；CASE WHEN 派生 1 个字段；输出 3 列。（结构推断；证据 scope_profile）

SQL 头部注释（原文，作者说法，非 SQL 事实）（SQL注释）：

> 任务：客户渠道汇总（合成示例）
> 口径：仅统计生效状态的客户
> 口径问题联系 <email>（合成地址）

共 2 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `dim.channel` | 渠道维表（合成） | 聚合来源（aggregate_source） | 1 / 2 | 完整 | `ROOT` |
| `ods.channel_event` | 渠道事件明细（合成） | 聚合来源（aggregate_source） | 4 / 4 | 完整 | `ROOT` |

## 2. 输出表形态与粒度

- 形态：聚合型（aggregated）（结构推断；证据 logic:ROOT:group_by:001）
- 粒度：一行对应一组 `ROOT.customer_id`、`ROOT.channel_name`（物理来源：`ods.channel_event.customer_id`、`ods.channel_event.channel_code`）（依据 GROUP BY 键，basis=group_by）（结构推断；证据 logic:ROOT:group_by:001）
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：`dt`；分区列不计入候选键（元数据事实）
- 行数放大风险：
  - LEFT_OUTER JOIN `dim.channel`：⚠ 未知（unknown）——物理表无主键事实（结构推断；证据 logic:ROOT:join:001）

## 3. 加工链路

共 1 个阶段，按拓扑序逐个展开。

### 阶段 1：ROOT（`ROOT`，角色 aggregate）

- 直接输入：`dim.channel`、`ods.channel_event`（SQL事实）
- 直接读取物理表：`dim.channel`、`ods.channel_event`（SQL事实）
- 动作：
  - 关联：LEFT_OUTER 关联 dim.channel，键 channel_code，右侧无匹配时保留左行，右侧字段为空（注释：按渠道编码补充维度；SQL注释）（SQL事实；证据 logic:ROOT:join:001）
  - 过滤：只保留 status = 'ACTIVE' 的记录（注释：仅生效状态；SQL注释）（SQL事实；证据 logic:ROOT:filter:001）
  - 聚合：按 customer_id、CASE WHEN channel_code = 'A' THEN 'ONLINE' ELSE 'OFFLINE' END 分组聚合：SUM(amount)（SQL事实；证据 logic:ROOT:group_by:001）
  - 条件派生：派生 channel_name：channel_code = 'A' → 'ONLINE'；否则 'OFFLINE'（SQL事实；证据 logic:ROOT:case_when:001）
- 输出：3 列（`customer_id`、`channel_name`、`total_amount`）（SQL事实）

## 4. 规则清单

共 3 条规则（CASE 分支 1 条、过滤 1 条、连接条件 1 条）；条件为 SQL 原文，字段注释为元数据事实。

| 规则 | 类型 | 阶段 | 条件 | 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rule:001 | CASE 分支（case_branch） | `ROOT` | `channel_code = 'A' → 'ONLINE'；否则 'OFFLINE'` | `ods.channel_event.channel_code`（注释未知） | — | — | `logic:ROOT:case_when:001` |
| rule:002 | 过滤（filter） | `ROOT` | `` `s`.`status` = 'ACTIVE' /* 仅生效状态 */ `` | `ods.channel_event.status`（注释未知） | 仅生效状态 | 否 | `logic:ROOT:filter:001` |
| rule:003 | 连接条件（join_condition） | `ROOT` | `` `s`.`channel_code` = `d`.`channel_code` /* 按渠道编码补充维度 */ `` | `ods.channel_event.channel_code`（注释未知）、`dim.channel.channel_code`（注释未知） | 按渠道编码补充维度 | — | `logic:ROOT:join:001` |

## 5. 字段语义

共 3 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.channel_summary.customer_id` | （注释未知）：直接取自 ods.channel_event.customer_id（表：渠道事件明细（合成））；注释：客户号 | attribute | — | ✓ |
| 2 | `mart.channel_summary.channel_name` | （注释未知）：channel_code = 'A' → 'ONLINE'；否则 'OFFLINE'；来源 ods.channel_event.channel_code（表：渠道事件明细（合成））；注释：渠道编码（合成值域） | conditional_label | — | ✓ |
| 3 | `mart.channel_summary.total_amount` | （注释未知）：按 customer_id、CASE WHEN channel_code = 'A' THEN 'ONLINE' ELSE 'OFFLINE' END 聚合：SUM(amount)；来源 ods.channel_event.amount（表：渠道事件明细（合成））；注释：金额合计（元） | measure | SUM(amount)；未在聚合路径上发现日期过滤 | ✓ |

### 字段 mart.channel_summary.customer_id

- 语义：（注释未知）：直接取自 ods.channel_event.customer_id（表：渠道事件明细（合成））；注释：客户号
- 注释：客户号（SQL注释）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_event.customer_id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.channel_event.customer_id；粒度=preserved（SQL事实）
- 最终表达式：`` `s`.`customer_id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.channel_summary.channel_name

- 语义：（注释未知）：channel_code = 'A' → 'ONLINE'；否则 'OFFLINE'；来源 ods.channel_event.channel_code（表：渠道事件明细（合成））；注释：渠道编码（合成值域）
- 注释：渠道编码（合成值域）（SQL注释）
- 取值：'OFFLINE'（待确认）、'ONLINE'（待确认）（该列取值已被 SQL 证明封闭）（SQL事实；证据 rule:001）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_event.channel_code`（注释未知）（SQL事实）
- 结构角色：conditional_label（末步变换 CONDITIONAL）（结构推断；证据 mc:002）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（case_when）：channel_code = 'A' → 'ONLINE'；否则 'OFFLINE'；粒度=preserved（SQL事实）
- 最终表达式：`` CASE WHEN `s`.`channel_code` = 'A' THEN 'ONLINE' ELSE 'OFFLINE' END ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

### 字段 mart.channel_summary.total_amount

- 语义：（注释未知）：按 customer_id、CASE WHEN channel_code = 'A' THEN 'ONLINE' ELSE 'OFFLINE' END 聚合：SUM(amount)；来源 ods.channel_event.amount（表：渠道事件明细（合成））；注释：金额合计（元）
- 口径：
  - 统计对象：`dim.channel`、`ods.channel_event` 的记录（聚合于 `ROOT`）
  - 时间范围：未在聚合路径上发现日期过滤
  - 纳入条件：只保留 status = 'ACTIVE' 的记录
  - 聚合：按 customer_id、channel_name 汇总 SUM(amount)（分组键落目标列 `customer_id`、`channel_name`）
  - 单位/类型：未知；单位未知
  - 空值：无可证明的关联致空，未见缺失回填
  - 更新频率：未知（任务元信息未提供）
- 注释：金额合计（元）（SQL注释）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_event.amount`（注释未知）（SQL事实）
- 结构角色：measure（末步变换 AGGREGATE）（结构推断；证据 mc:003）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（aggregate）：按 customer_id、CASE WHEN channel_code = 'A' THEN 'ONLINE' ELSE 'OFFLINE' END 聚合：SUM(amount)；粒度=changed（SQL事实）
- 最终表达式：`` SUM(`s`.`amount`) ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:003（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 2/2 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=metadata_not_provided）（元数据事实）
- 本文档的结构推断项：9 项（按 semantic.json 路径：fields[].structural_role 3、output_shape.candidate_keys 1、output_shape.fan_out_risks[] 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- ⚠ table_comment_missing：缺少表注释的表（1 张）：mart.channel_summary（元数据事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
