---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_self_join"
target_table: "mart.node_edges"
stmt_kind: "INSERT"
lineage_digest: "cd5641d03833f8d7"
---

# 任务语义描述 mart.node_edges

## 1. 任务概览

- 目标表：`mart.node_edges`（表注释：注释未知）（元数据事实）
- 语句类型：INSERT；无分区（SQL事实）
- 目标表元数据来源：无（元数据事实）
- 结构摘要：ROOT 直接读取 ods.nodes；输出 2 列。（结构推断；证据 scope_profile）

共 1 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `ods.nodes` | 注释未知 | 主表（driving） | 3 / 3 | 完整 | `ROOT` |

## 2. 输出表形态与粒度

- 形态：关联补充型投影（enriched_projection）（结构推断；证据 logic:ROOT:join:001）
- 粒度：一行对应 `ods.nodes` 的一行（依据主表行，basis=driving_table_rows）（结构推断；证据 ods.nodes）
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：无；分区列不计入候选键（元数据事实）
- 行数放大风险：
  - INNER JOIN `ods.nodes`：⚠ 未知（unknown）——物理表无主键事实（结构推断；证据 logic:ROOT:join:001）

## 3. 加工链路

共 1 个阶段，按拓扑序逐个展开。

### 阶段 1：ROOT（`ROOT`，角色 join）

- 直接输入：`ods.nodes`（SQL事实）
- 直接读取物理表：`ods.nodes`（SQL事实）
- 动作：
  - 关联：INNER 关联 ods.nodes，键 a.parent_id = b.id、batch_id，无匹配的行被丢弃（SQL事实；证据 logic:ROOT:join:001）
- 输出：2 列（`id`、`parent_id`）（SQL事实）

## 4. 规则清单

共 1 条规则（连接条件 1 条）；条件为 SQL 原文，字段注释为元数据事实。

| 规则 | 类型 | 阶段 | 条件 | 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rule:001 | 连接条件（join_condition） | `ROOT` | `` `a`.`parent_id` = `b`.`id` AND `a`.`batch_id` = `b`.`batch_id` `` | `ods.nodes.parent_id`（注释未知）、`ods.nodes.id`（注释未知）、`ods.nodes.batch_id`（注释未知） | — | — | `logic:ROOT:join:001` |

## 5. 字段语义

共 2 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `mart.node_edges.id` | （注释未知）：直接取自 ods.nodes.id（注释未知） | attribute | — | ✓ |
| 2 | `mart.node_edges.parent_id` | （注释未知）：直接取自 ods.nodes.id（注释未知） | attribute | — | ✓ |

### 字段 mart.node_edges.id

- 语义：（注释未知）：直接取自 ods.nodes.id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.nodes.id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.nodes.id；粒度=preserved（SQL事实）
- 最终表达式：`` `a`.`id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 mart.node_edges.parent_id

- 语义：（注释未知）：直接取自 ods.nodes.id（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：未知（元数据事实）
- 来源：`ods.nodes.id`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.nodes.id；粒度=preserved（SQL事实）
- 最终表达式：`` `b`.`id` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 1/1 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：未做目标列绑定（target_binding_absent_reason=metadata_not_provided）（元数据事实）
- 本文档的结构推断项：8 项（按 semantic.json 路径：fields[].structural_role 2、output_shape.candidate_keys 1、output_shape.fan_out_risks[] 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- 治理线索：无（SQL事实）
- 信息项：1（见 semantic.json findings）（SQL事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
