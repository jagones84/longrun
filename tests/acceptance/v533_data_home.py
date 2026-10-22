#!/usr/bin/env python3
"""v533 — user data lives OUTSIDE the checkout, and can be moved (JAG-533).

The repository is a checkout: `git pull` replaces it, a container may mount it
read-only, and it is world-readable. Sessions, the event log, indexes, costs and
the self-evolution runtime are USER STATE and must live under one root the
operator chooses, with sane per-OS defaults.

Locks:
  A  the resolution order (env > config.json data_home > platform default);
  B  the defaults are the OS conventions (LOCALAPPDATA / XDG / Library);
  C  no module still derives a mutable path from the repo root;
  D  a move is real: copy, verify, delete the source, persist the choice;
  E  a move refuses a target inside the repo (the whole point);
  F  the status/percentages the progress bar reads;
  G  the sandbox scratch root follows the data home too;
  H  workspace project state (rules, prompt.d) never lands in the workspace;
  I  the pre-JAG-534 ~/.config/longrun is adopted into ~/.longrun/config.

Deterministic: temp dirs, no live model, no network.
Run: python3 tests/acceptance/v533_data_home.py
"""
import importlib
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v533-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "old", "data")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(TMP, "newhome")
for k in ("SESSIONS_DIR", "ROLES_DIR", "DB", "CODEBASE_DIR", "KNOWLEDGE_DIR",
          "EMBEDDING_DIR", "THREADS_DIR", "COSTS_DIR", "EDITS_DIR", "RUNS_DIR",
          "GRAPH_DIR", "MATRIX_DOT", "WORKSPACES_ROOT", "AGENTS_FILE", "TEAMS_FILE",
          "JOBS_FILE", "ROUTINES_FILE", "APPROVALS", "DECISIONS_FILE", "SUBAGENT_DIR",
          "PRICES_FILE"):
    os.environ.pop("LONGRUN_" + k, None)
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import paths  # noqa: E402
from longrun.core import homemove  # noqa: E402

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


# --- A: resolution order ----------------------------------------------------
check("A1 the env override wins and is reported as such",
      paths.HOME_DIR == os.path.abspath(os.environ["LONGRUN_DATA_HOME"])
      and paths.HOME_SOURCE == "env", (paths.HOME_DIR, paths.HOME_SOURCE))
check("A2 the data dir follows the home when no explicit data dir is set",
      paths.DATA_DIR.endswith(os.path.join("data"))
      and "old" in paths.DATA_DIR, paths.DATA_DIR)

with open(paths.config_file(), "w", encoding="utf-8") as f:
    json.dump({"data_home": os.path.join(TMP, "fromcfg")}, f)
check("A3 config.json data_home is honoured when the env is absent",
      paths.configured_home() == os.path.join(TMP, "fromcfg"), paths.configured_home())
_prev = os.environ.pop("LONGRUN_DATA_HOME", None)
try:
    reloaded = importlib.reload(paths)
    check("A4 without the env the CONFIG value is used",
          reloaded.HOME_SOURCE == "config"
          and reloaded.HOME_DIR == os.path.join(TMP, "fromcfg"),
          (reloaded.HOME_DIR, reloaded.HOME_SOURCE, reloaded.HOME_SOURCE))
finally:
    os.environ["LONGRUN_DATA_HOME"] = _prev
    paths = importlib.reload(paths)

# --- B: OS defaults are the real conventions -------------------------------
_p = paths.platform_home()
check("B1 the platform default is absolute and names the product", os.path.isabs(_p), _p)
if os.name == "nt":
    check("B2 windows defaults under LOCALAPPDATA",
          "appdata" in _p.lower() and os.path.basename(_p).lower() == "longrun", _p)
else:
    check("B2 posix defaults to ONE dotted folder (~/.longrun)",
          os.path.basename(_p) == ".longrun"
          and "/.local/share/" not in _p and "Application Support" not in _p, _p)
check("B3 the home status payload names every root the UI shows",
      {"home", "source", "default", "config_dir", "data_dir", "legacy_in_repo",
       "legacy_home_dir", "matrix_dir", "workspaces_dir", "projects_dir"}
      <= set(paths.home_status()), sorted(paths.home_status()))

# --- C: nothing mutable is still derived from the repo root ----------------
_src = []
for _root, _dirs, _files in os.walk(os.path.join(REPO, "src", "longrun")):
    for _f in _files:
        if _f.endswith(".py"):
            with open(os.path.join(_root, _f), encoding="utf-8") as fh:
                _src.append((os.path.join(_root, _f), fh.read()))
# paths.py owns the documented LEGACY fallback and homemove.py is the migrator
# (it reads the old in-repo location ON PURPOSE); every other module must not.
_EXEMPT = {"paths.py", "homemove.py"}
_bad = [os.path.basename(p) for p, txt in _src
        if os.path.basename(p) not in _EXEMPT
        and ('REPO, "data"' in txt or 'REPO_ROOT, "data"' in txt
             or 'registry.REPO, "data"' in txt or '"data", "sessions"' in txt)]
check("C1 no module hardcodes <repo>/data any more (outside the migrator)",
      not _bad, _bad)
_bad_matrix = [os.path.basename(p) for p, txt in _src
               if os.path.basename(p) not in _EXEMPT
               and ('REPO, ".Matrix"' in txt or 'REPO_ROOT, ".Matrix"' in txt)]
check("C2 no module reads the Matrix runtime from the repo", not _bad_matrix, _bad_matrix)
check("C3 the legacy in-repo data dir is still recognised (a move must find it)",
      "legacy = os.path.join(REPO_ROOT, \"data\")" in
      open(os.path.join(REPO, "src", "longrun", "util", "paths.py"),
           encoding="utf-8").read(), "")

# --- H: workspace project state never lands inside the workspace ------------
_ws = os.path.join(TMP, "ws")
os.makedirs(os.path.join(_ws, ".longrun", "rules"), exist_ok=True)
with open(os.path.join(_ws, ".longrun", "Project_rules.md"), "w", encoding="utf-8") as f:
    f.write("legacy project rule")
_state = paths.workspace_state_dir(_ws)
check("H1 workspace state lives under the data home, not the workspace",
      os.path.realpath(_state).startswith(os.path.realpath(paths.DATA_DIR) + os.sep)
      and not os.path.realpath(_state).startswith(os.path.realpath(_ws) + os.sep), _state)
check("H2 the legacy <ws>/.longrun is ADOPTED (moved), not duplicated",
      os.path.isfile(os.path.join(_state, "Project_rules.md"))
      and not os.path.isdir(os.path.join(_ws, ".longrun")), _state)
check("H3 the same workspace always maps to the same state dir",
      paths.workspace_state_dir(_ws) == _state, _state)
_rules_src = open(os.path.join(REPO, "src", "longrun", "memory", "rules.py"),
                  encoding="utf-8").read()
check("H4 project rules resolve through paths.workspace_state_dir (never <ws>/.longrun)",
      "paths.workspace_state_dir" in _rules_src and 'get_workspace(), ".longrun"' not in _rules_src)

# --- I: the pre-JAG-534 preferences are adopted, never stranded -------------
if os.name != "nt":
    _fake = os.path.join(TMP, "fakehome")
    os.makedirs(os.path.join(_fake, ".config", "longrun"), exist_ok=True)
    # ONLY the pre-rename name: proves both the legacy copy AND the rename.
    with open(os.path.join(_fake, ".config", "longrun", "RULES.md"), "w",
              encoding="utf-8") as f:
        f.write("pre-rename global rule")
    _prev_cfg_dir = os.environ.pop("LONGRUN_CONFIG_DIR", None)
    _prev_home_env = os.environ.get("HOME")
    os.environ["HOME"] = _fake
    try:
        _pth = importlib.reload(paths)
        check("I1 the settings dir is <default home>/config (~/.longrun/config)",
              _pth.config_dir() == os.path.join(_fake, ".longrun", "config"),
              _pth.config_dir())
        check("I2 ~/.config/longrun is copied into it on first import",
              os.path.isfile(os.path.join(_fake, ".longrun", "config", "RULES.md")),
              _pth.config_dir())
        check("I3 a pre-rename RULES.md is adopted as Global_rules.md",
              os.path.isfile(os.path.join(_fake, ".longrun", "config", "Global_rules.md")),
              _pth.config_dir())
    finally:
        if _prev_home_env is not None:
            os.environ["HOME"] = _prev_home_env
        if _prev_cfg_dir:
            os.environ["LONGRUN_CONFIG_DIR"] = _prev_cfg_dir
        paths = importlib.reload(paths)

# --- J: an install from the cycle-19 XDG home keeps its data ----------------
# Moving the default from `~/.local/share/longrun` to `~/.longrun` must NOT
# blank an existing install: the old data dir is served (and flagged) until the
# operator moves it, exactly like the in-repo rescue.
if os.name != "nt":
    _fake2 = os.path.join(TMP, "home2")
    _old = os.path.join(_fake2, ".local", "share", "longrun", "data")
    os.makedirs(_old, exist_ok=True)
    with open(os.path.join(_old, "marker.txt"), "w", encoding="utf-8") as f:
        f.write("cycle 19 data")
    _saved = {k: os.environ.get(k) for k in
              ("LONGRUN_DATA_DIR", "LONGRUN_DATA_HOME", "LONGRUN_CONFIG_DIR",
               "HOME", "XDG_DATA_HOME")}
    for _k in ("LONGRUN_DATA_DIR", "LONGRUN_DATA_HOME", "LONGRUN_CONFIG_DIR"):
        os.environ.pop(_k, None)
    os.environ["HOME"] = _fake2
    os.environ["XDG_DATA_HOME"] = os.path.join(_fake2, ".local", "share")
    try:
        _p2 = importlib.reload(paths)
        check("J1 an upgrade from the XDG home keeps serving its data",
              os.path.realpath(_p2.DATA_DIR) == os.path.realpath(_old)
              and bool(_p2.LEGACY_HOME_DATA), _p2.DATA_DIR)
        check("J2 the status flags it so the UI offers the move",
              _p2.home_status().get("legacy_home_dir") == _p2.DATA_DIR,
              _p2.home_status().get("legacy_home_dir"))
    finally:
        for _k, _v in _saved.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
        paths = importlib.reload(paths)

# --- G: the sandbox scratch root is user data too --------------------------
# `registry.workspace_dir()` used to be `os.path.join(REPO, cfg["sandbox"]
# ["workspace"])`, so every run re-created `<repo>/data/sandbox/<run>` even
# after the migration (found live: data/sandbox/v521). The resolver is patched
# here so the test never depends on the operator's tracked tools.yaml.
from longrun.tools import registry  # noqa: E402

_orig_cfg = registry.load_config
try:
    registry.load_config = lambda reload=False: {"sandbox": {"workspace": "sandbox"}}
    _ws = registry.workspace_dir()
    check("G1 a relative sandbox workspace resolves under the data home",
          os.path.realpath(_ws) == os.path.realpath(os.path.join(paths.DATA_DIR, "sandbox")),
          _ws)
    registry.load_config = lambda reload=False: {"sandbox": {"workspace": "data/sandbox"}}
    check("G2 a pre-migration `data/sandbox` does not nest <home>/data/data",
          os.path.realpath(registry.workspace_dir())
          == os.path.realpath(os.path.join(paths.DATA_DIR, "sandbox")),
          registry.workspace_dir())
    _abs = os.path.join(TMP, "scratch")
    registry.load_config = lambda reload=False: {"sandbox": {"workspace": _abs}}
    check("G3 an absolute sandbox workspace is honoured as-is",
          registry.workspace_dir() == _abs, registry.workspace_dir())
finally:
    registry.load_config = _orig_cfg

# --- D: a move copies, verifies, deletes the source and persists the choice --
_src_dir = paths.DATA_DIR
with open(os.path.join(_src_dir, "hello.txt"), "w", encoding="utf-8") as f:
    f.write("x" * 4096)
os.makedirs(os.path.join(_src_dir, "sessions"), exist_ok=True)
with open(os.path.join(_src_dir, "sessions", "s1.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s1"}, f)
_target = os.path.join(TMP, "newhome")
# The self-evolution runtime lives beside `data/` in the old home, and the TARGET
# home already has an EMPTY `matrix/` (created at startup) — the move must MERGE
# instead of leaving 444 KB of git history behind.
os.makedirs(os.path.join(TMP, "old", "matrix", "git"), exist_ok=True)
with open(os.path.join(TMP, "old", "matrix", "git", "HEAD"), "w", encoding="utf-8") as f:
    f.write("ref: refs/heads/main\n")
os.makedirs(os.path.join(_target, "matrix"), exist_ok=True)
_start = homemove.start(_target)
check("D1 the move starts against the CURRENT data dir",
      _start.get("ok") is True and _start.get("source") == _src_dir, _start)
_deadline = time.time() + 25
while time.time() < _deadline and homemove.status()["phase"] in ("scanning", "copying"):
    time.sleep(0.05)
_st = homemove.status()
check("D2 it finishes cleanly and reports 100%",
      _st["phase"] == "done" and _st["pct"] == 100.0 and not _st["error"], _st)
_dest = os.path.join(_target, "data")
check("D3 every file arrived, with its content",
      os.path.isfile(os.path.join(_dest, "hello.txt"))
      and os.path.getsize(os.path.join(_dest, "hello.txt")) == 4096
      and os.path.isfile(os.path.join(_dest, "sessions", "s1.json")), _dest)
check("D4 the OLD data dir is gone once the copy verified",
      _st.get("removed_source") is True and not os.path.isdir(_src_dir), _src_dir)
with open(paths.config_file(), encoding="utf-8") as f:
    _cfg = json.load(f)
check("D5 config.json records the new home and asks for a restart",
      _cfg.get("data_home") == _target and _st.get("restart_required") is True, _cfg)
check("D6 the self-evolution runtime followed the move (merged, not stranded)",
      os.path.isfile(os.path.join(_target, "matrix", "git", "HEAD"))
      and not os.path.isdir(os.path.join(TMP, "old", "matrix", "git")), _target)

# --- E: a dangerous target is refused --------------------------------------
_inside = homemove.validate(os.path.join(REPO, "data-moved"))
check("E1 a target INSIDE the harness repository is refused",
      _inside.get("ok") is False and "inside the harness repository" in
      (_inside.get("error") or ""), _inside)
_missing = homemove.validate(os.path.join(TMP, "no-such-parent", "x"))
check("E2 a target whose parent does not exist is refused (never mkdir -p silently)",
      _missing.get("ok") is False and "does not exist" in (_missing.get("error") or ""),
      _missing)

# --- F: the progress the bar renders ---------------------------------------
_st2 = homemove.status()
check("F1 status exposes phase/done/total/pct/copied/files for the UI",
      {"phase", "done", "total", "pct", "copied", "files"} <= set(_st2), sorted(_st2))

print("---")
ok = sum(results)
print("v533: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
