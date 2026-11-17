#!/usr/bin/env python3
"""v1104 — the repair outcomes reach the operator's panel.

Round 36. Rounds 34–35 gave a repair draft a lifecycle (the commit that answered
it, the sessions written after it, `resolved` / `fixed-open` / `unobserved`), but
none of it reached Settings ▸ Improvements: the panel listed skill drafts only, so
an applied fix looked exactly like an open one. `/api/improvement` now carries
`repairs` and the panel renders each draft with its state and its window.

  A  no drafts: empty, and the counters are 0 (never a missing key)
  B  a draft is `open` and `proposed`
  C  a recorded fix moves it out of `open`; the state and the window travel
  D  `unobserved` is NOT open work (it waits for data, not for a hand)
  E  the panel: the block exists and renders the states it is given
  F  the graphic rules: every state is a glyph with its name (title + aria-label)

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1104_improvement_repairs.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1104-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402,F401 — the supported import order
from longrun.core import httpapi  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
TIMEOUT = "timeout — the terminal was reset"
OLD = time.mktime(time.strptime("2026-01-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
NEW = time.mktime(time.strptime("2026-06-10 12:00:00", "%Y-%m-%d %H:%M:%S"))


def session(sid, cards, mt):
    p = os.path.join(SESS, sid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)
    os.utime(p, (mt, mt))


session("s_old", [{"tool": "shell.exec", "ok": False, "error": TIMEOUT}] * 2, OLD)
session("s_new", [{"tool": "shell.exec", "ok": False, "error": TIMEOUT}], NEW)

# ------------------------------------------------------ A: nothing yet --------
empty = httpapi.improvement_repairs()
check("A1 an empty store answers with the key, not a missing one",
      empty.get("states") == [] and empty.get("total") == 0
      and empty.get("open") == 0, empty)
check("A2 with nothing to evaluate the store is not scanned (sessions 0, not a lie)",
      empty.get("sessions") == 0, empty)

# ------------------------------------------------- a draft becomes open work ---
OUT = os.path.join(str(improve.PROPOSAL_DIR), "repairs")
rep = selfevolve.issue_drafts(OUT, limit=5, min_severity="info")
made = httpapi.improvement_repairs()
check("B1 a fresh draft is one open row",
      made.get("total") == 1 and made.get("open") == 1, made)
check("B2 its state is `proposed` and it claims no window",
      made["states"][0].get("status") == "proposed"
      and made["states"][0].get("sessions_since") is None, made["states"][0])

# ------------------------------------------------ C: a fix closes it ---------
selfevolve.repair_mark(OUT, "fail-shell-exec-timeout", "abc123", when="2026-03-01")
fixed = httpapi.improvement_repairs()
row = (fixed.get("states") or [{}])[0]
check("C1 a recorded fix leaves `open`",
      fixed.get("open") == 0 and fixed.get("total") == 1, fixed)
check("C2 and the state carries its window (1 failure in 1 session after the fix)",
      row.get("status") == "fixed-open" and row.get("count_since") == 1
      and row.get("sessions_since") == 1, row)
check("C3 the commit travels with the row",
      (row.get("fix") or {}).get("commit") == "abc123", row.get("fix"))

# ------------------------------------------------- D: unobserved is not open --
selfevolve.repair_mark(OUT, "fail-shell-exec-timeout", "abc123", when="2026-09-01")
un = httpapi.improvement_repairs()
row = (un.get("states") or [{}])[0]
check("D1 a fix with no session after it is `unobserved`",
      row.get("status") == "unobserved" and row.get("sessions_since") == 0, row)
check("D2 and it is not counted as open work",
      un.get("open") == 0, un)

# ------------------------------------------------------------ E: the panel ---
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the panel has its own block and count",
      'id="impRepairsBox"' in UI and 'id="impRepairs"' in UI
      and 'id="impRepairCount"' in UI, "")
check("E2 the render reads the API's own rows",
      'd.repairs' in UI and 'repD.states' in UI, "")
check("E3 every state has a glyph", all(
    ('%s: "' % k) in UI or ('"%s"' % k) in UI
    for k in ("resolved", "fixed-open", "unobserved", "proposed")), "")
check("E4 the words name the outcome, not a verdict alone",
      "no session or run after the fix — nothing claimed" in UI
      and '0 in " + win + " after the fix' in UI
      and "run step(s) in " in UI, "")
check("E5 the state glyph is NAMED (title + aria-label) — no bare emoji",
      'aria-label="' in UI and 'title="' in UI and "word[st]" in UI, "")

print("\n---\nv1104: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
