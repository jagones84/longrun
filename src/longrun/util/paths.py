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
       macOS    ~/.longrun
       Linux    ~/.longrun

The bootstrap ``config.json`` and the other tiny preference files
(``Global_rules.md``, ``AGENTS.md``, ``prompt.d/``) live in the DEFAULT home's
``config/`` subfolder — ``~/.longrun/config`` — so everything the harness owns
sits under ONE ``.longrun`` root with ``config/``, ``data/``, ``matrix/`` and
``workspaces/`` beside each other. It stays at the DEFAULT location even when
``data_home`` points elsewhere, because it is what records that choice.
``LONGRUN_CONFIG_DIR`` overrides it (tests).

``LONGRUN_DATA_DIR`` still overrides the DATA DIR alone (tests point it at a temp
directory); it does not move the self-evolution root.

LEGACY: a checkout that still carries ``<repo>/data`` keeps being served from
there UNTIL the operator moves it, instead of silently starting empty — a
migration that loses the chat history is worse than the violation itself. The
UI flags that state and offers the move (``core/homemove.py``).
"""
import hashlib
import json
import os
import shutil
import sys

# src/longrun/util/paths.py -> src/longrun/util -> src/longrun -> src -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEBUI_DIR = os.path.join(REPO_ROOT, "webui")

# The IMMUTABLE self-evolution nucleus: code, tracked by the repo.
MATRIX_SRC_DIR = os.environ.get("LONGRUN_MATRIX_SRC") or os.path.join(REPO_ROOT, "src", "Matrix")


def config_dir():
    """The bootstrap preference dir (tiny files only, never databases).

    ``<default home>/config`` — ``~/.longrun/config`` on Linux/macOS. It stays
    at the DEFAULT location even when ``data_home`` points elsewhere: it is what
    records where the data home is, so it cannot depend on it.
    """
    env = os.environ.get("LONGRUN_CONFIG_DIR")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip()))
    return os.path.join(platform_home(), "config")


def _legacy_config_dir():
    """The pre-JAG-534 location (``~/.config/longrun``) — read-only rescue."""
    return os.path.join(os.path.expanduser("~"), ".config", "longrun")


def _adopt_legacy_config():
    """One-time copies from older layouts. Never destructive, never overriding."""
    new = config_dir()
    if not os.environ.get("LONGRUN_CONFIG_DIR"):
        legacy = _legacy_config_dir()
        if (os.path.abspath(legacy) != os.path.abspath(new)
                and os.path.isdir(legacy)
                and not os.path.isfile(os.path.join(new, "config.json"))):
            try:
                os.makedirs(new, exist_ok=True)
                for name in os.listdir(legacy):
                    src, dst = os.path.join(legacy, name), os.path.join(new, name)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        shutil.copy2(src, dst)
            except OSError:
                pass
    # The global rules file was renamed RULES.md -> Global_rules.md; an install
    # that predates the rename must not silently lose its rules.
    old_rules = os.path.join(new, "RULES.md")
    new_rules = os.path.join(new, "Global_rules.md")
    if os.path.isfile(old_rules) and not os.path.exists(new_rules):
        try:
            shutil.copy2(old_rules, new_rules)
        except OSError:
            pass


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
    """The OS-conventional per-user root for everything Longrun owns."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or \
            os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "Longrun")
    # macOS and Linux: one dotted folder, so config/, data/, matrix/ and
    # workspaces/ sit together instead of being scattered across XDG dirs.
    return os.path.join(os.path.expanduser("~"), ".longrun")


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


# JAG-534: adopt the pre-JAG-534 preferences (~/.config/longrun) BEFORE reading
# them, so the first import after an upgrade does not start with an empty config
# (which would silently fall back to the platform home and look like data loss).
_adopt_legacy_config()

HOME_DIR, HOME_SOURCE = resolve_home()


def _legacy_home_data():
    """The DATA dir of the pre-JAG-534 platform home, or "" when impossible.

    Cycle 19 kept real data in `$XDG_DATA_HOME/longrun` (Linux) /
    `~/Library/Application Support/Longrun` (macOS). An install upgraded from
    there must keep being served until the operator moves it: the alternative is
    a silent empty start, which reads exactly like data loss.
    """
    if os.name == "nt":
        return ""              # the Windows default never changed
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Longrun/data")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "longrun", "data")


def _pick_data_dir():
    """The data dir + whether it is the LEGACY in-repo one."""
    env = os.environ.get("LONGRUN_DATA_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env)), False
    home_data = os.path.join(HOME_DIR, "data")
    if os.path.isdir(home_data):
        return home_data, False
    old_home = _legacy_home_data()
    if old_home and os.path.isdir(old_home):
        return old_home, False
    legacy = os.path.join(REPO_ROOT, "data")
    if os.path.isdir(legacy):
        return legacy, True
    return home_data, False


_LEGACY_HOME_DATA = _legacy_home_data()
DATA_DIR, LEGACY_DATA_IN_REPO = _pick_data_dir()
# Non-empty ONLY while a cycle-19 (XDG/macOS) home is still being served.
LEGACY_HOME_DATA = (DATA_DIR if _LEGACY_HOME_DATA
                    and os.path.realpath(DATA_DIR) == os.path.realpath(_LEGACY_HOME_DATA)
                    else "")
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
# JAG-534: per-workspace PROJECT state (Project_rules.md, rules/, prompt.d/).
# Lives beside the codebase index, under DATA_DIR, so a home move carries it.
PROJECTS_DIR = os.environ.get("LONGRUN_PROJECTS_DIR") or os.path.join(DATA_DIR, "projects")


def workspace_state_dir(ws):
    """Per-workspace harness state, OUTSIDE the workspace itself.

    Project rules and prompt addenda used to live in ``<ws>/.longrun``, which
    meant the harness wrote a dot-folder into every checkout it touched (the
    harness repo included). They now live in ``<data>/projects/<slug>-<sha8>/``
    — exactly like the per-workspace codebase index. A legacy ``<ws>/.longrun``
    is MOVED here the first time that workspace is used, so nothing is lost.
    """
    root = os.path.abspath(os.path.expanduser(str(ws or os.getcwd())))
    name = os.path.basename(root.rstrip(os.sep)) or "workspace"
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:40]
    dest = os.path.join(PROJECTS_DIR, "%s-%s" % (
        safe or "workspace", hashlib.sha1(root.encode("utf-8")).hexdigest()[:8]))
    legacy = os.path.join(root, ".longrun")
    if os.path.isdir(legacy) and not os.path.exists(dest):
        try:
            os.makedirs(PROJECTS_DIR, exist_ok=True)
            os.replace(legacy, dest)
        except OSError:
            pass
    return dest


def home_status():
    """Everything the Settings panel needs to describe the data home."""
    return {
        "home": HOME_DIR,
        "source": HOME_SOURCE,
        "default": platform_home(),
        "config_dir": config_dir(),
        "data_dir": DATA_DIR,
        "target_data_dir": TARGET_DATA_DIR,
        "legacy_in_repo": LEGACY_DATA_IN_REPO,
        "legacy_home_dir": LEGACY_HOME_DATA,
        "repo_data_dir": os.path.join(REPO_ROOT, "data"),
        "matrix_dir": MATRIX_DOT_DIR,
        "workspaces_dir": WORKSPACES_DIR,
        "projects_dir": PROJECTS_DIR,
    }
