#!/usr/bin/env python3
"""v1097 — the register can be read as of a date (the post-adoption window).

Round 28. Every ranking so far read the WHOLE store, so a class fixed in code
kept sitting at the top of `self.failures` forever and the post-adoption
question ("is it still happening?") had no answer — the round-25 closure named
that measurement and the register could not produce it. Measured 2026-11-18:
all 26 "missing REQUIRED argument" cards predate the current session store's
newest day, i.e. they are history, not today.

  A  `_since_epoch` reads an ISO date/time or an epoch, and is total on junk
  B  the window bounds the SESSION corpus (file mtime, inclusive)
  C  the same window bounds the run-record corpus — one rule for both
  D  the answer states the epoch it used, and an absent window stays `None`
  E  the surface: `self.failures` accepts `since` and returns `failures.since`

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1097_failure_window.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1097-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs"), exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
OLD = time.mktime(time.strptime("2026-01-15 12:00:00", "%Y-%m-%d %H:%M:%S"))
NEW = time.mktime(time.strptime("2026-06-15 12:00:00", "%Y-%m-%d %H:%M:%S"))
SINCE = "2026-03-01"


def session(sid, cards, mt):
    p = os.path.join(SESS, sid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)
    os.utime(p, (mt, mt))


def record(name, steps, mt):
    p = os.path.join(RUNS, name + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"run_id": name, "steps": steps}, f)
    os.utime(p, (mt, mt))


# --------------------------------------------------------- A: the bound -----
check("A1 no bound is None", selfevolve._since_epoch(None) is None
      and selfevolve._since_epoch("") is None and selfevolve._since_epoch(0) is None)
check("A2 an epoch passes through", selfevolve._since_epoch(1234.5) == 1234.5
      and selfevolve._since_epoch("1234.5") == 1234.5)
want = time.mktime(time.strptime("2026-03-01", "%Y-%m-%d"))
check("A3 an ISO date is local midnight", selfevolve._since_epoch(SINCE) == want,
      selfevolve._since_epoch(SINCE))
check("A4 a date-time is read in the forms a person writes",
      selfevolve._since_epoch("2026-03-01T10:30") ==
      time.mktime(time.strptime("2026-03-01 10:30", "%Y-%m-%d %H:%M"))
      and selfevolve._since_epoch("2026-03-01 10:30") ==
      time.mktime(time.strptime("2026-03-01 10:30", "%Y-%m-%d %H:%M")))
check("A5 junk is all time, never a crash",
      selfevolve._since_epoch("yesterday") is None
      and selfevolve._since_epoch(True) is None)

# ------------------------------------------------- B/C: both corpora --------
session("s_old", [
    {"tool": "shell.exec", "ok": False, "error": "permission denied by policy: <path>"},
    {"tool": "shell.exec", "ok": False, "error": "permission denied by policy: <path>"},
], OLD)
session("s_new", [
    {"tool": "shell.exec", "ok": False, "error": "missing REQUIRED argument(s) 'command'"},
], NEW)
record("r_old", [{"tool": "fs.read", "ok": False, "error": "no such file: <path>"}], OLD)
record("r_new", [{"tool": "fs.write", "ok": False,
                  "error": "missing REQUIRED argument(s) 'path'"}], NEW)

all_time = selfevolve.session_failures(limit=50)
windowed = selfevolve.session_failures(limit=50, since=SINCE)
check("B1 all time sees both sessions", all_time["sessions"] == 2, all_time)
check("B2 the window sees only the newer one",
      windowed["sessions"] == 1
      and all("missing REQUIRED" in c["error"] for c in windowed["classes"]), windowed)
check("B3 the boundary is inclusive (a file exactly at `since` is in)",
      selfevolve.session_failures(limit=50, since=NEW)["sessions"] == 1, "")
check("B4 the answer states the epoch it used",
      windowed.get("since") == selfevolve._since_epoch(SINCE)
      and all_time.get("since") is None, (windowed.get("since"), all_time.get("since")))

both = selfevolve.failure_candidates(limit=50, include_sessions=True, since=SINCE)
check("C1 one rule bounds the run records too", both["runs"] == 1, both.get("runs"))
check("C2 the old class is gone from the merged ranking",
      sorted(c["tool"] for c in both["classes"]) == ["fs.write", "shell.exec"],
      both["classes"])
check("C3 the merged answer states the window", both.get("since") == windowed.get("since"))
check("C4 a junk bound is all time here too",
      selfevolve.failure_candidates(limit=50, include_sessions=True,
                                    since="not-a-date")["sessions"] == 2)

# ---------------------------------------------------------- D: surface ------
check("D1 the `self` schema gives `failures` its second field",
      registry._SUBTOOL_FIELDS["self"]["failures"] == ["limit", "since"],
      registry._SUBTOOL_FIELDS["self"]["failures"])
res = T.execute("self", {"action": "failures", "limit": 5, "since": SINCE})
pay = res.get("failures") or {}
check("D2 `self.failures` passes `since` and reports the window",
      pay.get("since") == selfevolve._since_epoch(SINCE)
      and pay.get("sessions") == 1, pay)
check("D3 and the ranking is the windowed one",
      all("missing REQUIRED" in (c.get("error") or "") for c in pay.get("classes") or []),
      pay.get("classes"))
check("D4 without `since` it is still the whole store",
      (T.execute("self", {"action": "failures", "limit": 5}).get("failures") or {})
      .get("since") is None)

print("\n---\nv1097: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
