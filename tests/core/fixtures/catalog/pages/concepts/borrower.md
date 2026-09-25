# 借款人

`concept:borrower` · 角色 · [贷款](../index.md) · 已确认（owner）

## 1. 定义与身份

A customer while they hold at least one loan that is not settled.

| 项 | 内容 |
| --- | --- |
| 种类 | 角色 |
| 状态 | 已确认（owner） |
| 同义词 | — |
| 承担者 | [客户](customer.md) |
| 语境 | 贷款 |
| 成立条件 | holds at least one loan whose status is not settled |

### 标识符

（目录未登记标识符）

## 2. 数据清单

### 角色视图

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_lending_borrower_df` | 表注释：Borrowers | 客户号（推断）；血缘已证明 `customer_id` | 快照；按单个 dt 分区取数 | 调度 day | customers holding at least one loan that is not settled | dwd_lending_borrower_daily | 在用 · 草拟（llm） |

- `demo_dwd.dwd_lending_borrower_df` 血缘一跳：上游 `demo_dwd.dwd_lending_loan_df`、`demo_dwd.dwd_party_customer_info_df`、`demo_ods.ods_credit_limit_df`；下游 `demo_ads.ads_collection_overdue_loan_df`

## 3. 属性

### 度量

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 授信额度 `attr:borrower.credit_limit` | The most the borrower may owe at once. | decimal(18,2) / CNY | — | `demo_dwd.dwd_lending_borrower_df.credit_limit` | `demo_dwd.dwd_lending_borrower_df.credit_limit` = `` MAX(`cr`.`credit_limit`) ``（血缘） | 已确认（owner） |

## 4. 关系

### 关联、组成与泛化

| 关系 | 种类 | 读法 | 对端 | 基数 | 证据连接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| owes `rel:borrower_owes_loan` | 关联 | 借款人 owes 借据 | [借据](loan.md) | 借款人 1 : 借据 1..* | 1 次（如 `demo_dwd.dwd_lending_borrower_df.customer_id = demo_dwd.dwd_lending_loan_df.customer_id`） | 已确认（owner） |

### 参与的事件

| 事件 | 本概念角色 | 事件表现表数 | 证据连接 |
| --- | --- | --- | --- |
| [放款](disbursement.md) | borrower | 0 | —（一端无表现表） |
| [豁免](fee_waiver.md) | borrower | 1 | 0 次 |

### 本概念的角色

本概念是[客户](customer.md)的角色，成立条件：holds at least one loan whose status is not settled

## 5. 约束

（无）

## 6. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 6/10（60%） |
| 没有表现表 | 否 |
| 未绑定列 | 无 |
| 未落表属性 | 无 |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | `rel:fee_waiver.borrower` |
