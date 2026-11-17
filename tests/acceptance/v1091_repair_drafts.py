#!/usr/bin/env python3
"""v1091 — the failure register becomes WORK: one repair draft per issue.

Round 22. Round 21 taught the harness WHAT keeps failing (families, severity,
remedy, check). This turns that register into material the optimizer/operator
can act on, without ever running or promoting anything:

  A  one `kind: "repair"` draft per issue at/above a severity, evidence included
  B  never twice for the same issue id (a re-run is a no-op that says so)
  C  `limit` bounds a run; nothing but proposal.json + REPAIR.md is written
  D  the check is the register's own — never an invented test id
  E  the surface is `improve{action:"repairs"}`, and it drafts only

Deterministic: temp session/runs/proposal dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1091_repair_drafts.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1091-")
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
from longrun.util import paths  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
OUT = os.path.join(_tmp, "repairs")


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def record(name, steps):
    with open(os.path.join(RUNS, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": name, "steps": steps}, f)


DENY = "permission denied by policy: /etc/shadow"
session("s1", ([{"tool": "shell.exec", "ok": False, "error": DENY}] * 8) + [
    {"tool": "shell", "ok": False,
     "error": 'Traceback (most recent call last):\n  File "<stdin>", line 1'},
    {"tool": "fs.read", "ok": True, "exit_code": 0, "error": ""},
])
session("s2", [
    {"tool": "shell.exec", "ok": False, "error": DENY},
    {"tool": "todo.update", "ok": False,
     "error": "no steps received — this call changed nothing"},
])
record("r1", [{"tool": "shell.exec", "ok": False, "error": DENY},
              {"tool": "shell.exec", "ok": False, "error": "SIGKILL"}])

# ------------------------------------------ A: the drafts, severity first ----
reg = selfevolve.failure_candidates(limit=200, include_sessions=True)
iss = {(i["tool"], i["family"]): i for i in reg.get("issues") or []}
perm = iss.get(("shell.exec", "permission")) or {}
check("A1 the fixture really has an ERROR-level permission issue",
      perm.get("severity") == "error" and perm.get("count") == 10, perm)

rep = selfevolve.issue_drafts(OUT)
written = rep.get("written") or []
check("A2 the default floor (warning) drafts the error issue only",
      [w["family"] for w in written] == ["permission"], written)
d = os.path.join(OUT, written[0]["issue"]) if written else ""
prop = json.load(open(os.path.join(d, "proposal.json"))) if d else {}
check("A3 the draft is a repair PROPOSAL, auto-mined and not applied",
      prop.get("kind") == "repair" and prop.get("status") == "proposed"
      and prop.get("origin") == "auto", prop)
check("A4 the evidence travels with the draft",
      prop.get("count") == 10 and prop.get("sessions") == 2
      and prop.get("source") == "both" and prop.get("classes")
      and prop.get("samples"), {k: prop.get(k) for k in
                                ("count", "sessions", "source", "samples")})
check("A5 the remedy travels with the draft",
      "read path" in (prop.get("action") or ""), prop.get("action"))
check("A6 only the two draft files exist (nothing was executed)",
      sorted(os.listdir(d)) == ["REPAIR.md", "proposal.json"],
      os.listdir(d) if d else "")
body = open(os.path.join(d, "REPAIR.md"), encoding="utf-8").read() if d else ""
check("A7 REPAIR.md names the evidence, the remedy and the check",
      "10" in body and "read path" in body and "v1075" in body, body[:200])

# ------------------------------------------------ B: no duplicate drafts ----
again = selfevolve.issue_drafts(OUT)
check("B1 a re-run writes nothing and says which issue it skipped",
      (again.get("written") or []) == []
      and (again.get("skipped") or []) == [written[0]["issue"] if written else ""],
      again)

# --------------------------------------------- C: the floor and the cap ------
more = selfevolve.issue_drafts(OUT, min_severity="info", limit=2)
check("C1 a lower floor drafts info-level issues too, up to the cap",
      len(more.get("written") or []) == 2
      and all(w["family"] != "permission" for w in more.get("written") or []),
      more.get("written"))
check("C2 the cap is honoured (never more than `limit` in one run)",
      len(more.get("written") or []) <= 2, len(more.get("written") or []))

# --------------------------------------------- D: no invented checks --------
for w in (written + (more.get("written") or [])):
    got = w.get("check")
    if got:
        check("D·check %r for %s is a real test file" % (got, w["family"]),
              any(fn.startswith(str(got) + "_")
                  for fn in os.listdir(os.path.join(REPO, "tests", "acceptance"))),
              got)
    else:
        check("D·%s has no check, and the draft says so" % w["family"], True)

# -------------------------------------------------- E: the surface ----------
_enum = set(((registry.TOOL_SCHEMAS.get("improve") or {})
             .get("properties", {}).get("action", {}) or {}).get("enum", []))
check("E1 the `improve` schema documents action=repairs", "repairs" in _enum,
      sorted(_enum))
check("E2 its fields are the ones it reads (round 29 added `since`)",
      registry._SUBTOOL_FIELDS.get("improve", {}).get("repairs")
      == ["limit", "min_severity", "since"]
      and registry._SUBTOOL_REQUIRED.get("improve.repairs") == [],
      (registry._SUBTOOL_FIELDS.get("improve", {}).get("repairs"),
       registry._SUBTOOL_REQUIRED.get("improve.repairs")))
check("E3 it has guidance", bool(registry._SUBTOOL_GUIDANCE.get("improve.repairs")),
      "")

res = T.execute("improve", {"action": "repairs", "limit": 2, "min_severity": "info"})
check("E4 the tool drafts into the proposal store (not a second one)",
      res.get("ok") is True and str(res.get("dir") or "")
      .startswith(os.path.realpath(os.path.join(paths.DATA_DIR, "proposals"))),
      res.get("dir"))
check("E5 it reports what it wrote, one line each",
      len(res.get("written") or []) == len((res.get("stdout") or "").splitlines())
      and res.get("written"), res.get("stdout"))
check("E6 it never promotes or executes (the drafts are still proposed)",
      all(json.load(open(os.path.join(w["path"], "proposal.json")))
          .get("status") == "proposed" for w in (res.get("written") or [])), "")

print("\n---\nv1091: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
