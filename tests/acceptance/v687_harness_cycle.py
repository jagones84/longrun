#!/usr/bin/env python3
"""v687 — H2-7 conservative cycle + API/panel source contracts.

The cycle is the point where the five modules become one behaviour:
record -> two scoped editors -> independent injected probes -> successor ->
confounded NO_ENTRY reflection. Production refuses until whole-run isolation is
available; injected tests do not establish confinement or scientific transfer.

  A  no session -> refused; a dry run records the run and lists library hits with
     NO model call and NO probe
  B  an injected cycle verifies a successor, keeps evidence without durable
     proposals/adoption, and cleans all probe scratch
  C  a clean run (no failed step) produces no candidates
  D  disabled and whole-run isolation refusal stop before editor spend
  E  status() reads REAL state (enabled flag, per-domain counts, last report)
  F  route/panel source contracts remain pinned (not live rendering proof)

No model, no network, no server: the editor call and the probe runner are injected.
"""
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v687-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR",
           "RUNS_DIR", "PROJECTS_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import cycle as CY  # noqa: E402
from longrun.harness import library as L  # noqa: E402
from longrun.harness import probe as P  # noqa: E402
from longrun.harness import record as R  # noqa: E402
from longrun.util import improve as IMP  # noqa: E402

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


probe_calls = []


def probe_runner(_plan, _timeout):
    """The candidate run: the same goal, the failing step GONE (a fixed error)."""
    probe_calls.append(sorted(_plan["staged"]))
    sid = "probe-x-%d" % len(probe_calls)
    sess = {"id": sid, "created": 300.0, "model": "m", "workspace": _plan["workspace"],
            "messages": [{"role": "user", "content": SESS["messages"][0]["content"]}],
            "tool_cards": [{"tool": "fs.read", "ok": True,
                            "args": {"path": "in.csv"}, "result": "a,b\n1,2",
                            "error": "", "exit_code": 0, "ts": 301.0}]}
    return {"record": R.build(sid, session=sess), "goal": SESS["messages"][0]["content"],
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
before = IMP.list_proposals()
with patch.object(IMP, "propose", side_effect=AssertionError("cycle wrote inbox")), \
        patch.object(L, "add", side_effect=AssertionError("cycle wrote library")):
    ran = CY.run(SID, domain="office", dry_run=False, c=ON, call=editor_call, runner=probe_runner)
check("B1 the cycle reports no adoption despite supported execution",
      ran["status"] == "no adoption" and ran["adopted"] is None
      and ran["kept"] == ["reconcile"] and ran["reflection"]["status"] == "NO_ENTRY")
check("B2 duplicate candidates produce one trial and no proposal",
      ran["proposals"] == [] and len(ran["trials"]) == 1
      and probe_calls == [["reconcile"], ["reconcile"]] and IMP.list_proposals() == before)
check("B2b the duplicate is named in the refusals",
      any("already proposed" in str(r.get("reason")) for r in ran.get("refusals") or []),
      ran.get("refusals"))
check("B3 no durable library entry is created",
      L.index("office")["entries"] == [] and ran["reflection"]["edits"][0]["attribution"] == "confounded"
      and ran["reflection"]["edits"][0]["confidence"] == "insufficient")
check("B4 the contrast that justified it is recorded as improved",
      (ran.get("contrast") or {}).get("verdict") == "improved"
      and (ran["contrast"].get("errors") or {}).get("fixed"), ran.get("contrast"))
check("B5 the probe scratch is cleaned after the cycle",
      all(not os.path.exists(os.path.join(P.root(), trial["probe_id"]))
          for trial in ran["trials"] + [ran["successor"]]))
check("B6 successor has independent execution evidence",
      ran["trials"][0]["record"]["run_id"] != ran["successor"]["record"]["run_id"]
      and ran["reflection"]["successor_run"] == ran["successor"]["record"]["run_id"])

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
with patch.object(P, "plan", side_effect=AssertionError("production staging")):
    production = CY.run(SID, dry_run=False, c=ON,
                        call=lambda *_a: (_ for _ in ()).throw(AssertionError("editor spend")))
check("D2 production whole-run isolation refusal precedes editor spend",
      production["status"] == "refused" and "whole-run" in production["reason"]
      and production["proposals"] == [] and production["probe"] is None)

# ----------------------------------------------------------------- E: status --
st = CY.status()
check("E1 status reports the real switch", st["enabled"] is False)
check("E2 status counts the empty library honestly", st["library"]["domains"].get("office") == 0
      and st["library"]["entries"] == 0,
      st["library"])
check("E3 status carries the most recent report (the isolation refusal)",
      (st["last"] or {}).get("session") == SID
      and (st["last"] or {}).get("status") == "refused"
      and "whole-run" in st["last"]["reason"]
      and st["isolation"]["available"] is False)

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

# ------------------- G: only what the probe APPLIED can be adopted (live flaw) --
# Two guardrails write the same file; the probe applies one. The cycle used to
# report both as kept and store a library entry that held neither text in full.
# Independent trials now execute BOTH texts; composition retains only one target.
TWO = [{"kind": "guardrail", "name": "rules-a", "content": "Always inventory inputs.\n"},
       {"kind": "guardrail", "name": "rules-b", "content": "Never guess a path.\n"}]


def two_call(_msgs, *_a, **_k):
    return json.dumps({"candidates": TWO}), "", "stub"


probe_calls.clear()
two = CY.run(SID, domain="two", dry_run=False, c=ON, call=two_call, runner=probe_runner)
check("G1 only the applied candidate is kept", two.get("kept") == ["rules-a"], two.get("kept"))
check("G2 the refused twin is named with its reason",
      any("same file as" in str(r.get("reason")) for r in two.get("refusals") or []),
      two.get("refusals"))
check("G3 both candidates run independently before the single-target successor",
      probe_calls == [["rules-a"], ["rules-b"], ["rules-a"]]
      and [t["candidate"]["name"] for t in two["trials"]] == ["rules-a", "rules-b"])
check("G4 reflection retains both confounded trials without durable adoption",
      [e["name"] for e in two["reflection"]["edits"]] == ["rules-a", "rules-b"]
      and two["reflection"]["status"] == "NO_ENTRY" and two["adopted"] is None
      and two["proposals"] == [] and L.index("two")["entries"] == []
      and IMP.list_proposals() == before)

# --------------------------------------- H: composed successor can regress ---
DISTINCT = [TWO[0], SKILL]
trial_calls = []


def distinct_call(_msgs):
    return json.dumps({"candidates": DISTINCT}), "", "stub"


def regressing_runner(plan, timeout):
    trial_calls.append(sorted(plan["staged"]))
    payload, error = probe_runner(plan, timeout)
    if len(plan["staged"]) > 1:
        payload["record"]["steps"].append(
            {"tool": "fs.read", "ok": False, "error": "permission denied", "exit_code": 1})
    return payload, error


regressed = CY.run(SID, domain="regression", dry_run=False, c=ON,
                   call=distinct_call, runner=regressing_runner)
check("H1 distinct components run alone, then together",
      trial_calls == [["rules-a"], ["reconcile"], ["reconcile", "rules-a"]]
      and len(regressed["trials"]) == 2
      and all(t["contrast"]["verdict"] == "improved" for t in regressed["trials"]))
check("H2 a mixed successor rejects both individually supported edits",
      regressed["successor"]["contrast"]["verdict"] == "mixed"
      and regressed["kept"] == []
      and {r["name"] for r in regressed["rejected"]} == {"rules-a", "reconcile"}
      and "mixed" in regressed["decision"])
check("H3 failed composition preserves observations, not proposals or lessons",
      regressed["status"] == "no adoption" and regressed["adopted"] is None
      and regressed["proposals"] == [] and regressed["reflection"]["status"] == "NO_ENTRY"
      and len(regressed["reflection"]["edits"]) == 2
      and L.index("regression")["entries"] == [] and IMP.list_proposals() == before)
check("H4 every independent and successor scratch tree is removed",
      all(not os.path.exists(os.path.join(P.root(), trial["probe_id"]))
          for trial in regressed["trials"] + [regressed["successor"]]))

# ---------------------------------------------------------- I: cap refusal ---
too_many = DISTINCT + [dict(SKILL, name="extra")]
cap_calls = []


def cap_editor(_msgs):
    return json.dumps({"candidates": too_many}), "", "stub"


capped = CY.run(SID, dry_run=False, c=ON, call=cap_editor,
                runner=lambda *_a: cap_calls.append("spawn"))
check("I1 candidate cap refuses before any probe or durable write",
      capped["status"] == "refused" and "cap" in capped["reason"]
      and cap_calls == [] and capped["proposals"] == [] and IMP.list_proposals() == before)

# -------------------------------------- J: real pre-existing library state ---
# This explicit fixture is not cycle adoption. Preserve populated status/hit
# coverage while the cycle itself must never create a durable entry.
fixture = os.path.join(TMP, "existing-SKILL.md")
with open(fixture, "w", encoding="utf-8") as f:
    f.write("Existing fixture skill: reconcile schedule and budget.\n")
entry = L.add("existing", {
    "id": "existing-reconcile", "task_kind": "reconcile schedule budget",
    "lesson": "Existing fixture only; not an experimental transfer claim.",
    "files": {"SKILL.md": fixture},
})
st = CY.status()
check("J1 status counts real populated and empty domains",
      entry is not None and st["library"]["domains"]["existing"] == 1
      and st["library"]["domains"]["office"] == 0 and st["library"]["entries"] == 1)
fixture_calls = []
existing = CY.run(SID, domain="existing", dry_run=True, c=ON,
                  call=lambda *_a: fixture_calls.append("editor"),
                  runner=lambda *_a: fixture_calls.append("probe"))
check("J2 dry run reads existing library hits without editing or probing",
      existing["library_hits"] == ["existing-reconcile"] and fixture_calls == []
      and existing["adopted"] is None and existing["proposals"] == [])
check("J3 last report round-trips and fixture does not create inbox proposals",
      CY.last() == existing and CY.status()["library"]["entries"] == 1
      and IMP.list_proposals() == before)

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
