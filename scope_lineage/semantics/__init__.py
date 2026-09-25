"""Table semantics: what one target table means, written for people, checked by machine.

Three deterministic steps around one model-written document (``table-semantics/1``):

- :func:`build_packets` gathers every fact about a target table -- metadata, producing
  tasks and their SQL, input tables, and the lineage facts the semantic profile derives
  -- into a packet a model writes from;
- :func:`validate_document` holds a written document to its JSON Schema and to the
  packet (nine cross checks), and says per item what to rewrite;
- :func:`apply_confirmations` writes a person's answers back into the documents.

The package reads contract-derived views only (``render``): the command line loads the
lineage, the task JSON and the schema metadata and hands them over as plain data. No
model is called here; that stays in the agent skill.
"""

from __future__ import annotations

from .confirm import ConfirmResult, apply_confirmations
from .packet import PACKET_FORMAT, UnknownTables, build_packets, packet_digest
from .packet_markdown import render_packet_markdown
from .schema import CONFIRMATIONS_FORMAT, DOC_FORMAT, packaged_schema, schema_errors
from .validate import (
    CHECKS,
    REPORT_FORMAT,
    render_validation_text,
    validate_document,
    validation_report,
)

__all__ = [
    "CHECKS",
    "CONFIRMATIONS_FORMAT",
    "ConfirmResult",
    "DOC_FORMAT",
    "PACKET_FORMAT",
    "REPORT_FORMAT",
    "UnknownTables",
    "apply_confirmations",
    "build_packets",
    "packaged_schema",
    "packet_digest",
    "render_packet_markdown",
    "render_validation_text",
    "schema_errors",
    "validate_document",
    "validation_report",
]
