#!/usr/bin/env python3
"""v794 — a lesson learned in one project does not leak into another (M1).

Live evidence for the need: the harness ledger has 259 auto-distilled lessons
(`origin=reflect`), ALL written into one global file `agent_notes.md`, and every
session of every project loads them. Meta² (the corpus's strongest accumulation
result) measures the cost: a task-local edit kept globally degrades the NEXT task.

Contract locked here:
  * a record written with `workspace="<path>"` is visible in THAT workspace and
    invisible in another;
  * a record with NO workspace is GLOBAL and visible EVERYWHERE — so this change
    can hide nothing that was already stored (the 259 existing lessons stay);
  * `workspace=None` (every pre-M1 call path) means NO FILTER, i.e. the old
    behaviour byte-for-byte;
  * all four readers honour it: query, search (keyword), semantic_query
    (incl. its keyword fallback), recall_governed;
  * the prompt pull and the reflect writer really pass the workspace.

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v794_memory_workspace_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v794-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory             # noqa: E402

WS_A = os.path.join(TMP, "proj-a")
WS_B = os.path.join(TMP, "proj-b")
for _d in (WS_A, WS_B):
    os.makedirs(_d, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _texts(recs):
    return [str((r or {}).get("content") or "") for r in recs]


def _hits_texts(hits):
    return [str((r or {}).get("content") or "") for _s, r in hits]


# ---- the three records -----------------------------------------------------
memory.store("agent.note", "lesson for project A", origin="reflect", workspace=WS_A)
memory.store("agent.note", "lesson for project B", origin="reflect", workspace=WS_B)
memory.store("agent.note", "global lesson, no workspace", origin="user")

# ---- A. the store round-trips the field ------------------------------------
_raw = open(memory._path("agent.note"), encoding="utf-8").read()
check("A1 the workspace is written to the file (front-matter)",
      ("workspace: %s" % WS_A) in _raw, _raw[:120])

_all = _texts(memory.query(None, None, 50))
check("A2 no filter sees every record (pre-M1 behaviour)",
      "lesson for project A" in _all and "lesson for project B" in _all
      and "global lesson, no workspace" in _all, _all)

_a = _texts(memory.query(None, None, 50, WS_A))
check("A3 workspace A sees its own + the global one",
      "lesson for project A" in _a and "global lesson, no workspace" in _a, _a)
check("A4 workspace A does NOT see project B's lesson",
      "lesson for project B" not in _a, _a)

_b = _texts(memory.query(None, None, 50, WS_B))
check("A5 workspace B sees its own + the global, not A's",
      "lesson for project B" in _b and "global lesson, no workspace" in _b
      and "lesson for project A" not in _b, _b)

check("A6 explicit None == no filter",
      len(_texts(memory.query(None, None, 50, None))) == 3)
check("A7 a blank workspace == no filter",
      len(_texts(memory.query(None, None, 50, ""))) == 3)

# ---- B. path spellings -----------------------------------------------------
_trailing = _texts(memory.query(None, None, 50, WS_A + os.sep))
check("B1 a trailing separator is the same workspace",
      "lesson for project A" in _trailing and "lesson for project B" not in _trailing,
      _trailing)

# ---- C. every reader honours it -------------------------------------------
_kw = _hits_texts(memory.search("lesson project", None, 10, False, WS_A))
check("C1 search (keyword) filters", "lesson for project A" in _kw
      and "lesson for project B" not in _kw, _kw)
_kw_none = _hits_texts(memory.search("lesson project", None, 10, False))
check("C2 search without a workspace still sees both",
      "lesson for project A" in _kw_none and "lesson for project B" in _kw_none, _kw_none)

_sem = _hits_texts(memory.semantic_query("lesson project", None, 10, 0.15, WS_A))
check("C3 semantic_query (fallback path) filters",
      "lesson for project A" in _sem and "lesson for project B" not in _sem, _sem)

_gov = _hits_texts(memory.recall_governed("lesson project", None, 10, False, False, WS_A))
check("C4 recall_governed filters",
      "lesson for project A" in _gov and "lesson for project B" not in _gov, _gov)

_health = memory.health()
check("C5 health() still counts EVERY record (it repairs, it does not read)",
      _health.get("total") == 3, _health)

# ---- D. the call sites really pass the workspace ---------------------------
def _src(rel):
    with open(os.path.join(REPO, "src", "longrun", rel), encoding="utf-8") as fh:
        return fh.read()


_ce = _src(os.path.join("model", "context_engine.py"))
check("D1 the prompt pull threads the workspace through retrieve/build",
      "workspace=None):" in _ce and "retrieve(query, workspace=workspace)" in _ce
      and "workspace=sess.get(\"workspace\")" in _ce, "")
_ag = _src(os.path.join("agent", "agent.py"))
_n_sites = _ag.count("workspace=(sess or {})")
check("D2 BOTH session call sites pass the workspace (assemble_turn + reflect writer)",
      _n_sites >= 2, "occurrences=%d" % _n_sites)

# ---- E. never raises on garbage -------------------------------------------
check("E1 _ws_key tolerates None / int / object",
      memory._ws_key(None) == "" and isinstance(memory._ws_key(123), str)
      and isinstance(memory._ws_key(object()), str))
check("E2 _visible tolerates a record without the field",
      memory._visible({"content": "x"}, memory._ws_key(WS_A)) is True)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
