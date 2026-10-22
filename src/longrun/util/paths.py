"""Central filesystem anchors for the Longrun package (JAG-181, JAG-533).

Every module imports its paths from here instead of deriving them from its own
``__file__``, so moving a module inside the package never changes which repo
directory (config, skills, webui) it reads.

JAG-533 — USER DATA NEVER LIVES IN THE CHECKOUT
------------------------------------------------
The repository is a checkout: it is replaced by the next ``git pull``, it may be
read-only, and it is world-readable in a container. Mutable user state (sessions,
events, indexes, costs, the self-evolution checkout) therefore lives under ONE
root, ``HOME_DIR``, outside the repo, resolved in this order:

  1. ``LONGRUN_DATA_HOME``  — explicit env override (highest).
  2. ``data_home`` in ``<config>/config.json`` — what the Settings panel writes.
  3. the PLATFORM default:
       Windows  %LOCALAPPDATA%\\Longrun
       macOS    ~/Library/Application Support/Longrun
       Linux    $XDG_DATA_HOME/longrun  (else ~/.local/share/longrun)

``LONGRUN_DATA_DIR`` still overrides the DATA DIR alone (tests point it at a temp
directory); it does not move the self-evolution root.

LEGACY: a checkout that still carries ``<repo>/data`` keeps being served from
there UNTIL the operator moves it, instead of silently starting empty — a
migration that loses the chat history is worse than the violation itself. The
UI flags that state and offers the move (``core/homemove.py``).
"""
import json
import os
import sys

# src/longrun/util/paths.py -> src/longrun/util -> src/longrun -> src -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEBUI_DIR = os.path.join(REPO_ROOT, "webui")

# The IMMUTABLE self-evolution nucleus: code, tracked by the repo.
MATRIX_SRC_DIR = os.environ.get("LONGRUN_MATRIX_SRC") or os.path.join(REPO_ROOT, "src", "Matrix")


def config_dir():
    """The bootstrap preference dir (tiny files only, never databases).

    ``config.json`` lives HERE and not under HOME_DIR on purpose: it is what
    records WHERE the data home is, so it cannot depend on it.
    """
    return os.environ.get("LONGRUN_CONFIG_DIR") or \
        os.path.join(os.path.expanduser("~"), ".config", "longrun")


def config_file():
    return os.path.join(config_dir(), "config.json")


def read_config():
    """The bootstrap config.json dict ({} on any error — never raises)."""
    try:
        with open(config_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — a bad config must not break startup
        return {}


def platform_home():
    """The OS-conventional per-user data root for Longrun."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or \
            os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "Longrun")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                            "Longrun")
    base = os.environ.get("XDG_DATA_HOME") or \
        os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "longrun")


def configured_home():
    """The `data_home` saved by the Settings panel, or "" when unset/invalid."""
    v = read_config().get("data_home")
    v = str(v).strip() if v else ""
    if not v:
        return ""
    return os.path.abspath(os.path.expanduser(v))


def resolve_home():
    """(path, source) for the data home; source is env|config|platform."""
    env = os.environ.get("LONGRUN_DATA_HOME")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip())), "env"
    cfg = configured_home()
    if cfg:
        return cfg, "config"
    return platform_home(), "platform"


HOME_DIR, HOME_SOURCE = resolve_home()


def _pick_data_dir():
    """The data dir + whether it is the LEGACY in-repo one."""
    env = os.environ.get("LONGRUN_DATA_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env)), False
    home_data = os.path.join(HOME_DIR, "data")
    legacy = os.path.join(REPO_ROOT, "data")
    # A configured/moved home always wins; the legacy dir is only a rescue for a
    # checkout that has not been migrated yet (never override real data at HOME).
    if HOME_SOURCE in ("env", "config") and os.path.isdir(home_data):
        return home_data, False
    if not os.path.isdir(home_data) and os.path.isdir(legacy):
        return legacy, True
    return home_data, False


DATA_DIR, LEGACY_DATA_IN_REPO = _pick_data_dir()
# Where the operator WANTS the data (what a move targets; differs from DATA_DIR
# while a legacy checkout is still being served).
TARGET_DATA_DIR = os.path.join(HOME_DIR, "data")

# Session store. Overridable so tests/CI can run against a scratch directory
# (`LONGRUN_SESSIONS_DIR`) without touching the live transcripts.
SESSIONS_DIR = os.environ.get("LONGRUN_SESSIONS_DIR") or os.path.join(DATA_DIR, "sessions")
# JAG-316: persisted high-water mark for session job labels (monotonic counter).
_JOBSEQ_FILE = os.path.join(SESSIONS_DIR, ".jobseq")
# JAG-400: two SEPARATE index stores, kept OUTSIDE the user's project in the app
# data dir (the VS Code/Cursor `workspaceStorage`/`globalStorage` convention).
#  - CODEBASE index: ONE DB PER WORKSPACE PATH (like project rules) — not global.
#  - KNOWLEDGE base: GLOBAL (notebooks of sources). Different file, different life.
# Both are overridable so tests run against a scratch dir.
CODEBASE_DIR = os.environ.get("LONGRUN_CODEBASE_DIR") or os.path.join(DATA_DIR, "codebase")
KNOWLEDGE_DIR = os.environ.get("LONGRUN_KNOWLEDGE_DIR") or os.path.join(DATA_DIR, "knowledge")
# JAG-403: per-batch embedding cost log (separate small DB, append-only).
EMBEDDING_DIR = os.environ.get("LONGRUN_EMBEDDING_DIR") or os.path.join(DATA_DIR, "embedding")
# JAG-431j: the per-session THREAD ledger (durable chat outline, compaction-proof).
# Overridable so tests never write it into the live data/.
THREADS_DIR = os.environ.get("LONGRUN_THREADS_DIR") or os.path.join(DATA_DIR, "threads")
# JAG-533: the self-evolution RUNTIME checkout (a git clone + rules + skills +
# checkpoints, rewritten at runtime) — mutable state, so it lives under HOME, not
# in the repository.
MATRIX_DOT_DIR = os.environ.get("LONGRUN_MATRIX_DOT") or os.path.join(HOME_DIR, "matrix")
# The default root for new workspaces (user PROJECTS, not app data).
WORKSPACES_DIR = os.environ.get("LONGRUN_WORKSPACES_ROOT") or \
    os.path.join(HOME_DIR, "workspaces")


def home_status():
    """Everything the Settings panel needs to describe the data home."""
    return {
        "home": HOME_DIR,
        "source": HOME_SOURCE,
        "default": platform_home(),
        "data_dir": DATA_DIR,
        "target_data_dir": TARGET_DATA_DIR,
        "legacy_in_repo": LEGACY_DATA_IN_REPO,
        "repo_data_dir": os.path.join(REPO_ROOT, "data"),
        "matrix_dir": MATRIX_DOT_DIR,
        "workspaces_dir": WORKSPACES_DIR,
    }
