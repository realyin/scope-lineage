"""Corpus-wide sweep: every produced document satisfies the contract invariants.

The AMBIGUOUS defect lived in the repo's own examples for months
(subscription_account_snapshot, chain mc:108) because no test asked whether the
document's derivation layers agree with each other — each layer's tests validate that
layer against its own expectation, and golden byte tests lock contradictions in along
with everything else. This sweep is the ratchet: it parses the full corpus through the
production paths and requires zero invariant violations, so the next cross-layer
contradiction fails a test the day it is introduced instead of shipping.

Verified to bite: run against the pre-fix tree, this sweep reports exactly the known
defect (chain complete + AMBIGUOUS root, chain complete + e2e incomplete) on the
subscription corpus entries, and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage import (
    parse_all_scope_lineage,
    parse_task_lineage,
    validate_contract_invariants,
)
from scope_lineage.contract import to_lineage_dict, to_task_lineage_dict

from .differential_compare import build_manifest

REPO = Path(__file__).resolve().parents[2]
MANIFEST = build_manifest(REPO)


@pytest.mark.parametrize("key", sorted(MANIFEST), ids=lambda key: key)
def test_corpus_documents_satisfy_contract_invariants(key: str) -> None:
    item = MANIFEST[key]
    violations: list[str] = []

    statements = parse_all_scope_lineage(
        item["sql"], task_name=item["task_name"], schema=item["schema"]
    )
    for index, result in enumerate(statements):
        document = to_lineage_dict(result)
        violations.extend(
            f"statement_docs[{index}]: {error}"
            for error in validate_contract_invariants(document)
        )

    task = parse_task_lineage(
        item["sql"], task_name=item["task_name"], schema=item["schema"]
    )
    task_document = to_task_lineage_dict(task)
    violations.extend(
        f"task_doc: {error}"
        for error in validate_contract_invariants(task_document)
    )

    assert not violations, "\n".join(violations)
