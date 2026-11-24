"""Inputs for the page-answer tests: the demo semantics document with three questions, and
a second table's document built from it, so an answer can cross two tables."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from service_paths import CUSTOMER, LOAN

QUESTIONS = [
    {"id": "q1", "text": "性别码值除了 F、M、U 以外，还会不会出现其他值？",
     "about": ["column:gender_cd"], "status": "open"},
    {"id": "q2", "text": "客户号在同一分区内是否唯一？", "about": [], "status": "open"},
    {"id": "q3", "text": "实名认证状态的取值含义是什么？", "about": [], "status": "open"},
]


def document_path(semantics: Path, table: str) -> Path:
    return semantics / f"{table}.json"


def read_document(semantics: Path, table: str) -> dict:
    return json.loads(document_path(semantics, table).read_text(encoding="utf-8"))


def write_document(semantics: Path, table: str, document: dict) -> None:
    path = document_path(semantics, table)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    touch_later(path)


def touch_later(path: Path, seconds: int = 10) -> None:
    """Move a file's mtime forward, so a signature taken in the same instant still differs."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 1_000_000_000))


def prepare(semantics: Path) -> None:
    """Three questions on the customer table, and a loan table document with two."""
    customer = read_document(semantics, CUSTOMER)
    customer["summary"]["questions"] = copy.deepcopy(QUESTIONS)
    write_document(semantics, CUSTOMER, customer)
    loan = copy.deepcopy(customer)
    loan["table"] = LOAN
    loan["summary"]["questions"] = [
        {"id": "q1", "text": "放款日期是否可能晚于到期日？", "about": [], "status": "open"},
        {"id": "q2", "text": "贷款余额的单位是元还是分？", "about": [], "status": "open"},
    ]
    write_document(semantics, LOAN, loan)


def set_question(semantics: Path, table: str, question: str, **fields) -> None:
    """Change one question of a document on disk (as a rewrite or a confirm would)."""
    document = read_document(semantics, table)
    for item in document["summary"]["questions"]:
        if item["id"] == question:
            item.update(fields)
            for key in [k for k, v in fields.items() if v is None]:
                item.pop(key)
    write_document(semantics, table, document)


def answer_on_disk(semantics: Path, table: str, question: str, answer: str, by: str, on: str):
    set_question(semantics, table, question, status="answered", answer=answer, answered_by=by,
                 answered_on=on)


def text_of(semantics: Path, table: str, question: str) -> str:
    document = read_document(semantics, table)
    return next(q["text"] for q in document["summary"]["questions"] if q["id"] == question)
