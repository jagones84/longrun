#!/usr/bin/env python3
"""v935 — a batch of N items always accounts for N outcomes (frontier F3).

The observed defect (D1, 2026-11-03): a `batch` with two subagent items produced
ONE result and the turn continued with exit 0, so the work of the second item was
lost without a failure line. The structural check is a COUNT, not the message:
every item the harness accepted must leave exactly one outcome in the combined
observation.

Deterministic: no model, no network, no server. The Session Job scheduler is
stubbed to return fewer subjobs than it created — the silent drop itself.

Run: python3 tests/acceptance/v935_batch_no_silent_drop.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v935-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR", "MATRIX_SRC",
           "MATRIX_DOT"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv  # noqa: E402,F401 — server imports agent's prompt constants
from longrun.agent import agent as A  # noqa: E402
from longrun.agent import session_jobs as SJ  # noqa: E402

results = []
SESS = {"id": "v935-sess"}
EVENTS = []
ACT = {"calls": [{"action": "subagent", "goal": "alpha"},
                 {"action": "subagent", "goal": "beta"}]}

# The scheduler ACCEPTED two subjobs and returns only the first one: the exact
# shape of the silent drop. The fix must name the missing one as a FAILURE.
CREATED = {"ok": True, "job": "SJ1", "session": SESS["id"],
           "subjobs": ["SJ1.1", "SJ1.2"],
           "labels": {"SJ1.1": "alpha", "SJ1.2": "beta"}, "record": {}}
DROPPED = {"ok": False, "job": "SJ1", "status": "partial", "text": "",
           "subjobs": [{"id": "SJ1.1", "label": "alpha", "status": "done",
                        "result": "alpha done"}]}


def _fake_create(*_a, **_k):
    return dict(CREATED)


def _fake_run(*_a, **_k):
    return dict(DROPPED)


_orig_create, _orig_run = SJ.create, SJ.run
SJ.create, SJ.run = _fake_create, _fake_run
try:
    TEXT = A._apply_chat_batch(SESS, ACT, lambda kind, **kw: EVENTS.append((kind, kw)), None)
finally:
    SJ.create, SJ.run = _orig_create, _orig_run


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# A) The header counts what was accepted.
check("A1 the header reports the two accepted subagent items",
      "Batch of 2 call(s)" in TEXT and "subagents: 2" in TEXT, TEXT[:160])

# B) Every accepted item has its OWN outcome block.
check("B1 the finished item is present with its result",
      "SJ1.1" in TEXT and "alpha done" in TEXT)
check("B2 the DROPPED item is still named in the batch",
      "SJ1.2" in TEXT, TEXT[-500:])
check("B3 the dropped item is marked FAILED, not omitted",
      "SJ1.2" in TEXT and "FAILED" in TEXT.split("SJ1.2", 1)[0].rsplit("###", 1)[-1],
      TEXT[-500:])
check("B4 the observation explains it was silently dropped",
      "no outcome" in TEXT.lower() or "silent" in TEXT.lower(), TEXT[-400:])

# C) Two item outcomes, not one (the blocker line itself is not an outcome).
check("C1 exactly one `### subagent` block per accepted item",
      TEXT.count("### subagent") == 2, TEXT.count("### subagent"))

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
