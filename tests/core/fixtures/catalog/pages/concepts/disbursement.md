# 放款

事件 · [贷款](../index.md) · 本页 17% 草拟、已确认的条目标 ✓

## 一页纸概览

**是什么**：The shop pays the principal of a loan out to the borrower.

**怎么认出来**：

- 放款流水号：一开始就有，全局唯一

**参与者**：borrower → 借款人；loan → 借据

**发生时间**：放款时间

## 附录

### A1 定义与身份

The shop pays the principal of a loan out to the borrower.

| 项 | 内容 |
| --- | --- |
| 编号 | `concept:disbursement` |
| 种类 | 事件 |
| 状态 | 已确认（task） |
| 同义词 | — |
| 发生时间 | 放款时间 `attr:disbursement.disbursed_at` |
| 参与者 borrower | [借款人](borrower.md)（一个） |
| 参与者 loan | [借据](loan.md)（一个） |

#### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 放款流水号 `id:disbursement_txn_no` | 始终 | 全局 | `disburse_txn_no` | — | 草拟（sql） |

### A2 数据清单

（目录未登记表现表）

### A3 带本概念标识的表

（没有表绑定本概念的标识符）

### A4 属性

#### 度量

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 放款金额 `attr:disbursement.amount` | The amount paid out. | decimal(18,2) / CNY | — | （未落表） | — | 已确认（task） |

#### 时间

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 放款时间 `attr:disbursement.disbursed_at` | When the money left the shop. | timestamp | — | （未落表） | — | 已确认（task） |

### A5 关系

#### 关联、组成与泛化

（无）

#### 参与的事件

（无）

#### 本概念的角色

（无）

### A6 约束

（无）

### A7 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 1/6（17%） |
| 没有表现表 | 是 |
| 未绑定列 | 无 |
| 未落表属性 | `attr:disbursement.disbursed_at`；`attr:disbursement.amount` |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | 无 |
