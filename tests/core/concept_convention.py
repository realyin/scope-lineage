"""The table-name convention the concept-layer fixtures are written in.

The concept layer reads no table-name suffix unless the caller configures one
(``domain-profile/1``'s ``table_name_convention``, WP11 / D2). Fixtures whose tables are
named ``*_df`` / ``*_di`` to exercise a rule *about* a snapshot or an increment pass this
convention, the suffixes the layer used to ship.
"""

WAREHOUSE_CONVENTION = {
    "full": ["df", "hf", "mf", "wf", "all"],
    "incremental": ["di", "hi", "mi", "wi"],
}
