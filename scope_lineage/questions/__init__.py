"""Acceptance questions: grading generated pages with a question set.

An answerer model reads only the pages and answers; a grader model holds each answer to
the question's reference answer and evidence and scores it 2 / 1 / 0. This package does
the deterministic parts around those two calls:

- :func:`validate_document` holds a ``question-set/1`` or ``question-grades/1`` document
  to its schema, unique ids and non-blank reference answers;
- :func:`select_questions` picks a sample by id and by table or concept;
- :func:`render_answer_sheet` writes the answerer's sheet (questions only),
  :func:`parse_answers` reads the answers back by their ``## <id>`` headings, and
  :func:`render_grading_sheet` puts question, reference answer, evidence and answer side
  by side for the grader;
- :func:`score_report` sums a grading round, with earlier rounds as comparison columns,
  and :func:`render_score_markdown` writes it for a person.

No model is called here; the two prompts live in the agent skill. The command line loads
the YAML or JSON files and hands them over as plain data.
"""

from __future__ import annotations

from .schema import GRADES_FORMAT, SET_FORMAT, packaged_schema, validate_document
from .score import SCORE_FORMAT, graded_ids_outside, label_rounds, score_report
from .score_markdown import render_score_markdown
from .select import SelectionError, select_questions
from .sheets import GAPS, Answers, parse_answers, render_answer_sheet, render_grading_sheet

__all__ = [
    "Answers",
    "GAPS",
    "GRADES_FORMAT",
    "SCORE_FORMAT",
    "SET_FORMAT",
    "SelectionError",
    "graded_ids_outside",
    "label_rounds",
    "packaged_schema",
    "parse_answers",
    "render_answer_sheet",
    "render_grading_sheet",
    "render_score_markdown",
    "score_report",
    "select_questions",
    "validate_document",
]
