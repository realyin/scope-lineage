# 治理缺口

[返回目录](index.md)

## 按概念

| 概念 | 草拟占比 | 没有表现表 | 未绑定列 | 未落表属性 | 缺码值属性 |
| --- | --- | --- | --- | --- | --- |
| [应用账户](concepts/app_account.md) | 1/12（8%） | 否 | 0 | 0 | 0 |
| [借款人](concepts/borrower.md) | 6/10（60%） | 否 | 0 | 0 | 0 |
| [渠道](concepts/channel.md) | 0/4（0%） | 是 | 0 | 1 | 0 |
| [客户](concepts/customer.md) | 7/22（32%） | 否 | 1 | 0 | 0 |
| [放款](concepts/disbursement.md) | 1/6（17%） | 是 | 0 | 2 | 0 |
| [豁免](concepts/fee_waiver.md) | 13/13（100%） | 否 | 0 | 0 | 0 |
| [实名认证](concepts/identity_verification.md) | 3/3（100%） | 是 | 0 | 1 | 0 |
| [分期借据](concepts/installment_loan.md) | 3/5（60%） | 是 | 0 | 1 | 0 |
| [借据](concepts/loan.md) | 4/33（12%） | 否 | 0 | 0 | 0 |
| [还款](concepts/repayment.md) | 0/14（0%） | 否 | 0 | 0 | 0 |

## 没有表现表的概念

- [渠道](concepts/channel.md)
- [放款](concepts/disbursement.md)
- [实名认证](concepts/identity_verification.md)
- [分期借据](concepts/installment_loan.md)

## 未绑定列

- `demo_dwd.dwd_party_customer_ext_df.ext_json`

## 未落表属性

- 渠道名称 `attr:channel.channel_name`
- 放款时间 `attr:disbursement.disbursed_at`
- 放款金额 `attr:disbursement.amount`
- 认证时间 `attr:identity_verification.verified_at`
- 期数 `attr:installment_loan.term_count`

## 缺码值的状态/码值类属性

（无）

## 证据与目录矛盾

- `demo_dwd.dwd_lending_loan_df`：目录声明粒度已证明，血缘只到候选（`loan_no`）

## 元数据有、语料未用的绑定列

- `demo_dwd.dwd_lending_loan_status_his.loan_status`

## 无连接证据的关系

- `rel:fee_waiver.borrower`：豁免 borrower 借款人
- `rel:repayment.payer`：还款 payer 客户
- `rel:fee_waiver.loan`：豁免 loan 借据
- `rel:loan_renews_loan`：借据 renews 借据

## 含义待确认的码值

| 码值集 | 待确认的值（目录的猜测） | 使用它的属性 |
| --- | --- | --- |
| 借据状态 `code:loan_status` | `9`（疑似核销） | 借据状态 `attr:loan.loan_status` |
| 豁免类型 `code:waiver_type` | `OTH`（other charges） | 豁免类型 `attr:fee_waiver.waiver_type` |

## 冗余属性列（按表）

信息项，不算缺口：这些列在另一个概念的标识符旁重复该概念的属性。

| 表 | 冗余属性列数 | 列 |
| --- | --- | --- |
| `demo_dwd.dwd_lending_loan_df` | 1 | `customer_gender_cd`：客户.性别（经 `customer_id`） |
