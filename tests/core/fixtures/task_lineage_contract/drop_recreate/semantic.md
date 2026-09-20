# 任务语义描述：golden_drop_recreate

共 2 条写入语句；最终产出表：`mart.channel_daily`（来自 `final_table_states`，已排除会话内关系与目录写入）。

## stmt:002

---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_drop_recreate#1"
target_table: "mart.channel_daily"
stmt_kind: "CTAS"
lineage_digest: "cc26076f7841fe52"
---

# 任务语义描述 mart.channel_daily

## 1. 任务概览

- 目标表：`mart.channel_daily`（表注释：注释未知）（元数据事实）
- 语句类型：CTAS；无分区（SQL事实）
- 目标表元数据来源：schema（元数据事实）
- 结构摘要：按 channel_id、stat_date 汇总，行来自 ods.channel_events；输出 3 列。（结构推断；证据 scope_profile）

共 1 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `ods.channel_events` | 注释未知 | 聚合来源（aggregate_source） | 3 / 3 | 完整 | `ROOT` |

## 2. 输出表形态与粒度

- 形态：聚合型（aggregated）（结构推断；证据 logic:ROOT:group_by:001）
- 粒度：一行对应一组 `ROOT.channel_id`、`ROOT.stat_date`（物理来源：`ods.channel_events.channel_id`、`ods.channel_events.stat_date`）（依据 GROUP BY 键，basis=group_by）（结构推断；证据 logic:ROOT:group_by:001）
- 键：目标表列 `channel_id`、`stat_date`——由 GROUP BY 键保证输出内唯一（key_confidence=proven）（结构推断）
- 分区列：无；分区列不计入候选键（元数据事实）
- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）

## 3. 加工链路

共 1 个阶段，按拓扑序逐个展开。

### 阶段 1：ROOT（`ROOT`，角色 aggregate）

- 直接输入：`ods.channel_events`（SQL事实）
- 直接读取物理表：`ods.channel_events`（SQL事实）
- 动作：
  - 聚合：按 channel_id、stat_date 分组聚合：SUM(amount)（SQL事实；证据 logic:ROOT:group_by:001）
- 输出：3 列（`channel_id`、`stat_date`、`amount_sum`）（SQL事实）

## 4. 规则清单

- 本语句没有过滤、连接或 CASE 规则。（SQL事实）

## 5. 字段语义

共 3 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.channel_daily.channel_id` | （注释未知）：直接取自 ods.channel_events.channel_id（注释未知） | candidate_key | — | ✓ |
| 2 | `mart.channel_daily.stat_date` | （注释未知）：直接取自 ods.channel_events.stat_date（注释未知） | candidate_key | — | ✓ |
| 3 | `mart.channel_daily.amount_sum` | （注释未知）：按 channel_id、stat_date 聚合：SUM(amount)；来源 ods.channel_events.amount（注释未知） | measure | SUM(amount)；未在聚合路径上发现日期过滤 | ✓ |

### 字段 mart.channel_daily.channel_id

- 语义：（注释未知）：直接取自 ods.channel_events.channel_id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_events.channel_id`（注释未知）（SQL事实）
- 结构角色：candidate_key（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.channel_events.channel_id；粒度=preserved（SQL事实）
- 最终表达式：`` `channel_events`.`channel_id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.channel_daily.stat_date

- 语义：（注释未知）：直接取自 ods.channel_events.stat_date（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_events.stat_date`（注释未知）（SQL事实）
- 结构角色：candidate_key（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.channel_events.stat_date；粒度=preserved（SQL事实）
- 最终表达式：`` `channel_events`.`stat_date` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

### 字段 mart.channel_daily.amount_sum

- 语义：（注释未知）：按 channel_id、stat_date 聚合：SUM(amount)；来源 ods.channel_events.amount（注释未知）
- 口径：
  - 统计对象：`ods.channel_events` 的记录（聚合于 `ROOT`）
  - 时间范围：未在聚合路径上发现日期过滤
  - 纳入条件：无
  - 聚合：按 channel_id、stat_date 汇总 SUM(amount)（分组键落目标列 `channel_id`、`stat_date`）
  - 单位/类型：未知；单位未知
  - 空值：无可证明的关联致空，未见缺失回填
  - 更新频率：未知（任务元信息未提供）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_events.amount`（注释未知）（SQL事实）
- 结构角色：measure（末步变换 AGGREGATE）（结构推断；证据 mc:003）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（aggregate）：按 channel_id、stat_date 聚合：SUM(amount)；粒度=changed（SQL事实）
- 最终表达式：`` SUM(`channel_events`.`amount`) ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:003（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 1/1 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=statement_defines_its_own_columns）（元数据事实）
- 本文档的结构推断项：8 项（按 semantic.json 路径：fields[].structural_role 3、output_shape.candidate_keys 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。


## stmt:003

---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_drop_recreate#2"
target_table: "mart.channel_daily"
stmt_kind: "INSERT"
lineage_digest: "9baefef9eaebeec6"
---

# 任务语义描述 mart.channel_daily

## 1. 任务概览

- 目标表：`mart.channel_daily`（表注释：注释未知）（元数据事实）
- 语句类型：INSERT；无分区（SQL事实）
- 目标表元数据来源：schema（元数据事实）
- 结构摘要：行来源 ods.channel_backfill；输出 3 列。（结构推断；证据 scope_profile）

共 1 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `ods.channel_backfill` | 注释未知 | 主表（driving） | 3 / 3 | 完整 | `ROOT` |

## 2. 输出表形态与粒度

- 形态：过滤投影型（filtered_projection）（结构推断；证据 ROOT）
- 粒度：一行对应 `ods.channel_backfill` 的一行（依据主表行，basis=driving_table_rows）（结构推断；证据 ods.channel_backfill）
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：无；分区列不计入候选键（元数据事实）
- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）

## 3. 加工链路

共 1 个阶段，按拓扑序逐个展开。

### 阶段 1：ROOT（`ROOT`，角色 pass_through）

- 直接输入：`ods.channel_backfill`（SQL事实）
- 直接读取物理表：`ods.channel_backfill`（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：3 列（`channel_id`、`stat_date`、`amount`）（SQL事实）

## 4. 规则清单

- 本语句没有过滤、连接或 CASE 规则。（SQL事实）

## 5. 字段语义

共 3 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.channel_daily.channel_id` | （注释未知）：直接取自 ods.channel_backfill.channel_id（注释未知） | attribute | — | ✓ |
| 2 | `mart.channel_daily.stat_date` | （注释未知）：直接取自 ods.channel_backfill.stat_date（注释未知） | attribute | — | ✓ |
| 3 | `mart.channel_daily.amount` | （注释未知）：直接取自 ods.channel_backfill.amount（注释未知） | attribute | — | ✓ |

### 字段 mart.channel_daily.channel_id

- 语义：（注释未知）：直接取自 ods.channel_backfill.channel_id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_backfill.channel_id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.channel_backfill.channel_id；粒度=preserved（SQL事实）
- 最终表达式：`` `channel_backfill`.`channel_id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.channel_daily.stat_date

- 语义：（注释未知）：直接取自 ods.channel_backfill.stat_date（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_backfill.stat_date`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.channel_backfill.stat_date；粒度=preserved（SQL事实）
- 最终表达式：`` `channel_backfill`.`stat_date` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

### 字段 mart.channel_daily.amount

- 语义：（注释未知）：直接取自 ods.channel_backfill.amount（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.channel_backfill.amount`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:003）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.channel_backfill.amount；粒度=preserved（SQL事实）
- 最终表达式：`` `channel_backfill`.`amount` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:003（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 1/1 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=metadata_not_provided）（元数据事实）
- 本文档的结构推断项：8 项（按 semantic.json 路径：fields[].structural_role 3、output_shape.candidate_keys 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
