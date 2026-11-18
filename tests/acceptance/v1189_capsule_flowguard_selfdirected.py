#!/usr/bin/env python3
"""v1189 — skill capsules, behavioural flow guard, self-directed improvement (round 120).

Sources:
  * arXiv:2611.10022 "How Much Skill Orchestration Can LLM Agents Compile Away?" —
    one-trace capsules, replay before reuse, return control only where needed.
  * arXiv:2611.21520 "Safe Resemblance, Silent Propagation" — behavioural target,
    direct operating point, authorization decides.
  * arXiv:2611.23219 "Do LLM Agents Still Need to Be Told How to Self-Improve?" —
    the self-directed paradigm and its evidence.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1189_capsule_flowguard_selfdirected.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1189-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import skill_cache as SK       # noqa: E402
from longrun.harness import flow_guard as FG        # noqa: E402
from longrun.harness import self_directed as SD     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. skill capsules ------------------------------------------------------
INV = {
    "skill": "csv-report", "skill_path": "skills/core/csv-report",
    "params": {"path": "in.csv", "out": "out.md"},
    "bindings": {"customer": "ACME"},
    "preconditions": ["file:in.csv"],
    "steps": [
        {"tool": "fs.read", "args": {"path": "in.csv"}},
        {"tool": "python.run", "args": {"path": "in.csv"}, "deterministic": True},
        {"tool": "fs.write", "args": {"path": "out.md", "content": "ACME totals"}},
        {"kind": "judge", "why": "decide the chart style", "expectation": "style chosen"},
        {"tool": "fs.write", "args": {"path": "out.md", "content": "final"}},
    ],
}
cap = SK.compile_capsule(INV)
check("a capsule compiles from a real invocation", cap["capsule"]["skill"] == "csv-report", cap)
check("a parameter value becomes a named slot",
      cap["capsule"]["steps"][0]["args"]["path"] == {"slot": "path"}
      and cap["capsule"]["steps"][0]["slots"] == ["path"], cap["capsule"]["steps"][0])
check("an instance value of the request is not hard-coded into the capsule",
      any(f["kind"] == "unparameterised-binding" for f in cap["findings"]), cap["findings"])
check("a capsule that embeds an instance value cannot be replayed",
      cap["capsule"]["safe"] is False
      and SK.replay(cap["capsule"], {"params": {"path": "x", "out": "y"}})["decision"] == "invalid",
      cap["capsule"]["safe"])
check("a non-deterministic step becomes a control point",
      cap["capsule"]["controls"] == [3] and cap["capsule"]["steps"][3]["op"] == "judge",
      cap["capsule"]["steps"][3])

# A clean capsule for the replay checks: every request value is a declared parameter.
CLEAN_INV = {**INV, "bindings": {},
             "params": {"path": "in.csv", "out": "out.md", "content": "totals"},
             "steps": [dict(s) for s in INV["steps"]]}
CLEAN_INV["steps"][2] = {"tool": "fs.write", "args": {"path": "out.md", "content": "totals"}}
CAP = SK.compile_capsule(CLEAN_INV)["capsule"]
check("a fully parameterised capsule is safe to replay", CAP["safe"] is True, CAP["safe"])

check("a request missing a slot does not match the capsule",
      SK.applies(CAP, {"params": {}})["applies"] is False)
check("a request with every slot matches",
      SK.applies(CAP, {"params": {"path": "x", "out": "y", "content": "z"}})["applies"])

reuse = SK.replay(CAP, {"params": {"path": "x", "out": "y", "content": "z"},
                        "holds": ["file:in.csv"]})
check("an inapplicable detail still returns control before it, never after",
      reuse["decision"] == "return-control" and reuse["return_at"] == 3, reuse)
check("the returned plan stops before the control point",
      [s["tool"] for s in reuse["plan"]] == ["fs.read", "python.run", "fs.write"], reuse["plan"])

stuck = SK.replay(CAP, {"params": {"path": "x"}})
check("a missing binding makes the capsule invalid, not best-effort",
      stuck["decision"] == "invalid", stuck)
stale = SK.replay(CAP, {"params": {"path": "x", "out": "y", "content": "z"}, "holds": []})
check("a broken precondition invalidates the capsule", stale["decision"] == "invalid", stale)
check("the source skill stays available for recovery",
      reuse["source_skill"] == "skills/core/csv-report")

check("a skill supplied as a plain id still compiles",
      SK.compile_capsule({"steps": []}, "demo")["capsule"]["skill"] == "demo")

unattended = {"skill": "k", "params": {}, "steps": [{"tool": "fs.read", "args": {}}]}
sav = SK.savings(SK.compile_capsule(unattended)["capsule"], 10, 100)
check("a replayable capsule has a token saving", sav["saved_tokens"] == 90, sav)
check("a capsule that returns control claims no saving",
      SK.savings(cap["capsule"], 10, 100)["saved_tokens"] == 0)

# ---- 1b. admission gates, deoptimization, amortization (same paper) ----------
G1 = {"skill": "g", "slots": ["a"], "steps": [
    {"index": 0, "op": "call", "tool": "p1", "args": {"x": {"slot": "a"}}, "output": "o1"},
    {"index": 1, "op": "call", "tool": "p2", "args": {"y": {"slot": "o1"}}, "output": "o2"},
]}
gate = SK.qualify(G1, examples=["o1", "o2"], checks={"p1": True, "p2": True})
check("a well-formed candidate passes all three admission gates",
      gate["ok"] is True and gate["gate"] == 3 and gate["findings"] == [], gate)
undeclared = SK.qualify({**G1, "steps": [{"index": 0, "op": "call", "tool": "p1",
                                          "args": {"x": {"slot": "nope"}}}]})
check("a program reading a value the capsule never declares fails gate 1",
      undeclared["ok"] is False and undeclared["gate"] == 1
      and undeclared["findings"][0]["kind"] == "undeclared-slot", undeclared)
twow = SK.qualify({"slots": [], "steps": [
    {"index": 0, "op": "call", "tool": "p1", "args": {}, "output": "o"},
    {"index": 1, "op": "call", "tool": "p2", "args": {}, "output": "o"}]})
check("two programs writing one binding fails gate 1",
      any(f["kind"] == "two-writers" for f in twow["findings"]), twow)
early = SK.qualify({"slots": [], "steps": [
    {"index": 0, "op": "call", "tool": "p1", "args": {"x": {"slot": "o"}}},
    {"index": 1, "op": "call", "tool": "p2", "args": {}, "output": "o"}]})
check("reading an output before the program that writes it fails gate 1",
      any(f["kind"] == "read-before-write" for f in early["findings"]), early)
gate2 = SK.qualify(G1, examples=["o1", "o2"], checks={"p1": True, "p2": False})
check("a program that does not build fails gate 2 and names its step",
      gate2["ok"] is False and gate2["gate"] == 2 and gate2["failed_steps"] == [1], gate2)
gate3 = SK.qualify(G1, examples=["o1"], checks={"p1": True, "p2": True})
check("replay without a recorded value for an output fails gate 3",
      gate3["ok"] is False and gate3["gate"] == 3
      and gate3["findings"][0]["kind"] == "replay-missing-example", gate3)

deopt = SK.deoptimize(G1, 1)
check("only the failed program leaves the compiled path",
      deopt["decision"] == "return-control" and deopt["return_at"] == 1
      and deopt["resume_after"] == 2
      and [s["tool"] for s in deopt["plan"]] == ["p1"], deopt)
check("the handed-over step keeps its source for recovery",
      deopt["hand_over"]["source"] == "g", deopt["hand_over"])
check("a step outside the capsule cannot be deoptimized",
      SK.deoptimize(G1, 9)["decision"] == "invalid")

check("the compile call is repaid after cost divided by the per-reuse saving",
      SK.payback(60, 100, 40)["reuses"] == 1.0, SK.payback(60, 100, 40))
check("a warm run that saves nothing never repays compilation",
      SK.payback(60, 50, 50)["reuses"] is None)

# ---- 2. flow guard ----------------------------------------------------------
block = FG.judge({"behaviour": {"fresh_computations": 2},
                  "policy": {}, "similarity": 0.42})
check("a functional relay is blocked on behaviour, not on similarity",
      block["decision"] == "block" and block["functional"], block)
check("a low-similarity functional relay is reported as a similarity miss",
      any(f["kind"] == "similarity-miss" for f in block["findings"]), block)
quoted = FG.judge({"behaviour": {"fresh_computations": 1},
                   "policy": {"quotation_allowed": True}, "similarity": 0.95})
check("a functional relay under an authorizing policy is a policy decision, not a score",
      quoted["decision"] == "flag"
      and any(f["kind"] == "authorization-conflict" for f in quoted["findings"]), quoted)
legit = FG.judge({"behaviour": {"fresh_computations": 0},
                  "policy": {"quotation_allowed": True}, "similarity": 0.97})
check("an authorized, non-functional relay is allowed", legit["decision"] == "allow", legit)
check("its high overlap is named a false alarm of the surface criterion",
      any(f["kind"] == "similarity-false-alarm" for f in legit["findings"]), legit)
unauth = FG.judge({"behaviour": {"fresh_computations": 0}, "policy": {}, "similarity": 0.1})
check("reuse without authorization is flagged even with no fresh computation",
      unauth["decision"] == "flag"
      and any(f["kind"] == "unauthorized-reuse" for f in unauth["findings"]), unauth)

SCORES = [0.9, 0.8, 0.75, 0.4, 0.35, 0.2]
LABELS = [True, True, False, False, True, False]
cal = FG.calibrate(SCORES, LABELS, target_fpr=0.34)
check("calibration returns a direct threshold meeting the target on its own set",
      cal["threshold"] is not None and cal["false_alert_rate"] <= 0.34, cal)
ev = FG.evaluate(SCORES, LABELS, cal["threshold"])
check("evaluation applies the threshold directly",
      ev["tp"] + ev["fn"] == 3 and abs(ev["false_alert_rate"]
                                       - round(ev["fp"] / (ev["fp"] + ev["tn"]), 4)) < 1e-9, ev)
new_scores = [0.85, 0.82, 0.81]
new_labels = [False, False, False]
moved = FG.evaluate(new_scores, new_labels, cal["threshold"])
check("the same threshold on a new template set is measured, not assumed to transfer",
      moved["false_alert_rate"] == 1.0, moved)
check("calibration refuses a set with no legitimate example",
      FG.calibrate([0.9], [True])["threshold"] is None)

# ---- 3. self-directed improvement -----------------------------------------
GOOD = {
    "primitives": ["collect_episode", "update_notes"],
    "budget": {"total": 1000, "unit": "calls"},
    "goal": {"general": True, "specified_as": "objective"},
    "loop": "self",
    "curriculum_choices": [{"chose": "harder maps first", "at": 3}],
    "artifacts": [{"name": "notes.md", "diff": "+ look before the jump"}],
    "transfer": {"before": 0.4, "after": 0.55, "held_out": True},
}
good = SD.audit(GOOD)
check("a run with primitives, a budget, its own curriculum and held-out transfer is self-directed",
      good["verdict"] == "self-directed" and good["findings"] == [], good)
scripted = SD.audit({**GOOD, "loop": "external"})
check("an externally imposed loop is not evidence for the paradigm",
      scripted["verdict"] == "scripted"
      and any(f["kind"] == "externally-imposed-loop" for f in scripted["findings"]), scripted)
nobud = SD.audit({**GOOD, "budget": {}})
check("a run with no budget is scripted", nobud["verdict"] == "scripted", nobud)
proc = SD.audit({**GOOD, "goal": {"general": True, "specified_as": "procedure"}})
check("a goal that names the steps prescribes the curriculum",
      any(f["kind"] == "prescribed-curriculum" for f in proc["findings"]), proc)
nocurr = SD.audit({**GOOD, "curriculum_choices": []})
check("no record of choosing what to practise keeps it out of self-directed",
      nocurr["verdict"] == "scripted", nocurr)
nodiff = SD.audit({**GOOD, "artifacts": [{"name": "notes.md"}]})
check("an artifact with no recorded diff is semi, not self-directed",
      nodiff["verdict"] == "semi"
      and any(f["kind"] == "unrecorded-updates" for f in nodiff["findings"]), nodiff)
notheld = SD.audit({**GOOD, "transfer": {"before": 0.4, "after": 0.5}})
check("transfer that is not held out is semi",
      any(f["kind"] == "transfer-not-held-out" for f in notheld["findings"]), notheld)

check("transfer moves in the measured direction",
      SD.transfer(GOOD)["verdict"] == "improved" and SD.transfer(GOOD)["delta"] == 0.15,
      SD.transfer(GOOD))
check("a flat transfer is not called an improvement",
      SD.transfer({"transfer": {"before": 0.4, "after": 0.4}})["verdict"] == "flat")
check("transfer without before/after is unusable, not zero",
      SD.transfer({})["usable"] is False)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
