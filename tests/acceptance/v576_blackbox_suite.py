#!/usr/bin/env python3
"""v576 — M9 black-box suite: the guardrails hold end-to-end (notes/M9-*).

Drives the PUBLIC loop (`agent_run_v2`) with scripted adversarial models —
no model, no network. `approvals.wait` is patched to auto-approve so the
suite measures the GATE DECISION (auto vs required), not the human wait;
`on_event` is captured for fence notes. What it proves:

  P1 tainted auto -> required (M2a end-to-end, reason names the taint)
  P2 pure auto -> executes with no approval asked (no added friction)
  P3 off-intent tool -> intent-fence note event, run still completes
  P4 granted required approval is spent after execution (uses_left 0)
  P5 phantom subagent citation -> required (R1 end-to-end)

R2 is NOT isolable end-to-end (in the real loop every execution leaves an
observation, so M2a always shadows it) — covered by the pure v566 tests.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v576-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.tools import approvals  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_waits = []
_orig_wait = approvals.wait


def _approve_all(aid, timeout=None, checkpoint=None, **_k):
    _waits.append(aid)
    return approvals.decide(aid, "approve", by="v576")


approvals.wait = _approve_all


def _run(goal, script, max_steps=4):
    events = []
    try:
        res = API.agent_run_v2(
            goal, max_steps=max_steps, script=script,
            on_event=lambda kind, **d: events.append((kind, d)))
    finally:
        pass
    return res, events


def _new_records(before):
    seen = set(before)
    return [r for r in approvals.list_all(None, 100000) if r["id"] not in seen]


def _ids():
    return [r["id"] for r in approvals.list_all(None, 100000)]


try:
    # ---- P2 baseline first (pure context, zero friction) -----------------------
    before = _ids()
    _waits.clear()
    res, _ev = _run("do admin checks",
                    [{"action": "tool", "tool": "glob", "args": {"pattern": "*.py"}}],
                    max_steps=2)
    new = _new_records(before)
    check("P2 pure auto executes with no approval asked",
          res.get("termination") == "completed" and not _waits
          and len(new) == 1 and new[0].get("status") == "auto_approved",
          (res.get("termination"), [r.get("status") for r in new]))

    # ---- P1 taint end-to-end ----------------------------------------------------
    before = _ids()
    _waits.clear()
    res, _ev = _run("do admin checks",
                    [{"action": "tool", "tool": "glob", "args": {"pattern": "*.py"}},
                     {"action": "tool", "tool": "process", "args": {"action": "list"}}],
                    max_steps=3)
    new = _new_records(before)
    _proc = [r for r in new if r.get("tool") in ("process", "process.list")]
    check("P1 tainted standing auto escalates to required",
          res.get("termination") == "completed" and len(_waits) == 1 and len(_proc) == 1
          and "standing auto-approval suspended" in (_proc[0].get("reason") or ""),
          (res.get("termination"), [r.get("reason") for r in _proc]))

    # ---- P5 delegation end-to-end -------------------------------------------------
    before = _ids()
    _waits.clear()
    res, _ev = _run("do admin checks",
                    [{"action": "tool", "tool": "glob",
                      "args": {"pattern": "sub_deadbeef01*"}}],
                    max_steps=2)
    new = _new_records(before)
    check("P5 phantom subagent citation requires approval",
          res.get("termination") == "completed" and len(_waits) == 1 and len(new) == 1
          and "delegation must revalidate" in (new[0].get("reason") or "")
          and "sub_deadbeef01" in (new[0].get("reason") or ""),
          (res.get("termination"), len(_waits),
           [(r.get("status"), r.get("reason")) for r in new]))

    # ---- P4 the granted mark is spent ----------------------------------------------
    before = _ids()
    _waits.clear()
    res, _ev = _run("do admin checks",
                    [{"action": "tool", "tool": "python", "args": {"code": "1"}}],
                    max_steps=2)
    new = _new_records(before)
    check("P4 executed approvals are spent (no replay)",
          res.get("termination") == "completed" and len(new) == 1
          and new[0].get("status") == "approved" and new[0].get("uses_left") == 0,
          (res.get("termination"), [(r.get("status"), r.get("uses_left")) for r in new]))

    # ---- P3 fence note ---------------------------------------------------------------
    _waits.clear()
    res, ev = _run("do admin checks",
                   [{"action": "tool", "tool": "fs.read",
                     "args": {"path": "qqq-zzz.txt"}}],
                   max_steps=2)
    _fence = [d for k, d in ev if k == "agent.trace_policy"
              and d.get("rule") == "intent-fence"]
    check("P3 off-intent tools earn a fence note and the run completes",
          res.get("termination") == "completed" and len(_fence) == 1
          and "qqq-zzz" in (_fence[0].get("note") or ""),
          (res.get("termination"), len(_fence)))
finally:
    approvals.wait = _orig_wait

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
