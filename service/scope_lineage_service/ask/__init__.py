"""The ask panel: a data question answered by a model on the server, through the catalog tools.

The model is told what to do by one text, the skill's walk (``catalog-answers.md`` with the
reference it cites), packaged here as an exact copy of the skill files -- a test holds the
copies to their sources. Its tools are the catalog answers (``CatalogState``), the same
functions the HTTP and MCP endpoints call. Nothing here runs SQL; the pending file is the
only thing written, and only when the server was given one.

The modules: ``walk`` (the system prompt), ``tools`` (the tools and their checks),
``loop`` (one question: model turns and tool calls, with caps and cancel), ``service``
(conversations in memory and the runs the page polls), ``anthropic_model`` (the one place
the ``anthropic`` SDK is imported, lazily) and ``fake_model`` (a scripted stand-in for
reviewing the page without a key or a network).
"""
