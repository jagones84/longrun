#!/usr/bin/env python3
"""v1105 — the failure register names WHOSE sessions produced a class.

Round 37 (Who&When Pro, arXiv:2607.09996 — attribution has a WHO axis). Rounds
21–36 named the tool, the family, the remedy, the check, the retry rate, the
recovery rate, the refusals and the repair's window; the only answer to "whose?"
was a session COUNT. Measured 2026-11-18 over the live store: 158 failed cards
belong to 37 different agents, and the biggest row spans four of them.

  A  the index reads the org chart's own store, and invents nobody
  B  a class row carries its agents; an unknown session adds nothing
  C  an issue sums its classes, so the same remedy names every agent
  D  the draft states WHO (or says the org chart does not know them)
  E  the register line the model reads carries the names too

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1105_failure_attribution_who.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1105-")
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
HEAD = "shell.exec: missing REQUIRED argument 'cmd'"
HEAD2 = "required: command"


def session(sid, cards):
    p = os.path.join(SESS, sid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def card(err):
    return {"tool": "shell.exec", "ok": False, "error": err}


# s_a / s_b are known agents; s_c is a session the org chart does not know;
# s_d is a second CLASS (same tool, same family) hit by the same agent as s_a.
session("s_a", [card(HEAD)] * 2)
session("s_b", [card(HEAD)] * 1)
session("s_c", [card(HEAD)] * 1)
session("s_d", [card(HEAD2)] * 1)

AGENTS = {"s_a": {"id": "A61", "n": 61, "session": "s_a", "created": 1.0,
                  "name": "llama_cp HF Scout", "role": "hf-model-scout"},
          "s_b": {"id": "A170", "n": 170, "session": "s_b", "created": 1.0,
                  "name": "Engine Programmer", "role": "engine-programmer"},
          "s_d": {"id": "A61", "n": 61, "session": "s_d", "created": 1.0,
                  "name": "llama_cp HF Scout", "role": "hf-model-scout"},
          # no `session`: a record that names nobody must not become "".
          "ghost": {"id": "A999", "n": 999, "created": 1.0, "name": "ghost"}}
AGENTS_FILE = os.path.join(os.environ["LONGRUN_DATA_DIR"], "agents.json")
with open(AGENTS_FILE, "w", encoding="utf-8") as f:
    json.dump({"agents": AGENTS, "seq": 999}, f)

# ------------------------------------------------- A: the index -----------------
idx = selfevolve._agents_index()
check("A1 the org chart's shaped store is read (`{'agents': {...}}`, not a bare list)",
      len(idx) == 3 and idx.get("s_b", {}).get("id") == "A170", idx)
check("A2 the record carries the name and the role, not only the id",
      idx.get("s_a", {}).get("name") == "llama_cp HF Scout"
      and idx.get("s_a", {}).get("role") == "hf-model-scout", idx.get("s_a"))
check("A3 a record with no session id attributes nothing (no empty-string key)",
      "" not in idx and "ghost" not in idx and len(idx) == 3, sorted(idx))
os.rename(AGENTS_FILE, AGENTS_FILE + ".off")
gone = selfevolve._agents_index()
os.rename(AGENTS_FILE + ".off", AGENTS_FILE)
check("A4 a missing store answers {} — attribution is never worth a crash", gone == {}, gone)

# ------------------------------------------------- B: the class row ------------
classes = {c["error"]: c for c in selfevolve.session_failures(limit=10)["classes"]}
c1 = classes.get(HEAD) or {}
c2 = classes.get(HEAD2) or {}
check("B1 the class counts every card (4 in 3 sessions, one of them unknown)",
      c1.get("count") == 4 and c1.get("sessions") == 3, c1)
check("B2 its agents sum 3 of 4 — the unknown session is not attributed to a guess",
      sum(a["count"] for a in c1.get("agents") or []) == 3, c1.get("agents"))
check("B3 most failed first: A61 (2) before A170 (1)",
      [a["id"] for a in c1.get("agents") or []] == ["A61", "A170"], c1.get("agents"))
check("B4 the name and the role travel with the count",
      (c1.get("agents") or [{}])[0].get("name") == "llama_cp HF Scout"
      and (c1.get("agents") or [{}])[0].get("role") == "hf-model-scout",
      c1.get("agents"))
check("B5 the second class has its own WHO", [a["id"] for a in c2.get("agents") or []] == ["A61"],
      c2.get("agents"))

# ------------------------------------------------- C: the issue ----------------
rep = selfevolve.failure_candidates(limit=10, include_sessions=True)
iss = (rep.get("issues") or [{}])[0]
check("C1 the issue groups both classes (4 + 1)", iss.get("count") == 5, iss)
check("C2 and sums the agents across them: A61 3 (2 + 1), A170 1",
      [(a["id"], a["count"]) for a in iss.get("agents") or []]
      == [("A61", 3), ("A170", 1)], iss.get("agents"))
check("C3 the class rows keep their own attribution", len(iss.get("classes") or []) == 2,
      iss.get("classes"))

# ------------------------------------------------- D: the draft ---------------
OUT = os.path.join(_tmp, "repairs")
res = selfevolve.issue_drafts(OUT, limit=5, min_severity="info")
name = (res.get("written") or [{}])[0].get("issue")
prop = json.load(open(os.path.join(OUT, name, "proposal.json"), encoding="utf-8"))
md = open(os.path.join(OUT, name, "REPAIR.md"), encoding="utf-8").read()
check("D1 proposal.json carries the agents, not only the count",
      [(a["id"], a["count"]) for a in prop.get("agents") or []]
      == [("A61", 3), ("A170", 1)], prop.get("agents"))
check("D2 REPAIR.md states WHO, with the count beside each name",
      "**Who:** A61 llama_cp HF Scout (3), A170 Engine Programmer (1)" in md,
      [l for l in md.splitlines() if l.startswith("**Who:**")])
check("D3 the draft does not claim the unknown session belongs to anyone",
      "(4)" not in md and "top three" not in md, md.split("**Who:**")[1][:120])

# A store the org chart does not know: the draft SAYS so instead of guessing.
os.rename(AGENTS_FILE, AGENTS_FILE + ".off")
EMP = os.path.join(_tmp, "repairs-empty")
selfevolve.issue_drafts(EMP, limit=1, min_severity="info")
em = open(os.path.join(EMP, os.listdir(EMP)[0], "REPAIR.md"), encoding="utf-8").read()
os.rename(AGENTS_FILE + ".off", AGENTS_FILE)
check("D4 with no agent rows the draft says the org chart has no mapping",
      "**Who:** no agent row names these sessions" in em, em.split("**Severity:**")[0])

# ------------------------------------------------- E: the register line -------
info = T.execute("self", {"action": "failures", "limit": 6})
line = ((info.get("failure_lines") or [""])[0])
check("E1 the line the model reads names the agents (`· who: A61 3, A170 1`)",
      "· who: A61 3, A170 1" in line, line)
check("E2 the issue's own reach stays its number (5 cards) while the agents sum 4",
      "5 in 3 session(s)" in line and "who: A61 3, A170 1" in line, line)
check("E3 the payload the panel reads carries the same rows",
      (info.get("failures") or {}).get("issues", [{}])[0].get("agents")
      and (info["failures"]["issues"][0]["agents"][0]["id"] == "A61"),
      (info.get("failures") or {}).get("issues", [{}])[0].get("agents"))

print("\n---\nv1105: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
