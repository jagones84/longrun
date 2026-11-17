#!/usr/bin/env python3
"""v1103 — a repair draft has a lifecycle: fix recorded, outcome measured.

Round 34. Rounds 22/29 turn the register into `kind: "repair"` drafts, and each
draft's Status section told the reader to "re-read `self.failures` to prove the
issue is gone" — a proof nobody stored. Measured 2026-11-18: a repair was written
`status: "proposed"` and no code path ever changed it (skill drafts have
verified/rejected/archived; repairs had none).

  A  a draft without a fix is `proposed` and makes no claim (`count_since` None)
  B  a fix date between two sessions counts ONLY what was written after it, and
     the window carries its denominator (`sessions_since`)
  C  no occurrence in a NON-empty window is `resolved`; no session at all is
     `unobserved` — zero out of zero is not evidence
  D  the record is refused without a commit, for an unknown draft, and for a
     name that is not a plain directory (no traversal, nothing created)
  E  the surface: `improve repair-fixed` (including `when`) and the outcome on
     `improve.repairs`
  F  the schema: the fields and the two required arguments

Deterministic: temp session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1103_repair_lifecycle.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1103-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

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
OLD = time.mktime(time.strptime("2026-01-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
NEW = time.mktime(time.strptime("2026-06-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
TIMEOUT = "timeout — the terminal was reset"


def session(sid, cards, mt):
    p = os.path.join(SESS, sid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)
    os.utime(p, (mt, mt))


session("s_old", [{"tool": "shell.exec", "ok": False, "error": TIMEOUT}] * 2, OLD)
session("s_new", [{"tool": "shell.exec", "ok": False, "error": TIMEOUT}], NEW)
# A LATER session with a different failure: a fix dated before it has a window
# with sessions in it and none of the class — that is a real `resolved`.
LATE = time.mktime(time.strptime("2026-08-01 12:00:00", "%Y-%m-%d %H:%M:%S"))
session("s_late", [{"tool": "fs.read", "ok": False,
                    "error": "no such file: <path>"}], LATE)

OUT = os.path.join(_tmp, "repairs")
rep = selfevolve.issue_drafts(OUT, limit=5, min_severity="info")
NAME = "fail-shell-exec-timeout"
prop = json.load(open(os.path.join(OUT, NAME, "proposal.json"), encoding="utf-8"))
check("A1 the draft targets the measured (tool, family)",
      (prop.get("tool"), prop.get("family")) == ("shell.exec", "timeout"), prop)
check("A2 and starts life as `proposed`", prop.get("status") == "proposed",
      prop.get("status"))

st = {s["issue"]: s for s in selfevolve.repair_states(OUT).get("states") or []}
check("A3 a draft without a fix makes no claim",
      (st.get(NAME) or {}).get("status") == "proposed"
      and (st.get(NAME) or {}).get("count_since") is None
      and (st.get(NAME) or {}).get("sessions_since") is None, st.get(NAME))

# --------------------------------------------------- B: the window is the fix --
res = selfevolve.repair_mark(OUT, NAME, "abc123", note="the timeout route",
                             when="2026-03-01")
check("B1 the fix is recorded with its commit and date",
      res.get("ok") is True and res["fix"]["commit"] == "abc123"
      and res["fix"]["date"] == selfevolve._since_epoch("2026-03-01"), res)
prop2 = json.load(open(os.path.join(OUT, NAME, "proposal.json"), encoding="utf-8"))
check("B2 proposal.json now says `fixed`", prop2.get("status") == "fixed",
      prop2.get("status"))
st = {s["issue"]: s for s in selfevolve.repair_states(OUT).get("states") or []}
mine = st.get(NAME) or {}
check("B3 only what was written AFTER the fix counts",
      mine.get("status") == "fixed-open" and mine.get("count_since") == 1, mine)
check("B4 and the window carries its denominator (2 sessions after 2026-03-01)",
      mine.get("sessions_since") == 2, mine)

# ------------------------------------------------------- C: it can resolve ----
selfevolve.repair_mark(OUT, NAME, "abc123", when="2026-07-01")
st = {s["issue"]: s for s in selfevolve.repair_states(OUT).get("states") or []}
mine = st.get(NAME) or {}
check("C1 no occurrence in a NON-empty window is `resolved`",
      mine.get("status") == "resolved" and mine.get("count_since") == 0
      and mine.get("sessions_since") == 1, mine)
selfevolve.repair_mark(OUT, NAME, "abc123", when="2026-09-01")
st = {s["issue"]: s for s in selfevolve.repair_states(OUT).get("states") or []}
mine = st.get(NAME) or {}
check("C2 zero failures out of ZERO sessions is `unobserved`, not `resolved`",
      mine.get("status") == "unobserved" and mine.get("sessions_since") == 0, mine)

# ------------------------------------------------------ D: the refusals ------
bad = selfevolve.repair_mark(OUT, NAME, "")
check("D1 a fix without a commit is refused",
      bad.get("ok") is False and "commit" in str(bad.get("error")), bad)
bad = selfevolve.repair_mark(OUT, "fail-not-a-draft", "abc123")
check("D2 an unknown draft is refused", bad.get("ok") is False, bad)
bad = selfevolve.repair_mark(OUT, "../etc", "abc123")
check("D3 a name that is not a plain directory is refused (no traversal)",
      bad.get("ok") is False and not os.path.exists(os.path.join(_tmp, "etc")), bad)

# ------------------------------------------------------------ E: the surface --
# The tool keeps its drafts under its OWN proposals dir (`improve.PROPOSAL_DIR`),
# so the surface is driven there: create through the tool, close through the tool.
from longrun.util import improve  # noqa: E402

TOOL_DIR = os.path.join(improve.PROPOSAL_DIR, "repairs")
made = T.execute("improve", {"action": "repairs", "limit": 5, "min_severity": "info"})
check("E1 the tool can mint the draft it will close",
      any(w.get("issue") == NAME for w in made.get("written") or []),
      made.get("written"))
r = T.execute("improve", {"action": "repair-fixed", "issue": NAME, "commit": "def456"})
check("E2 the surface records the close",
      r.get("ok") is True and (r.get("fix") or {}).get("commit") == "def456", r)
check("E3 a close dated now has no session after it — `unobserved`, and it says so",
      "unobserved" in (r.get("stdout") or "")
      and (r.get("state") or {}).get("status") == "unobserved", r.get("stdout"))
# A fix dated between the two sessions must read back as still open — and the
# moment must come from the caller, never from "now" (a commit from last week is
# not today, or the window hides the evidence that followed it).
r_when = T.execute("improve", {"action": "repair-fixed", "issue": NAME,
                               "commit": "def456", "when": "2026-03-01"})
check("E4 the surface carries `when` into the record (not 'now')",
      r_when.get("ok") is True
      and (r_when.get("fix") or {}).get("date") == selfevolve._since_epoch("2026-03-01")
      and (r_when.get("state") or {}).get("status") == "fixed-open", r_when)
r2 = T.execute("improve", {"action": "repairs", "limit": 5, "min_severity": "info"})
states = r2.get("states") or []
check("E5 `repairs` reports the state of its drafts",
      any(s.get("issue") == NAME and s.get("status") == "fixed-open" for s in states),
      states)
check("E6 and prints it, not only the new drafts",
      "fixed-open" in (r2.get("stdout") or "")
      and "in the 2 session(s) after the fix" in (r2.get("stdout") or ""),
      (r2.get("stdout") or "")[:300])
r3 = T.execute("improve", {"action": "repair-fixed", "issue": NAME})
check("E7 the tool refuses a close without a commit",
      r3.get("ok") is False and "commit" in str(r3.get("error") or ""), r3)

# ------------------------------------------------------------- F: the schema --
check("F1 the field map names the four arguments",
      registry._SUBTOOL_FIELDS["improve"]["repair-fixed"]
      == ["issue", "commit", "when", "note"],
      registry._SUBTOOL_FIELDS["improve"].get("repair-fixed"))
check("F2 and the two required ones",
      registry._SUBTOOL_REQUIRED["improve.repair-fixed"] == ["issue", "commit"],
      registry._SUBTOOL_REQUIRED.get("improve.repair-fixed"))

print("\n---\nv1103: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
