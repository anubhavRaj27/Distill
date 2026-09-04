"""Everything the server knows about the Agent-to-User Interface protocol.

Confined to this package on purpose (requirement A2-01's mitigation): the renderer has
shipped breaking changes in three consecutive minor versions, so when the protocol moves,
one directory moves with it.

The model never sees an A2UI message. It emits a ``Visual`` (``app.insights.queryspec``),
the server evaluates the query, and ``build.py`` turns the evaluated result into messages.
That separation is decision D37: the agent chooses the shape, the server owns the numbers.
"""
