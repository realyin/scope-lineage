---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "merge_contract"
target_table: "mart.customer_profile"
stmt_kind: "MERGE"
lineage_digest: "b61fff94e3fe4f30"
---

# 任务语义描述 mart.customer_profile

## 1. 任务概览

- 目标表：`mart.customer_profile`（表注释：注释未知）（元数据事实）
- 语句类型：MERGE；无分区（SQL事实）
- 目标表元数据来源：schema（元数据事实）
- 结构摘要：ROOT 不直接读取物理表；关联 1 个上游（1 个其他）；输出 3 列。（结构推断；证据 scope_profile）

共 1 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `ods.customer_delta` | 注释未知 | MERGE 来源（merge_source） | 2 / 2 | 完整 | `subq:source` |

## 2. 输出表形态与粒度

- ⚠ 形态：未能判定（unknown）（结构推断；证据 ROOT）
- ⚠ 粒度：未能判定（basis=unknown）（结构推断；证据 ROOT）
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：无；分区列不计入候选键（元数据事实）
- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）

## 3. 加工链路

共 2 个阶段，按拓扑序逐个展开。

### 阶段 1：source（`subq:source`，角色 pass_through）

- 直接输入：`ods.customer_delta`（SQL事实）
- 直接读取物理表：`ods.customer_delta`（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：2 列（`customer_id`、`customer_name`）（SQL事实）

### 阶段 2：ROOT（`ROOT`，角色 pass_through）

- 直接输入：`subq:source`（SQL事实）
- 直接读取物理表：无（仅读上游 scope）（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：3 列（`customer_name`、`customer_id`、`customer_name`）（SQL事实）

## 4. 规则清单

- 本语句没有过滤、连接或 CASE 规则。（SQL事实）

## 5. 字段语义

共 3 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.customer_profile.customer_name（merge:matched 分支 0）` | （注释未知）：直接取自 ods.customer_delta.customer_name（注释未知） | attribute | — | ✓ |
| 2 | `mart.customer_profile.customer_id（merge:not_matched 分支 1）` | （注释未知）：直接取自 ods.customer_delta.customer_id（注释未知） | attribute | — | ✓ |
| 3 | `mart.customer_profile.customer_name（merge:not_matched 分支 1）` | （注释未知）：直接取自 ods.customer_delta.customer_name（注释未知） | attribute | — | ✓ |

### 字段 mart.customer_profile.customer_name（merge:matched 分支 0）

- 语义：（注释未知）：直接取自 ods.customer_delta.customer_name（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.customer_delta.customer_name`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 第 1–2/2 步：直接透传（经 `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `source`.`customer_name` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.customer_profile.customer_id（merge:not_matched 分支 1）

- 语义：（注释未知）：直接取自 ods.customer_delta.customer_id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.customer_delta.customer_id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 第 1–2/2 步：直接透传（经 `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `source`.`customer_id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

### 字段 mart.customer_profile.customer_name（merge:not_matched 分支 1）

- 语义：（注释未知）：直接取自 ods.customer_delta.customer_name（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.customer_delta.customer_name`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:003）
- 加工步骤：
  - 第 1–2/2 步：直接透传（经 `subq:source` → `ROOT`）；粒度=preserved（SQL事实）
- 最终表达式：`` `source`.`customer_name` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:003（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 1/1 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=binding_not_applicable_for_statement）（元数据事实）
- 本文档的结构推断项：8 项（按 semantic.json 路径：fields[].structural_role 3、output_shape.candidate_keys 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
