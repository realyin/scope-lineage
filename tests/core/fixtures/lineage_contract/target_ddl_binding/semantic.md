---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "golden_target_ddl_binding"
target_table: "dwd.account_daily"
stmt_kind: "INSERT_OVERWRITE"
lineage_digest: "49ca4ef5f9e34e0f"
---

# 任务语义描述 dwd.account_daily

## 1. 任务概览

- 目标表：`dwd.account_daily`（表注释：账户日快照（合成）；业务域 账户域；项目 账户日报（合成）；负责人 demo_owner）（元数据事实）
- 语句类型：INSERT_OVERWRITE；静态分区 dt = `20260801`（SQL事实）
- 目标表元数据来源：target_ddl（元数据事实）
- 结构摘要：ROOT 直接读取 ods.account_snapshot；输出 2 列。（结构推断；证据 scope_profile）

共 1 张输入表（角色为结构推断，其余为 SQL/元数据事实）：

| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |
| --- | --- | --- | --- | --- | --- |
| `ods.account_snapshot` | 注释未知 | 主表（driving） | 2 / 2 | 完整 | `ROOT` |

## 2. 输出表形态与粒度

- 形态：过滤投影型（filtered_projection）（结构推断；证据 ROOT）
- 粒度：一行对应 `ods.account_snapshot` 的一行（依据主表行，basis=driving_table_rows）（结构推断；证据 ods.account_snapshot）
- 候选键：无（结构未证明任一键唯一）（结构推断）
- 分区列：`dt`；分区列不计入候选键（元数据事实）
- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）

## 3. 加工链路

共 1 个阶段，按拓扑序逐个展开。

### 阶段 1：ROOT（`ROOT`，角色 pass_through）

- 直接输入：`ods.account_snapshot`（SQL事实）
- 直接读取物理表：`ods.account_snapshot`（SQL事实）
- 动作：无（该 scope 只做投影）。（SQL事实）
- 输出：2 列（`account_id`、`balance`）（SQL事实）

## 4. 规则清单

- 本语句没有过滤、连接或 CASE 规则。（SQL事实）

## 5. 字段语义

共 2 个目标字段。

### 完整字段清单

| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |
| --- | --- | --- | --- | --- | --- |
| 1 | `dwd.account_daily.account_id` | （注释未知）：直接取自 ods.account_snapshot.account_key（注释未知） | attribute | — | ✓ |
| 2 | `dwd.account_daily.balance` | （注释未知）：直接取自 ods.account_snapshot.balance_value（注释未知） | attribute | — | ✓ |

### 字段 dwd.account_daily.account_id

- 语义：（注释未知）：直接取自 ods.account_snapshot.account_key（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：bigint（元数据事实）
- 来源：`ods.account_snapshot.account_key`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:001）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.account_snapshot.account_key；粒度=preserved（SQL事实）
- 最终表达式：`` `s`.`account_key` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:001（SQL事实）

### 字段 dwd.account_daily.balance

- 语义：（注释未知）：直接取自 ods.account_snapshot.balance_value（注释未知）
- 目标注释：注释未知（元数据事实）
- 类型：decimal(18,2)（元数据事实）
- 来源：`ods.account_snapshot.balance_value`（注释未知）（SQL事实）
- 结构角色：attribute（末步变换 DIRECT）（结构推断；证据 mc:002）
- 加工步骤：
  - 步骤 1/1 @ `ROOT`（direct_projection）：直接投影自 ods.account_snapshot.balance_value；粒度=preserved（SQL事实）
- 最终表达式：`` `s`.`balance_value` ``（SQL事实）
- 追溯：完整；mapping_chain_id=mc:002（SQL事实）

## 6. 可信度与边界

- 元数据覆盖：输入表 1/1 完整；目标表列注释⚠ 不可用——字段语义退化为来源注释加加工复述（元数据事实）
- 追溯不完整字段：无（SQL事实）
- AMBIGUOUS 字段：无（SQL事实）
- 事实缺口：0 条（SQL事实）
- 解析警告：无（SQL事实）
- 目标列绑定：status=applied、method=ddl_position（按 DDL 位置绑定，目标表 DDL 变更会导致列错位）（元数据事实）
- 本文档的结构推断项：7 项（按 semantic.json 路径：fields[].structural_role 2、output_shape.candidate_keys 1、output_shape.grain 1、output_shape.key_confidence 1、output_shape.shape 1、output_shape.unexposed_keys 1；完整清单见 semantic.json 的 confidence.inferred_items）（结构推断）

#### 治理线索

- ⚠ alias_position_mismatch：按位置写入且 2/2 个投影的 SQL 别名与 DDL 同位置列名不同（如 目标 account_id ← 别名 wrong_key、目标 balance ← 别名 wrong_balance）——生产数据写错列或元数据列序过期，需 DESC 表核对（SQL事实+元数据事实；证据 mc:001, mc:002）
- ⚠ table_comment_missing：缺少表注释的表（1 张）：ods.account_snapshot（元数据事实）

## 7. 给 Agent 的说明

- 本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，可按行尾的证据 id 回查。
- 业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 `LLM推断` / `待业务确认`。
- 任何未标 `元数据事实` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，要么是本文档的结构推断。
