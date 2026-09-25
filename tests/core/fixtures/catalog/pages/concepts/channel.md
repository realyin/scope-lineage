# 渠道

`concept:channel` · 实体 · [客户与账户](../index.md) · 已确认（owner）

## 1. 定义与身份

An app or partner through which customers reach the shop.

| 项 | 内容 |
| --- | --- |
| 种类 | 实体 |
| 状态 | 已确认（owner） |
| 同义词 | — |
| 主标识符 | 渠道编码 `id:channel_code` |

### 标识符

| 标识符 | 产生条件 | 唯一范围 | 物理拼写 | 对照 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 渠道编码 `id:channel_code`（主） | 始终 | 全局 | `channel_code` | — | 已确认（owner） |

## 2. 数据清单

（目录未登记表现表）

## 3. 带本概念标识的表

| 表 | 表的概念 | 列 | 标识符 | 方式 |
| --- | --- | --- | --- | --- |
| `demo_dwd.dwd_party_account_map_df` | [应用账户](app_account.md) | `channel_code` | 渠道编码 `id:channel_code` | 外部标识符 |
| `demo_dws.dws_lending_loan_summary_1d` | [借据](loan.md) | `channel_code` | 渠道编码 `id:channel_code` | 外部标识符 |

## 4. 属性

### 描述

| 属性 | 定义 | 类型/单位 | 码值 | 所在表列 | 加工口径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 渠道名称 `attr:channel.channel_name` | The display name of the channel. | string | — | （未落表） | — | 已确认（owner） |

## 5. 关系

### 关联、组成与泛化

| 关系 | 种类 | 读法 | 对端 | 基数 | 证据连接 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| is opened in `rel:app_account_opened_in_channel` | 关联 | 渠道 hosts 应用账户 | [应用账户](app_account.md) | 应用账户 0..* : 渠道 1 | —（一端无表现表） | 已确认（sql） |

### 参与的事件

（无）

### 本概念的角色

（无）

## 6. 约束

（无）

## 7. 治理缺口

| 缺口 | 明细 |
| --- | --- |
| 草拟占比 | 0/4（0%） |
| 没有表现表 | 是 |
| 未绑定列 | 无 |
| 未落表属性 | `attr:channel.channel_name` |
| 缺码值的状态/码值类属性 | 无 |
| 证据与目录矛盾 | 无 |
| 元数据有、语料未用的绑定列 | 无 |
| 无连接证据的关系 | 无 |
