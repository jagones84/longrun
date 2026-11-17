#!/usr/bin/env python3
"""v1109 — the register ranks what did NOT recover first.

Round 41. Round 31 measured that 70 % of failed cards are followed by a success of
the same tool in the same stage: a stumble, not a break. The register still ranked
by raw count, so a class with 10 of 10 recovered (`shell.exec · timeout`) outranked
one with 7 unresolved (`shell.exec · permission`). Ranking is now severity first,
then `unresolved = count - recovered`.

  A  at warning, a 2-unresolved class outranks a 3-card fully recovered one
  B  at error, the same inversion with a larger count
  C  a runs-only class credits no recovery (the corpus cannot see it)
  D  severity still dominates, and the order is total and stable

Deterministic: temp data/session/harness dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1109_unresolved_first.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1109-")
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
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
MISSING = "no such file: <path>"


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def fail(tool, err=MISSING, node=None):
    return {"tool": tool, "ok": False, "error": err, "node": node}


def ok(tool, node=None):
    return {"tool": tool, "ok": True, "result": "ok", "node": node}


# A: 3 cards, every one recovered (a stumble) — the LARGER count.
session("s_a", [fail("grep.search"), ok("grep.search")] * 3)
# A: 2 cards in 2 sessions, none recovered.
session("s_b", [fail("fs.read")])
session("s_c", [fail("fs.read")])
# B: 10 cards, all recovered — the LARGER count at error severity.
session("s_d", [fail("shell.exec")] + [ok("shell.exec")] * 1 + [fail("shell.exec"), ok("shell.exec")] * 9)
# B: 3 cards in 3 sessions, none recovered.
for sid in ("s_e", "s_f", "s_g"):
    session(sid, [fail("shell")])
# C: a class the sessions never saw.
with open(os.path.join(RUNS, "run1.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "run1", "steps": [
        {"tool": "web.fetch", "ok": False, "error": MISSING},
        {"tool": "web.fetch", "ok": False, "error": MISSING}]}, f)

rep = selfevolve.failure_candidates(limit=50, include_sessions=True)
issues = rep["issues"]
by = {(i["tool"], i["family"]): i for i in issues}
order = [(i["tool"], i["family"]) for i in issues]
grep, fs = ("grep.search", "not-found"), ("fs.read", "not-found")
sh, she = ("shell", "error"), ("shell.exec", "error")
# `shell` fails MISSING → its family is not-found, not "error": look it up by tool.
sh = next(k for k in order if k[0] == "shell")
she = next(k for k in order if k[0] == "shell.exec")

# ------------------------------------------------- A: warning inversion --------
a1, a2 = by.get(grep) or {}, by.get(fs) or {}
check("A1 a 3-card fully recovered class is a stumble: unresolved 0",
      a1.get("count") == 3 and a1.get("recovered") == 3 and a1.get("unresolved") == 0, a1)
check("A2 a 2-card never-recovered class carries unresolved 2",
      a2.get("count") == 2 and a2.get("unresolved") == 2, a2)
check("A3 both are the same severity, so the count alone would invert the order",
      a1.get("severity") == a2.get("severity") == "warning"
      and a1.get("count", 0) > a2.get("count", 0), (a1.get("severity"), a2.get("severity")))
check("A4 and the never-recovered class ranks FIRST",
      order.index(fs) < order.index(grep), order)

# ------------------------------------------------- B: error inversion ----------
b_exec, b_shell = by.get(she) or {}, by.get(sh) or {}
check("B1 a 10-card fully recovered class is a stumble: unresolved 0",
      b_exec.get("count") == 10 and b_exec.get("recovered") == 10
      and b_exec.get("unresolved") == 0, b_exec)
check("B2 a 3-card never-recovered class carries unresolved 3 at the same severity",
      b_shell.get("count") == 3 and b_shell.get("unresolved") == 3
      and b_shell.get("severity") == b_exec.get("severity") == "error", b_shell)
check("B3 and ranks FIRST", order.index(sh) < order.index(she), order)

# ------------------------------------------------- C: runs only ---------------
web = by.get(("web.fetch", "not-found")) or {}
check("C1 a runs-only class credits no recovery",
      web.get("recovered") == 0 and web.get("recovery_rate") is None
      and web.get("unresolved") == web.get("count") == 2, web)

# ------------------------------------------------- D: severity, total, stable --
ranks = [selfevolve._SEV_RANK.get(i["severity"], 3) for i in issues]
check("D1 severity still dominates: the ranks never decrease",
      ranks == sorted(ranks), ranks)
again = selfevolve.failure_candidates(limit=50, include_sessions=True)
check("D2 the order is total and stable (same input, same order)",
      [(i["tool"], i["family"]) for i in again["issues"]] == order, "")

print("\n---\nv1109: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
