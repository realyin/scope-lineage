"""Run a statement's SQL on real rows, so a claim can be checked against what happens.

The tool's conclusions are about data it never sees: "this output is unique by ``id``",
"this JOIN cannot duplicate a row". A snapshot test pins what the tool *says*; it cannot
tell whether that is *true* -- the ``rank() = 1`` test pinned the wrong answer for as long
as it existed. A witness runs the same SQL in SQLite over small tables whose values come
from a three-value domain, so collisions, ties and duplicates are the normal case, and
checks the property the claim asserts.

The rule a witness enforces is one-directional: **claimed ⇒ holds** on every dataset.
A claim the tool does not make is never a failure here; a claim it makes that one
dataset breaks always is.

SQLite stands in for Spark only on the shared subset these statements use (GROUP BY,
DISTINCT, window ranking, joins, IN, CASE). Spark-specific semantics -- partition
overwrite modes, sort stability -- are simulated explicitly or not covered.
"""

from __future__ import annotations

import random
import sqlite3
from typing import Iterable, Iterator, Mapping, Sequence

# Every table a witness reads or writes, with its columns. `ods.base.rid` is a serial row
# id: a JOIN duplicated a base row exactly when a `rid` appears twice in the result.
TABLES: dict[str, list[str]] = {
    "ods.e": ["id", "v", "ts", "dt", "keep"],
    "ods.base": ["rid", "id", "b"],
    "mart.dim": ["id", "v", "dt"],
}
SCHEMAS = ("ods", "mart")
DOMAIN = (1, 2, 3)
SQLITE_SUPPORTS_WINDOWS = sqlite3.sqlite_version_info >= (3, 25, 0)


def connect(rows: Mapping[str, Sequence[tuple]]) -> sqlite3.Connection:
    """A fresh in-memory database holding ``rows``, table names spelt ``schema.table``."""
    db = sqlite3.connect(":memory:")
    for schema in SCHEMAS:
        db.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
    for table, columns in TABLES.items():
        db.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        data = list(rows.get(table) or [])
        if data:
            marks = ", ".join("?" for _ in columns)
            db.executemany(f"INSERT INTO {table} VALUES ({marks})", data)
    return db


def datasets(seed: int, count: int = 30) -> Iterator[dict[str, list[tuple]]]:
    """``count`` small random corpora over ``DOMAIN``: seeded, so a failure reproduces."""
    rng = random.Random(seed)
    for _ in range(count):
        events = [
            tuple(rng.choice(DOMAIN) for _ in TABLES["ods.e"])
            for _ in range(rng.randint(0, 7))
        ]
        base = [
            (rid, rng.choice(DOMAIN), rng.choice(DOMAIN))
            for rid in range(rng.randint(0, 5))
        ]
        yield {"ods.e": events, "ods.base": base}


def query(db: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple]]:
    cursor = db.execute(sql)
    return [item[0] for item in cursor.description or []], cursor.fetchall()


def unique_by(columns: Sequence[str], rows: Iterable[tuple], keys: Sequence[str]) -> bool:
    """Whether no two rows agree on ``keys`` (an empty key set: at most one row)."""
    positions = [columns.index(key) for key in keys]
    seen: set[tuple] = set()
    for row in rows:
        value = tuple(row[position] for position in positions)
        if value in seen:
            return False
        seen.add(value)
    return True


def schema_map() -> dict[str, list[str]]:
    """The same tables, as the tool's schema argument."""
    return {table: list(columns) for table, columns in TABLES.items()}
