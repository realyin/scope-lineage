# 记录范围与有效性

[返回目录](index.md)

每张表现表的记录范围（scope）按过滤类别归组，类别由关键词判断；一行说到几类时每类都列。

## 有效记录/记录状态

| 表 | 概念 | 时间语义 | 记录范围 |
| --- | --- | --- | --- |
| `demo_dwd.dwd_party_customer_info_df` | [客户](concepts/customer.md) | 快照；按单个 dt 分区取数 | only customers whose customer_status is active |

## 删除/注销

| 表 | 概念 | 时间语义 | 记录范围 |
| --- | --- | --- | --- |
| `demo_dwd.dwd_party_customer_info_df` | [客户](concepts/customer.md) | 快照；按单个 dt 分区取数 | 注销客户不入表（is_cancelled = 1 的行被过滤） |

## 去重/最新

| 表 | 概念 | 时间语义 | 记录范围 |
| --- | --- | --- | --- |
| `demo_dwd.dwd_party_account_map_df` | [应用账户](concepts/app_account.md) | 快照；按单个 dt 分区取数 | latest row per account and channel (row_number = 1 by update_time) |

## 分区/快照日期

| 表 | 概念 | 时间语义 | 记录范围 |
| --- | --- | --- | --- |
| `demo_dwd.dwd_lending_loan_df` | [借据](concepts/loan.md) | 快照；按单个 dt 分区取数 | each dt partition is the full snapshot of that day |

## 其他

| 表 | 概念 | 时间语义 | 记录范围 |
| --- | --- | --- | --- |
| `demo_dwd.dwd_lending_borrower_df` | [借款人](concepts/borrower.md) | 快照；按单个 dt 分区取数 | customers holding at least one loan that is not settled |

## 未声明记录范围的表

- `demo_dwd.dwd_collection_fee_waiver_di`（[豁免](concepts/fee_waiver.md)）
- `demo_dwd.dwd_lending_loan_status_his`（[借据](concepts/loan.md)）
- `demo_dwd.dwd_lending_repayment_di`（[还款](concepts/repayment.md)）
- `demo_dwd.dwd_party_customer_ext_df`（[客户](concepts/customer.md)）
- `demo_dws.dws_lending_loan_summary_1d`（[借据](concepts/loan.md)）

## 引用了表的业务规则与值域约束

| 表 | 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_lending_loan_df` | `cons:principal_positive` | 值域 | 本金 `attr:loan.principal` | principal > 0 | 硬 | 已确认（owner） |
| `demo_dwd.dwd_party_customer_info_df` | `cons:active_customers_only` | 业务规则 | 客户 `concept:customer` | customer counts read only rows whose customer_status is active | 软 | 草拟（owner） |
