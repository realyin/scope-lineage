# 豁免

`concept:fee_waiver` · 事件 · [催收](../index.md) · 草拟（llm）

## 1. 定义与身份

The shop forgives part of what an overdue loan owes.

| 项 | 内容 |
| --- | --- |
| 种类 | 事件 |
| 状态 | 草拟（llm） |
| 同义词 | — |
| 发生时间 | 豁免时间 `attr:fee_waiver.waived_at` |
| 参与者 loan | [借据](loan.md)（一个） |
| 参与者 borrower | [借款人](borrower.md)（一个） |

### 标识符

（目录未登记标识符）

## 2. 数据清单

### 事件明细

| 表 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_collection_fee_waiver_di` | `waiver_seq`（推断） | 增量 | — | 全部 | — | 在用 · 草拟（llm） |

## 3. 属性

### 描述

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 豁免类型 `attr:fee_waiver.waiver_type` | What part of the debt was forgiven. | string | PEN=penalty waived；INT=interest waived；OTH（含义待确认：other charges） | `demo_dwd.dwd_collection_fee_waiver_di.waiver_type`（码值映射 PEN→penalty waived, INT→interest waived） | — | 草拟（llm） |

### 度量

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 豁免金额 `attr:fee_waiver.amount` | The amount forgiven. | decimal(18,2) / CNY | — | `demo_dwd.dwd_collection_fee_waiver_di.waive_amt` | — | 草拟（llm） |

### 时间

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 豁免时间 `attr:fee_waiver.waived_at` | When the waiver took effect. | timestamp | — | `demo_dwd.dwd_collection_fee_waiver_di.waive_time` | — | 草拟（llm） |

## 4. 关系

### 关联、组成与泛化

（无）

### 参与的事件

（无）

### 本概念的角色

（无）

## 5. 约束

（无）

## 6. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 13/13（100%） |
| 没有表现表 | 否 |
| 未绑定列 | 无 |
| 未落表属性 | 无 |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | `rel:fee_waiver.borrower`；`rel:fee_waiver.loan` |
