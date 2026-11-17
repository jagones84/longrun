#!/usr/bin/env python3
"""v1106 — an issue's reach is the UNION of its classes, and its units are named.

Round 38. Round 37 printed the WHO beside the count and exposed two numbers that
could not both be true: `shell · tool-error — 32 in 1 session(s) · who: A11 16`
(16 of the 32 came from the run-record corpus, which has no sessions at all), and
an issue that sums several classes reported the LARGEST class's session count
instead of the sessions it actually reached.

  A  an issue's `sessions` is the union of its classes, not the max
  B  the class carries WHICH sessions; no emitted row leaks the id list
  C  a mixed issue names its two units (session cards + run-record steps)
  D  the register line the model reads carries the split
  E  the draft states the split too
  F  a runs-only class claims no session and no recovery rate

Deterministic: temp data/session/harness dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1106_issue_reach_union.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1106-")
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
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
HEAD = "shell.exec: missing REQUIRED argument 'cmd'"
HEAD2 = "required: command"


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def card(err):
    return {"tool": "shell.exec", "ok": False, "error": err}


# One class in two sessions, a second class in a THIRD session, and two steps of
# the same failure in a run record — two corpora and two units.
session("s_a", [card(HEAD)] * 2)
session("s_b", [card(HEAD)] * 1)
session("s_c", [card(HEAD2)] * 1)
with open(os.path.join(RUNS, "run1.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "run1", "steps": [
        {"tool": "shell.exec", "ok": False, "error": HEAD},
        {"tool": "shell.exec", "ok": False, "error": HEAD},
        # one step of a class the sessions never saw
        {"tool": "fs.read", "ok": False, "error": "no such file: <path>"},
    ]}, f)

# ------------------------------------------------- A: the union ----------------
rep = selfevolve.failure_candidates(limit=10, include_sessions=True)
iss = next(i for i in rep["issues"] if i["family"] == "missing-argument")
check("A1 the issue counts both corpora (4 cards + 2 run steps = 6)",
      iss["count"] == 6 and iss["from_sessions"] == 4 and iss["from_runs"] == 2, iss)
check("A2 its reach is the UNION of the classes' sessions (3), not the max (2)",
      iss["sessions"] == 3, iss["sessions"])
check("A3 a class row keeps its own two-corpus split",
      sorted((c.get("from_sessions"), c.get("from_runs")) for c in iss["classes"])
      == [(1, 0), (3, 2)], iss["classes"])

# --------------------------------------------- B: the ids are internal --------
cls = next(c for c in selfevolve.session_failures(limit=10)["classes"]
           if c["error"] == HEAD)
check("B1 `session_failures` names the sessions behind a class",
      sorted(cls.get("session_ids") or []) == ["s_a", "s_b"], cls.get("session_ids"))
check("B2 and no emitted class row leaks the id list",
      all("session_ids" not in c for c in rep["classes"]), "")

# ------------------------------------------------- C: the units ----------------
_lines = (T.execute("self", {"action": "failures", "limit": 6})
          .get("failure_lines") or [""])
line, all_lines = _lines[0], "\n".join(_lines)
check("C1 the register line names the split",
      "6 (4 cards + 2 run steps) in 3 session(s)" in line, line)

# ------------------------------------------------- D: the draft ----------------
OUT = os.path.join(_tmp, "repairs")
res = selfevolve.issue_drafts(OUT, limit=5, min_severity="info")
name = (res.get("written") or [{}])[0].get("issue")
md = open(os.path.join(OUT, name, "REPAIR.md"), encoding="utf-8").read()
prop = json.load(open(os.path.join(OUT, name, "proposal.json"), encoding="utf-8"))
check("D1 REPAIR.md states the two units in its header",
      "**6** failure(s) (4 session card(s) + 2 run step(s)) in **3** session(s)" in md,
      [l for l in md.splitlines() if l.startswith("**Severity:**")])
check("D2 proposal.json carries the split", prop.get("from_sessions") == 4
      and prop.get("from_runs") == 2, (prop.get("from_sessions"), prop.get("from_runs")))

# ------------------------------------------------- E: runs only ----------------
only = next(i for i in rep["issues"] if i["family"] == "not-found")
check("E1 a runs-only issue claims no session and no recovery rate",
      only["from_sessions"] == 0 and only["from_runs"] == 1
      and only["sessions"] == 0 and only["recovery_rate"] is None, only)
check("E2 its register line says there is no session corpus",
      "1 run records only, no session corpus" in all_lines, all_lines)

print("\n---\nv1106: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
