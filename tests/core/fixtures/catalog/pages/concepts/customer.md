# 客户

`concept:customer` · 实体 · [客户与账户](../index.md) · 已确认（owner）

## 1. 定义与身份

A person the shop has registered, whether or not they ever borrow.

| 项 | 内容 |
| --- | --- |
| 种类 | 实体 |
| 状态 | 已确认（owner） |
| 同义词 | 用户 |
| 主标识符 | 客户号 `id:customer_id` |

### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 客户号 `id:customer_id`（主） | 始终 | 全局 | `customer_id`；`demo_ods.ods_core_customer_df.cust_no` | 应用账户号 一对多，经 `demo_dwd.dwd_party_account_map_df` | 已确认（owner） |
| 认证客户号 `id:verified_customer_no` | assigned when the customer passes identity verification（状态：已认证） | 全局 | `verified_customer_no` | 客户号 一对一 | 草拟（comment） |

### 状态机

状态属性：认证状态 `attr:customer.verification_status`

| 值 | 名称 |
| --- | --- |
| `unverified` | 未认证 |
| `verified` | 已认证 |

| 迁移事件 | 从 | 到 |
| --- | --- | --- |
| [实名认证](identity_verification.md) | 未认证 | 已认证 |

## 2. 数据清单

### 核心

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_party_customer_info_df` | 表注释：Customer master, one row per customer | 客户号（已证明）；血缘已证明 `customer_id` | 快照；按单个 dt 分区取数 | daily；调度 day | only customers whose customer_status is active；注销客户不入表（is_cancelled = 1 的行被过滤） | dwd_party_customer_info_daily | 在用 · 已确认（sql） |

- `demo_dwd.dwd_party_customer_info_df` 血缘一跳：上游 `demo_ods.ods_core_customer_df`；下游 `demo_dwd.dwd_lending_borrower_df`、`demo_dws.dws_lending_loan_summary_1d`

### 扩展

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_party_customer_ext_df` | — | 客户号（声明） | 快照；按单个 dt 分区取数 | — | 全部 | — | 在用 · 草拟（comment） |

## 3. 带本概念标识的表

| 表 | 表的概念 | 列 | 标识符 | 方式 |
| --- | --- | --- | --- | --- |
| `demo_dwd.dwd_lending_borrower_df` | [借款人](borrower.md) | `customer_id` | 客户号 `id:customer_id` | 标识符 |
| `demo_dwd.dwd_lending_loan_df` | [借据](loan.md) | `customer_id` | 客户号 `id:customer_id` | 外部标识符 |
| `demo_dwd.dwd_lending_repayment_di` | [还款](repayment.md) | `customer_id` | 客户号 `id:customer_id` | 外部标识符 |
| `demo_dwd.dwd_party_account_map_df` | [应用账户](app_account.md) | `customer_id` | 客户号 `id:customer_id` | 外部标识符 |
| `demo_dwd.dwd_party_customer_ext_df` | 本概念 | `customer_id` | 客户号 `id:customer_id` | 标识符 |
| `demo_dwd.dwd_party_customer_info_df` | 本概念 | `customer_id` | 客户号 `id:customer_id` | 标识符 |
| `demo_dwd.dwd_party_customer_info_df` | 本概念 | `verified_customer_no` | 认证客户号 `id:verified_customer_no` | 标识符 |

## 4. 属性

### 描述

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 性别 `attr:customer.gender` | The gender the customer declared at registration. | string | F=female；M=male；U=unknown（停用） | `demo_dwd.dwd_lending_borrower_df.gender_cd`；`demo_dwd.dwd_lending_loan_df.customer_gender_cd` 冗余（经 `customer_id`）；`demo_dwd.dwd_party_customer_info_df.gender_cd`（码值映射 F→female, M→male, U→unknown） | `demo_dwd.dwd_lending_borrower_df.gender_cd` = `` MAX(`c`.`gender_cd`) ``（血缘）；`demo_dwd.dwd_lending_loan_df.customer_gender_cd` = `` `l`.`cust_gender` ``（血缘）；`demo_dwd.dwd_party_customer_info_df.gender_cd` = `` `latest`.`gender_cd` ``（血缘） | 已确认（owner） |

### 状态

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 认证状态 `attr:customer.verification_status` | Whether the customer has passed identity verification. | integer | 0=unverified；1=verified | `demo_dwd.dwd_party_customer_info_df.verify_status` | `demo_dwd.dwd_party_customer_info_df.verify_status` = `` `latest`.`verify_status` ``（血缘） | 已确认（owner） |

### 时间

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 注册时间 `attr:customer.registered_at` | When the customer first registered. | timestamp | — | `demo_dwd.dwd_party_customer_info_df.register_time` | `demo_dwd.dwd_party_customer_info_df.register_time`：from_unixtime(register_ts) | 已确认（owner） |

## 5. 关系

### 关联、组成与泛化

| 关系 | 种类 | 读法 | 对端 | 基数 | 证据连接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| holds `rel:customer_holds_app_account` | 组成 | 客户 holds 应用账户 | [应用账户](app_account.md) | 客户 1 : 应用账户 0..* | 1 次（如 `demo_dwd.dwd_party_customer_info_df.customer_id = demo_dwd.dwd_party_account_map_df.customer_id`） | 已确认（owner） |

### 参与的事件

| 事件 | 本概念角色 | 事件表现表数 | 证据连接 |
| --- | --- | --- | --- |
| [实名认证](identity_verification.md) | customer | 0 | —（一端无表现表） |
| [还款](repayment.md) | payer | 1 | 0 次；同表携带两端：`demo_dwd.dwd_lending_repayment_di` |

### 本概念的角色

| 角色 | 语境 | 成立条件 | 表现表数 |
| --- | --- | --- | --- |
| [借款人](borrower.md) | 贷款 | holds at least one loan whose status is not settled | 1 |

## 6. 约束

| 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `cons:one_account_per_channel` | 基数 | holds `rel:customer_holds_app_account` | a customer holds at most one account in each channel | 软 | 草拟（sql） |
| `cons:active_customers_only` | 业务规则 | 客户 `concept:customer` | customer counts read only rows whose customer_status is active | 软 | 草拟（owner） |

## 7. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 8/23（35%） |
| 没有表现表 | 否 |
| 未绑定列 | `demo_dwd.dwd_party_customer_ext_df.ext_json` |
| 未落表属性 | 无 |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | `rel:repayment.payer` |
