# 借据

`concept:loan` · 实体 · [贷款](../index.md) · 已确认（owner）

## 1. 定义与身份

One amount lent to a borrower, repaid over one or more instalments.

| 项 | 内容 |
| --- | --- |
| 种类 | 实体 |
| 状态 | 已确认（owner） |
| 同义词 | 对客借据 |
| 主标识符 | 借据号 `id:loan_no` |

### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 借据号 `id:loan_no`（主） | 始终 | 全局 | `loan_no` | — | 已确认（owner） |

### 状态机

状态属性：借据状态 `attr:loan.loan_status`

| 值 | 名称 |
| --- | --- |
| `normal` | 正常 |
| `overdue` | 逾期 |
| `settled` | 结清 |

| 迁移事件 | 从 | 到 |
| --- | --- | --- |
| [还款](repayment.md) | 逾期 | 正常 |
| [还款](repayment.md) | 正常 | 结清 |
| [豁免](fee_waiver.md) | 逾期 | 结清 |

## 2. 数据清单

### 核心

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_lending_loan_df` | 表注释：Loan snapshot；备注：A renewal loan names the loan it renews in orig_loan_no; the renewed loan stays in the table as settled. | 借据号（已证明）；血缘候选 `loan_no` | 快照；按单个 dt 分区取数 | daily；调度 day | 全部 | dwd_lending_loan_daily | 在用 · 已确认（sql） |

- `demo_dwd.dwd_lending_loan_df` 血缘一跳：上游 `demo_ods.ods_loan_contract_df`、`demo_ods.ods_loan_penalty_di`；下游 `demo_ads.ads_collection_overdue_loan_df`、`demo_dwd.dwd_lending_borrower_df`、`demo_dwd.dwd_lending_repayment_di`、`demo_dws.dws_lending_loan_summary_1d`

### 状态历史

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_lending_loan_status_his` | 表注释：Loan status history (zipper) | 借据号 + `start_date`（声明） | 拉链；按有效期窗口取数（start_date ≤ 查询日 < end_date，端点开闭以表口径为准） | — | 全部 | — | 在用 · 已确认（owner） |

- `demo_dwd.dwd_lending_loan_status_his` 血缘一跳：下游 `demo_ads.ads_loan_status_span_df`

### 汇总

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dws.dws_lending_loan_summary_1d` | 表注释：Loans per channel per day | 渠道编码 + `stat_date`（声明）；血缘已证明 `channel_code` | 增量 | 调度 day | 全部 | dws_lending_loan_summary_daily | 已废弃 · 已确认（owner）；由 `demo_dws.dws_lending_loan_summary_v2_1d` 替代 |

- `demo_dws.dws_lending_loan_summary_1d` 血缘一跳：上游 `demo_dwd.dwd_lending_loan_df`、`demo_dwd.dwd_party_account_map_df`、`demo_dwd.dwd_party_customer_info_df`

## 3. 带本概念标识的表

| 表 | 表的概念 | 列 | 标识符 | 方式 |
| --- | --- | --- | --- | --- |
| `demo_dwd.dwd_collection_fee_waiver_di` | [豁免](fee_waiver.md) | `loan_no` | 借据号 `id:loan_no` | 外部标识符 |
| `demo_dwd.dwd_lending_loan_df` | 本概念 | `loan_no` | 借据号 `id:loan_no` | 标识符 |
| `demo_dwd.dwd_lending_loan_df` | 本概念 | `orig_loan_no` | 借据号 `id:loan_no` | 外部标识符（自关联） |
| `demo_dwd.dwd_lending_loan_status_his` | 本概念 | `loan_no` | 借据号 `id:loan_no` | 标识符 |
| `demo_dwd.dwd_lending_repayment_di` | [还款](repayment.md) | `loan_no` | 借据号 `id:loan_no` | 外部标识符 |

## 4. 属性

### 状态

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 借据状态 `attr:loan.loan_status` | Where the loan is in its life cycle. | string | 1=normal；2=overdue；3=settled；9（含义待确认：疑似核销） | `demo_dwd.dwd_lending_loan_df.loan_status`（码值映射 1→normal, 2→overdue, 3→settled）；`demo_dwd.dwd_lending_loan_status_his.loan_status`（元数据有、语料未用） | `demo_dwd.dwd_lending_loan_df.loan_status` = `` `l`.`loan_status` ``（血缘） | 已确认（owner） |

### 度量

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 本金 `attr:loan.principal` | The amount lent. | decimal(18,2) / CNY | — | `demo_dwd.dwd_lending_loan_df.principal_amt` | `demo_dwd.dwd_lending_loan_df.principal_amt` = `` `l`.`principal` ``（血缘） | 已确认（owner） |
| 逾期罚息 `attr:loan.overdue_penalty` | Penalty interest accrued while the loan is overdue. | decimal(18,2) / CNY | — | `demo_dwd.dwd_lending_loan_df.penalty_amt` | overdue principal x daily penalty rate x days overdue；`demo_dwd.dwd_lending_loan_df.penalty_amt`：sum of the daily penalty accruals up to dt | 已确认（owner） |

## 5. 关系

### 关联、组成与泛化

| 关系 | 种类 | 读法 | 对端 | 基数 | 证据连接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| owes `rel:borrower_owes_loan` | 关联 | 借据 is owed by 借款人 | [借款人](borrower.md) | 借款人 1 : 借据 1..* | 1 次（如 `demo_dwd.dwd_lending_borrower_df.customer_id = demo_dwd.dwd_lending_loan_df.customer_id`） | 已确认（owner） |
| is a kind of `rel:installment_loan_is_a_loan` | 泛化 | 分期借据 is a kind of 借据 | [分期借据](installment_loan.md) | 分期借据 0..1 : 借据 1 | —（一端无表现表）；同表携带两端：`demo_dwd.dwd_collection_fee_waiver_di`、`demo_dwd.dwd_lending_loan_df`、`demo_dwd.dwd_lending_loan_status_his`、`demo_dwd.dwd_lending_repayment_di` | 草拟（llm） |
| renews `rel:loan_renews_loan` | 关联 | 借据 renews 借据 | 本概念（自关联，经 `demo_dwd.dwd_lending_loan_df.orig_loan_no`） | 借据 0..1 : 借据 0..1 | 0 次；同表携带两端：`demo_dwd.dwd_lending_loan_df`；目录证据：`demo_dwd.dwd_lending_loan_df.orig_loan_no` | 草拟（sql） |

### 参与的事件

| 事件 | 本概念角色 | 事件表现表数 | 证据连接 |
| --- | --- | --- | --- |
| [放款](disbursement.md) | loan | 0 | —（一端无表现表） |
| [豁免](fee_waiver.md) | loan | 1 | 0 次；同表携带两端：`demo_dwd.dwd_collection_fee_waiver_di` |
| [还款](repayment.md) | loan | 1 | 1 次（如 `demo_dwd.dwd_lending_loan_df.loan_no = demo_dwd.dwd_lending_repayment_di.loan_no`） |

### 本概念的角色

（无）

## 6. 约束

| 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `cons:loan_no_unique` | 唯一 | 借据号 `id:loan_no` | no two loans share a loan_no, whatever the channel | 硬 | 已确认（owner） |
| `cons:principal_positive` | 值域 | 本金 `attr:loan.principal` | principal > 0 | 硬 | 已确认（owner） |
| `cons:settled_is_final` | 状态迁移 | 借据状态 `attr:loan.loan_status` | a settled loan never changes status again | 硬 | 已确认（owner） |
| `cons:penalty_rule` | 派生 | 逾期罚息 `attr:loan.overdue_penalty` | accrues only while loan_status is overdue | 软 | 草拟（comment） |

## 7. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 4/33（12%） |
| 没有表现表 | 否 |
| 未绑定列 | 无 |
| 未落表属性 | 无 |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | `demo_dwd.dwd_lending_loan_df`：目录声明粒度已证明，血缘只到候选（`loan_no`） |
| 元数据有、语料未用的绑定列 | `demo_dwd.dwd_lending_loan_status_his.loan_status` |
| 无连接证据的关系 | `rel:fee_waiver.loan`；`rel:loan_renews_loan` |
