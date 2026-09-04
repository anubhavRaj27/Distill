"""Query specifications, their evaluation, field statistics, and the dashboard.

This package is where decision D37 is enforced: **the model chooses what to compute, and
this code computes it.** A model emits a ``DataQuery``; nothing a model writes is ever
executed, and no number a model types is ever displayed.
"""
