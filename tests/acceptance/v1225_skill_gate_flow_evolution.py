#!/usr/bin/env python3
"""v1225 — skill gate, skill population flow, skill evolution (round 156).

Sources:
  * arXiv:2608.05810 — the Cold/Warm/Hot tiers, the three critics, the
    capability–contamination curve, marginal-gain selection and the irreversibility
    of post-hoc rollback.
  * arXiv:2611.20584 — the closed-credit ledger, the zero-sum projection gate, the
    response regimes, the acoustic speeds, the credit shock and the stall diagnosis.
  * arXiv:2611.03238 — the Skill/Reference schema, source-grounded evidence, the
    three-cause diagnosis, history-free validation and regression-certified merges.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1225_skill_gate_flow_evolution.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1225-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import skill_gate as SG  # noqa: E402
from longrun.harness.checks import skill_flow as SF  # noqa: E402
from longrun.harness.checks import skill_evolution as SE  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. pre-commit skill gate (arXiv:2608.05810) ----------------------
T = SG.tiers()
check("the hierarchy has three tiers", T["tiers"] == ["cold", "warm", "hot"])
check("a new skill is cold by default", T["default"] == "cold")
check("Gate 1 conjoins three critics",
      T["gates"]["cold_to_warm"] == ["schema", "replay", "semantic"])
check("Gate 2 is marginal gain", T["gates"]["warm_to_hot"] == ["marginal-gain"])
C = SG.critic({"schema_ok": True, "replay_delta": 0.02, "semantic_ok": True})
check("a skill clearing all three is promoted", C["verdict"] == "promote-warm")
check("the replay need only match, not improve", C["checks"]["replay"] is True)
CB = SG.critic({"schema_ok": True, "replay_delta": 0.02, "semantic_ok": False})
check("a semantic failure rejects", CB["verdict"] == "reject")
check("the failing critic is named", CB["failed"] == ["semantic"])
check("a negative replay delta rejects",
      SG.critic({"schema_ok": True, "replay_delta": -0.01,
                 "semantic_ok": True})["failed"] == ["replay"])
check("a missing delta is refused", SG.critic({})["verdict"] == "insufficient-input")
G = SG.gain({"pool_rate": 0.60, "injected_rate": 0.48})
check("the injection gain is a difference", close(G["gain"], -0.12))
check("a negative singleton gain is individually harmful",
      G["verdict"] == "individually-harmful")
check("two safe skills with a harmful pair are combinatorial",
      SG.taxonomy({"singletons": [0.01, 0.02], "pair_gain": -0.03})["level"]
      == "combinatorial")
check("a negative singleton is individual contamination",
      SG.taxonomy({"singletons": [-0.1, 0.02]})["level"] == "individual")
check("a compatible pair is not contamination",
      SG.taxonomy({"singletons": [0.01], "pair_gain": 0.02})["level"] == "none")
CURVE = SG.curve([
    {"round": "R1", "pool": 35, "rate": 48},
    {"round": "R2", "pool": 68, "rate": 60},
    {"round": "R3", "pool": 105, "rate": 62},
    {"round": "R4", "pool": 141, "rate": 52},
    {"round": "R5", "pool": 179, "rate": 50},
])
check("the peak is 62 at pool 105", CURVE["peak"]["pool"] == 105)
check("the ungated curve falls after its peak", CURVE["verdict"] == "phase-transition")
check("the peak-to-R5 drop is 12 points", close(CURVE["drop"], 12.0))
check("the curve rises before the peak", CURVE["monotone_before_peak"] is True)
GATED = SG.curve([
    {"round": "R1", "pool": 5, "rate": 52},
    {"round": "R2", "pool": 15, "rate": 58},
    {"round": "R3", "pool": 25, "rate": 62},
    {"round": "R4", "pool": 30, "rate": 68},
    {"round": "R5", "pool": 37, "rate": 72},
])
check("the gated curve is monotone", GATED["verdict"] == "monotone")
check("the gated pool is 5x smaller", 179 / 37 > 4.0)
WARM = {"schema_ok": True, "replay_delta": 0.0, "semantic_ok": True}
SEL = SG.select([
    dict(WARM, id="A", gain=5.0),
    dict(WARM, id="B", gain=4.0, interactions={"A": -7.0}),
    dict(WARM, id="C", gain=3.0),
    dict(WARM, id="D", gain=-1.0),
])
check("greedy takes the best singleton first", SEL["hot"][0] == "A")
check("a candidate that conflicts with the set is rejected", "B" not in SEL["hot"])
check("a positive addition is taken", "C" in SEL["hot"])
check("a negative candidate is rejected", "D" in SEL["rejected"])
check("the joint gain is the sum of kept gains", close(SEL["gain"], 8.0))
check("an empty candidate list is refused", SG.select([])["verdict"] == "no-candidates")
# Gate 1 is a prerequisite for Gate 2: gain alone cannot admit a candidate.
NOGATE = SG.select([{"id": "A", "gain": 100.0}])
check("a candidate with no Gate-1 evidence is never promoted",
      NOGATE["hot"] == [] and NOGATE["unadmitted"] == ["A"], NOGATE)
BADGATE = SG.select([{"id": "A", "gain": 100.0, "schema_ok": True,
                      "replay_delta": -1.0, "semantic_ok": True}])
check("a candidate that failed a critic is never promoted on gain",
      BADGATE["hot"] == [] and BADGATE["unadmitted"] == ["A"], BADGATE)
check("a committee of no eligible candidates is not a promotion",
      NOGATE["verdict"] == "no-promotion")
# Interaction convention: interactions[id] is THIS candidate's extra gain when
# `id` is already Hot, so the total must equal the greedy objective.
DIR = SG.select([dict(WARM, id="X", gain=2.0),
                 dict(WARM, id="Y", gain=2.0, interactions={"X": 1.0})])
check("a directed interaction is counted once, in the direction that occurred",
      DIR["hot"] == ["X", "Y"] and close(DIR["gain"], 5.0), DIR)
REV = SG.select([dict(WARM, id="A", gain=2.0, interactions={"B": 9.0}),
                 dict(WARM, id="B", gain=2.0)])
check("an interaction toward a skill that joined later is not counted",
      REV["hot"] == ["A", "B"] and close(REV["gain"], 4.0), REV)
SYM = SG.select([dict(WARM, id="A", gain=2.0, interactions={"B": 1.0}),
                 dict(WARM, id="B", gain=2.0, interactions={"A": 1.0})])
check("a symmetric pair is not double-counted",
      close(SYM["gain"], 5.0) and SYM["hot"] == ["A", "B"], SYM)
IR = SG.irreversibility({"peak": 62.3, "after": 50.0, "source_recovery": 1.7,
                         "lineage_recovery": 6.7})
check("the collapse is 12.3 points", close(IR["drop"], 12.3))
check("source removal recovers only 13.8%", close(IR["source_share"], 1.7 / 12.3))
check("the residual is 10.6 points", close(IR["residual_after_source"], 10.6))
check("the contamination is irreversible", IR["verdict"] == "irreversible")
RB = SG.rollback({"source": "git", "derived": {"git": ["merge", "rebase"],
                                               "merge": ["merge-fix"]}})
check("descendants are traced through two hops",
      RB["descendants"] == ["merge", "merge-fix", "rebase"])
check("the lineage contains the source", RB["lineage"][0] == "git")
check("a leaf has no descendants",
      SG.rollback({"source": "x"})["verdict"] == "no-descendants")
check("the gate audit names its misreadings",
      set(kinds(SG.audit_record({"removal_is_cleanup": True,
                                 "one_critic_is_enough": True})))
      == {"removal-is-cleanup", "one-critic-is-enough"})
check("the gate advice lists six habits", len(SG.advise({})["findings"]) == 6)

# ---- 2. population flow (arXiv:2611.20584) ----------------------------
L = SF.ledger([{"kind": "mint", "amount": 100},
               {"kind": "transfer", "amount": 30},
               {"kind": "transfer", "amount": 20}])
check("a closed ledger keeps its total", close(L["total"], 100.0))
check("transfers do not change the total", L["verdict"] == "closed")
LO = SF.ledger([{"kind": "mint", "amount": 100},
                {"kind": "destroy", "amount": 15}])
check("destroying credit opens the ledger", LO["verdict"] == "open")
check("the destruction is a named violation",
      LO["violations"][0]["kind"] == "credit-destroyed")
check("two mints open the ledger",
      SF.ledger([{"kind": "mint", "amount": 1},
                 {"kind": "mint", "amount": 1}])["verdict"] == "open")
PR = SF.project([{"id": "a", "d": 3}, {"id": "b", "d": 4},
                 {"id": "c", "d": 5}], reserve=10)
check("the reserve takes the first two", len(PR["accepted"]) == 2)
check("the third is dropped", PR["dropped"][0]["id"] == "c")
check("the centroid does not move", close(PR["centroid_shift"], 0.0))
check("the projection conserves", PR["verdict"] == "conserved")
RW = SF.regime([0, 0, 1, 2, 3, 4, 5])
check("a linear radius is a wave", RW["verdict"] == "wave-like")
check("the wave speed is one instance per round", close(RW["slope"], 1.0))
check("the wave fit is clean", close(RW["r2"], 1.0))
check("a one-round full response is mean-field",
      SF.regime([0, 48, 48, 48])["verdict"] == "mean-field")
check("a decaying response is dissipative",
      SF.regime([0, 10, 7, 5, 4, 3, 2])["verdict"] == "dissipative")
check("a short series is refused", SF.regime([0, 1])["verdict"] == "too-few-points")
SO = SF.sound({"kappa_a": 0.5, "rho": 4, "kappa_v": 0.25, "g": 16})
check("the credit branch runs at sqrt(2*kappa*rho)", close(SO["c_rho"], 2.0))
check("the equation of state is quadratic", close(SO["pressure"], 8.0))
check("the displacement branch is reported", close(SO["c_v"], 2.8284271247, 1e-6))
check("a positive speed is hyperbolic", SO["verdict"] == "hyperbolic")
SH = SF.shock({"gradient": 10, "c_rho": 2, "rho": 4})
check("compression beyond the flux is a shock", SH["verdict"] == "credit-shock")
check("the margin is negative when shocked", close(SH["margin"], -2.0))
check("a gradient under the flux is stable",
      SF.shock({"gradient": 5, "c_rho": 2, "rho": 4})["verdict"] == "stable")
IN = SF.instruments({"times": [1, 2, 4, 8], "taus": [1, 2, 4, 8],
                     "chi4": 2.0, "beta": -0.58})
check("aging grows linearly in log time", close(IN["aging_exponent"], 1.0))
check("positive aging is not stationary", IN["verdict"] == "aging")
check("flat waiting times are stationary",
      SF.instruments({"times": [1, 2, 4], "taus": [1, 1, 1]})["verdict"]
      == "stationary")
D1 = SF.diagnose({"aging": 0.3, "chi4": 2.0})
check("freezing is diagnosed with aging and chi4", D1["cause"] == "structural-freezing")
check("freezing is treated by annealing", D1["prescription"] == "anneal")
D2 = SF.diagnose({"aging": 0, "gate_info": 1, "individual_info": 0})
check("information exhaustion is separated", D2["cause"] == "information-exhaustion")
check("information exhaustion refreshes validation",
      D2["prescription"] == "refresh-validation")
D3 = SF.diagnose({"aging": 0, "gate_info": 0, "individual_info": 0,
                  "accept_rate": 0})
check("proposal exhaustion is separated", D3["cause"] == "proposal-exhaustion")
check("proposal exhaustion enriches the reflector",
      D3["prescription"] == "enrich-reflector")
check("the flow audit names its misreadings",
      set(kinds(SF.audit_record({"legislation_without_projection": True,
                                 "constants_are_universal": True})))
      == {"legislation-without-projection", "constants-are-universal"})
check("the flow advice lists six habits", len(SF.advise({})["findings"]) == 6)

# ---- 3. skill evolution (arXiv:2611.03238) ----------------------------
SK = SE.entry({"kind": "skill", "name": "plot3d", "description": "plot",
               "applicability": "KAlgebra", "preconditions": "graph tab",
               "body": "type the expression"})
check("a complete Skill is valid", SK["verdict"] == "valid-entry")
check("a Skill's fields are the paper's five",
      SK["fields"] == ["name", "description", "applicability", "preconditions",
                       "body"])
CHECK_SKILL = SE.entry({"kind": "skill", "name": "plot3d"})
check("a Skill without a body is incomplete",
      CHECK_SKILL["missing"] == ["description", "applicability", "preconditions",
                                 "body"])
check("a Reference has three fields",
      SE.entry({"kind": "reference", "name": "power",
                "purpose": "power function", "content": "power(a,b)"})["verdict"]
      == "valid-entry")
check("an unknown kind is refused", SE.entry({"kind": "tool"})["verdict"]
      == "unknown-kind")
EV = SE.evidence({"entries": [
    {"name": "plot3d", "source_locations": ["manual p.12"]},
    {"name": "power", "source_locations": []},
]})
check("an ungrounded entry is named", EV["untraceable"] == ["power"])
check("the library is untraceable", EV["verdict"] == "untraceable")
check("all grounded entries pass",
      SE.evidence({"entries": [{"name": "x", "source_locations": ["p1"]}]})["verdict"]
      == "traceable")
check("grounding failure produces no candidate",
      SE.diagnose({"cause": "grounding_failure"})["verdict"] == "no-candidate")
check("a revision must target a routed entry",
      SE.diagnose({"cause": "modify_existing", "target": "t1",
                   "routed": ["t2"]})["verdict"] == "target-not-routed")
check("a routed revision is a candidate",
      SE.diagnose({"cause": "modify_existing", "target": "t1",
                   "routed": ["t1"]})["verdict"] == "revision-candidate")
check("an addition needs source support",
      SE.diagnose({"cause": "add_new_knowledge"})["verdict"] == "no-source-support")
check("a supported addition is a candidate",
      SE.diagnose({"cause": "add_new_knowledge", "source_support": True})["verdict"]
      == "addition-candidate")
check("an unknown cause is refused", SE.diagnose({"cause": "vibes"})["verdict"]
      == "unknown-cause")
check("grounding cannot emit a candidate",
      SE.candidate({"cause": "grounding_failure", "kind": "skill"})["verdict"]
      == "no-candidate")
check("a revision can emit a candidate",
      SE.candidate({"cause": "modify_existing", "kind": "skill"})["verdict"]
      == "candidate-ready")
VA = SE.validate({"fresh_session": True, "history_empty": True,
                  "evaluator_decides": True, "one_candidate": True})
check("a history-free single-candidate validation passes", VA["verdict"] == "accepted")
VB = SE.validate({"fresh_session": True, "history_empty": False,
                  "evaluator_decides": True, "one_candidate": True})
check("a validation carrying history is rejected", VB["failed"] == ["empty-history"])
check("two candidates at once are rejected",
      SE.validate({"fresh_session": True, "history_empty": True,
                   "evaluator_decides": True, "one_candidate": False})["failed"]
      == ["one-candidate"])
check("a single candidate is adopted without replay",
      SE.consolidate({"candidates": [{"id": "a"}]})["verdict"]
      == "single-candidate")
check("a merge without regression is uncertified",
      SE.consolidate({"candidates": [{"id": "a"}, {"id": "b"}]})["verdict"]
      == "uncertified")
check("an all-pass replay certifies the merge",
      SE.consolidate({"candidates": [{"id": "a"}, {"id": "b"}],
                      "replays": [{"passed": True}, {"passed": True}]})["verdict"]
      == "certified")
check("a content failure forces a revision",
      SE.consolidate({"candidates": [{"id": "a"}, {"id": "b"}],
                      "replays": [{"passed": False, "cause": "content"}]})["verdict"]
      == "revise")
check("a grounding-only failure may be kept",
      SE.consolidate({"candidates": [{"id": "a"}, {"id": "b"}],
                      "replays": [{"passed": False, "cause": "grounding"}],
                      "keep": True})["verdict"] == "certified-on-grounding")
B = SE.budget({"tasks": 108, "group": 4})
check("the execution bound is |E|(2M+M)", B["execution_bound"] == 972)
check("the regression bound is (1+M)|Q|", B["regression_bound"] == 16)
check("the defaults are 3/3/3",
      B["explore"] == 3 and B["submit"] == 3 and B["consolidation"] == 3)
check("the evolution audit names its misreadings",
      set(kinds(SE.audit_record({"merge_skips_regression": True,
                                 "history_leaks_into_validation": True})))
      == {"merge-skips-regression", "history-leaks-into-validation"})
check("the evolution advice lists six habits", len(SE.advise({})["findings"]) == 6)

# ---- verdict ----------------------------------------------------------
TOTAL = len(RESULTS)
PASSED = sum(RESULTS)
print("\n%d/%d checks passed" % (PASSED, TOTAL))
sys.exit(0 if PASSED == TOTAL else 1)
