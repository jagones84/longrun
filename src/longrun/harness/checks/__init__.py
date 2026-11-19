#!/usr/bin/env python3
"""Report-only checkers — one deterministic module per paper/round.

Nothing in the running app imports from this package. Each module takes plain
data (a dict/list, usually read from a JSON file by `core/forge.py`), returns a
verdict, and writes nothing. `docs/ARCHITECTURE.md` calls these "report-only":
a verdict is evidence about the record it was handed, never a claim that the
live system is protected.

The CLI is the only adapter: `python3 forge.py <group> <action> FILE.json`.
Importing a module from here inside `agent/`, `core/api_v02.py`,
`core/httpapi.py` or `tools/` is a layering error — put the live seam in
`longrun.harness` (wired modules) instead.
"""
