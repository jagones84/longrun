"""Central filesystem anchors for the Longrun package (JAG-181).

Every module imports its paths from here instead of deriving them from its own
``__file__``, so moving a module inside the package never changes which repo
directory (data, config, skills, webui) it reads.
"""
import os

# src/longrun/util/paths.py -> src/longrun/util -> src/longrun -> src -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(REPO_ROOT, "data")
# Session store. Overridable so tests/CI can run against a scratch directory
# (`LONGRUN_SESSIONS_DIR`) without touching the live transcripts.
SESSIONS_DIR = os.environ.get("LONGRUN_SESSIONS_DIR") or os.path.join(DATA_DIR, "sessions")
# JAG-316: persisted high-water mark for session job labels (monotonic counter).
_JOBSEQ_FILE = os.path.join(SESSIONS_DIR, ".jobseq")
WEBUI_DIR = os.path.join(REPO_ROOT, "webui")
# JAG-397: knowledge index store. One sqlite DB per workspace, kept OUTSIDE the
# user's project, in the app data dir — the same convention the big IDEs use
# (VS Code/Cursor `workspaceStorage`/`globalStorage`). Overridable for tests.
INDEX_DIR = os.environ.get("LONGRUN_INDEX_DIR") or os.path.join(os.path.dirname(SESSIONS_DIR), "index")

