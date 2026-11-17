#!/usr/bin/env python3
"""v1110 — the register the agent reads reaches the operator's panel.

Round 42. Rounds 21–41 built `self.failures`: classes, remedy, check, retries,
recovery, refusals, WHO, the two corpora, the unresolved-first order. Settings ▸
Improvements listed skill drafts and repair drafts only — the register itself was
invisible there. `/api/improvement` now carries `failures` and the panel renders
it: severity, class, count, unresolved, the agents behind it, the check, the remedy.

  A  an empty store answers with the key and zeros, never a missing field
  B  the rows are the register's own (unresolved, agents, remedy, check)
  C  the order is the register's own (unresolved first within a severity)
  D  `limit` is honoured and `sessions` states what was scanned
  E  the panel block exists and renders the rows it is given
  F  the graphic rules: the severity is named (title + aria-label), and the
     empty state says why it is empty

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1110_register_panel.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1110-")
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

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------- A: nothing yet --------------
empty = httpapi.improvement_failures()
check("A1 an empty store answers with the key and zeros",
      empty.get("issues") == [] and empty.get("sessions") == 0
      and empty.get("runs") == 0, empty)
check("A2 never a missing key", set(empty) >= {"issues", "sessions", "runs", "since"}, empty)

# ------------------------------------------------- B: a real store ------------
SESS = os.environ["LONGRUN_SESSIONS_DIR"]
MISSING = "no such file: <path>"


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def fail(tool, err=MISSING):
    return {"tool": tool, "ok": False, "error": err}


def okc(tool):
    return {"tool": tool, "ok": True, "result": "ok"}


# fs.read: 2 failures, never recovered. grep.search: 3 failures, all recovered.
session("s_a", [fail("fs.read")])
session("s_b", [fail("fs.read")])
session("s_c", [fail("grep.search"), okc("grep.search")] * 3)
# one agent behind the never-recovered class
with open(os.path.join(os.environ["LONGRUN_DATA_DIR"], "agents.json"), "w",
          encoding="utf-8") as f:
    json.dump({"agents": {"s_a": {"id": "A61", "n": 61, "session": "s_a",
                                  "created": 1.0, "name": "llama_cp HF Scout",
                                  "role": "hf-model-scout"}}, "seq": 61}, f)

reg = httpapi.improvement_failures(limit=8)
issues = reg.get("issues") or []
check("B1 the rows are the register's own",
      issues and all(k in issues[0] for k in
                     ("id", "tool", "family", "severity", "count", "unresolved",
                      "agents", "action", "check")), issues[:1])
check("B2 the unresolved measure travels", any(
    i["tool"] == "fs.read" and i["unresolved"] == i["count"] == 2 for i in issues), issues)
check("B3 and the WHO travels", any(
    i["tool"] == "fs.read" and [a["id"] for a in i["agents"]] == ["A61"]
    for i in issues), issues)

# ------------------------------------------------- C: the register's order ----
check("C1 unresolved first: fs.read (2 unresolved) precedes grep.search (0)",
      [i["tool"] for i in issues].index("fs.read")
      < [i["tool"] for i in issues].index("grep.search"), [i["tool"] for i in issues])

# ------------------------------------------------- D: limit and the scan -------
one = httpapi.improvement_failures(limit=1)
check("D1 `limit` is honoured", len(one.get("issues") or []) == 1, one)
check("D2 the answer states what was scanned",
      one.get("sessions") == 3, one.get("sessions"))

# ------------------------------------------------- E: the panel ---------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the panel has its own block and counters",
      'id="impRegisterBox"' in UI and 'id="impRegister"' in UI
      and 'id="impRegisterCount"' in UI, "")
check("E2 the render reads the API's own rows",
      "d.failures" in UI and "regD.issues" in UI, "")
check("E3 each row names the class, the count and the unresolved part",
      'i.tool || "?"' in UI and "failure(s) · " in UI and "unresolved" in UI, "")
check("E4 the agents and the remedy travel to the row",
      "i.agents" in UI and "i.action" in UI and "who: " in UI, "")

# ------------------------------------------------- F: graphic rules -----------
check("F1 the severity is NAMED, not a bare letter",
      'aria-label="' + "' + esc(sev)" in UI and 'title="' + "' + esc(sev" in UI, "")
check("F2 the empty state says why it is empty",
      "no failure class in the store yet — nothing measured" in UI, "")

print("\n---\nv1110: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
