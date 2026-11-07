#!/usr/bin/env python3
"""v869 — the loop stops paying for bookkeeping it can already prove.

Measured 2026-11-07 (LHB run 2026-11-07_222543, and the ladder probe): a one-file
task (`out/hello.txt` containing `ok`) cost 12-15 model calls and 130k tokens, of
which 40% of all tool calls in the suite were `todo.update`. Three causes, one test
each:

  A  the model asked `self.tools` how to call `fs.write`  -> the core signatures
     are now a line in the prompt (not the registry dump JAG-513b removed);
  B  a one-action request was forced into a 2-8 step plan -> the threshold is now
     THREE OR MORE steps;
  C  the read-back + verify gate fired although the turn had ALREADY re-opened
     what it wrote (with `fs.read`, or with a read-only shell command after a
     shell write) -> `own_verified` suppresses them, and nothing else.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v869-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402
from longrun.core import api_v02               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. the prompt carries the five core signatures ------------------------
_tctx = api_v02.tool_context()
check("A1 tool_context names the core tools with their REQUIRED args",
      "Core tools" in _tctx and "`fs.write {path, content}`" in _tctx
      and "`shell.exec {command}`" in _tctx, _tctx[-300:])
check("A2 it is a signature line, not the registry dump JAG-513b removed",
      "self.tools {query" in _tctx and _tctx.count("·") <= 6)

# ---- B. a one-action request is no longer forced into a plan ---------------
check("B1 TASK_POLICY thresholds the plan at THREE OR MORE steps",
      "THREE OR MORE steps" in agent.TASK_POLICY, agent.TASK_POLICY[:200])
check("B2 it says a one/two-action request needs no list",
      "need NO list" in agent.TASK_POLICY)
check("B3 the old blanket rule is gone",
      "needs more than one action" not in agent.TASK_POLICY)

# ---- C. read-only shell detection (the gate's new input) -------------------
R = agent._shell_looks_read_only
check("C1 a pure read counts", R("cat out/report.json") is True)
check("C2 a read chained after another read counts",
      R("cat out/a.txt && wc -c out/a.txt && cmp <(printf ok) out/a.txt") is True)
check("C3 a redirect disqualifies the whole command",
      R("printf 'ok' > out/a.txt && cat out/a.txt") is False)
check("C4 a mutation disqualifies it", R("cat out/a.txt && rm out/a.txt") is False)
check("C5 a tee disqualifies it", R("cat out/a.txt | tee out/b.txt") is False)
check("C6 an empty/unknown command is not a verification", R("") is False and R("make") is False)
check("C7 `ls` alone is not proof of CONTENT", R("ls -la out") is False)

# ---- D. the flag is set only by a real re-open of an owned artifact --------
ws = tempfile.mkdtemp(prefix="v869-ws-")
sess = {"id": "v869-sess", "messages": [], "workspace": ws}
own = os.path.join(ws, "out", "report.json")

_st = {"wrote": True, "paths": {own}}
agent._note_chat_verification("fs.read", {"path": "out/report.json"}, sess, _st)
check("D1 fs.read of a path this turn wrote sets own_verified",
      _st.get("own_verified") is True, _st)

_st2 = {"wrote": True, "paths": {own}}
agent._note_chat_verification("fs.read", {"path": "data/sales.csv"}, sess, _st2)
check("D2 reading an INPUT is not verifying an output", _st2.get("own_verified") is not True)

_st3 = {"wrote": True, "paths": set()}
agent._note_chat_verification("shell.exec", {"command": "cat out/report.json"}, sess, _st3)
check("D3 a read-only shell after a shell write sets it", _st3.get("own_verified") is True)

_st4 = {"wrote": False, "paths": set()}
agent._note_chat_verification("shell.exec", {"command": "cat out/report.json"}, sess, _st4)
check("D4 nothing written this turn -> no verification flag", _st4.get("own_verified") is not True)

_st5 = {"wrote": True, "paths": {own}}
agent._note_chat_verification("todo.update", {"steps": []}, sess, _st5)
check("D5 bookkeeping never sets it", _st5.get("own_verified") is not True)

# a WRITE done through the shell leaves `paths` empty: only time can attribute it
import time as _t  # noqa: E402
os.makedirs(os.path.join(ws, "out"), exist_ok=True)
with open(own, "w", encoding="utf-8") as fh:
    fh.write("{}")
_st6 = {"wrote": True, "opaque": True, "paths": set(), "since": _t.time() - 5}
agent._note_chat_verification("fs.read", {"path": "out/report.json"}, sess, _st6)
check("D6 fs.read of a file this shell turn modified counts", _st6.get("own_verified") is True)

_st7 = {"wrote": True, "opaque": True, "paths": set(), "since": _t.time() + 3600}
agent._note_chat_verification("fs.read", {"path": "out/report.json"}, sess, _st7)
check("D7 a file older than the turn proves nothing", _st7.get("own_verified") is not True)

# ---- E. the read-back is skipped ONLY when the premise is already met ------
with open(os.path.join(ws, "report.csv"), "w", encoding="utf-8") as fh:
    fh.write("id,amount\nA,10\nB,20\n")

_e1 = {"left": 1}
_txt1 = agent._deliverable_review_text(sess, "write a report.csv", since=0.0, state=_e1)
check("E1 a turn that never opened its output still gets the read-back",
      bool(_txt1) and "READ-BACK" in str(_txt1), str(_txt1)[:80])

_e2 = {"left": 1, "own_verified": True}
_txt2 = agent._deliverable_review_text(sess, "write a report.csv", since=0.0, state=_e2)
check("E2 a verified turn spends no round on it", _txt2 is None, _txt2)
check("E3 and its budget is closed, so nothing re-arms it", _e2.get("left") == 0, _e2)
check("E4 so no verify-gate debt is opened",
      agent._review_action_owed(_e2) is False, _e2)

# ---- F. the gate keeps its teeth on the path it exists for ----------------
_e3 = {"left": 1, "review_sent": True, "after_review": False}
check("F1 a close after the read-back still owes a real tool",
      agent._review_action_owed(_e3) is True)

# ---- G. BOTH tool paths feed the flag (single call AND batch) -------------
_SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("G1 the verification is wired on the single-call path and the batch path",
      _SRC.count("_note_chat_verification(tool, args, sess") >= 2,
      _SRC.count("_note_chat_verification(tool, args, sess"))

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
