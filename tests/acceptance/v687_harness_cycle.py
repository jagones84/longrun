#!/usr/bin/env python3
"""v687 — H2-7 one cycle + the API + the panel section.

The cycle is the point where the five modules become one behaviour:
record -> two scoped editors -> isolated probe -> compose -> library, with the
paper's order (`papers/harness2/harness2_2610.14224.txt:225-368`).

  A  no session -> refused; a dry run records the run and lists library hits with
     NO model call and NO probe
  B  a real cycle adopts one library entry, writes the proposal, and cleans the
     probe scratch
  C  a clean run (no failed step) produces no candidates
  D  disabled refuses a real cycle (the switch the operator owns)
  E  status() reads REAL state (enabled flag, per-domain counts, last report)
  F  the route exists on GET and POST, and the panel renders that payload — the
     UI must not invent a number the API did not return

No model, no network, no server: the editor call and the probe runner are injected.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v687-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import cycle as CY  # noqa: E402
from longrun.harness import library as L  # noqa: E402
from longrun.harness import probe as P  # noqa: E402
from longrun.harness import record as R  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


WS = os.path.join(TMP, "ws")
os.makedirs(WS, exist_ok=True)
with open(os.path.join(WS, "in.csv"), "w", encoding="utf-8") as f:
    f.write("a,b\n1,2\n")
SID = "sess-cycle"
SESS = {
    "id": SID, "created": 100.0, "model": "m", "workspace": WS,
    "messages": [{"role": "user", "content": "Reconcile the schedule against the budget."}],
    "tool_cards": [
        {"tool": "fs.read", "ok": True, "args": {"path": os.path.join(WS, "in.csv")},
         "result": "a,b", "error": "", "exit_code": 0, "ts": 101.0},
        {"tool": "shell", "ok": False, "args": {"command": "curl x"},
         "result": "", "error": "exit 7 connection refused", "exit_code": 7, "ts": 102.0},
    ],
    "injects": [],
}
with open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], SID + ".json"), "w",
          encoding="utf-8") as f:
    json.dump(SESS, f)
CLEAN = dict(SESS, id="sess-clean", tool_cards=[SESS["tool_cards"][0]])
with open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], "sess-clean.json"), "w",
          encoding="utf-8") as f:
    json.dump(CLEAN, f)

SKILL = {"kind": "skill", "name": "reconcile", "why": "no input inventory",
         "content": "When reconciling, inventory every input first.\n"}


def editor_call(_msgs, *_a, **_k):
    return json.dumps({"candidates": [SKILL]}), "", "stub"


def probe_runner(_plan, _timeout):
    """The candidate run: the same goal, the failing step GONE (a fixed error)."""
    sess = {"id": "probe-x", "created": 300.0, "model": "m", "workspace": WS,
            "messages": [{"role": "user", "content": SESS["messages"][0]["content"]}],
            "tool_cards": [{"tool": "fs.read", "ok": True,
                            "args": {"path": "in.csv"}, "result": "a,b\n1,2",
                            "error": "", "exit_code": 0, "ts": 301.0}]}
    return {"record": R.build("probe-x", session=sess), "goal": SESS["messages"][0]["content"],
            "created": 300.0, "model": "m", "error": ""}, ""


ON = {"enabled": True, "max_candidates": 2, "max_seconds": 5, "max_steps": 3,
      "copy_max_mb": 8, "keep": False}
OFF = dict(ON, enabled=False)

# --------------------------------------------------------------- A: dry run --
check("A1 no session is refused", CY.run(None)["status"] == "refused")
calls = []
dry = CY.run(SID, domain="office", dry_run=True, c=ON,
             call=lambda *a, **k: calls.append(1), runner=lambda *a, **k: calls.append(1))
check("A2 a dry run records the run", dry["status"] == "dry-run"
      and dry["base"]["steps"] == 2 and dry["base"]["failures"] == 1, dry["base"])
check("A3 a dry run names the observed error class",
      any("connection refused" in c for c in dry["base"]["error_classes"]),
      dry["base"]["error_classes"])
check("A4 a dry run calls no model and spawns no probe", calls == [])
check("A5 the dry run is the LAST report", (CY.last() or {}).get("status") == "dry-run")

# ------------------------------------------------------------- B: real cycle --
ran = CY.run(SID, domain="office", dry_run=False, c=ON, call=editor_call, runner=probe_runner)
check("B1 the cycle adopts an entry", ran["status"] == "adopted" and ran["adopted"], ran.get("status"))
check("B2 the same candidate from the second scope is NOT proposed twice",
      len(ran["proposals"]) == 1, ran["proposals"])
check("B2b the duplicate is named in the refusals",
      any("already proposed" in str(r.get("reason")) for r in ran.get("refusals") or []),
      ran.get("refusals"))
check("B3 the adopted entry is in the office library",
      len(L.index("office")["entries"]) == 1, L.index("office"))
check("B4 the contrast that justified it is recorded as improved",
      (ran.get("contrast") or {}).get("verdict") == "improved"
      and (ran["contrast"].get("errors") or {}).get("fixed"), ran.get("contrast"))
check("B5 the probe scratch is cleaned after the cycle",
      not os.path.isdir(os.path.join(P.root(), (ran.get("probe") or {}).get("probe_id") or "x")))

# ----------------------------------------------------------- C: nothing to fix --
clean = CY.run("sess-clean", domain="office", dry_run=False, c=ON,
               call=editor_call, runner=probe_runner)
check("C1 a clean run produces no candidates", clean["status"] == "no candidates", clean)
check("C2 it says WHY (the editor's skip reason)",
      "no observed failure" in (clean.get("reason") or ""), clean.get("reason"))

# ---------------------------------------------------------------- D: disabled --
off = CY.run(SID, domain="office", dry_run=False, c=OFF, call=editor_call, runner=probe_runner)
check("D1 a disabled probe refuses the cycle", off["status"] == "refused"
      and "LONGRUN_HARNESS_ENABLED" in off["reason"], off)

# ----------------------------------------------------------------- E: status --
st = CY.status()
check("E1 status reports the real switch", st["enabled"] is False)
check("E2 status counts the library per domain", st["library"]["domains"].get("office") == 1,
      st["library"])
check("E3 status carries the most recent report (the disabled refusal)",
      (st["last"] or {}).get("session") == SID
      and (st["last"] or {}).get("status") == "refused", (st["last"] or {}).get("status"))

# ------------------------------------------------------------ F: API + panel --
api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
snippet = api_src.split('"/api/harness/cycle"')
check("F1 the route is registered for GET and POST", len(snippet) == 3,
      len(snippet) - 1)
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("F2 the panel reads that endpoint", "/api/harness/cycle" in ui
      and "loadHarnessCycle" in ui and 'id="hcLib"' in ui)
check("F3 the panel escapes model-derived strings", "esc(String(r.status))" in ui)
check("F4 no forbidden feature is claimed in the panel",
      "auto-apply" not in ui.lower().split('id="hcbox"')[-1][:2000])
# F5 (live defect, 2026-10-28): the section rendered EMPTY ("—") on every visit
# because opening the Improvement category loaded the proposals and the memories
# but never the cycle. The panel must read real state when it opens.
_branch = ui.split('else if (name === "improvement") {', 1)[-1].split("else if (name === ", 1)[0]
check("F5 opening Improvement loads the cycle section", "loadHarnessCycle()" in _branch,
      _branch.strip().splitlines()[:4])

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
