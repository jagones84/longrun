#!/usr/bin/env python3
"""v415 — baseline toolset: python / process / glob (JAG-426 · Domain 5).

Longrun shipped 17 native tools but had NO native Python execution (only via the
external pmcp MCP client), no process management and no structured file listing.
This pins the three new primitives, their policies (python/process-kill need
approval, process-list and glob are auto), and their hard guards.

Deterministic, no live server. Run: python3 tests/v415_baseline_tools.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v415-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry       # noqa: E402
from longrun.tools import tools as T     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


NAMES = {t["name"] for t in registry.catalog() if t.get("name")}


def _spec_approval(name):
    """Declarative policy from config/tools.yaml (independent of any overlay)."""
    return (registry.tool_spec(name) or {}).get("approval")


def _classify_normal(name, args):
    """classify() under the NEUTRAL approvals mode — the live install may set
    `approvals.mode: full` in data/tools.overlay.yaml (never ask), which would
    mask the per-tool policy this test is about."""
    cfg = registry.load_config()
    ap = cfg.setdefault("approvals", {})
    saved = ap.get("mode")
    ap["mode"] = "normal"
    try:
        return registry.classify(name, args)[0]
    finally:
        ap["mode"] = saved if saved is not None else "normal"


# ---- 1. declared + policy ----------------------------------------------------
check("1a python/process/glob are registered tools",
      {"python", "process", "glob"}.issubset(NAMES), sorted(NAMES)[:8])
check("1b python is approval=required (declared + classified)",
      _spec_approval("python") == "required"
      and _classify_normal("python", {"code": "1"}) == "required")
check("1c process: declared required, list auto-approved, kill required",
      _spec_approval("process") == "required"
      and "^list$" in ((registry.tool_spec("process") or {}).get("auto_approve") or [])
      and _classify_normal("process", {"action": "list"}) == "auto"
      and _classify_normal("process", {"action": "kill", "pid": 42}) == "required")
check("1d glob is read-only (declared auto)",
      _spec_approval("glob") == "auto" and _classify_normal("glob", {"pattern": "*"}) == "auto")

# ---- 2. python executes ------------------------------------------------------
r = T.execute("python", {"code": "print(6*7)"}, run_id="v415")
check("2a python runs and returns stdout", r.get("ok") is True and "42" in (r.get("stdout") or ""),
      (r.get("stdout") or "")[:60])
r2 = T.execute("python", {"code": "import sys; sys.exit(3)"}, run_id="v415")
check("2b a non-zero exit is reported (ok False, exit 3)",
      r2.get("ok") is False and r2.get("exit_code") == 3, r2.get("exit_code"))
r3 = T.execute("python", {"code": ""}, run_id="v415")
check("2c empty code is refused", r3.get("ok") is False)

# ---- 3. process --------------------------------------------------------------
pl = T.execute("process", {"action": "list", "limit": 5}, run_id="v415")
check("3a process list returns rows", pl.get("ok") is True and pl.get("count", 0) >= 1,
      pl.get("count"))
check("3b kill of pid<=1 is refused",
      T.execute("process", {"action": "kill", "pid": 1}, run_id="v415").get("ok") is False)
check("3c kill of the harness itself is refused",
      T.execute("process", {"action": "kill", "pid": os.getpid()}, run_id="v415").get("ok") is False)
check("3d kill without a pid is refused",
      T.execute("process", {"action": "kill"}, run_id="v415").get("ok") is False)

# ---- 4. glob -----------------------------------------------------------------
g = T.execute("glob", {"pattern": "**/*.py", "root": os.path.join(REPO, "src", "longrun", "tools")},
              run_id="v415")
check("4a glob finds files",
      g.get("ok") is True and g.get("count", 0) >= 5 and any("tools.py" in f for f in g.get("files", [])),
      g.get("count"))
check("4b glob honours the allowed roots (escape refused)",
      T.execute("glob", {"pattern": "*", "root": "/etc"}, run_id="v415").get("ok") is False)
check("4c glob without a pattern is refused",
      T.execute("glob", {}, run_id="v415").get("ok") is False)

print("---")
okc = sum(results)
print("\nv415: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
