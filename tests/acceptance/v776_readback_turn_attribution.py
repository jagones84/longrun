#!/usr/bin/env python3
"""v776 — "what YOU WROTE this turn" must be the TURN's, not the folder's.

Operator (2026-11-02): *"perche dopo un semplice prompt mio l harness ha buttato
dentro il review a caso? poi cons scritto cosa … cazzo centra orbit.. ce qualcosa
generico che non va"*.

Measured on the live event log (`~/.longrun/data/events.db`), session
`b7329cccf94c` — an orchestrator whose workspace is THIS repo root, shared with
every other writer on the machine:

  * 22:23:38 the operator asked a plain question. The turn ran **ZERO** tool calls
    (`tool.call` count 0 in the window; only `chat.delta` + one `harness.inject`).
    At 22:23:57 the harness injected "READ-BACK of what you WROTE this turn: -
    src/longrun/orbit/web/orbit.html (html) — 226698 bytes" — a file ANOTHER
    agent had re-saved 9 s earlier. The turn wrote nothing; it was told what a
    stranger had written.
  * 23:40:50, a turn whose OWN write was `trash/report-scrapling.md` (`fs.write`)
    was additionally told it had written `README.md` — written by another process
    at 23:38:34. The read-back then armed the close GATE on a foreign file.

Root cause: the read-back decides "what you WROTE" from mtime alone (`since` =
turn start), so in a shared workspace ANY fresh document is attributed to the
turn. The harness already knows what its own turn did, and it must use that.

  A  `inventory(own_paths=..., opaque=...)` narrows the answer to the turn;
  B  the defaults are exactly the old behaviour (a caller that does not know);
  C  `review()` reports only the turn's own files, and nothing when it wrote none;
  D  the agent records the turn's facts from EVERY ingress path (single + batch);
  E  `_deliverable_review_text` + `_stop_floor_text` use them — so a foreign file
     can neither be claimed as ours NOR silently suppress the delivery floor;
  F  the live shape reproduced end-to-end: a plain question with no tool call gets
     NO read-back, while the same folder with the path attributed to it does.

Deterministic: temp dirs only. No live model, no network, no server.
Run: python3 tests/acceptance/v776_readback_turn_attribution.py
"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="sf-v776-")
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
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail else ""))


WS = os.path.join(TMP, "root")
os.makedirs(WS, exist_ok=True)


def _fresh(name, body="a,b\n1,2\n"):
    p = os.path.join(WS, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


OWN = _fresh("mine.csv")
FOREIGN = _fresh("README.md", "someone else's readme\n")
SINCE = time.time() - 1.0


def _paths(**kw):
    return sorted(e["path"] for e in A.inventory(WS, since=SINCE, **kw))


# --- A/B: the attribution at the artifacts layer ------------------------------
check("A1 own_paths + no shell keeps ONLY the turn's own file",
      _paths(own_paths=[OWN], opaque=False) == ["mine.csv"], _paths(own_paths=[OWN], opaque=False))
check("A2 a foreign fresh file is NOT reported when the turn named another path",
      "README.md" not in _paths(own_paths=[OWN], opaque=False))
check("A3 a turn that named NO path and ran no shell has nothing to report",
      _paths(own_paths=set(), opaque=False) == [], _paths(own_paths=set(), opaque=False))
check("A4 a turn that ran a SHELL is never filtered (it could have written anything)",
      _paths(own_paths=[OWN], opaque=True) == ["README.md", "mine.csv"],
      _paths(own_paths=[OWN], opaque=True))
check("B1 own_paths=None is the old behaviour (a caller that does not know)",
      _paths() == ["README.md", "mine.csv"] and _paths(own_paths=None, opaque=True) == ["README.md", "mine.csv"])
check("B2 a RELATIVE own_path is resolved against the workspace, never silently dropped",
      _paths(own_paths=["mine.csv"], opaque=False) == ["mine.csv"])

# --- C: the read-back itself --------------------------------------------------
txt_own = A.review(WS, "write mine.csv", since=SINCE, own_paths=[OWN], opaque=False) or ""
check("C1 the read-back names the turn's own file",
      "mine.csv" in txt_own and "README.md" not in txt_own, txt_own[:200])
check("C2 nothing attributable → no read-back at all",
      A.review(WS, "why did you stop?", since=SINCE, own_paths=set(), opaque=False) is None)
check("C3 the unfiltered default still reads back everything (back-compat)",
      "README.md" in (A.review(WS, "x", since=SINCE) or ""))

# --- D: the agent records the turn's facts -----------------------------------
_s = stores.get_or_create_session("v776-attrib", "attribution")
_s["workspace"] = WS
stores.save_session(_s)
SESS = stores.load_session("v776-attrib")

st = {"left": 1, "wrote": False, "opaque": False, "paths": set()}
AG._note_chat_mutation(SESS, "fs.read", {"path": "README.md"}, state=st)
check("D1 a NON-mutating tool leaves the turn's facts untouched",
      st == {"left": 1, "wrote": False, "opaque": False, "paths": set()}, st)
AG._note_chat_mutation(SESS, "fs.write", {"path": "out/a.md"}, state=st)
check("D2 fs.write marks the turn as a writer and records the ABSOLUTE path",
      st["wrote"] is True and st["opaque"] is False
      and st["paths"] == {os.path.abspath(os.path.join(WS, "out/a.md"))}, st)
AG._note_chat_mutation(SESS, "shell.exec", {"command": "python3 x.py"}, state=st)
check("D3 a shell makes the turn OPAQUE (its target is not interpretable)", st["opaque"] is True, st)

# --- E: the two consumers ----------------------------------------------------
state_none = {"left": 1, "wrote": False, "opaque": False, "paths": set()}
check("E1 a plain question (no tool call) gets NO read-back — the operator's case",
      AG._deliverable_review_text(SESS, "perche ti sei fermato? no farlo piu",
                                  SINCE, state_none) is None)
state_own = {"left": 1, "wrote": True, "opaque": False, "paths": {FOREIGN}}
txt_e2 = AG._deliverable_review_text(SESS, "write README.md", SINCE, state_own) or ""
check("E2 the same folder WITH the path attributed to the turn DOES read back",
      "README.md" in txt_e2 and "mine.csv" not in txt_e2, txt_e2[:200])
check("E3 a foreign fresh file cannot silently suppress the delivery floor",
      AG._stop_floor_text(SESS, SINCE, False, "budget", 2, state=state_none) is not None)
check("E4 the floor stays silent when the turn DID write something",
      AG._stop_floor_text(SESS, SINCE, False, "budget", 2,
                          state={"paths": {FOREIGN}, "opaque": False}) is None)

# --- F: the wiring (every ingress path passes the facts) ----------------------
check("F1 the turn state carries the three attribution facts",
      '"left": 1, "wrote": False, "opaque": False, "paths": set()' in SRC)
check("F2 BOTH mutation call sites feed the state (single call + batch)",
      SRC.count("_note_chat_mutation(sess, tool, args, state=") == 2,
      SRC.count("_note_chat_mutation(sess, tool, args, state="))
check("F3 BOTH stop paths hand the state to the floor",
      SRC.count("state=_deliv_state)") >= 3, SRC.count("state=_deliv_state)"))
check("F4 the read-back passes own_paths/opaque to review AND gaps",
      "own_paths=_own, opaque=_opaque)" in SRC
      and SRC.count("own_paths=_own, opaque=_opaque)") == 2,
      SRC.count("own_paths=_own, opaque=_opaque)"))
check("F5 the batch ingest thread is wired from the loop",
      "state=None):" in SRC.split("def _apply_chat_batch")[1][:200])

print("---")
ok = sum(results)
print("\nv776: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
