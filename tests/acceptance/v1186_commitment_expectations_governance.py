#!/usr/bin/env python3
"""v1186 — plan commitment, expectation checks, tool governance (round 117).

Sources:
  * arXiv:2611.19663 "When AI Agents Should Repair, Replan, or Abandon" — damage
    depth, 1 + R(G)/n revalidation, structure-dependent switch point, stability
    price, patch debt, value of diagnosis.
  * arXiv:2611.02438 "As Expected?" — expectation per batched step, comparison
    with the observation, early termination and replan from the current
    observation.
  * arXiv:2611.06682 "SecureGARD" — executable ontology + episode state, and the
    deterministic ready / waiting / forbidden decision.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1186_commitment_expectations_governance.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1186-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import commitment as PC          # noqa: E402
from longrun.harness import expectations as EX    # noqa: E402
from longrun.harness import governance as GV      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. plan commitment ----------------------------------------------------
SERIAL = ["a1", "a2", "a3", "a4"]
SERIAL_EDGES = [("a1", "a2"), ("a2", "a3"), ("a3", "a4")]
check("a broken action damages everything downstream in a serial plan",
      PC.damaged(SERIAL, SERIAL_EDGES, ["a1"]) == {"a1", "a2", "a3", "a4"})
check("a broken tail action damages only itself",
      PC.damaged(SERIAL, SERIAL_EDGES, ["a4"]) == {"a4"})
check("depth is the share of the plan the damage reaches",
      PC.depth(SERIAL, SERIAL_EDGES, ["a2"]) == 0.75)
check("R(G) counts pairs joined by a dependency path",
      PC.pairs(SERIAL, SERIAL_EDGES) == 6)
check("one broken action revalidates 1 + R/n actions",
      PC.revalidation_cost(SERIAL, SERIAL_EDGES) == 2.5)
check("a serial plan is one chain", PC.chains(SERIAL, SERIAL_EDGES) == 1)

PARALLEL = ["b1", "b2", "b3", "b4"]
PAR_EDGES = [("b1", "b2")]
check("parallel chains count as separate structures", PC.chains(PARALLEL, PAR_EDGES) == 3)
serial_switch = PC.switch_point(SERIAL, SERIAL_EDGES, 0.5)
par_switch = PC.switch_point(PARALLEL, PAR_EDGES, 0.5)
check("a serial plan crosses the threshold at smaller raw damage than parallel chains",
      serial_switch is not None and par_switch is not None and serial_switch < par_switch,
      (serial_switch, par_switch))

shallow = PC.decide({"actions": SERIAL, "edges": SERIAL_EDGES, "broken": ["a4"]})
check("shallow damage is repaired", shallow["decision"] == "repair", shallow)
deep = PC.decide({"actions": SERIAL, "edges": SERIAL_EDGES, "broken": ["a1"]})
check("deep damage is replanned", deep["decision"] == "replan", deep)
abandon = PC.decide({"actions": SERIAL, "edges": SERIAL_EDGES, "broken": ["a1"],
                     "goal_value": 1, "abandon_value": 5})
check("a goal not worth its cost is abandoned", abandon["decision"] == "abandon", abandon)

stable = PC.decide({"actions": SERIAL, "edges": SERIAL_EDGES, "broken": ["a1"],
                    "fresh_value": 10, "repaired_value": 9, "stability_price": 5})
check("an expensive switch keeps the worse repaired plan",
      stable["decision"] == "repair"
      and any("switching costs" in r for r in stable["reasons"]), stable)
unstable = PC.decide({"actions": PARALLEL, "edges": PAR_EDGES, "broken": ["b2"],
                      "fresh_value": 10, "repaired_value": 2, "stability_price": 1})
check("a cheap switch takes the better fresh plan",
      unstable["decision"] == "replan", unstable)
debt = PC.decide({"actions": SERIAL, "edges": SERIAL_EDGES, "broken": ["a4"],
                  "patch_debt": 9, "patch_step": 2, "debt_limit": 10})
check("patch debt forces the rebuild", debt["decision"] == "replan"
      and any("patch debt" in r for r in debt["reasons"]), debt)

diag = PC.worth_diagnosis({"depth_uncertainty": 0.4, "repair_replan_gap": 10,
                           "diagnosis_cost": 1})
check("diagnosis is worth it when uncertainty times the gap beats its cost", diag["worth"], diag)
diag_cheap = PC.worth_diagnosis({"depth_uncertainty": 0.01, "repair_replan_gap": 10,
                                 "diagnosis_cost": 5})
check("a certain damage is not worth measuring twice", not diag_cheap["worth"], diag_cheap)

# ---- 2. expectation-observation consistency --------------------------------
STEPS = [
    {"expect": {"exit": 0, "file": "a.txt"}, "observation": {"exit": 0, "file": "a.txt", "ms": 4}},
    {"expect": {"exit": 0, "file": "b.txt"}, "observation": {"exit": 1, "file": "b.txt"}},
    {"expect": {"exit": 0, "file": "c.txt"}, "observation": {"exit": 0, "file": "c.txt"}},
]
res = EX.verify(STEPS)
check("a consistent step continues the batch", res["steps"][0]["status"] == "consistent", res)
check("a mismatch stops the batch at that step",
      res["steps"][1]["status"] == "mismatch" and res["first_mismatch"] == 1, res)
check("the batch asks to replan from the current observation",
      res["action"] == "replan" and res["replan_from"] == 1, res)
check("steps after the mismatch are never reached",
      res["steps"][2]["status"] == "not-reached" and res["not_reached"] == 1, res)
check("an undeclared key is not judged",
      EX.verify(STEPS, keys=["exit"])["first_mismatch"] == 1)
check("a fully consistent batch continues", EX.verify(STEPS[:1])["action"] == "continue")
check("a step without an expectation cannot be verified",
      EX.verify([{"observation": {}}])["steps"][0]["status"] == "no-expectation")
sav = EX.savings(STEPS, 100)
check("the early stop is costed against the skipped steps",
      sav["saved_tokens"] == 100 and sav["not_reached"] == 1, sav)

# ---- 3. tool governance ----------------------------------------------------
ONT = {
    "read_file": {"effect": "read"},
    "write_file": {"requires": ["plan-approved"], "grants": ["file-written"]},
    "send_mail": {"requires": ["draft-reviewed"], "grant_required": "human-send"},
    "drop_all": {"forbids": ["audit-locked"]},
    "recoverable": ["draft-reviewed"],
    "protected": ["human-send"],
}
check("a consistent ontology declares no contradiction",
      GV.check_ontology(ONT)["verdict"] == "consistent", GV.check_ontology(ONT))
bad = dict(ONT)
bad["sneaky"] = {"grants": ["human-send"]}
check("an action granting a protected obligation breaks the ontology",
      any(p["kind"] == "protected-obligation-granted"
          for p in GV.check_ontology(bad)["problems"]), GV.check_ontology(bad))
contra = dict(ONT)
contra["both"] = {"grants": ["x"], "forbids": ["x"]}
check("granting and forbidding the same obligation is inconsistent",
      any(p["kind"] == "grants-and-forbids" for p in GV.check_ontology(contra)["problems"]))

ready = GV.decide({"action": "read_file"}, ONT, {"done": []})
check("a call with no unmet obligation is ready", ready["decision"] == "ready", ready)
wait = GV.decide({"action": "send_mail"}, ONT, {"done": [], "grants": []})
check("an unmet but recoverable obligation is waiting",
      wait["decision"] == "waiting" and wait["recoverable"], wait)
forbid = GV.decide({"action": "write_file"}, ONT, {"done": []})
check("an unrecoverable obligation forbids the call",
      forbid["decision"] == "forbidden", forbid)
grant = GV.decide({"action": "send_mail"}, ONT,
                  {"done": ["draft-reviewed"], "grants": []})
check("a missing authorization forbids even with obligations met",
      grant["decision"] == "forbidden" and "human-send" in grant["missing"], grant)
granted = GV.decide({"action": "send_mail"}, ONT,
                    {"done": ["draft-reviewed"], "grants": ["human-send"]})
check("the call is ready once the episode holds the authorization",
      granted["decision"] == "ready", granted)
locked = GV.decide({"action": "drop_all"}, ONT, {"done": [], "flags": ["audit-locked"]})
check("a forbidden condition stops the call", locked["decision"] == "forbidden", locked)
unknown = GV.decide({"action": "rm_rf"}, ONT, {"done": []})
check("an undeclared action is forbidden, never defaulted to ready",
      unknown["decision"] == "forbidden", unknown)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
