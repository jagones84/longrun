#!/usr/bin/env python3
"""v853 — the prompt's memory section must not walk the whole store quadratically.

Operator report (2026-11-07): "the WebUI is very slow now, even expanding a team or
switching session". Measured on the DGX: `GET /api/context` answered in
5303-6295 ms while every other session-switch endpoint stayed under 100 ms, and a
concurrent `GET /api/sessions` went from 5 ms to 664 ms — one request froze the
whole process. The cost was `memory.dedupe`, quadratic over the records
`governed_query` loads (500 per kind): 3695 ms for 498 agent.note records, dropping
none of them.

What this pins:
  A) `dedupe(records, limit=k)` returns EXACTLY the first k survivors of a full
     pass `dedupe(records)[:k]` — the early exit may not change the result;
  B) near-duplicates still collapse (the guard the section exists for);
  C) with no `limit` the contract is unchanged (a full pass, same output);
  D) the work is bounded: naming 4 memories must not read the whole store —
     measured by counting `_norm` calls, the one thing `dedupe` spends time on
     (125k calls before the fix, ~4 after);
  E) `governed_query` still returns the same top-N it returned from a full pass.

Deterministic, no model, no network.

Run:  python3 tests/acceptance/v853_prompt_memory_dedupe_budget.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-853-")
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

from longrun.memory import memory as mem  # noqa: E402

# isolate the store: redirect DATA_DIR/CORE to the temp dir, force the keyword path
mem.DATA_DIR = os.path.join(tmp, "memory")
mem.CORE_PATH = os.path.join(mem.DATA_DIR, "core.md")
os.makedirs(mem.DATA_DIR, exist_ok=True)
mem._vector_db = {}                 # falsy -> semantic_query falls back to keyword
mem._rebuild_index = lambda *a, **k: None   # writer-side vector work is not under test

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def rec(text, mid="m"):
    return {"mid": mid, "kind": "agent.note", "content": text, "ts": 1.0}


# ---- A/B/C: the dedupe contract (synthetic, so the verdicts are inspectable) ----
near = rec("always restart the longrun service after a runtime change")
near2 = rec("always restart the longrun service after a runtime change now")
far = rec("prefer the shared drag engine over a second order store")
empty = rec("", mid="empty")

sample = [near, near2, far, empty, rec("another plainly different lesson")]

check("A1 a twin is still dropped",
      len(mem.dedupe(sample)) == len(sample) - 1,
      "in=%d out=%d" % (len(sample), len(mem.dedupe(sample))))

for k in (1, 2, 3, len(sample), len(sample) + 5):
    try:
        got = mem.dedupe(sample, limit=k)
    except TypeError as e:      # pre-fix: the bounded call does not exist yet
        check("A2 limit=%s is the full pass's first %s" % (k, k), False, str(e))
        continue
    want = mem.dedupe(sample)[:k]
    check("A2 limit=%s is the full pass's first %s" % (k, k),
          [r["mid"] for r in got] == [r["mid"] for r in want],
          "got=%s want=%s" % ([r["mid"] for r in got], [r["mid"] for r in want]))

check("C1 without limit the output is unchanged (full pass)",
      len(mem.dedupe(sample)) == 4, "n=%d" % len(mem.dedupe(sample)))

# ---- D/E: the real store, at the size the operator's box reached ----
# 600 GENUINELY DISTINCT lessons: each carries its own unique tokens, so none of
# them is a near-duplicate of another. A dataset whose rows share most tokens
# would collapse under the very guard being tested and hide the cost it exists to
# bound (the first version of this file did exactly that and reported n=2).
N = 600
for i in range(N):
    mem.store("agent.note",
              "lesson %d kept alpha%d beta%d gamma%d delta%d"
              % (i, i, i, i, i), source="v853")
# a planted near-duplicate of the NEWEST record (governed_query ranks newest first)
mem.store("agent.note",
          "lesson %d kept alpha%d beta%d gamma%d delta%d"
          % (N - 1, N - 1, N - 1, N - 1, N - 1), source="v853")

norm_calls = [0]
_real_norm = mem._norm


def _counting_norm(content):
    norm_calls[0] += 1
    return _real_norm(content)


mem._norm = _counting_norm
try:
    hits = mem.governed_query(kind="agent.note", limit=4)
finally:
    mem._norm = _real_norm

check("D1 governed_query returns the requested rows",
      len(hits) == 4, "n=%d" % len(hits))
check("D2 naming 4 of %d records stays bounded (<=50 _norm calls)" % (N + 1),
      norm_calls[0] <= 50, "calls=%d" % norm_calls[0])

# E: the same top-N a full pass (the old, unbounded algorithm) produces
recs = mem.query(None, "agent.note", limit=500)
full = mem.dedupe(mem.rank(recs))[:4]
check("E1 the fast path returns the full pass's own top-4",
      [r["mid"] for r in hits] == [r["mid"] for r in full],
      "fast=%s full=%s" % ([r["mid"] for r in hits], [r["mid"] for r in full]))
check("E2 the planted twin never appears twice",
      len({r.get("content") for r in hits}) == len(hits))

print("")
print("%d/%d GREEN" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
