#!/usr/bin/env python3
"""v783 — the read-back's "incomplete delivery" extra cycle is ONE-SHOT.

Found 2026-11-04 on the live event log (`~/.longrun/data/events.db`), session
`48c6e90156c5` (agent A52, a dispatched teammate): ONE `chat.run` (id 2347006,
00:15:50 -> `chat.done` 00:27:46) carried ~15 consecutive `harness.inject`
"review" turns, every one a READ-BACK of the SAME file, and the turn only closed
when the "Answer the user now in plain text" final nudge arrived. The dispatched
teammate spent ~12 minutes looping, so its reply never reached the orchestrator
(A54), whose chat showed no dispatch run after the operator's "??".

Root cause: `_deliverable_review_text` re-armed its budget with
`state["left"] = max(int(state["left"]), 1)` on EVERY cycle while
`artifacts.gaps()` stayed non-empty — the cap the docstring promised ("the total
at two read-backs") was not real: the flag that grants the extra cycle was never
consumed.

  A  a persistent gap no longer re-arms the budget; the turn closes
  B  a clean delivery still earns exactly the base read-back
  C  the one-shot flag is the wiring that makes the cap real

Deterministic: temp dirs only. No live model, no network, no server.
Run: python3 tests/acceptance/v783_readback_gap_once.py
"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="sf-v783-")
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
from longrun.plan import artifacts as A        # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


def _session(name, workspace):
    s = stores.get_or_create_session(name, "v783", workspace=workspace)
    stores.save_session(s)
    return stores.load_session(name)


def _drive(sess, workspace, own, request, cap=12):
    """Run the REAL gate exactly as the turn loop does, and count the cycles.

    Mirrors the loop: while `_deliverable_review_text` keeps returning text the
    turn `continue`s; a None ends it. Returns how many read-backs were emitted.
    """
    state = {"left": 1, "wrote": True, "opaque": False, "paths": set(own)}
    n = 0
    while n < cap:
        if not AG._deliverable_review_text(sess, request, SINCE, state):
            break
        n += 1
    return n, state


# --- A: a persistent gap cannot loop the read-back ---------------------------
WS = os.path.join(TMP, "root")
os.makedirs(os.path.join(WS, "output"), exist_ok=True)
# an EMPTY artifact is a mechanical, permanent gap ("empty or unreadable")
BLANK = os.path.join(WS, "output", "blank.txt")
with open(BLANK, "w", encoding="utf-8") as f:
    f.write("")
SINCE = time.time() - 1.0
OWN = {os.path.abspath(BLANK)}

_g = A.gaps(WS, since=SINCE, own_paths=OWN, opaque=False)
check("A0 the delivery gap is mechanical and persistent", any("blank.txt" in g for g in _g), _g)

SESS = _session("v783-gap", WS)
_cycles, _st = _drive(SESS, WS, OWN, "produce the report file")
check("A1 a persistent gap caps the read-back at TWO cycles (never loops)",
      _cycles == 2, "cycles=%d state=%r" % (_cycles, _st))
check("A2 the budget is spent and the one-shot flag is consumed",
      int(_st.get("left") or 0) <= 0 and _st.get("gap_cycle_used") is True, _st)

# --- B: a clean delivery earns exactly the base read-back --------------------
WS2 = os.path.join(TMP, "clean")
os.makedirs(os.path.join(WS2, "output"), exist_ok=True)
OK = os.path.join(WS2, "output", "ok.csv")
with open(OK, "w", encoding="utf-8") as f:
    f.write("a,b\n1,2\n")
OWN2 = {os.path.abspath(OK)}
check("B0 a clean delivery has NO gap", A.gaps(WS2, since=SINCE, own_paths=OWN2,
                                               opaque=False) == [],
      A.gaps(WS2, since=SINCE, own_paths=OWN2, opaque=False))
SESS2 = _session("v783-clean", WS2)
_cycles2, _st2 = _drive(SESS2, WS2, OWN2, "write ok.csv")
check("B1 a clean delivery earns exactly ONE read-back", _cycles2 == 1,
      "cycles=%d state=%r" % (_cycles2, _st2))

# --- C: the wiring that makes the cap real -----------------------------------
check("C1 the extra cycle is guarded by a one-shot flag",
      'not state.get("gap_cycle_used")' in SRC
      and 'state["gap_cycle_used"] = True' in SRC,
      "one-shot guard")
check("C2 the flag is read BEFORE it is set (it can only gate, never re-arm)",
      SRC.index('not state.get("gap_cycle_used")')
      < SRC.index('state["gap_cycle_used"] = True'))

print("---")
ok = sum(results)
print("\nv783: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
