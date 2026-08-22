"""Contract-derived renderers. Consumes the versioned JSON documents only."""

# ruff: noqa: F401 -- re-export of the render facade.

from .mapping_markdown import (
    DOC_FORMAT,
    render_mapping_markdown,
    render_warnings_markdown,
)
