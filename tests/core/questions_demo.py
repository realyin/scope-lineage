"""Shared fixtures for the ``questions`` tests: a small synthetic question set and grades.

The set is written as YAML with integer ``scoring`` keys, the way a person writes it, so
every test also exercises the loader. Tables and concepts are made up.
"""

from __future__ import annotations

import json
from pathlib import Path

CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
CONTRACT = "demo_dwd.dwd_loan_contract_info_df"

SET_YAML = f"""\
doc_format: question-set/1
subject: 演示客户切片
status: draft
scoring:
  2: 正确完整
  1: 方向对但不完整
  0: 错误或没找到
questions:
  - id: Q01
    table: {CUSTOMER}
    type: 粒度
    text: 这张表一行是什么？
    answer_key: 每个客户每个分区日一行，键是 cust_id + dt。
    evidence: [材料包 粒度节, "SQL: GROUP BY cust_id"]
  - id: Q02
    table: {CUSTOMER}
    type: 码值
    text: cust_status 取值 1 表示什么？
    answer_key: 1 表示正常。
    evidence: [列注释 cust_status]
    owner_check: 取值 2 的含义材料里没有，需要 owner 确认。
  - id: Q03
    table: {CONTRACT}
    type: 取数
    text: 取当前有效合同怎么写条件？
    answer_key: 取最新 dt 分区，contract_status = '1'。
    evidence: [记录范围节]
  - id: Q04
    concept: concept:customer
    type: 选表
    text: 要客户基本信息应该用哪张表？
    answer_key: 用 {CUSTOMER}。
    evidence: 概念页 数据清单
"""

ANSWERS_MD = """\
# 作答

前言不算任何一题。

## Q01

每个客户每天一行（见「一页纸 · 一行是什么」）。

### 依据

页面第一节。

## Q02 （码值题）

1 表示正常；2 的含义页面没写，待 owner 确认。

```text
## not-a-question
```

## Q03

不知道。
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_set(tmp_path: Path, text: str = SET_YAML) -> Path:
    return write(tmp_path / "questions.yaml", text)


def grades(round_label: str, scores: dict, **extra) -> dict:
    """A question-grades/1 document; ``scores`` maps id -> (score, gap[, reason])."""
    rows = []
    for qid, (score, gap, *reason) in scores.items():
        rows.append({
            "id": qid, "score": score, "gap": gap,
            "reason": reason[0] if reason else f"{qid} 的理由",
        })
    return {
        "doc_format": "question-grades/1", "set": "questions.yaml",
        "round": round_label, "grades": rows, **extra,
    }


def write_grades(tmp_path: Path, name: str, document: dict) -> Path:
    return write(tmp_path / name, json.dumps(document, ensure_ascii=False))
