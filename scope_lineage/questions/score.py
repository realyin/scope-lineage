"""Summing one grading round, and earlier rounds beside it (``question-score/1``).

Only graded questions count toward the maximum; ungraded ones are listed instead, so a
round over a sample scores the sample. Every round is scored over the same questions,
which is what makes the comparison columns comparable.
"""

from __future__ import annotations

from .select import place_of, type_of
from .sheets import GAPS

SCORE_FORMAT = "question-score/1"


def graded_ids_outside(questions: list[dict], grades: dict) -> list[str]:
    """Ids a grades document scores that the set does not have."""
    known = {question["id"] for question in questions}
    return [grade["id"] for grade in grades["grades"] if grade["id"] not in known]


def label_rounds(rounds: list[tuple[object, str]]) -> list[str]:
    """One distinct label per ``(round, file stem)``; the last (current) round wins ties."""
    used: set[str] = set()
    labels: list[str] = [""] * len(rounds)
    for index in [len(rounds) - 1, *range(len(rounds) - 1)]:
        declared, stem = rounds[index]
        label = str(declared) if declared not in (None, "") else stem
        if label in used:
            label = stem
        base, n = label, 2
        while label in used:
            label, n = f"{base}#{n}", n + 1
        used.add(label)
        labels[index] = label
    return labels


def score_report(
    questions: list[dict], rounds: list[tuple[str, dict]], *, set_label: str, subject: str
) -> dict:
    """The report over ``questions`` for ``rounds`` (oldest first; the last is current)."""
    label, current = rounds[-1]
    graded = _graded(questions, current)
    stats = [(name, _round_stats(questions, doc)) for name, doc in rounds]
    return {
        "doc_format": SCORE_FORMAT,
        "set": set_label,
        "subject": subject,
        "round": label,
        "total": _tally([grade for _, grade in graded], len(questions)),
        "by_type": _breakdown(stats, "by_type"),
        "by_table": _breakdown(stats, "by_table"),
        "by_gap": _by_gap(graded),
        "lost": [_row(q, g) for q, g in graded if g["score"] < 2],
        "key_wrong": [_row(q, g) for q, g in graded if g.get("gap") == "key_wrong"],
        "ungraded": [q["id"] for q in questions if q["id"] not in _by_id(current)],
        "rounds": [{"round": name, "total": s["total"]} for name, s in stats],
        "changes": _changes(questions, rounds) if len(rounds) > 1 else [],
    }


def _by_id(grades: dict) -> dict[str, dict]:
    return {grade["id"]: grade for grade in grades["grades"]}


def _graded(questions: list[dict], grades: dict) -> list[tuple[dict, dict]]:
    by_id = _by_id(grades)
    return [(q, by_id[q["id"]]) for q in questions if q["id"] in by_id]


def _tally(grades: list[dict], questions: int) -> dict:
    points = sum(grade["score"] for grade in grades)
    top = 2 * len(grades)
    return {
        "questions": questions, "graded": len(grades), "points": points, "max": top,
        "percent": _percent(points, top),
    }


def _percent(points: int, top: int) -> float | None:
    return round(100 * points / top, 1) if top else None


def _round_stats(questions: list[dict], grades: dict) -> dict:
    graded = _graded(questions, grades)
    return {
        "total": _tally([g for _, g in graded], len(questions)),
        "by_type": _grouped(questions, graded, type_of),
        "by_table": _grouped(questions, graded, place_of),
    }


def _grouped(questions: list[dict], graded: list[tuple[dict, dict]], key) -> dict[str, dict]:
    sizes: dict[str, int] = {}
    for question in questions:
        sizes[key(question)] = sizes.get(key(question), 0) + 1
    groups: dict[str, list[dict]] = {name: [] for name in sizes}
    for question, grade in graded:
        groups[key(question)].append(grade)
    return {name: _tally(grades, sizes[name]) for name, grades in groups.items()}


def _breakdown(stats: list[tuple[str, dict]], part: str) -> list[dict]:
    current = stats[-1][1][part]
    return [
        {
            "key": name, **tally,
            "rounds": {label: s[part][name]["percent"] for label, s in stats},
        }
        for name, tally in current.items()
    ]


def _by_gap(graded: list[tuple[dict, dict]]) -> list[dict]:
    rows = []
    for gap in GAPS:
        hit = [g for _, g in graded if g.get("gap", "none") == gap]
        if hit:
            rows.append({"gap": gap, "count": len(hit), "lost": sum(2 - g["score"] for g in hit)})
    return rows


def _row(question: dict, grade: dict) -> dict:
    return {
        "id": question["id"], "table": place_of(question), "type": type_of(question),
        "score": grade["score"], "gap": grade.get("gap", "none"),
        "reason": grade.get("reason", ""),
    }


def _changes(questions: list[dict], rounds: list[tuple[str, dict]]) -> list[dict]:
    by_round = [(label, _by_id(doc)) for label, doc in rounds]
    rows = []
    for question in questions:
        scores = {
            label: grades[question["id"]]["score"] if question["id"] in grades else None
            for label, grades in by_round
        }
        if len(set(scores.values())) > 1:
            rows.append({"id": question["id"], "scores": scores})
    return rows
