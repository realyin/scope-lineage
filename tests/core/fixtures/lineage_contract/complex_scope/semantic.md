---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_complex_scope"
target_table: "mart.user_value"
stmt_kind: "INSERT_OVERWRITE"
lineage_digest: "5916c6127c587bb4"
---

# 任务语义描述 mart.user_value

## 1. 任务概览

- 目标表：`mart.user_value`（表注释：注释未知）（元数据事实）
- 语句类型：INSERT_OVERWRITE；无分区（SQL事实）
- 目标表元数据来源：无（元数据事实）
- 结构摘要：行来源 ods.events（经 cte:aggregated → cte:ranked → union:main:b01 → union:main）、ods.fallback_users（经 union:main:b02 → union:main）；关联 1 个上游（1 个合并）；输出 1 列。（结构推断；证据 scope_profile）

共 3 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `ods.events` | 注释未知 | 主表（driving） | 2 / 2 | 完整 | `cte:aggregated` |
| `ods.fallback_users` | 注释未知 | 主表（driving） | 1 / 1 | 完整 | `union:main:b02` |
| `ods.users` | 注释未知 | 合并分支（union_branch） | 1 / 1 | 完整 | `union:main:b01` |

## 2. 输出表形态与粒度

- 形态：合并型（union_merge）（结构推断；证据 union:main）
- ⚠ 粒度：未能判定（basis=unknown）（结构推断；证据 ROOT 含 UNION（行数为各分支之和，非单一上游行数））
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：无；分区列不计入候选键（元数据事实）
- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）

## 3. 加工链路

共 6 个阶段，按拓扑序逐个展开。

### 阶段 1：aggregated（`cte:aggregated`，角色 aggregate）

- 直接输入：`ods.events`（SQL事实）
- 直接读取物理表：`ods.events`（SQL事实）
- 动作：
  - 聚合：按 user_id 分组聚合：SUM(amount)（SQL事实；证据 logic:cte:aggregated:group_by:001）
- 输出：2 列（`user_id`、`total_amount`）（SQL事实）

### 阶段 2：main:b02（`union:main:b02`，角色 union_branch）

- 直接输入：`ods.fallback_users`（SQL事实）
- 直接读取物理表：`ods.fallback_users`（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：1 列（`user_id`）（SQL事实）

### 阶段 3：ranked（`cte:ranked`，角色 dedup）

- 直接输入：`cte:aggregated`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 上游物理表（来源边界）：`ods.events`（SQL事实）
- 动作：
  - 窗口（意图 keep_latest_per_group）：全表窗口，按 total_amount 降序编号（rn）；union:main:b01 以 rn = 1 消费，即每组保留最新一条（结构推断；证据 logic:cte:ranked:window:001, logic:union:main:b01:filter:001）
- 输出：2 列（`user_id`、`rn`）（SQL事实）

### 阶段 4：main:b01（`union:main:b01`，角色 union_branch）

- 直接输入：`cte:ranked`、`ods.users`（SQL事实）
- 直接读取物理表：`ods.users`（SQL事实）
- 上游物理表（来源边界）：`ods.events`、`ods.users`（SQL事实）
- 动作：
  - 关联：INNER 关联 ods.users，键 user_id，无匹配的行被丢弃（SQL事实；证据 logic:union:main:b01:join:001）
  - 过滤：只保留 rn = 1 的记录（SQL事实；证据 logic:union:main:b01:filter:001）
- 输出：1 列（`user_id`）（SQL事实）

### 阶段 5：main（`union:main`，角色 union）

- 直接输入：`union:main:b01`、`union:main:b02`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 上游物理表（来源边界）：`ods.events`、`ods.fallback_users`、`ods.users`（SQL事实）
- 动作：
  - 合并：合并 2 个分支（来自 ods.events、ods.users、ods.fallback_users）（SQL事实；证据 union:main）
- 输出：1 列（`user_id`）（SQL事实）

### 阶段 6：ROOT（`ROOT`，角色 transform）

- 直接输入：`union:main`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：1 列（`user_id`）（SQL事实）

## 4. 规则清单

共 2 条规则（过滤 1 条、连接条件 1 条）；条件为 SQL 原文，字段注释为元数据事实。

| 规则 | 类型 | 阶段 | 条件 | 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rule:001 | 过滤（filter） | `union:main:b01` | `` `r`.`rn` = 1 `` | `cte:ranked.rn`（scope 内部列） | — | 否 | `logic:union:main:b01:filter:001` |
| rule:002 | 连接条件（join_condition） | `union:main:b01` | `` `r`.`user_id` = `u`.`user_id` `` | `ods.events.user_id`（注释未知）、`ods.users.user_id`（注释未知）、`cte:ranked.user_id`（scope 内部列） | — | — | `logic:union:main:b01:join:001` |

## 5. 字段语义

共 1 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.user_value.user_id` | （注释未知）：直接取自 ods.events.user_id（注释未知）、ods.fallback_users.user_id（注释未知） | attribute | — | ✓ |

### 字段 mart.user_value.user_id

- 语义：（注释未知）：直接取自 ods.events.user_id（注释未知）、ods.fallback_users.user_id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.events.user_id`（注释未知）、`ods.fallback_users.user_id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 UNION）（结构推断；证据 mc:001）
- 加工步骤：
  - 第 1–2/6 步：直接透传（经 `cte:aggregated` → `cte:ranked`）；粒度=preserved（SQL事实）
  - 第 3–4/6 步：各分支直接透传（经 `union:main:b01`、`union:main:b02`）；粒度=preserved（SQL事实）
  - 步骤 5/6 @ `union:main`（union）：合并 2 个分支（来自 union:main:b01.user_id、union:main:b02.user_id）；粒度=preserved（SQL事实）
  - 步骤 6/6 @ `ROOT`（union）：合并 1 个分支（来自 union:main.user_id）；粒度=preserved（SQL事实）
- 最终表达式：`user_id`（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 3/3 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=metadata_not_provided）（元数据事实）
- 本文档的结构推断项：7 项（按 semantic.json 路径：fields[].structural_role 1、output_shape.candidate_keys 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1、stages[].actions[].intent 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
