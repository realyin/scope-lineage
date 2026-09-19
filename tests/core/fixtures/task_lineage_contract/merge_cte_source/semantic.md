# 任务语义描述：golden_merge_cte_source

共 1 条写入语句；最终产出表：`mart.event_target`（来自 `final_table_states`，已排除会话内关系与目录写入）。

## stmt:001

---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_merge_cte_source#0"
target_table: "mart.event_target"
stmt_kind: "MERGE"
lineage_digest: "0c7c8256f8eb5427"
---

# 任务语义描述 mart.event_target

## 1. 任务概览

- 目标表：`mart.event_target`（表注释：注释未知）（元数据事实）
- 语句类型：MERGE；无分区（SQL事实）
- 目标表元数据来源：schema（元数据事实）
- 结构摘要：ROOT 不直接读取物理表；关联 1 个上游（1 个其他）；输出 6 列。（结构推断；证据 scope_profile）

共 2 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `dim.accounts` | 注释未知 | MERGE 来源（merge_source） | 2 / 2 | 完整 | `cte:staged` |
| `ods.events` | 注释未知 | MERGE 来源（merge_source） | 3 / 3 | 完整 | `cte:staged` |

## 2. 输出表形态与粒度

- ⚠ 形态：未能判定（unknown）（结构推断；证据 ROOT）
- ⚠ 粒度：未能判定（basis=unknown）（结构推断；证据 ROOT）
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：无；分区列不计入候选键（元数据事实）
- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）

## 3. 加工链路

共 3 个阶段，按拓扑序逐个展开。

### 阶段 1：staged（`cte:staged`，角色 join）

- 直接输入：`dim.accounts`、`ods.events`（SQL事实）
- 直接读取物理表：`dim.accounts`、`ods.events`（SQL事实）
- 动作：
  - 关联：LEFT_OUTER 关联 dim.accounts，键 account_id，右侧无匹配时保留左行，右侧字段为空（SQL事实；证据 logic:cte:staged:join:001）
- 输出：3 列（`id`、`event_type`、`account_key`）（SQL事实）

### 阶段 2：source（`subq:source`，角色 pass_through）

- 直接输入：`cte:staged`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：3 列（`id`、`event_type`、`account_key`）（SQL事实）

### 阶段 3：ROOT（`ROOT`，角色 pass_through）

- 直接输入：`subq:source`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：6 列（`id`、`event_type`、`account_key`、`id`、`event_type`、`account_key`）（SQL事实）

## 4. 规则清单

共 1 条规则（连接条件 1 条）；条件为 SQL 原文，字段注释为元数据事实。

| 规则 | 类型 | 阶段 | 条件 | 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rule:001 | 连接条件（join_condition） | `cte:staged` | `` `e`.`account_id` = `a`.`account_id` `` | `ods.events.account_id`（注释未知）、`dim.accounts.account_id`（注释未知） | — | — | `logic:cte:staged:join:001` |

## 5. 字段语义

共 6 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.event_target.id（merge:matched 分支 0）` | （注释未知）：直接取自 ods.events.id（注释未知） | attribute | — | ✓ |
| 2 | `mart.event_target.event_type（merge:matched 分支 0）` | （注释未知）：直接取自 ods.events.event_type（注释未知） | attribute | — | ✓ |
| 3 | `mart.event_target.account_key（merge:matched 分支 0）` | （注释未知）：直接取自 dim.accounts.account_key（注释未知）（关联未命中时为空） | attribute | — | ✓ |
| 4 | `mart.event_target.id（merge:not_matched 分支 1）` | （注释未知）：直接取自 ods.events.id（注释未知） | attribute | — | ✓ |
| 5 | `mart.event_target.event_type（merge:not_matched 分支 1）` | （注释未知）：直接取自 ods.events.event_type（注释未知） | attribute | — | ✓ |
| 6 | `mart.event_target.account_key（merge:not_matched 分支 1）` | （注释未知）：直接取自 dim.accounts.account_key（注释未知）（关联未命中时为空） | attribute | — | ✓ |

### 字段 mart.event_target.id（merge:matched 分支 0）

- 语义：（注释未知）：直接取自 ods.events.id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.events.id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 第 1–3/3 步：直接透传（经 `cte:staged` → `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `source`.`id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.event_target.event_type（merge:matched 分支 0）

- 语义：（注释未知）：直接取自 ods.events.event_type（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.events.event_type`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 第 1–3/3 步：直接透传（经 `cte:staged` → `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `source`.`event_type` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

### 字段 mart.event_target.account_key（merge:matched 分支 0）

- 语义：（注释未知）：直接取自 dim.accounts.account_key（注释未知）（关联未命中时为空）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`dim.accounts.account_key`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:003）
- 加工步骤：
  - 第 1–3/3 步：直接透传（经 `cte:staged` → `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `source`.`account_key` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:003（SQL事实）

### 字段 mart.event_target.id（merge:not_matched 分支 1）

- 语义：（注释未知）：直接取自 ods.events.id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.events.id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:004）
- 加工步骤：
  - 第 1–3/3 步：直接透传（经 `cte:staged` → `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`source.id`（SQL事实）
- 追溯：完整；mapping_chain_id=mc:004（SQL事实）

### 字段 mart.event_target.event_type（merge:not_matched 分支 1）

- 语义：（注释未知）：直接取自 ods.events.event_type（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.events.event_type`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:005）
- 加工步骤：
  - 第 1–3/3 步：直接透传（经 `cte:staged` → `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`source.event_type`（SQL事实）
- 追溯：完整；mapping_chain_id=mc:005（SQL事实）

### 字段 mart.event_target.account_key（merge:not_matched 分支 1）

- 语义：（注释未知）：直接取自 dim.accounts.account_key（注释未知）（关联未命中时为空）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`dim.accounts.account_key`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:006）
- 加工步骤：
  - 第 1–3/3 步：直接透传（经 `cte:staged` → `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`source.account_key`（SQL事实）
- 追溯：完整；mapping_chain_id=mc:006（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 2/2 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=binding_not_applicable_for_statement）（元数据事实）
- 本文档的结构推断项：11 项（按 semantic.json 路径：fields[].structural_role 6、output_shape.candidate_keys 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
