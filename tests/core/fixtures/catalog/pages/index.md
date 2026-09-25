# 本体目录：demo-lending

A fictional consumer-lending shop. Every name in this catalog is synthetic; it exists to show each element of the catalog-yaml/1 format once.

> ontology-json/3 · 10 个概念 · 18 个属性 · 12 条关系 · 9 张表现表 · 血缘证据 8 个任务 · 表卡证据 15 张

## 概念

### 催收 `domain:collection`

Work on overdue loans, including the waivers granted to settle them.

| 概念 | 种类 | 定义 | 表现表 | 状态 |
| --- | --- | --- | --- | --- |
| [豁免](concepts/fee_waiver.md) | 事件 | The shop forgives part of what an overdue loan owes. | 1 | 草拟（llm） |

### 贷款 `domain:lending`

Loans from disbursement to settlement.

| 概念 | 种类 | 定义 | 表现表 | 状态 |
| --- | --- | --- | --- | --- |
| [借款人](concepts/borrower.md) | 角色 | A customer while they hold at least one loan that is not settled. | 1 | 已确认（owner） |
| [放款](concepts/disbursement.md) | 事件 | The shop pays the principal of a loan out to the borrower. | 0 | 已确认（task） |
| [分期借据](concepts/installment_loan.md) | 实体 | A loan repaid in fixed monthly instalments. | 0 | 草拟（llm） |
| [借据](concepts/loan.md) | 实体 | One amount lent to a borrower, repaid over one or more instalments. | 3 | 已确认（owner） |
| [还款](concepts/repayment.md) | 事件 | A customer pays money back against one or more loans. | 1 | 已确认（sql） |

### 客户与账户 `domain:party`

Who the shop lends to and the accounts they sign in with.

| 概念 | 种类 | 定义 | 表现表 | 状态 |
| --- | --- | --- | --- | --- |
| [应用账户](concepts/app_account.md) | 实体 | The sign-in account a customer holds in one channel. | 1 | 已确认（sql） |
| [渠道](concepts/channel.md) | 实体 | An app or partner through which customers reach the shop. | 0 | 已确认（owner） |
| [客户](concepts/customer.md) | 实体 | A person the shop has registered, whether or not they ever borrow. | 2 | 已确认（owner） |
| [实名认证](concepts/identity_verification.md) | 事件 | The customer proves who they are; afterwards they may borrow. | 0 | 草拟（comment） |

## 标识符

| 标识符 | 识别 | 唯一范围 | 物理拼写 | 状态 |
| --- | --- | --- | --- | --- |
| 应用账户号 `id:app_account_id` | [应用账户](concepts/app_account.md) | 每个渠道内唯一 | `demo_dwd.dwd_party_account_map_df.account_id` | 已确认（sql） |
| 渠道编码 `id:channel_code` | [渠道](concepts/channel.md) | 全局 | `channel_code` | 已确认（owner） |
| 客户号 `id:customer_id` | [客户](concepts/customer.md) | 全局 | `customer_id`；`demo_ods.ods_core_customer_df.cust_no` | 已确认（owner） |
| 放款流水号 `id:disbursement_txn_no` | [放款](concepts/disbursement.md) | 全局 | `disburse_txn_no` | 草拟（sql） |
| 借据号 `id:loan_no` | [借据](concepts/loan.md) | 全局 | `loan_no` | 已确认（owner） |
| 还款流水号 `id:repayment_txn_no` | [还款](concepts/repayment.md) | 全局 | `repay_txn_no` | 已确认（mixed） |
| 认证客户号 `id:verified_customer_no` | [客户](concepts/customer.md) | 全局 | `verified_customer_no` | 草拟（comment） |

完整说明见 [identifiers.md](identifiers.md)。

## 治理缺口

| 缺口 | 数量 |
| --- | --- |
| 草拟对象占比 | 42/122（34%） |
| 没有表现表的概念 | 4 |
| 未绑定列 | 1 |
| 未落表属性 | 5 |
| 缺码值的状态/码值类属性 | 0 |
| 证据与目录矛盾 | 1 |
| 元数据有、语料未用的绑定列 | 1 |
| 无连接证据的关系 | 4 |

逐项明细见 [governance.md](governance.md)。
