"""Stable public API for SQL parsing and versioned Lineage Core artifacts."""

# ruff: noqa: F401 -- imports below are the intentionally declared public facade.

from .contract import (
    to_lineage_dict,
    to_lineage_json,
    to_task_lineage_dict,
    to_task_lineage_json,
    validate_contract_invariants,
    validate_cross_references,
    validate_diagnostics_document,
    validate_lineage_document,
    write_task_lineage,
)
from .contract.lineage import to_dict, to_json
from .metadata.schema_metadata import (
    DictSchemaProvider,
    MetadataFileError,
    SchemaMap,
    SchemaProvider,
    column_details_for_table,
    check_metadata_file,
    catalog_prefixes,
    load_schema,
    load_schema_sources,
    metadata_dict_reader,
    normalize_schema_map,
    normalize_table_name,
)
from .metadata.metadata_patch import (
    MetadataPatch,
    MetadataPatchError,
    apply_metadata_patch,
    load_metadata_patch,
)
from .metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
    load_target_table_metadata,
    lookup_target_table_metadata,
)
from .scope.expression_refs import extract_qualified_field_refs
from .scope.parser import resolve_display_expression
from .scope.scope_builder import (
    NoSupportedWriteStatementError,
    parse_all_scope_lineage,
    parse_scope_lineage,
)
from .scope.scope_types import (
    CONSTANT_SCOPE_ID,
    NON_PHYSICAL_SOURCE_SCOPES,
    SYSTEM_SCOPE_ID,
    DiagnosticWarning,
    Diagnostics,
    ScopeColumn,
    ScopeData,
    ScopeFieldUsage,
    ScopeGraph,
    ScopeGraphEdge,
    ScopeInputEdge,
    ScopeLineageResult,
    ScopeLogicBlock,
    ScopeOutputField,
    SourceRef,
)
from .sqlglot_config import suppress_invalid_json_path_warnings
from .scope.task_lineage import TaskLineageResult, parse_task_lineage
from .contract.fold import fold_session_scoped
from .render.glossary import build_glossary, render_glossary_markdown
from .render.glossary_template import (
    build_overrides_template,
    render_overrides_template_markdown,
)
from .render.mapping_markdown import render_mapping_markdown, render_warnings_markdown
from .render.ontology import build_ontology, render_ontology_index_markdown
from .render.semantic_markdown import render_semantic_markdown
from .render.semantic_profile import build_semantic_profile
from .render.table_cards import (
    apply_table_cards,
    build_table_cards,
    render_table_card_markdown,
    render_table_index_markdown,
    table_card_filename,
)


PUBLIC_CORE_API = frozenset({
    "PUBLIC_CORE_API",
    "CONSTANT_SCOPE_ID",
    "DiagnosticWarning",
    "Diagnostics",
    "fold_session_scoped",
    "DictSchemaProvider",
    "MetadataFileError",
    "MetadataPatch",
    "MetadataPatchError",
    "NoSupportedWriteStatementError",
    "NON_PHYSICAL_SOURCE_SCOPES",
    "SchemaMap",
    "SchemaProvider",
    "ScopeColumn",
    "ScopeData",
    "ScopeFieldUsage",
    "ScopeGraph",
    "ScopeGraphEdge",
    "ScopeInputEdge",
    "ScopeLineageResult",
    "ScopeLogicBlock",
    "ScopeOutputField",
    "SourceRef",
    "SYSTEM_SCOPE_ID",
    "TargetColumnMetadata",
    "TargetMetadataMap",
    "TargetTableMetadata",
    "TaskLineageResult",
    "apply_metadata_patch",
    "apply_table_cards",
    "build_glossary",
    "build_ontology",
    "build_overrides_template",
    "build_semantic_profile",
    "build_table_cards",
    "catalog_prefixes",
    "column_details_for_table",
    "check_metadata_file",
    "extract_qualified_field_refs",
    "load_metadata_patch",
    "load_schema",
    "load_schema_sources",
    "load_target_table_metadata",
    "lookup_target_table_metadata",
    "metadata_dict_reader",
    "normalize_schema_map",
    "normalize_table_name",
    "parse_all_scope_lineage",
    "parse_scope_lineage",
    "parse_task_lineage",
    "render_glossary_markdown",
    "render_ontology_index_markdown",
    "render_overrides_template_markdown",
    "render_mapping_markdown",
    "render_semantic_markdown",
    "render_table_card_markdown",
    "render_table_index_markdown",
    "render_warnings_markdown",
    "resolve_display_expression",
    "suppress_invalid_json_path_warnings",
    "table_card_filename",
    "to_dict",
    "to_json",
    "to_lineage_dict",
    "to_lineage_json",
    "to_task_lineage_dict",
    "to_task_lineage_json",
    "validate_contract_invariants",
    "validate_diagnostics_document",
    "validate_cross_references",
    "validate_lineage_document",
    "write_task_lineage",
})

__all__ = sorted(PUBLIC_CORE_API)
