"""Read-only HTTP and MCP servers for the scope-lineage catalog answer commands.

Both servers answer through ``scope_lineage.cli_catalog_answers``, the functions the
``scope-lineage catalog`` commands themselves call, so an answer served here is the one
``--json`` prints. Neither runs SQL; the only file either writes is the pending file it
was started with. The HTTP server's opt-in ask panel (``ask/``) has a model answer data
questions with those same answers as its only tools.
"""

__version__ = "0.1.0"
