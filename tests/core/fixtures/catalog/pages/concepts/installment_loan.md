# 分期借据

`concept:installment_loan` · 实体 · [贷款](../index.md) · 草拟（llm）

## 1. 定义与身份

A loan repaid in fixed monthly instalments.

| 项 | 内容 |
| --- | --- |
| 种类 | 实体 |
| 状态 | 草拟（llm） |
| 同义词 | — |
| 主标识符 | 借据号 `id:loan_no` |

### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 借据号 `id:loan_no`（主） | 始终 | 全局 | `loan_no` | — | 已确认（owner） |

## 2. 数据清单

（目录未登记表现表）

## 3. 带本概念标识的表

| 表 | 表的概念 | 列 | 标识符 | 方式 |
| --- | --- | --- | --- | --- |
| `demo_dwd.dwd_collection_fee_waiver_di` | [豁免](fee_waiver.md) | `loan_no` | 借据号 `id:loan_no` | 外部标识符 |
| `demo_dwd.dwd_lending_loan_df` | [借据](loan.md) | `loan_no` | 借据号 `id:loan_no` | 标识符 |
| `demo_dwd.dwd_lending_loan_df` | [借据](loan.md) | `orig_loan_no` | 借据号 `id:loan_no` | 外部标识符（自关联） |
| `demo_dwd.dwd_lending_loan_status_his` | [借据](loan.md) | `loan_no` | 借据号 `id:loan_no` | 标识符 |
| `demo_dwd.dwd_lending_repayment_di` | [还款](repayment.md) | `loan_no` | 借据号 `id:loan_no` | 外部标识符 |

## 4. 属性

### 描述

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 期数 `attr:installment_loan.term_count` | How many instalments the loan is split into. | integer | — | （未落表） | — | 草拟（llm） |

## 5. 关系

### 关联、组成与泛化

| 关系 | 种类 | 读法 | 对端 | 基数 | 证据连接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| is a kind of `rel:installment_loan_is_a_loan` | 泛化 | 分期借据 is a kind of 借据 | [借据](loan.md) | 分期借据 0..1 : 借据 1 | —（一端无表现表） | 草拟（llm） |

### 参与的事件

（无）

### 本概念的角色

（无）

## 6. 约束

| 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `cons:loan_no_unique` | 唯一 | 借据号 `id:loan_no` | no two loans share a loan_no, whatever the channel | 硬 | 已确认（owner） |

## 7. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 3/5（60%） |
| 没有表现表 | 是 |
| 未绑定列 | 无 |
| 未落表属性 | `attr:installment_loan.term_count` |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | 无 |
