#!/usr/bin/env python3
"""v597 (RED) — Cline plan-before-act: session plan mode gates mutating tools.

Cline's Plan mode lets the agent explore but blocks modification tools until
the operator approves the proposed plan. Longrun has per-tool approvals but
no session-level plan lock: nothing stops the agent from acting before any
plan was reviewed. The slice (kernel only, established v595 pattern):

- `stores.set_plan_mode(sid, on)` persists the lock;
  `stores.propose_plan(sid, steps)` stores `{steps, status: proposed}`
  (empty steps raise); `stores.approve_plan(sid)` needs a proposed plan
  and flips to Act (`plan_mode` off, status approved);
  `stores.reject_plan(sid)` keeps the lock (status rejected).
- `registry.PLAN_GATED_TOOLS` (fs.write/fs.edit/shell/git/python x2 names)
  + `registry.session_plan_locked(sid)`; `classify()` denies gated tools
  for locked sessions ("plan mode ..."), read-only tools pass through,
  and even `approvals.mode=full` never bypasses an explicit lock
  (matrix-promote precedent).

Deterministic: isolated dirs, no model, no network.
Run: python3 tests/acceptance/v597_plan_mode.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="lr-plan-v597-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_DATA_DIR"] = _tmp
for d in ("cfg", "sessions"):
    os.makedirs(os.path.join(_tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: the session plan state machine -------------------------------------------
check("A1 set_plan_mode exists", callable(getattr(stores, "set_plan_mode", None)))
check("A2 propose_plan exists", callable(getattr(stores, "propose_plan", None)))
check("A3 approve_plan exists", callable(getattr(stores, "approve_plan", None)))
check("A4 reject_plan exists", callable(getattr(stores, "reject_plan", None)))
s = stores.get_or_create_session(None, title="v597")
sid = s["id"]
if all(callable(getattr(stores, n, None)) for n in
        ("set_plan_mode", "propose_plan", "approve_plan", "reject_plan")):
    stores.set_plan_mode(sid, True)
    check("A5 plan mode on persists",
          stores.load_session(sid).get("plan_mode") is True)
    stores.propose_plan(sid, ["survey the repo", "write the fix", "run tests"])
    plan = stores.load_session(sid).get("plan") or {}
    check("A6 proposal stores steps as proposed",
          plan.get("status") == "proposed" and len(plan.get("steps") or []) == 3,
          repr(plan))
    try:
        stores.propose_plan(sid, [])
        check("A7 empty steps rejected", False, "no raise")
    except ValueError:
        check("A7 empty steps rejected", True)
    stores.approve_plan(sid)
    s2 = stores.load_session(sid)
    check("A8 approval flips to act, plan kept approved",
          s2.get("plan_mode") is False
          and (s2.get("plan") or {}).get("status") == "approved",
          repr({k: s2.get(k) for k in ("plan_mode", "plan")}))
    try:
        stores.approve_plan(sid)
        check("A9 second approval rejected", False, "no raise")
    except ValueError:
        check("A9 second approval rejected", True)
    stores.set_plan_mode(sid, True)
    stores.propose_plan(sid, ["other plan"])
    stores.reject_plan(sid)
    s3 = stores.load_session(sid)
    check("A10 rejection keeps the lock",
          s3.get("plan_mode") is True
          and (s3.get("plan") or {}).get("status") == "rejected")
else:
    for n in ("A5", "A6", "A7", "A8", "A9", "A10"):
        check(n, False, "plan API missing")

# ---- B: the gate in classify ------------------------------------------------------
check("B1 PLAN_GATED_TOOLS covers write/edit/shell/git/python",
      {"fs.write", "fs.edit", "shell", "shell.exec", "git", "git.run",
       "python", "python.run"} <= set(getattr(registry, "PLAN_GATED_TOOLS", ())),
      repr(getattr(registry, "PLAN_GATED_TOOLS", None)))
if hasattr(registry, "PLAN_GATED_TOOLS"):
    stores.set_plan_mode(sid, True)
    stores.propose_plan(sid, ["step one"])
    dec, why = registry.classify("shell", {"_session": sid})
    check("B2 mutating tool denied in plan mode",
          dec == "denied" and "plan mode" in why, repr((dec, why)))
    dec, why = registry.classify("fs.read", {"_session": sid})
    check("B3 read-only tool not plan-gated", "plan mode" not in why,
          repr((dec, why)))
    stores.approve_plan(sid)
    dec, why = registry.classify("shell", {"_session": sid})
    check("B4 approval unblocks mutating tools", "plan mode" not in why,
          repr((dec, why)))
    stores.set_plan_mode(sid, True)
    stores.propose_plan(sid, ["step two"])
    real_cfg = registry.load_config
    real_spec = registry.tool_spec
    registry.load_config = lambda reload=False: {"approvals": {"mode": "full"},
                                                 "tools": {}}

    def _fake_spec(name, ext_snapshot=None, mtx_snapshot=None):
        s = real_spec(name, ext_snapshot, mtx_snapshot)
        if name == "shell" and isinstance(s, dict):
            s = dict(s, enabled=True, approval="auto", auto_approve=[],
                     deny=[])
        return s

    registry.tool_spec = _fake_spec
    try:
        dec, why = registry.classify("shell", {"_session": sid})
        check("B5 even full mode never bypasses the lock",
              dec == "denied" and "plan mode" in why, repr((dec, why)))
    finally:
        registry.load_config = real_cfg
        registry.tool_spec = real_spec
    dec, why = registry.classify("shell", {"_session": "no-such-session"})
    check("B6 unknown sessions unaffected", "plan mode" not in why,
          repr((dec, why)))
else:
    for n in ("B2", "B3", "B4", "B5", "B6"):
        check(n, False, "PLAN_GATED_TOOLS missing")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
