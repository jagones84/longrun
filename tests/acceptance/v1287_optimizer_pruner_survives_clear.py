#!/usr/bin/env python3
"""v1287 — the optimizer pruner's memory survives `clear_decided` (I-4).

Bug-hunt/RSI pass 2026-11-23. The RRSI pruner (`optimizer.run`) skips a delta
whose identity is already in `_evolution_history()`. That history was built ONLY
from the proposal store, and `improve.clear_decided()` DELETES decided proposals
(its docstring says "the ledger already records every decision") — but the ledger
row carried no delta IDENTITY, so the pruner's memory died with the file and a
denied/reverted delta could be re-proposed after a "clear decided": the exact
oscillation the pruner exists to stop.

Fix: `_submit` stamps `delta_key` on the durable ledger, and `_evolution_history`
merges the refused deltas back from the record that is never deleted.

Contract:
  A `_submit` creates a registry proposal; deny + `clear_decided` removes the JSON
  B `_evolution_history` still reports the refused delta (from the ledger)
  C `run()` skips a re-proposal of that same delta after the clear
  D `_history_block` tolerates the identity-only (durable) rows

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1287_optimizer_pruner_survives_clear.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-v1287-")
os.environ["LONGRUN_OFFLINE"] = "1"
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "PROPOSALS_DIR",
           "IMPROVEMENT_DIR", "MATRIX_DOT", "MATRIX_SRC", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(tmp, _k)
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)

from longrun.evolve import optimizer as O       # noqa: E402
from longrun.util import improve as I           # noqa: E402
from longrun.tools import registry              # noqa: E402

registry._external_tools = lambda: {}

DELTA = {"target": "shell.exec", "field": "approval", "value": "required",
         "reason": "the row was too permissive", "confidence": "high"}

# ---- A: submit through the real optimizer path, deny, clear ----------------
pid = O._submit(DELTA, {}, "v1287")
check("A1 the optimizer submitted a registry proposal", isinstance(pid, str) and pid, pid)
_d = I.decide(pid, "deny")
check("A2 the proposal was denied",
      _d.get("ok") is True and _d.get("status") == "denied", _d)
_cleared = I.clear_decided()
check("A3 clear_decided removed the proposal JSON", int(_cleared.get("removed") or 0) >= 1, _cleared)
check("A4 the store no longer holds it",
      all(p.get("id") != pid for p in I.list_proposals()), I.list_proposals())

# ---- B: the pruner still remembers it, from the durable ledger -------------
_key = O._delta_key(DELTA)
hist = O._evolution_history()
check("B1 the durable history still carries the refused delta",
      any(h.get("key") == _key and h.get("status") == "denied" for h in hist),
      [(h.get("status"), h.get("key")) for h in hist])
_block = O._history_block(hist)
check("B2 the prompt block handles the identity-only rows (no crash, no 'None')",
      isinstance(_block, str) and "None" not in _block, _block)

# ---- C: a re-proposal after the clear is skipped ---------------------------
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: {}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._read_refusals = lambda sid: {}
O._call_model = lambda prompt: json.dumps(DELTA)
_r = O.run("v1287-b")
check("C1 a re-proposal after clear_decided is skipped",
      _r.get("skip") is True and "already proposed" in (_r.get("reason") or ""),
      _r.get("reason"))

print("---")
ok_n = sum(RESULTS)
print("v1287: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
