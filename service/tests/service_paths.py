"""Where the demo inputs live in the repository."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ONTOLOGY = REPO / "tests" / "core" / "fixtures" / "catalog" / "ontology.json"
SEMANTICS = REPO / "examples" / "table-semantics"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
LOAN = "demo_dwd.dwd_lending_loan_df"
