#!/usr/bin/env python3
"""v769 — `self.trace` tells the truth about loops and about its own cost.

Found while MONITORING a live session (operator request 2026-11-02: watch the
running sessions and fix what the harness gets wrong). Session `777378644e9c`
reported "7 repeated answers" — but only ONE was a real repeat: the other six
were DISTINCT tool calls (deepseek's native DSML markup) whose first 160
characters are identical, so the detector cried wolf on the very loop it exists
to catch. The same trace summed 678 kB under "what the harness spent … about its
own bookkeeping" while 88% of it was `observation` — the model's OWN tool
results, not harness talk.

Two contracts, both deterministic (no live model, no network):
  A. a "repeated answer" is a REPLY twice — machine tool-call markup never
     counts, and the comparison is the WHOLE (whitespace-normalised) body;
  B. the cost the harness spends on its OWN words is reported apart from the
     tool results it merely echoes back.
Run: python3 tests/acceptance/v769_harness_trace_truthfulness.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v769-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB",
           "COSTS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT", "GOALS_DIR"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
sys.path.insert(0, os.path.join(REPO, "src"))

# `core.server` first: `agent.agent` imports it at module top, so letting the
# agent module load first deadlocks the cycle (v768 imports in this order too).
from longrun.core import server as _srv            # noqa: E402,F401
from longrun.agent import agent as AG              # noqa: E402
from longrun.memory import stores                  # noqa: E402
from longrun.tools import diag                     # noqa: E402

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def run_trace(messages, injects=None):
    """A fresh isolated session and its harness trace."""
    s = stores.get_or_create_session(None, "trace")
    sid = s["id"]
    sess = stores.load_session(sid) or {}
    sess["messages"] = messages
    if injects is not None:
        sess["injects"] = injects
    stores.save_session(sess)
    return diag.harness_trace(sid)


# ============================================================================
# A — the repeat detector: a REPLY twice, machine markup never
# ============================================================================
# Two DISTINCT tool calls sharing the first 160 characters of DSML markup —
# exactly the false positive that fired six times on the live session.
_MARK = '<\uff5c\uff5cDSML\uff5c\uff5c'
_shared = (_MARK + ' calls>\n' + _MARK + ' invoke name="shell.exec">\n'
           + _MARK + ' parameter name="command">cd /home/jagones/Repositories/jevarium '
           + "&& " + "x" * 220)
call_a = _shared + " echo AAA</" + _MARK + " parameter>"
call_b = _shared + " echo BBB</" + _MARK + " parameter>"
check("A0 the fixture really is the model's machine markup",
      AG._looks_like_json_action(call_a) and AG._looks_like_json_action(call_b))
check("A0b the two fixtures share their first 160 characters",
      " ".join(call_a.split())[:160] == " ".join(call_b.split())[:160])

t = run_trace([{"role": "user", "content": "go"},
               {"role": "assistant", "content": call_a},
               {"role": "assistant", "content": call_b}])
check("A1 two distinct tool calls are NOT 'repeated answers'",
      t["repeated_answers"] == [], t["repeated_answers"])

# Two replies that share an opening but diverge later are different answers.
r1 = {"role": "assistant", "content": "A" * 200 + " END-ONE"}
r2 = {"role": "assistant", "content": "A" * 200 + " END-TWO"}
t = run_trace([{"role": "user", "content": "go"}, r1, r2])
check("A2 replies sharing a 160-char prefix but diverging are not repeats",
      t["repeated_answers"] == [])

# A genuinely duplicated reply IS the loop signature and must still be caught.
same = {"role": "assistant", "content": "Done — the migration is applied."}
t = run_trace([{"role": "user", "content": "go"}, dict(same), dict(same)])
check("A3 an identical reply twice IS reported",
      len(t["repeated_answers"]) == 1 and t["repeated_answers"][0]["i"] == 2,
      t["repeated_answers"])

# Whitespace is not a difference: the SAME reply, re-wrapped, is still a repeat.
t = run_trace([{"role": "user", "content": "go"},
               {"role": "assistant", "content": "Done.\n\nAll good."},
               {"role": "assistant", "content": "Done.  All good."}])
check("A4 whitespace-only differences still count as the same reply",
      len(t["repeated_answers"]) == 1)

# ============================================================================
# B — the harness's own cost is reported apart from the echoed tool results
# ============================================================================
injects = [
    {"kind": "observation", "text": "Z" * 5000, "after": 2},
    {"kind": "observation", "text": "Z" * 4000, "after": 4},
    {"kind": "nudge", "text": "N" * 300, "after": 6},
    {"kind": "continue", "text": "C" * 200, "after": 8},
]
t = run_trace([{"role": "user", "content": "go"},
               {"role": "assistant", "content": "done"}], injects)
check("B1 inject_chars still reports the total",
      t["inject_chars"] == 9500, t["inject_chars"])
check("B2 harness_chars counts ONLY the harness's own words (no observation)",
      t["harness_chars"] == 500, t["harness_chars"])
check("B3 the split is reported per kind",
      t["inject_chars_by_kind"].get("observation") == 9000
      and t["inject_chars_by_kind"].get("nudge") == 300,
      t["inject_chars_by_kind"])
check("B4 the per-kind split sums to the total",
      sum(t["inject_chars_by_kind"].values()) == t["inject_chars"])
check("B5 the reading no longer calls every injected char harness bookkeeping",
      "harness_chars" in t["reading"] and "observation" in t["reading"])

# ============================================================================
# C — the predicate reuses the ONE owner of "this is machine text"
# ============================================================================
src = open(os.path.join(REPO, "src", "longrun", "tools", "diag.py"), encoding="utf-8").read()
check("C1 the detector asks agent._looks_like_json_action",
      "_looks_like_json_action" in src)
check("C2 the comparison is the whole normalised body, not a 160-char prefix",
      '" ".join(body.split())' in src)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
