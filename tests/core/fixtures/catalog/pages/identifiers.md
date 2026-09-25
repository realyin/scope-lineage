# 标识符

[返回目录](index.md)

## 应用账户号 `id:app_account_id`

| 项 | 内容 |
| --- | --- |
| 识别 | [应用账户](concepts/app_account.md) |
| 产生条件 | 始终 |
| 唯一范围 | 每个渠道内唯一 |
| 物理拼写 | `demo_dwd.dwd_party_account_map_df.account_id` |
| 对照 | — |
| 格式 | — |
| 绑定列 | `demo_dwd.dwd_party_account_map_df.account_id`（标识符） |
| 状态 | 已确认（sql） |
| 备注 | The same number can appear under two channels, so it is unique only per channel. |

## 渠道编码 `id:channel_code`

| 项 | 内容 |
| --- | --- |
| 识别 | [渠道](concepts/channel.md) |
| 产生条件 | 始终 |
| 唯一范围 | 全局 |
| 物理拼写 | `channel_code` |
| 对照 | — |
| 格式 | — |
| 绑定列 | `demo_dwd.dwd_party_account_map_df.channel_code`（外部标识符）；`demo_dws.dws_lending_loan_summary_1d.channel_code`（外部标识符） |
| 状态 | 已确认（owner） |

## 客户号 `id:customer_id`

| 项 | 内容 |
| --- | --- |
| 识别 | [客户](concepts/customer.md) |
| 产生条件 | 始终 |
| 唯一范围 | 全局 |
| 物理拼写 | `customer_id`；`demo_ods.ods_core_customer_df.cust_no` |
| 对照 | 应用账户号 一对多，经 `demo_dwd.dwd_party_account_map_df` |
| 格式 | C followed by ten digits |
| 绑定列 | `demo_dwd.dwd_lending_borrower_df.customer_id`（标识符）；`demo_dwd.dwd_lending_loan_df.customer_id`（外部标识符）；`demo_dwd.dwd_lending_repayment_di.customer_id`（外部标识符）；`demo_dwd.dwd_party_account_map_df.customer_id`（外部标识符）；`demo_dwd.dwd_party_customer_ext_df.customer_id`（标识符）；`demo_dwd.dwd_party_customer_info_df.customer_id`（标识符） |
| 状态 | 已确认（owner） |

## 放款流水号 `id:disbursement_txn_no`

| 项 | 内容 |
| --- | --- |
| 识别 | [放款](concepts/disbursement.md) |
| 产生条件 | 始终 |
| 唯一范围 | 全局 |
| 物理拼写 | `disburse_txn_no` |
| 对照 | — |
| 格式 | — |
| 绑定列 | （无） |
| 状态 | 草拟（sql） |

## 借据号 `id:loan_no`

| 项 | 内容 |
| --- | --- |
| 识别 | [借据](concepts/loan.md) |
| 产生条件 | 始终 |
| 唯一范围 | 全局 |
| 物理拼写 | `loan_no` |
| 对照 | — |
| 格式 | — |
| 绑定列 | `demo_dwd.dwd_collection_fee_waiver_di.loan_no`（外部标识符）；`demo_dwd.dwd_lending_loan_df.loan_no`（标识符）；`demo_dwd.dwd_lending_loan_status_his.loan_no`（标识符）；`demo_dwd.dwd_lending_repayment_di.loan_no`（外部标识符） |
| 状态 | 已确认（owner） |

## 还款流水号 `id:repayment_txn_no`

| 项 | 内容 |
| --- | --- |
| 识别 | [还款](concepts/repayment.md) |
| 产生条件 | 始终 |
| 唯一范围 | 全局 |
| 物理拼写 | `repay_txn_no` |
| 对照 | — |
| 格式 | — |
| 绑定列 | `demo_dwd.dwd_lending_repayment_di.repay_txn_no`（标识符） |
| 状态 | 已确认（mixed） |

## 认证客户号 `id:verified_customer_no`

| 项 | 内容 |
| --- | --- |
| 识别 | [客户](concepts/customer.md) |
| 产生条件 | assigned when the customer passes identity verification（状态：已认证） |
| 唯一范围 | 全局 |
| 物理拼写 | `verified_customer_no` |
| 对照 | 客户号 一对一 |
| 格式 | — |
| 绑定列 | `demo_dwd.dwd_party_customer_info_df.verified_customer_no`（标识符） |
| 状态 | 草拟（comment） |
