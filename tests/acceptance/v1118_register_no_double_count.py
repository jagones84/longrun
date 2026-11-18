#!/usr/bin/env python3
"""v1118 — the register must not count the same failed call twice.

Round 52. The register sums two corpora: the live session cards (what the agent
saw) and the harness run records (what the runner wrote). For a session that ran
through the harness the record is BUILT FROM the same call, so every failure in
it exists twice. Measured 2026-11-18 on the live store: run `caef726a6faa` has
25 failed steps and 25 failed cards, all 25 matching on (session, ts, tool);
run `510162f477f0` matches 4/4. The largest register row, `shell · tool-error`,
read **32 failures / 16 unresolved** — 16 calls counted twice.

The two corpora stay different UNITS, but a call both saw is ONE failure:

  A  a call in both corpora counts once, attributed to the session
  B  a run-only step (no session file) still counts
  C  a session-only card still counts
  D  two run steps + one matching card = 2 failures, overlap 1
  E  the issue sums the deduped classes and its split closes
  F  a different timestamp is a different call (no dedupe)
  G  a card/step without a timestamp is never deduped (fail-open)

Deterministic: temp dirs only; no server, no model.
Run: python3 tests/acceptance/v1118_register_no_double_count.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1118-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
ERR = "shell.exec: no such option: --fail"


def card(err, ts=None, tool="shell.exec"):
    c = {"tool": tool, "ok": False, "error": err}
    if ts is not None:
        c["ts"] = ts
    return c


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def record(name, steps, session_id=None):
    rec = {"id": name, "steps": steps}
    if session_id is not None:
        rec["session_id"] = session_id
    with open(os.path.join(RUNS, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)


# One call seen by BOTH corpora (s1), one run-only step (run2), one session-only
# card (s3), and a two-step class of which only one step has a live card (s4).
session("s1", [card(ERR, ts=1000.5)])
record("s1", [{"tool": "shell.exec", "ok": False, "error": ERR, "ts": 1000.5}],
       session_id="s1")
record("run2", [{"tool": "shell.exec", "ok": False, "error": "boom: run only",
                 "ts": 2000.25}])
session("s3", [card("boom: session only", ts=3000.75)])
session("s4", [card("boom: twice", ts=4000.125)])
record("s4", [{"tool": "shell.exec", "ok": False, "error": "boom: twice", "ts": 4000.125},
              {"tool": "shell.exec", "ok": False, "error": "boom: twice", "ts": 4100.5}],
       session_id="s4")
# A ts-less pair: same text, no clock — must NOT be merged.
session("s5", [card("boom: timeless")])
record("s5", [{"tool": "shell.exec", "ok": False, "error": "boom: timeless"}],
       session_id="s5")
# Same class, different clock: two calls, not one.
session("s6", [card("boom: spaced", ts=6000.0)])
record("s6", [{"tool": "shell.exec", "ok": False, "error": "boom: spaced", "ts": 6100.0}],
       session_id="s6")

rep = selfevolve.failure_candidates(limit=50, include_sessions=True)
by_head = {c["error"]: c for c in rep["classes"]}


def cls(txt):
    return by_head.get(selfevolve.error_class(txt), {})


# A — the call both corpora saw is ONE failure, owned by the session.
a = cls(ERR)
check("A1 a call in both corpora counts once",
      a.get("count") == 1, a)
check("A2 it is attributed to the session, with the overlap named",
      a.get("from_sessions") == 1 and a.get("from_runs") == 0
      and a.get("overlap") == 1, a)
check("A3 its unresolved count uses the deduped total",
      a.get("unresolved") == 1, a)

# B / C — one corpus alone still counts.
b = cls("boom: run only")
check("B1 a run-only step is counted from the runs",
      b.get("count") == 1 and b.get("from_runs") == 1
      and b.get("from_sessions") == 0, b)
c = cls("boom: session only")
check("C1 a session-only card is counted from the sessions",
      c.get("count") == 1 and c.get("from_sessions") == 1
      and c.get("from_runs") == 0, c)

# D — two steps, one matching card: two calls, one overlap.
d = cls("boom: twice")
check("D1 two steps + one matching card = 2 failures",
      d.get("count") == 2, d)
check("D2 one session event + one run-only step, overlap 1",
      d.get("from_sessions") == 1 and d.get("from_runs") == 1
      and d.get("overlap") == 1, d)

# E — the issue's split closes on the deduped total.
bad = [i for i in rep["issues"]
       if int(i.get("count") or 0) != (int(i.get("from_sessions") or 0)
                                       + int(i.get("from_runs") or 0))]
check("E1 every issue: count == from_sessions + from_runs", not bad, bad[:1])
check("E2 no emitted class leaks the internal event keys",
      all("event_keys" not in c for c in rep["classes"]), "")

# F — a different clock is a different call.
f = cls("boom: spaced")
check("F1 the same text at a different ts is not merged",
      f.get("count") == 2 and f.get("overlap") == 0, f)

# G — no clock, no merge (a guess is worse than a count).
g = cls("boom: timeless")
check("G1 a ts-less pair is never deduped",
      g.get("count") == 2 and g.get("overlap") == 0, g)

# H — the emitted corpus obeys the same arithmetic.
live = selfevolve.failure_candidates(limit=400, include_sessions=True, max_sessions=60)
bad = [i for i in live["issues"]
       if int(i.get("count") or 0) != (int(i.get("from_sessions") or 0)
                                       + int(i.get("from_runs") or 0))]
check("H1 every emitted issue's split closes", not bad, bad[:1])
no_split = [c for c in live["classes"] if "overlap" not in c]
check("H2 every emitted class names its overlap (0 when none)", not no_split,
      no_split[:1])

print("\n---\nv1118: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
