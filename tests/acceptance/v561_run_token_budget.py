#!/usr/bin/env python3
"""v561 (staged, RED) — cumulative per-run token budget.

M6 of the upgrade plan: `RunState.tokens_spent` accumulates prompt+completion
tokens from every model call (failover hops included); `_run_tree_spent`
adds subagent descendants via `parent_run_id`; `agent_run_v2` stops with
`termination="budget"` when the tree spend reaches `token_budget`. Missing
usage adds 0 — never a chars/4 fiction — and `costs.record` of a counterless
call stays `usd None`.

Deterministic, no model, no network.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
TMP = tempfile.mkdtemp(prefix="sf-v561-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A  # noqa: E402
from longrun.model import costs as C  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


# ---- B: accounting helper ----------------------------------------------------
_acc = getattr(A, "_account_call", None)
check("B0 api_v02._account_call exists", callable(_acc))
if callable(_acc):
    _st = A.new_run("budget-probe", "m", 2)
    check("B1 usage adds prompt+completion",
          _acc(_st, {"prompt_tokens": 600, "completion_tokens": 400}) == 1000
          and _st.tokens_spent == 1000, getattr(_st, "tokens_spent", None))
    check("B2 empty/None/counterless usage adds 0",
          _acc(_st, {}) == 0 and _acc(_st, None) == 0
          and _acc(_st, {"note": "no counters"}) == 0
          and _st.tokens_spent == 1000, getattr(_st, "tokens_spent", None))
    _acc(_st, {"prompt_tokens": 300, "completion_tokens": 200})
    check("B3 spend accumulates across calls", _st.tokens_spent == 1500,
          getattr(_st, "tokens_spent", None))
else:
    for n in ("B1 usage adds prompt+completion",
              "B2 empty/None/counterless usage adds 0",
              "B3 spend accumulates across calls"):
        check(n, False, "_account_call missing")

# ---- C: the tree counts subagents -------------------------------------------
_tree = getattr(A, "_run_tree_spent", None)
check("C0 api_v02._run_tree_spent exists", callable(_tree))
if callable(_tree):
    _p = A.new_run("parent", "m", 2)
    _p.tokens_spent = 200
    _c = A.new_run("child", "m", 2)
    _c.tokens_spent = 400
    _c.parent_run_id = _p.id
    try:
        check("C1 a 400-token child counts on its parent",
              _tree(_p) == 600, _tree(_p))
        _c.parent_run_id = _c.id  # pathological self-cycle
        check("C2 a parent cycle still terminates", _tree(_c) == 400, _tree(_c))
    finally:
        A.RUNS.pop(_p.id, None)
        A.RUNS.pop(_c.id, None)
else:
    check("C1 a 400-token child counts on its parent", False, "_run_tree_spent missing")
    check("C2 a parent cycle still terminates", False, "_run_tree_spent missing")

# ---- D: the budget check helper ---------------------------------------------
_hit = getattr(A, "_budget_exceeded", None)
check("D0 api_v02._budget_exceeded exists", callable(_hit))
if callable(_hit):
    _s = A.new_run("b", "m", 2)
    _s.tokens_spent = 1000
    try:
        check("D1 spend at budget reports exceeded",
              _hit(_s, 1000) == (True, 1000), _hit(_s, 1000))
        check("D2 spend under budget reports the total",
              _hit(_s, 1001) == (False, 1000), _hit(_s, 1001))
        check("D3 no budget never trips", _hit(_s, None) == (False, 1000),
              _hit(_s, None))
    finally:
        A.RUNS.pop(_s.id, None)
else:
    for n in ("D1 spend at budget reports exceeded",
              "D2 spend under budget reports the total",
              "D3 no budget never trips"):
        check(n, False, "_budget_exceeded missing")

# ---- E: counterless cost stays unknown, never fiction ------------------------
_rec = C.record("sess-v561", "m", {"note": "provider said nothing"}, run="run-v561")
check("E1 a counterless call records usd None",
      isinstance(_rec, dict) and _rec.get("usd") is None, _rec)

# ---- F: source locks (the loop really accounts + caps) -----------------------
def _read(*parts):
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


_SRC = _read("src", "longrun", "core", "api_v02.py")
check("F1 the loop hands its usage to the router call",
      "usage=" in _SRC and "_router_stream(" in _SRC)
check("F2 the loop accounts every model call", "_account_call(" in _SRC)
check("F3 a spent budget ends the run as budget",
      '"budget"' in _SRC and "budget_capped" in _SRC)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
