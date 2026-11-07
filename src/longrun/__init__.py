"""Longrun — local agent harness (package).

All runtime modules live in subpackages under `src/longrun/` (core, agent,
orchestrate, plan, tools, model, memory, interop, util, orbit). Filesystem
anchors are centralised in `longrun.util.paths` so a module never depends on
its own location.
"""

# The ONE version string. `core.server.VERSION` and the self-knowledge block in
# the system prompt both read it: an agent that says "Longrun v0.6" while the
# service answers 1.0.0 is giving the model a false self-image (found live
# 2026-11-07 in A54's context, verified against `/api/self`).
__version__ = "1.0.0"

