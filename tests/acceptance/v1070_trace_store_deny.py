#!/usr/bin/env python3
"""v1070 — the agent may not rewrite its own record (trace tampering).

Source: "LLM Agents Can Easily Tamper With Their Own Traces" (arXiv:2609.30266,
stored S-2026-11-18-015): every tested harness but one let the agent DELETE its own
execution traces, defeating monitoring and audit; the fix is a control OUTSIDE the
agent's reach. Longrun already moves user state outside the checkout (paths.py
JAG-533) and seals the held-out judge (plan/heldout.py) — but a LEGACY in-checkout
`data/` sits INSIDE the fs roots, so `fs.write`/`fs.edit` could still rewrite the
runs, the transcript, the event log and the sealed judge. This pins the hard deny.

Contract:
  T1 `fs.write` to data/runs, data/sessions, data/threads, data/heldout is DENIED
  T2 `fs.write` to data/events.db is DENIED
  T3 `fs.edit` on the same store is DENIED
  T4 `fs.read` of the sealed heldout store is DENIED
  T5 an ordinary path is NOT denied (the guard is a store deny-list, not a blanket)

Deterministic: pure `registry.classify`, no server, no model.
Run: python3 tests/acceptance/v1070_trace_store_deny.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def decision(tool, path):
    d, why = registry.classify(tool, {"path": path})
    return d, why


STORE = os.path.join(REPO, "data")

for rel in ("runs/r1.json", "sessions/s.json", "threads/t.json", "heldout/manifest.json"):
    _d, _why = decision("fs.write", os.path.join(STORE, rel))
    check("T1 fs.write denied: data/%s" % rel, _d == "denied", (_d, _why))
_d, _why = decision("fs.write", os.path.join(STORE, "events.db"))
check("T2 fs.write denied: data/events.db", _d == "denied", (_d, _why))

for rel in ("runs/r1.json", "sessions/s.json", "heldout/manifest.json"):
    _d, _why = decision("fs.edit", os.path.join(STORE, rel))
    check("T3 fs.edit denied: data/%s" % rel, _d == "denied", (_d, _why))

_d, _why = decision("fs.read", os.path.join(STORE, "heldout", "manifest.json"))
check("T4 fs.read denied: data/heldout/manifest.json", _d == "denied", (_d, _why))

_d, _why = decision("fs.write", os.path.join(REPO, "src", "longrun", "note.txt"))
check("T5 an ordinary path is not denied", _d != "denied", (_d, _why))

print("\n---\nv1070: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
