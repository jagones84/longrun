#!/usr/bin/env python3
"""v1107 — a repair is judged on the whole trace store, not only on sessions.

Round 39. Round 38 taught the register to name its two corpora, and exposed the
same gap one level down: `repair_states` counted the class only in session files,
so a fix could read `resolved` from a session-only measurement while its class
was still failing in harness run records. The window now has two denominators
(`sessions_since`, `runs_since`) and `unobserved` needs BOTH to be empty.

  A  a class still failing in a run record after the fix is `fixed-open`
  B  a class absent from both corpora in a non-empty window is `resolved`
  C  no session and no run after the fix is `unobserved`
  D  the tool's stdout names the run-record window
  E  the panel names both corpora too
  F  the API carries the second denominator

Deterministic: temp data/session/harness dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1107_repair_window_runs.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1107-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402,F401 — the supported import order
from longrun.core import httpapi  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
FIX = time.mktime(time.strptime("2026-03-01 12:00:00", "%Y-%m-%d %H:%M:%S"))
AFTER = time.mktime(time.strptime("2026-06-01 12:00:00", "%Y-%m-%d %H:%M:%S"))

# One session and one run record written AFTER the fix. The session carries a
# class the drafts do not name; the run record carries one that draft A names.
with open(os.path.join(SESS, "s_after.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_after", "messages": [], "tool_cards": [
        {"tool": "web.search", "ok": False, "error": "timeout — the search timed out"}]}, f)
os.utime(os.path.join(SESS, "s_after.json"), (AFTER, AFTER))
with open(os.path.join(RUNS, "run_after.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "run_after", "steps": [
        {"tool": "shell.exec", "ok": False,
         "error": "shell.exec: missing REQUIRED argument 'cmd'"}]}, f)
os.utime(os.path.join(RUNS, "run_after.json"), (AFTER, AFTER))

OUT = os.path.join(str(improve.PROPOSAL_DIR), "repairs")


def draft(name, tool, family, fix=FIX):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    prop = {"kind": "repair", "status": "fixed" if fix else "proposed",
            "name": name, "issue": name, "tool": tool, "family": family}
    if fix:
        prop["fix"] = {"commit": "abc123", "date": fix, "note": ""}
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(prop, f)


draft("fail-shell-exec-missing-argument", "shell.exec", "missing-argument")
draft("fail-fs-read-not-found", "fs.read", "not-found")
LATE = time.mktime(time.strptime("2026-12-01 12:00:00", "%Y-%m-%d %H:%M:%S"))
draft("fail-web-search-timeout", "web.search", "timeout", fix=LATE)

states = {s["issue"]: s for s in selfevolve.repair_states(OUT)["states"]}

# ------------------------------------------------- A: run record still fails ---
a = states.get("fail-shell-exec-missing-argument") or {}
check("A1 the class still failing in a run record after the fix is `fixed-open`",
      a.get("status") == "fixed-open", a)
check("A2 and the occurrence is counted in the run corpus",
      a.get("count_since_runs") == 1 and a.get("count_since_sessions") == 0
      and a.get("count_since") == 1, a)
check("A3 the window carries both denominators",
      a.get("sessions_since") == 1 and a.get("runs_since") == 1, a)

# ------------------------------------------------- B: absent from both ---------
b = states.get("fail-fs-read-not-found") or {}
check("B1 a class absent from both corpora in a non-empty window is `resolved`",
      b.get("status") == "resolved" and b.get("count_since") == 0, b)
check("B2 its window still states the run record it was judged against",
      b.get("runs_since") == 1 and b.get("sessions_since") == 1, b)

# ------------------------------------------------- C: nothing after the fix ----
c = states.get("fail-web-search-timeout") or {}
check("C1 no session AND no run after the fix is `unobserved`",
      c.get("status") == "unobserved", c)
check("C2 with both denominators at zero — zero out of zero is not evidence",
      c.get("sessions_since") == 0 and c.get("runs_since") == 0, c)

# ------------------------------------------------- D: the tool's stdout --------
r = T.execute("improve", {"action": "repairs", "limit": 1, "min_severity": "error"})
out = r.get("stdout") or ""
check("D1 the still-open line names its run-record window",
      "[fixed-open] fail-shell-exec-missing-argument — 1 occurrence(s) in the "
      "1 session(s) + 1 run record(s) after the fix" in out, out[:400])

# ------------------------------------------------- E: the panel ---------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the empty state says no session AND no run",
      "no session or run after the fix" in UI, "")
check("E2 the row's window names both corpora",
      "runs_since" in UI and "run record(s)" in UI and "count_since_runs" in UI, "")
check("E3 the legend explains the run half",
      "sessions and run records after the fix" in UI, "")

# ------------------------------------------------- F: the API -----------------
api = httpapi.improvement_repairs()
check("F1 the endpoint carries the run denominator",
      api.get("runs") == 1 and api.get("total") == 3, api)

print("\n---\nv1107: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
