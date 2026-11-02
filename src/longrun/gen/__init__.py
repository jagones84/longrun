"""Text generation for the WebUI's editable surfaces (K-1/K-2).

Two modules, one subject:

* `surfaces` — the registry: per-surface system prompt, context gatherer key,
  model role and apply mode. The single owner of that prompt data.
* `generate` — the engine: gathers the surface's REAL context, resolves the model
  (that session's own model for a session-scoped surface), runs ONE completion and
  returns TEXT. It never writes; the operator saves.
"""
