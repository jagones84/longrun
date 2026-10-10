"""Central filesystem anchors for the Longrun package (JAG-181).

Every module imports its paths from here instead of deriving them from its own
``__file__``, so moving a module inside the package never changes which repo
directory (data, config, skills, webui) it reads.
"""
import os

# src/longrun/util/paths.py -> src/longrun/util -> src/longrun -> src -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# App data dir. Overridable (``LONGRUN_DATA_DIR``) so tests never write into the
# live data/ (config overlays, indexes, cost logs).
DATA_DIR = os.environ.get("LONGRUN_DATA_DIR") or os.path.join(REPO_ROOT, "data")
# Session store. Overridable so tests/CI can run against a scratch directory
# (`LONGRUN_SESSIONS_DIR`) without touching the live transcripts.
SESSIONS_DIR = os.environ.get("LONGRUN_SESSIONS_DIR") or os.path.join(DATA_DIR, "sessions")
# JAG-316: persisted high-water mark for session job labels (monotonic counter).
_JOBSEQ_FILE = os.path.join(SESSIONS_DIR, ".jobseq")
WEBUI_DIR = os.path.join(REPO_ROOT, "webui")
# JAG-400: two SEPARATE index stores, kept OUTSIDE the user's project in the app
# data dir (the VS Code/Cursor `workspaceStorage`/`globalStorage` convention).
#  - CODEBASE index: ONE DB PER WORKSPACE PATH (like project rules) — not global.
#  - KNOWLEDGE base: GLOBAL (notebooks of sources). Different file, different life.
# Both are overridable so tests run against a scratch dir.
CODEBASE_DIR = os.environ.get("LONGRUN_CODEBASE_DIR") or os.path.join(DATA_DIR, "codebase")
KNOWLEDGE_DIR = os.environ.get("LONGRUN_KNOWLEDGE_DIR") or os.path.join(DATA_DIR, "knowledge")
# JAG-403: per-batch embedding cost log (separate small DB, append-only).
EMBEDDING_DIR = os.environ.get("LONGRUN_EMBEDDING_DIR") or os.path.join(DATA_DIR, "embedding")

