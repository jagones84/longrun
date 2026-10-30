#!/usr/bin/env python3
"""v741 — the read-back reports THIS turn, never a neighbour's deliverables.

Operator (2026-10-30, second occurrence): *"the harness read-back keeps citing
benchmark files (`jobbench_4arm_online-merchants`, `bookkeeping`) that were never
produced in this conversation — possible cross-contamination between sessions; if
you want, give it a dedicated test."*

Root cause: the read-back decides "what you WROTE this turn" from mtime alone. A
chat whose workspace is the REPO ROOT therefore inherits every document a
concurrently-running benchmark writes, because those files live inside the chat's
workspace and are fresh. The session table already knows every workspace, so the
fix is a boundary, not a heuristic: a workspace that is strictly INSIDE mine is
another session's tree and is excluded (plus the campaign folder holding it).

  A  `_other_session_roots(sess)` excludes a NESTED workspace and its run folder;
     it never excludes my own workspace, nor an ANCESTOR workspace (that would
     erase the whole read-back of a chat nested in a bigger one).
  B  `_deliverable_review_text` reports the file I wrote and NOT the neighbour's.
  C  a nested chat still sees its own artifacts (the boundary is not a mute).

Deterministic: temp dirs, no live model, no network, no server.
Run: python3 tests/acceptance/v741_readback_session_boundary.py
"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="sf-v741-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT", "DATA_DIR"):
    _v = os.path.join(TMP, "state", _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE"):
        os.makedirs(_v, exist_ok=True)
    os.environ["LONGRUN_" + _k] = _v
os.environ["LONGRUN_DB"] = os.path.join(TMP, "state", "events.db")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv        # noqa: E402,F401 — import order
from longrun.agent import agent as AG          # noqa: E402
from longrun.memory import stores              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _ws(*parts):
    p = os.path.join(TMP, "root", *parts)
    os.makedirs(p, exist_ok=True)
    return p


MINE = _ws()
# a benchmark-shaped tree NESTED inside the chat's workspace, exactly as the
# real one is laid out:  <root>/.agent/BENCHMARKS/runs/<run>/<arm>/<task>/workspace
BENCH = _ws(".agent", "BENCHMARKS", "runs")
RUN_DIR = os.path.join(BENCH, "2026-10-30_run")
OTHER = os.path.join(RUN_DIR, "longrun", "task1", "workspace")
os.makedirs(OTHER, exist_ok=True)
PARENT = os.path.dirname(MINE)                         # an ancestor of MINE


def _sess(sid, ws, title):
    s = stores.get_or_create_session(sid, title)
    s["workspace"] = ws
    stores.save_session(s)
    return stores.load_session(sid)


me = _sess("me-0000000001", MINE, "chat with a broad workspace")
neighbour = _sess("nb-0000000002", OTHER, "benchmark task")
parent_sess = _sess("pa-0000000003", PARENT, "chat one level up")

# --- A: the boundary ---------------------------------------------------------
roots = AG._other_session_roots(me)
check("A1 another session's NESTED workspace is excluded",
      OTHER in roots, roots)
check("A2 the run folder that holds a nested workspace (its compare.md too) is excluded",
      RUN_DIR in roots, roots)
check("A3 my own workspace is never in the exclude list",
      os.path.abspath(MINE) not in roots)
check("A4 an ANCESTOR workspace is never excluded (it would mute the read-back)",
      os.path.abspath(PARENT) not in roots
      and not any(r == os.path.abspath(PARENT) for r in roots), roots)
check("A5 a chat nested under broader workspaces excludes nothing (all are ancestors)",
      AG._other_session_roots(neighbour) == [],
      AG._other_session_roots(neighbour))

# --- B: the read-back reports the right turn ---------------------------------
since = time.time() - 1.0
out_mine = os.path.join(MINE, "output")
out_other = os.path.join(OTHER, "output")
os.makedirs(out_mine, exist_ok=True)
os.makedirs(out_other, exist_ok=True)
with open(os.path.join(out_mine, "my_report.csv"), "w", encoding="utf-8") as f:
    f.write("a,b\n1,2\n")
with open(os.path.join(out_other, "their_report.csv"), "w", encoding="utf-8") as f:
    f.write("x,y\n3,4\n")
with open(os.path.join(RUN_DIR, "compare.md"), "w", encoding="utf-8") as f:
    f.write("# benchmark comparison\n")

txt = AG._deliverable_review_text(me, "do the thing", since, {"left": 3}) or ""
check("B1 my own deliverable is read back",
      "my_report.csv" in txt, txt[:300])
check("B2 a concurrent session's deliverable is NOT reported as mine",
      "their_report.csv" not in txt and "compare.md" not in txt, txt[:300])

# --- C: the boundary is not a mute ------------------------------------------
txt_nb = AG._deliverable_review_text(neighbour, "do the benchmark", since, {"left": 3}) or ""
check("C1 the nested session still sees its own deliverables",
      "their_report.csv" in txt_nb, txt_nb[:300])

print("---")
ok = sum(results)
print("\nv741: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
