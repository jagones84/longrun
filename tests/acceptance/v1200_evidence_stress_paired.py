#!/usr/bin/env python3
"""v1200 — evidence admission, safety-harness evolution, paired trials (round 131).

Sources:
  * arXiv:2611.22169 "Not All Evidence Is Admissible" — a tool output is a CARD
    and admission is a decision taken OUTSIDE the reasoner (a checker that sees
    only the input and the cards); the reference for a filter is a
    budget-matched random gate, so `seeing less` and `seeing better` are two
    different gains.
  * arXiv:2611.22583 "Evolution Under Fire" — utility constrains PARENTHOOD (a
    candidate that breaks the task is a counterexample, never a parent); parents
    come from the Pareto front of separate coordinates; a stressor is promoted
    only if the attack works AND the task survives AND the run completed; more
    qualified children is not a better search, and a linear chain regresses.
  * arXiv:2611.19359 "One Run Is Not Enough" — a paired design with an A/A noise
    floor, a pre-registered extension whose sign reversed, delivery and
    adherence rates, and the context cost of the mechanism.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1200_evidence_stress_paired.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1200-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import evidence_gate as EG  # noqa: E402
from longrun.harness.checks import stress_evolution as SE  # noqa: E402
from longrun.harness.checks import paired_trial as PT  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. evidence admission ------------------------------------------------
c1 = EG.card("vCDR 0.71", "contour overlaid on the fundus image", source="seg-A")
check("a complete card states a finding and the material it rests on",
      c1["complete"] is True and c1["findings"] == [], c1)
c2 = EG.card("consolidation in the right lower lobe", "")
check("a card with no material is incomplete",
      c2["complete"] is False and "material-missing" in kinds(c2), c2)

INPUT = "Patient note: the optic disc is visible; the ratio reads 0.71."
adm = EG.admit([
    {"finding": "vCDR 0.71", "material": "the ratio reads 0.71", "source": "seg-A"},
    {"finding": "vCDR 0.92", "material": "the ratio reads 0.92", "source": "seg-B"},
    {"finding": "possible glaucoma", "material": ""},
], {"input": INPUT})
check("only the cards verifiable against the input are admitted",
      len(adm["admitted"]) == 1
      and adm["admitted"][0]["finding"] == "vCDR 0.71", adm)
check("a quoted material absent from the input is refused",
      any(r["reasons"][0]["kind"] == "material-not-in-input"
          for r in adm["rejected"]), adm)
check("a finding with no material is refused",
      any(r["reasons"][0]["kind"] == "finding-without-material"
          for r in adm["rejected"]), adm)

ind = EG.admit([{"finding": "x", "material": "y"}],
               {"input": "y", "checker_reads": ["input", "cards", "hypothesis"]})
check("a checker that has seen the solver's hypothesis refuses to rule",
      ind["admitted"] is None and "checker-not-independent" in kinds(ind), ind)

con = EG.admit([
    {"finding": "lesion", "material": "m1", "key": "lesion", "value": "present"},
    {"finding": "lesion", "material": "m2", "key": "lesion", "value": "absent"},
], {"input": "m1 m2", "quoted": False})
check("contradicting cards are named, and the ruling still rests on fidelity",
      "cards-contradict" in kinds(con) and con["contested"] == ["lesion"], con)

allr = EG.admit([{"finding": "a", "material": "m"}],
                {"input": "m", "quoted": False})
check("admitting the whole pool is named as the everything-gate",
      "admitted-everything" in kinds(allr), allr)
none = EG.admit([], {"input": "x"})
check("an empty pool is named, not treated as a filter",
      "no-cards" in kinds(none) and none["admitted"] == [], none)

GATES = (
    [{"case": i, "policy": "none", "correct": (i % 4 == 0), "admitted": 0, "pool": 3}
     for i in range(8)]
    + [{"case": i, "policy": "all", "correct": (i % 8 == 0), "admitted": 3, "pool": 3}
       for i in range(8)]
    + [{"case": i, "policy": "random", "correct": (i % 6 == 0), "admitted": 2, "pool": 3}
       for i in range(8)]
    + [{"case": i, "policy": "gate", "correct": (i % 2 == 0), "admitted": 2, "pool": 3}
       for i in range(8)])
g = EG.gates(GATES)
check("the four gates are read separately",
      g["rates"]["none"] == 0.25 and g["rates"]["all"] == 0.125
      and g["rates"]["gate"] == 0.5 and g["rates"]["random"] == 0.25, g)
check("a gate that beats the matched random gate shows a selection gain",
      g["selection_term"] == 0.25 and g["budget_term"] == 0.125
      and "selection-gain" in kinds(g), g)
g2 = EG.gates([r for r in GATES if r["policy"] != "random"])
check("a comparison without the matched random arm is refused",
      "gate-not-measured" in kinds(g2), g2)
g3 = EG.gates([{"case": i, "policy": "all", "correct": True, "admitted": 3, "pool": 3}
               for i in range(4)]
              + [{"case": i, "policy": "gate", "correct": True, "admitted": 3, "pool": 3}
                 for i in range(4)]
              + [{"case": i, "policy": "random", "correct": True, "admitted": 3, "pool": 3}
                 for i in range(4)]
              + [{"case": i, "policy": "none", "correct": False, "admitted": 0, "pool": 3}
                 for i in range(4)])
check("a gate that admits everything shows no selection gain",
      g3["selection_term"] == 0.0 and "gain-is-only-budget" in kinds(g3)
      and "admits-almost-everything" in kinds(g3), g3)

fo = EG.first_order([{"admitted": True, "useful": 1},
                     {"admitted": True, "useful": 1},
                     {"admitted": False, "useful": -1},
                     {"admitted": False, "useful": -1}])
check("admission that tracks usefulness predicts a selection gain",
      fo["covariance"] > 0 and "selection-correlates-with-usefulness" in kinds(fo), fo)
fo2 = EG.first_order([{"admitted": True, "useful": -1},
                      {"admitted": False, "useful": 1}])
check("admission that tracks the misleading cards is named",
      fo2["covariance"] < 0 and "selection-anti-correlates" in kinds(fo2), fo2)
fo3 = EG.first_order([{"admitted": True, "useful": 0},
                      {"admitted": False, "useful": 0}])
check("content-agnostic admission has zero covariance",
      fo3["covariance"] == 0 and "selection-independent-of-content" in kinds(fo3), fo3)

adv = EG.advise({"checker_outside_context": True, "cards_verifiable": True,
                 "budget_matched_control": True})
check("a harness that governs evidence is told the tool claim only",
      kinds(adv) == ["tools-are-not-evidence-by-default"], adv)
adv2 = EG.advise({})
check("a harness that judges inside its own context is named",
      "judgement-inside-the-context" in kinds(adv2)
      and "unverifiable-tool-output" in kinds(adv2)
      and "no-budget-matched-control" in kinds(adv2), adv2)

# ---- 2. safety-harness evolution -----------------------------------------
q = SE.qualify({"utility": 0.45, "utility_floor": 0.40, "complete": True})
check("a candidate that holds utility may become a parent",
      q["parent"] is True and q["counterexample"] is False, q)
q2 = SE.qualify({"utility": 0.30, "utility_floor": 0.40})
check("a candidate that breaks the task is a counterexample, never a parent",
      q2["parent"] is False and "utility-lost" in kinds(q2), q2)
q3 = SE.qualify({"utility": 0.50, "utility_floor": 0.40, "errors": ["crash"]})
check("a candidate whose run errored cannot be a parent",
      q3["parent"] is False and "execution-incomplete" in kinds(q3), q3)
q4 = SE.qualify({})
check("a candidate with no records cannot be a parent",
      q4["parent"] is False and "no-records" in kinds(q4), q4)

pr = SE.promote({"attack_succeeded": True, "task_succeeded": True, "complete": True})
check("a stressor that attacks and preserves the task is promoted",
      pr["promoted"] is True and pr["findings"] == [], pr)
pr2 = SE.promote({"attack_succeeded": True, "task_succeeded": False})
check("a stressor that destroys the task is not promoted",
      pr2["promoted"] is False and "utility-destroyed" in kinds(pr2), pr2)
pr3 = SE.promote({"attack_succeeded": False, "task_succeeded": True})
check("a stressor the harness already resists carries no signal",
      pr3["promoted"] is False and "attack-failed" in kinds(pr3), pr3)
pr4 = SE.promote({"attack_succeeded": True, "task_succeeded": True, "errors": 1})
check("a stressor whose evaluation errored proves nothing",
      pr4["promoted"] is False and "incomplete-run" in kinds(pr4), pr4)
pr5 = SE.promote({"attack_succeeded": True, "task_succeeded": True, "duplicate": True})
check("a duplicate stressor is not promoted twice",
      pr5["promoted"] is False and "duplicate-stressor" in kinds(pr5), pr5)

pf = SE.pareto([{"id": "h0", "utility": 0.45, "risk": 0.50},
                {"id": "h1", "utility": 0.46, "risk": 0.03},
                {"id": "h2", "utility": 0.40, "risk": 0.20}])
check("a dominated candidate is off the front",
      pf["front"] == ["h1"] and sorted(pf["dominated"]) == ["h0", "h2"], pf)
pf2 = SE.pareto([{"id": "a", "utility": 0.50, "risk": 0.30},
                 {"id": "b", "utility": 0.40, "risk": 0.05}])
check("two candidates that trade utility for risk both stay on the front",
      sorted(pf2["front"]) == ["a", "b"], pf2)
pf3 = SE.pareto([{"id": "x", "score": 0.9}])
check("a scalarised candidate is named, because a single score hides its axis",
      "scalarised-candidate" in kinds(pf3) and pf3["front"] == [], pf3)
pf4 = SE.pareto([])
check("an empty archive has no frontier",
      pf4["front"] == [] and "no-candidates" in kinds(pf4), pf4)

front = [{"id": "h1", "utility_success": 46, "n": 60, "risk_success": 2, "risk_n": 60},
         {"id": "h2", "utility_success": 27, "n": 60, "risk_success": 28, "risk_n": 60}]
s1 = SE.sample_parent(front, seed=7)
s2 = SE.sample_parent(front, seed=7)
check("the parent sample is deterministic for a seed and comes from the front",
      s1["parent"] == s2["parent"] and s1["parent"] in ("h1", "h2"), s1)
s3 = SE.sample_parent([], seed=1)
check("an empty front has no parent to expand",
      s3["parent"] is None and "empty-front" in kinds(s3), s3)

cs = SE.compare_search([
    {"name": "tree", "budget": 128, "qualified": 33, "best_risk": 0.093,
     "terminal_risk": 0.093},
    {"name": "uniform", "budget": 128, "qualified": 45, "best_risk": 0.191,
     "terminal_risk": 0.191},
    {"name": "linear", "budget": 128, "qualified": 63, "best_risk": 0.280,
     "terminal_risk": 0.441}])
check("a linear chain that ends worse than its own best is named",
      "linear-chain-regresses" in kinds(cs), cs)
check("the configuration with more qualifiers is not the best one",
      "more-candidates-is-not-better" in kinds(cs), cs)
cs2 = SE.compare_search([{"name": "tree", "budget": 128, "qualified": 33,
                          "best_risk": 0.09}])
check("a search without a control is not a result",
      "no-control" in kinds(cs2), cs2)
cs3 = SE.compare_search([{"name": "tree", "budget": 128, "qualified": 33, "best_risk": 0.09},
                         {"name": "uniform", "budget": 64, "qualified": 45,
                          "best_risk": 0.19}])
check("a comparison across different budgets measures the budget",
      "budget-mismatch" in kinds(cs3), cs3)

tr = SE.transfer([{"id": "z1", "results": [
    {"recipient": "h1", "attack": True, "utility": True, "complete": True},
    {"recipient": "h2", "attack": True, "utility": True, "complete": True}]},
    {"id": "z2", "results": [
        {"recipient": "h1", "attack": True, "utility": True, "complete": True},
        {"recipient": "h2", "attack": True, "utility": False, "complete": True}]}])
check("a stressor counts as transferred only on every recipient",
      tr["transferring"] == ["z1"] and tr["source_only"] == ["z2"]
      and "stressor-transfers" in kinds(tr), tr)
tr2 = SE.transfer([{"id": "z3", "results": [
    {"recipient": "r", "attack": True, "utility": False, "complete": True}]}])
check("stressors that work only on their own target are named as overfit",
      "stressor-source-specific" in kinds(tr2), tr2)

sadv = SE.advise({"safety_gain": True, "utility_held": False})
check("safety bought by breaking the task is named",
      "safety-bought-with-utility" in kinds(sadv), sadv)
sadv2 = SE.advise({"utility_held": True, "negative_archive": True,
                   "adaptive_stressors": True, "transfer_checked": True})
check("a search that keeps its constraints reports only the search claim",
      kinds(sadv2) == ["defence-is-a-search-not-a-design"], sadv2)

# ---- 3. paired trials -----------------------------------------------------
PAIRS = ([{"task": "t%d" % i, "control": True, "treatment": True} for i in range(23)]
         + [{"task": "u%d" % i, "control": True, "treatment": False} for i in range(5)]
         + [{"task": "v%d" % i, "control": False, "treatment": True} for i in range(1)]
         + [{"task": "w%d" % i, "control": False, "treatment": False} for i in range(19)])
p = PT.paired(PAIRS)
check("the paired counts and the discordant pairs are read",
      p["n"] == 48 and p["control_solved"] == 28 and p["treatment_solved"] == 24
      and p["control_only"] == 5 and p["treatment_only"] == 1, p)
check("the exact test on the discordant pairs is reported",
      p["p"] == 0.21875 and p["effect"] == round(-4 / 48, 4), p)
check("the interval is the paired score interval, not a difference of intervals",
      p["interval"][0] < p["effect"] < p["interval"][1], p["interval"])
p0 = PT.paired([{"task": "a", "control": True, "treatment": True}])
check("no discordant pair means no evidence either way",
      p0["p"] == 1.0 and "not-significant" in kinds(p0), p0)

RUN1 = [{"task": "t%d" % i, "solved": i % 4 == 0} for i in range(48)]
RUN2 = [{"task": "t%d" % i, "solved": (i % 4 == 0) != (i < 9)} for i in range(48)]
nf = PT.noise_floor(RUN1, RUN2)
check("the A/A calibration measures the flips with no treatment",
      nf["flips"] == 9 and nf["n"] == 48 and nf["flip_rate"] == 0.1875, nf)
check("the noise floor sets a minimum detectable effect",
      nf["minimum_detectable_effect"] == 0.1751
      and "design-cannot-see-small-effects" in kinds(nf), nf)
nf2 = PT.noise_floor([{"task": "a", "solved": True}], [{"task": "b", "solved": True}])
check("no shared task means no calibration",
      nf2["flips"] is None and "no-aa-calibration" in kinds(nf2), nf2)

CL = PT.claim(PAIRS, floor=nf)
check("an effect smaller than the noise floor is named as within noise",
      "within-noise" in kinds(CL) and CL["minimum_detectable_effect"] == 0.1751, CL)
check("a paired claim that does not clear the floor is not significant",
      "not-significant" in kinds(CL), CL)
STRATA = [{"name": "first", "rows": [{"task": "t%d" % i, "control": i < 25,
                                      "treatment": i < 29} for i in range(48)]},
          {"name": "extension", "rows": [{"task": "e%d" % i, "control": i < 23,
                                          "treatment": i < 18} for i in range(50)]}]
CL2 = PT.claim(PAIRS, strata=STRATA, floor=nf)
check("a hypothesis whose sign reverses on the extension is named",
      "sign-does-not-replicate" in kinds(CL2), CL2)
CL3 = PT.claim(PAIRS)
check("a claim without an A/A floor has no scale",
      "noise-floor-missing" in kinds(CL3), CL3)

MECH = PT.mechanism({"opportunities": 45, "delivered": 21, "agent_wrote": 2,
                     "extra_tokens": 2000, "compactions_before": 23,
                     "compactions_after": 45})
check("a mechanism delivered at half the opportunities is named",
      MECH["delivery"] == round(21 / 45, 4) and "delivery-too-low" in kinds(MECH), MECH)
check("a mechanism the agent almost never uses is named",
      MECH["adherence"] == round(2 / 45, 4) and "adherence-too-low" in kinds(MECH), MECH)
check("the context cost of the mechanism is priced",
      "context-cost-unpriced" in kinds(MECH), MECH)
MECH2 = PT.mechanism({"opportunities": 10, "delivered": 10, "agent_wrote": 5})
check("a mechanism that always fires costs nothing, and is not named",
      kinds(MECH2) == [], MECH2)

FU = PT.funnel([{"name": "tasks", "in": 129, "out": 37},
                {"name": "deps", "in": 37, "out": 68},
                {"name": "wheels", "in": 68, "out": 105}])
check("a stage that drops tasks is named with its count",
      "stage-drops" in kinds(FU) and FU["valid"] == 105, FU)
FU2 = PT.funnel([])
check("a claim over an unreported funnel is refused",
      "validity-funnel-missing" in kinds(FU2), FU2)

BU = PT.budget([{"p": 0.019}, {"p": 0.029}, {"p": 0.0088}]
               + [{"p": 0.5} for _ in range(20)])
check("post-hoc tests are counted and corrected over every one of them",
      BU["post_hoc"] == 23 and "post-hoc-not-corrected" in kinds(BU), BU)
BU2 = PT.budget([{"p": 0.001}, {"p": 0.4}])
check("a small p that survives the bound over two tests is named",
      "post-hoc-survives-correction" in kinds(BU2), BU2)

padv = PT.advise({})
check("an unpaired single-run claim is named (three ways)",
      {"unpaired-comparison", "no-noise-floor", "single-run-claim"}
      <= set(kinds(padv)), padv)
padv2 = PT.advise({"paired": True, "aa_calibration": True, "runs_per_task": 1,
                   "preregistered": True})
check("a paired, calibrated, pre-registered claim reports only the null rule",
      kinds(padv2) == ["null-is-a-result"], padv2)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
