#!/usr/bin/env python3
"""v1274 — the data home lives OUTSIDE the checkout (ADR-0002), mechanically.

`docs/adr/0002-data-home-outside-the-checkout.md`: everything the harness owns lives
under ONE root (`~/.longrun`), never inside the repository, so "a `git pull`, a fresh
clone or a container image can never replace or expose the operator's sessions, costs or
rules". Every acceptance test *sets* `LONGRUN_DATA_HOME` for isolation, but nothing
asserted the invariant itself — that a DEFAULT install stores nothing inside the
checkout. This pin is that guard.

It also pins the documented precedence and the one deliberate exception:
`resolve_home()` is `env → config → platform`, and `config_dir()` ("what records where
the data home is") stays at the DEFAULT location even when the data home points
elsewhere.

Anti-vacuity: `REPO_ROOT` is asserted to equal this checkout first, so the
"not inside the repo" comparisons mean something; and the override is checked with TWO
values, so a hardcoded answer cannot pass.

Deterministic: no server, no model, no network. Everything runs on a temp home.
Run: python3 tests/acceptance/v1274_data_home_outside_repo.py
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1274-")

# Point BOTH roots at the temp BEFORE importing: `paths` resolves at import time, and
# a set `LONGRUN_CONFIG_DIR` also makes `_adopt_legacy_config()` a no-op (no touching
# the operator's real config).
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(TMP, "home_a")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import paths  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def inside(path, parent):
    """True when `path` is `parent` itself or lives under it."""
    p = os.path.abspath(path)
    q = os.path.abspath(parent)
    return p == q or p.startswith(q + os.sep)


# ---- 0. anti-vacuity: the repo root is really this checkout ----------------
check("paths.REPO_ROOT is this checkout (the 'inside the repo' test is meaningful)",
      os.path.abspath(paths.REPO_ROOT) == os.path.abspath(REPO), paths.REPO_ROOT)

# ---- 1. the override wins, and it is read (not hardcoded) ------------------
home_a = os.path.join(TMP, "home_a")
check("LONGRUN_DATA_HOME wins and is reported as source 'env'",
      paths.resolve_home() == (home_a, "env"), str(paths.resolve_home()))

os.environ["LONGRUN_DATA_HOME"] = os.path.join(TMP, "home_b")
check("changing the override changes the resolved home (it is really read)",
      paths.resolve_home() == (os.path.join(TMP, "home_b"), "env"), str(paths.resolve_home()))
os.environ["LONGRUN_DATA_HOME"] = home_a

# ---- 2. never inside the checkout -----------------------------------------
check("an overridden data home is not inside the repository",
      not inside(paths.resolve_home()[0], REPO), paths.resolve_home()[0])
check("the config dir is not inside the repository",
      not inside(paths.config_dir(), REPO), paths.config_dir())

# ---- 3. config_dir stays at the DEFAULT location (ADR-0002's one exception) -
check("config_dir does not follow the data home",
      not inside(paths.config_dir(), home_a)
      and os.path.abspath(paths.config_dir()) != os.path.abspath(home_a),
      "cfg=%s home=%s" % (paths.config_dir(), home_a))

# ---- 4. the load-bearing default, measured in a CLEAN interpreter ----------
env = dict(os.environ)
env.pop("LONGRUN_DATA_HOME", None)
env.pop("LONGRUN_CONFIG_DIR", None)
env.pop("XDG_DATA_HOME", None)
fake_home = os.path.join(TMP, "fakehome")
env["HOME"] = fake_home
env["LOCALAPPDATA"] = fake_home
code = (
    "import json, sys;"
    "sys.path.insert(0, %r);"
    "from longrun.util import paths;"
    "print(json.dumps({'home': paths.resolve_home(), 'cfg': paths.config_dir()}))"
    % os.path.join(REPO, "src")
)
proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
ok_parse = proc.returncode == 0
if not ok_parse:
    print("      subprocess stderr:", (proc.stderr or "").strip()[-200:])
check("a default install resolves its home from the platform (no env, no config)",
      ok_parse and json.loads(proc.stdout or "{}").get("home", [None])[1] == "platform",
      (proc.stdout or "").strip()[:120])

if ok_parse:
    default_home = json.loads(proc.stdout)["home"][0]
    default_cfg = json.loads(proc.stdout)["cfg"]
    check("a DEFAULT data home is outside the checkout (ADR-0002)",
          not inside(default_home, REPO), default_home)
    check("a default data home lands under the user's home, not the repo",
          inside(default_home, fake_home), "home=%s fake=%s" % (default_home, fake_home))
    check("a DEFAULT config dir is outside the checkout",
          not inside(default_cfg, REPO), default_cfg)

# ---- 5. SENSITIVITY: an in-repo data home IS resolved and detected ---------
# Without this, every "not inside the repo" check above could only pass (the test
# points the home at a temp dir). Here the home is deliberately pointed INSIDE the
# checkout: the resolver must report it, and `inside()` must flag it — i.e. the guard
# fires on the exact regression ADR-0002 exists to prevent.
env_repo = dict(env)
env_repo["LONGRUN_DATA_HOME"] = os.path.join(REPO, "data_probe")
env_repo["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
proc2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env_repo)
ok2 = proc2.returncode == 0
repo_home = (json.loads(proc2.stdout)["home"] if ok2 else [None, None])
check("SENSITIVITY: a data home pointed INSIDE the repo is resolved and detected",
      ok2 and repo_home[1] == "env"
      and os.path.abspath(repo_home[0]) == os.path.abspath(os.path.join(REPO, "data_probe"))
      and inside(repo_home[0], REPO),
      str(repo_home))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
