# 码值集

[返回目录](index.md)

## 性别 `code:gender`

| 项 | 内容 |
| --- | --- |
| 定义 | — |
| 取值 | F=female；M=male；U=unknown（停用） |
| 查找方式 | — |
| 使用它的属性 | 性别 `attr:customer.gender`（[客户](concepts/customer.md)） |
| 按顺序查它的列 | （无） |
| 状态 | 已确认（comment） |

## 借据状态 `code:loan_status`

| 项 | 内容 |
| --- | --- |
| 定义 | Where a loan is in its life cycle. |
| 取值 | 1=normal；2=overdue；3=settled；9（含义待确认：疑似核销） |
| 查找方式 | — |
| 使用它的属性 | 借据状态 `attr:loan.loan_status`（[借据](concepts/loan.md)） |
| 按顺序查它的列 | （无） |
| 状态 | 已确认（owner） |

## 认证状态 `code:verification_status`

| 项 | 内容 |
| --- | --- |
| 定义 | — |
| 取值 | 0=unverified；1=verified |
| 查找方式 | — |
| 使用它的属性 | 认证状态 `attr:customer.verification_status`（[客户](concepts/customer.md)） |
| 按顺序查它的列 | （无） |
| 状态 | 已确认（owner） |

## 豁免类型 `code:waiver_type`

| 项 | 内容 |
| --- | --- |
| 定义 | — |
| 取值 | PEN=penalty waived；INT=interest waived；OTH（含义待确认：other charges） |
| 查找方式 | — |
| 使用它的属性 | 豁免类型 `attr:fee_waiver.waiver_type`（[豁免](concepts/fee_waiver.md)） |
| 按顺序查它的列 | （无） |
| 状态 | 草拟（llm） |
