# 还款

`concept:repayment` · 事件 · [贷款](../index.md) · 已确认（sql）

## 1. 定义与身份

A customer pays money back against one or more loans.

| 项 | 内容 |
| --- | --- |
| 种类 | 事件 |
| 状态 | 已确认（sql） |
| 同义词 | — |
| 发生时间 | 还款时间 `attr:repayment.repaid_at` |
| 参与者 payer | [客户](customer.md)（一个） |
| 参与者 loan | [借据](loan.md)（多个） |

### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 还款流水号 `id:repayment_txn_no` | 始终 | 全局 | `repay_txn_no` | — | 已确认（mixed） |

## 2. 数据清单

### 事件明细

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_lending_repayment_di` | 表注释：Repayments | 还款流水号（已证明）；血缘已证明 `repay_txn_no` | 增量 | daily；调度 day | 全部 | dwd_lending_repayment_daily | 在用 · 已确认（sql） |

- `demo_dwd.dwd_lending_repayment_di` 血缘一跳：上游 `demo_dwd.dwd_lending_loan_df`、`demo_ods.ods_repay_txn_di`；下游 `demo_ads.ads_collection_overdue_loan_df`

## 3. 属性

### 度量

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 还款金额 `attr:repayment.amount` | The amount received. | decimal(18,2) / CNY | — | `demo_dwd.dwd_lending_repayment_di.repay_amt` | `demo_dwd.dwd_lending_repayment_di.repay_amt` = `` SUM(CAST(`r`.`amount` AS DECIMAL(18, 2))) ``（血缘） | 已确认（sql） |

### 时间

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 还款时间 `attr:repayment.repaid_at` | When the payment was received. | timestamp | — | `demo_dwd.dwd_lending_repayment_di.repay_time` | `demo_dwd.dwd_lending_repayment_di.repay_time` = `` MAX(`r`.`paid_time`) ``（血缘） | 已确认（sql） |

## 4. 关系

### 关联、组成与泛化

（无）

### 参与的事件

（无）

### 本概念的角色

（无）

## 5. 约束

| 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `cons:repaid_after_disbursed` | 时间 | 还款 `concept:repayment` | repaid_at is not earlier than the disbursed_at of every loan it pays | 硬 | 已确认（owner） |

## 6. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 0/14（0%） |
| 没有表现表 | 否 |
| 未绑定列 | 无 |
| 未落表属性 | 无 |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | `rel:repayment.payer` |
