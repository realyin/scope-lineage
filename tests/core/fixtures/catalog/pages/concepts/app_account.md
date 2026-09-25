# 应用账户

`concept:app_account` · 实体 · [客户与账户](../index.md) · 已确认（sql）

## 1. 定义与身份

The sign-in account a customer holds in one channel.

| 项 | 内容 |
| --- | --- |
| 种类 | 实体 |
| 状态 | 已确认（sql） |
| 同义词 | — |
| 主标识符 | 应用账户号 `id:app_account_id` |

### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 应用账户号 `id:app_account_id`（主） | 始终 | 每个渠道内唯一 | `demo_dwd.dwd_party_account_map_df.account_id` | — | 已确认（sql） |

## 2. 数据清单

### 标识映射

| 表 | 说明 | 粒度 | 时间语义 | 更新频率 | 记录范围 | 生产任务 | 表状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `demo_dwd.dwd_party_account_map_df` | 表注释：App account to customer map | 应用账户号 + 渠道编码（已证明）；血缘已证明 `account_id`、`channel_code` | 快照；按单个 dt 分区取数 | 调度 day | 全部 | dwd_party_account_map_daily | 在用 · 已确认（sql） |

- `demo_dwd.dwd_party_account_map_df` 血缘一跳：上游 `demo_ods.ods_app_account_df`；下游 `demo_dws.dws_lending_loan_summary_1d`

## 3. 带本概念标识的表

| 表 | 表的概念 | 列 | 标识符 | 方式 |
| --- | --- | --- | --- | --- |
| `demo_dwd.dwd_party_account_map_df` | 本概念 | `account_id` | 应用账户号 `id:app_account_id` | 标识符 |

## 4. 属性

### 时间

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 开户时间 `attr:app_account.opened_at` | When the account was opened in its channel. | timestamp | — | `demo_dwd.dwd_party_account_map_df.opened_time` | `demo_dwd.dwd_party_account_map_df.opened_time` = `` MIN(`ods_app_account_df`.`open_time`) ``（血缘） | 已确认（sql） |

## 5. 关系

### 关联、组成与泛化

| 关系 | 种类 | 读法 | 对端 | 基数 | 证据连接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| is opened in `rel:app_account_opened_in_channel` | 关联 | 应用账户 is opened in 渠道 | [渠道](channel.md) | 应用账户 0..* : 渠道 1 | —（一端无表现表）；同表携带两端：`demo_dwd.dwd_party_account_map_df`；目录证据：`demo_dwd.dwd_party_account_map_df.channel_code` | 已确认（sql） |
| holds `rel:customer_holds_app_account` | 组成 | 应用账户 is held by 客户 | [客户](customer.md) | 客户 1 : 应用账户 0..* | 1 次（如 `demo_dwd.dwd_party_customer_info_df.customer_id = demo_dwd.dwd_party_account_map_df.customer_id`） | 已确认（owner） |

### 参与的事件

（无）

### 本概念的角色

（无）

## 6. 约束

| 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `cons:one_account_per_channel` | 基数 | holds `rel:customer_holds_app_account` | a customer holds at most one account in each channel | 软 | 草拟（sql） |

## 7. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 1/12（8%） |
| 没有表现表 | 否 |
| 未绑定列 | 无 |
| 未落表属性 | 无 |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | 无 |
