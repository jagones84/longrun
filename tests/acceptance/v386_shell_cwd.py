#!/usr/bin/env python3
"""v386 — the `shell` tool honours an explicit working directory (JAG-386).

Reported: the model asked to run a command in a specific repo, but the command
started from the SESSION workspace. Root cause: the `shell` schema advertised
neither `cwd` nor `workspace`, and `_shell` only read an undocumented
`workspace` key — so the `cwd` the model emitted (the name the `git` tool
documents) was silently ignored and the injected session workspace won.

This suite freezes the fix:

  A) the schema now advertises `cwd` (optional; only `command` is required);
  B) an explicit `cwd` reaches the sandbox as its working directory;
  C) `cwd` WINS over the injected `workspace`;
  D) `workspace` alone still works (back-compat);
  E) a missing `cwd` is rejected up front and nothing is executed;
  F) an empty command is still rejected;
  G) (JAG-388) the SESSION WORKSPACE bounds EVERY tool: a shell cwd / `cd` / `-C`
     / absolute path word, a fs.* path, or a git `cwd` that lands OUTSIDE it is
     `required`, regardless of the per-tool policy and of the (now inert)
     `outside_workspace` toggle; only `mode=full` relaxes it. A RELATIVE path
     resolves against the session workspace; system/scratch trees stay auto.
     (JAG-516) `mode=full` ALSO lifts the fs.* ROOT allow-list, so fs.read /
     fs.write / fs.edit reach the whole filesystem like shell.exec already could.
  H) the approvals screen (policy card caption) documents the rule.

Deterministic, no model, no network. `sandbox.run` is stubbed, so no command is
ever really executed.

Run: python3 tests/acceptance/v386_shell_cwd.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-386-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def wsdir(name):
    """A workspace under an allowed root (REPO) so it is a realistic session dir."""
    p = os.path.join(REPO, "data", "v386-%s-%d" % (name, os.getpid()))
    os.makedirs(p, exist_ok=True)
    atexit.register(lambda: shutil.rmtree(p, ignore_errors=True))
    return p


# --- stub the sandbox so nothing actually runs -------------------------------
_calls = []


def _fake_run(command, run_id=None, timeout=None, workspace=None, **kw):
    _calls.append({"command": command, "workspace": workspace, "timeout": timeout})
    return {"exit_code": 0, "stdout": "ok", "stderr": "", "backend": "stub",
            "sandboxed": False}


tools.sandbox.run = _fake_run

# --- A: the schema advertises cwd --------------------------------------------
_props = registry.TOOL_SCHEMAS["shell"]["properties"]
check("A1 the shell schema advertises cwd", "cwd" in _props, str(sorted(_props)))
check("A2 only `command` is required (cwd is optional)",
      registry.TOOL_SCHEMAS["shell"]["required"] == ["command"],
      str(registry.TOOL_SCHEMAS["shell"]["required"]))

# --- B: an explicit cwd reaches the sandbox ----------------------------------
b = wsdir("B")
_calls.clear()
rb = tools._shell({"command": "pwd", "cwd": b}, "r1")
check("B1 an explicit absolute cwd reaches the sandbox",
      _calls and _calls[-1]["workspace"] == b, str(_calls))
check("B2 the command still reports success", rb.get("ok") is True, str(rb))

# --- C: cwd WINS over the injected workspace ---------------------------------
c1, c2 = wsdir("C1"), wsdir("C2")
_calls.clear()
tools._shell({"command": "pwd", "cwd": c1, "workspace": c2}, "r2")
check("C1 cwd wins over the workspace key",
      _calls and _calls[-1]["workspace"] == c1, str(_calls))

# --- D: workspace alone is still honoured (back-compat) ----------------------
_calls.clear()
tools._shell({"command": "pwd", "workspace": c2}, "r3")
check("D1 workspace alone still sets the working dir",
      _calls and _calls[-1]["workspace"] == c2, str(_calls))

# --- E: a missing cwd is rejected, nothing runs ------------------------------
_calls.clear()
miss = os.path.join(REPO, "data", "v386-does-not-exist-%d" % os.getpid())
re_ = tools._shell({"command": "pwd", "cwd": miss}, "r4")
check("E1 a missing cwd is rejected with a clear error",
      re_.get("ok") is False and "cwd not found" in (re_.get("error") or ""), str(re_))
check("E2 the sandbox is NOT called for a bad cwd", _calls == [], str(_calls))

# --- F: empty command still rejected -----------------------------------------
check("F1 an empty command is still rejected",
      tools._shell({"command": "   "}, "r5").get("ok") is False)

# --- G: the session workspace bounds EVERY tool (JAG-388) ---------------------
_cfg = json.loads(json.dumps(registry.load_config()))
_cfg.setdefault("approvals", {})
_cfg["approvals"]["mode"] = "normal"
# the OLD toggle must no longer defeat the boundary — prove it:
_cfg["approvals"]["outside_workspace"] = "auto"
# independent of whatever the live overlay set the shell policy to:
_cfg.setdefault("tools", {}).setdefault("shell", {})["approval"] = "required"
_real_load = registry.load_config
registry.load_config = lambda reload=False: _cfg


def _dec(tool, args):
    return registry.classify(tool, args, workspace=wc)


try:
    wc = wsdir("G")
    inside = os.path.join(wc, "sub")
    os.makedirs(inside, exist_ok=True)
    outside = wsdir("Goutside")   # a real dir OUTSIDE the workspace
    check("G1 a shell cwd INSIDE the workspace stays auto (read-only command)",
          _dec("shell", {"command": "pwd", "cwd": inside})[0] == "auto",
          str(_dec("shell", {"command": "pwd", "cwd": inside})))
    check("G2 a shell cwd OUTSIDE the workspace -> required",
          _dec("shell", {"command": "pwd", "cwd": outside})[0] == "required",
          str(_dec("shell", {"command": "pwd", "cwd": outside})))
    check("G3 no cwd -> the normal policy applies (read-only command auto)",
          _dec("shell", {"command": "pwd"})[0] == "auto",
          str(_dec("shell", {"command": "pwd"})))
    # the REAL escape: an auto-approved read command that CHAINS a cd outside
    check("G4 `ls && cd /fuori` cannot ride the auto-approve of `ls`",
          _dec("shell", {"command": "ls && cd /fuori && rm -rf x"})[0] == "required",
          str(_dec("shell", {"command": "ls && cd /fuori && rm -rf x"})))
    check("G5 a bare `cd /fuori && cmd` is required",
          _dec("shell", {"command": "cd /fuori && cmd"})[0] == "required",
          str(_dec("shell", {"command": "cd /fuori && cmd"})))
    check("G6 reading an absolute path OUTSIDE the ws (`cat /etc/shadow`) -> required",
          _dec("shell", {"command": "cat /etc/shadow"})[0] == "required",
          str(_dec("shell", {"command": "cat /etc/shadow"})))
    check("G7 a system/scratch path (`ls /usr/bin`, `echo x > /tmp/y`) stays auto",
          _dec("shell", {"command": "ls /usr/bin"})[0] == "auto"
          and _dec("shell", {"command": "echo x > /tmp/y"})[0] == "auto",
          str(_dec("shell", {"command": "ls /usr/bin"})))
    check("G8 fs.read OUTSIDE the ws -> required, INSIDE -> auto",
          _dec("fs.read", {"path": os.path.join(outside, "f.txt")})[0] == "required"
          and _dec("fs.read", {"path": os.path.join(inside, "f.txt")})[0] == "auto",
          str(_dec("fs.read", {"path": os.path.join(outside, "f.txt")})))
    check("G9 `git -C` OUTSIDE the ws -> required",
          _dec("git", {"args": "status", "cwd": outside})[0] == "required",
          str(_dec("git", {"args": "status", "cwd": outside})))
    _cwd0 = os.getcwd()
    os.chdir(wc)
    try:
        check("G11 a RELATIVE cwd inside the ws stays auto",
              _dec("shell", {"command": "pwd", "cwd": "sub"})[0] == "auto",
              str(_dec("shell", {"command": "pwd", "cwd": "sub"})))
    finally:
        os.chdir(_cwd0)
    # `tmp` is OUTSIDE the repo, which is exactly the root fs.* allow-lists to.
    check("G12 the fs ROOT allow-list refuses an outside path in normal mode",
          registry.resolve_path(os.path.join(tmp, "f.txt"), ["."])[1] is not None,
          str(registry.resolve_path(os.path.join(tmp, "f.txt"), ["."])))
    _cfg["approvals"]["mode"] = "full"
    check("G10 approvals.mode=full disables the whole boundary",
          _dec("shell", {"command": "cat /etc/shadow"})[0] == "auto"
          and _dec("fs.read", {"path": os.path.join(outside, "f.txt")})[0] == "auto")
    # JAG-516: full mode is the ONE switch that lifts the fs root allow-list, so
    # fs.read / fs.write / fs.edit see the whole filesystem — like shell.exec,
    # which never had a root policy. Any other mode keeps config/tools.yaml roots.
    _p, _err = registry.resolve_path(os.path.join(tmp, "f.txt"), ["."])
    check("G13 approvals.mode=full lifts the fs ROOT allow-list too",
          _err is None and _p == os.path.realpath(os.path.join(tmp, "f.txt")),
          str((_p, _err)))
finally:
    registry.load_config = _real_load

# --- H: the approvals screen documents the rule (JAG-388) --------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    _HTML = _f.read()
check("H1 the policy card states the universal, mode-governed rule",
      "outside the session workspace" in _HTML and "enforced in code" in _HTML, "")
check("H2 the now-inert `Outside workspace` toggle is gone from the UI",
      'mk("outside_workspace"' not in _HTML and "Outside workspace</span>" not in _HTML, "")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

