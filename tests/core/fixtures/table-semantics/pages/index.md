# 表语义目录

共 2 张表，每张一页。「校验通过率」取自 `semantic validate --json` 的报告，没有报告时写 —；「待确认问题」是还没回答的问题数。

## 按域

### 催收

| 表 | 这张表是什么 | 校验通过率 | 待确认问题 |
| --- | --- | --- | --- |
| [`demo_dwd.dwd_collection_fee_waiver_di`](demo_dwd.dwd_collection_fee_waiver_di.md) | 借据上发生的每一笔豁免，把「线上按余额成分豁免」和「线下豁免还款」两类合在一张表里。 | 93.8% | 2 |

### 客户与账户

| 表 | 这张表是什么 | 校验通过率 | 待确认问题 |
| --- | --- | --- | --- |
| [`demo_dwd.dwd_party_customer_info_df`](demo_dwd.dwd_party_customer_info_df.md) | 客户主表：每个客户号一行，取核心系统客户注册记录里最后更新的一条。 | 100.0% | 1 |

## 按概念

### [客户](../concepts/customer.md)

| 表 | 表现类型 | 这张表是什么 | 校验通过率 | 待确认问题 |
| --- | --- | --- | --- | --- |
| [`demo_dwd.dwd_party_customer_info_df`](demo_dwd.dwd_party_customer_info_df.md) | 核心 | 客户主表：每个客户号一行，取核心系统客户注册记录里最后更新的一条。 | 100.0% | 1 |

### [豁免](../concepts/fee_waiver.md)

| 表 | 表现类型 | 这张表是什么 | 校验通过率 | 待确认问题 |
| --- | --- | --- | --- | --- |
| [`demo_dwd.dwd_collection_fee_waiver_di`](demo_dwd.dwd_collection_fee_waiver_di.md) | 事件明细 | 借据上发生的每一笔豁免，把「线上按余额成分豁免」和「线下豁免还款」两类合在一张表里。 | 93.8% | 2 |
