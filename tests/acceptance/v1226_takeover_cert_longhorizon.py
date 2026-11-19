#!/usr/bin/env python3
"""v1226 — takeover evaluation, anytime certificates, long-horizon delivery (round 157).

Sources:
  * arXiv:2611.07307 — the delivery triple, the requirement atom, the RQ1–RQ3
    diagnostics, the post-state score and the omission case.
  * arXiv:2611.21241 — the time-uniform PAC-Bayes radius, the finite-grid price,
    the structured prior, the margin law, water-filling and selection optimism.
  * arXiv:2611.05620 — pass@1 under all-or-nothing plans, the regrade protocol,
    the reliability gap, the held-out split and both grading errors.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1226_takeover_cert_longhorizon.py
"""
import math
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1226-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import takeover_eval as TE  # noqa: E402
from longrun.harness.checks import anytime_cert as AC  # noqa: E402
from longrun.harness.checks import longhorizon_eval as LH  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. project takeover (arXiv:2611.07307) ---------------------------
A = TE.atom({"id": "r1", "attributes": {}, "lifecycle": "active", "scope": "app",
             "ambiguity": [], "implementation_evidence": []})
check("a full atom is valid", A["verdict"] == "valid-atom")
AB = TE.atom({"id": "r2", "attributes": {}})
check("a missing component is named",
      set(AB["missing"]) == {"lifecycle", "scope", "ambiguity",
                             "implementation_evidence"})
check("an atom without an id is refused", TE.atom({})["verdict"] == "missing-id")
U = TE.update({"holes": 8, "m2.5": "spec", "layout": "front"},
              {"set": {"layout": "back"}})
check("the update keeps an untouched constraint", "m2.5" in U["post"])
check("no constraint is omitted", U["verdict"] == "complete-update")
UO = TE.update({"holes": 8, "m2.5": "spec", "layout": "front"},
               {"state": {"layout": "back"}})
check("a rewrite that drops constraints is caught", UO["omitted"] == ["holes", "m2.5"])
check("the omission verdict is named", UO["verdict"] == "omitted-constraints")
UW = TE.update({"a": 1, "b": 2}, {"withdraw": ["b"]})
check("a withdrawn constraint is excluded", UW["omitted"] == [])
D = TE.delivery([
    {"build": True, "target": True, "regression": True},
    {"build": True, "target": False, "regression": True},
])
check("complete delivery needs all three checks", close(D["delivery_rate"], 0.5))
check("build passes are counted", close(D["checks"]["build"], 1.0))
check("target passes are counted", close(D["checks"]["target"], 0.5))
check("an empty target set is refused", TE.delivery([])["verdict"] == "no-targets")
R1 = TE.rq1({"requirements": ["r1", "r2"], "evidence": ["e1", "e2"]},
            {"requirements": ["r1", "r3"], "evidence": ["e1"]})
check("requirement precision is one of two", close(R1["requirements"]["precision"], 0.5))
check("requirement recall is one of two", close(R1["requirements"]["recall"], 0.5))
check("requirement F1 is one half", close(R1["requirements"]["f1"], 0.5))
check("evidence recall is one", close(R1["evidence"]["recall"], 1.0))
check("evidence F1 is two thirds", close(R1["evidence"]["f1"], 2 / 3))
R2 = TE.rq2({"requirements": ["a", "b"]}, {"requirements": ["a", "b", "c", "d"]},
            [{"score": 1.0}, {"score": 0.5}])
check("coverage is matched over gold", close(R2["coverage"], 0.5))
check("attribute score averages matched items", close(R2["attribute_score"], 0.75))
DEC = TE.decision([
    {"gold": "ACT", "pred": "ACT"},
    {"gold": "ACT", "pred": "CLARIFY"},
    {"gold": "CLARIFY", "pred": "CLARIFY"},
    {"gold": "CLARIFY", "pred": "ACT"},
])
check("decision accuracy is one half", close(DEC["accuracy"], 0.5))
check("ACT recall is one half", close(DEC["recall_act"], 0.5))
check("CLARIFY recall is one half", close(DEC["recall_clarify"], 0.5))
check("balanced accuracy averages the recalls",
      close(DEC["balanced_accuracy"], 0.5))
check("the always-ACT baseline is reported", close(DEC["always_act"], 0.5))
PS = TE.poststate({"pred": ["a", "b"], "gold": ["a", "b"],
                   "matched": [{"score": 1.0}], "exact": False})
check("the post-state score gives partial credit", close(PS["score"], 0.5))
check("a partial state is not exact", PS["verdict"] == "partial")
check("an exact state is named",
      TE.poststate({"pred": ["a"], "gold": ["a"], "matched": [{"score": 1.0}],
                    "exact": True})["verdict"] == "exact")
CL = TE.clarify({"issues_pred": ["i1", "i2"], "issues_gold": ["i1"],
                 "questions": [{"valid": True}, {"valid": False}]})
check("blocking-issue F1 is two thirds", close(CL["f1"], 2 / 3))
check("question validity is one half", close(CL["question_validity"], 0.5))
check("the takeover audit names its misreadings",
      set(kinds(TE.audit_record({"history_filter_assumed_better": True,
                                 "target_state_equals_implementation": True})))
      == {"history-filter-assumed-better", "target-state-equals-implementation"})
check("the takeover advice lists six habits", len(TE.advise({})["findings"]) == 6)

# ---- 2. anytime certificates (arXiv:2611.21241) -----------------------
check("identical means have zero divergence", close(AC.kl(0.3, 0.3), 0.0))
check("a zero empirical risk inverts to 1-exp(-eps)",
      close(AC.kl_inv(0.0, 0.1), 1 - math.exp(-0.1), 1e-9))
C16 = AC.grid({"n": 16, "recipes": 3, "delta": 0.05, "risk": 0.0})
C256 = AC.grid({"n": 256, "recipes": 3, "delta": 0.05, "risk": 0.0})
C1024 = AC.grid({"n": 1024, "recipes": 3, "delta": 0.05, "risk": 0.0})
check("the small audit is loose", 0.4 < C16["zero_error_upper"] < 0.6)
check("the medium audit tightens", 0.05 < C256["zero_error_upper"] < 0.10)
check("the large audit tightens further", 0.01 < C1024["zero_error_upper"] < 0.03)
check("the radius shrinks with n", C16["epsilon"] > C256["epsilon"] > C1024["epsilon"])
check("a bigger grid pays more", AC.grid({"n": 256, "recipes": 24,
                                          "delta": 0.05})["epsilon"]
      > C256["epsilon"])
CERT = AC.certificate({"n": 659, "kl_qp": 0.0, "delta": 0.05, "risk": 0.039})
check("a real audit is above its empirical risk", CERT["upper"] > 0.039)
check("the certificate is a radius plus inversion", CERT["verdict"] == "certified")
check("zero calibration samples are refused",
      AC.certificate({"n": 0})["verdict"] == "insufficient-input")
ST = AC.structured({"budget": 4, "verifiers": 9})
check("the structured prior charges both axes",
      close(ST["charge"], 2 * math.log(5) + 2 * math.log(10)))
M1 = AC.margin({"p_correct": 0.6, "p_wrong": 0.3, "b": 1, "m": 2})
check("a correct mode has a decaying error bound",
      close(M1["error_bound"], math.exp(-1 * 0.09 / 2)))
check("the forward regime is named", M1["verdict"] == "mode-correct")
M2 = AC.margin({"p_correct": 0.3, "p_wrong": 0.6, "b": 1, "m": 2})
check("a wrong mode is amplified", M2["verdict"] == "wrong-mode-amplified")
ALLOC = AC.allocate({"budget": 3, "items": [
    {"id": "contestable", "A": 1.0, "s": 1.0, "margin": 0.2},
    {"id": "settled", "A": 1.0, "s": 1.0, "margin": -0.2},
]})
check("the contestable example gets the budget",
      ALLOC["allocation"]["contestable"] > 1.0)
check("the settled example keeps the minimum",
      close(ALLOC["allocation"]["settled"], 1.0))
check("the mean meets the budget", close(ALLOC["mean"], 3.0, 1e-6))
check("a budget of one per item is the floor",
      AC.allocate({"budget": 1, "items": [{"id": "a", "A": 1, "s": 1,
                                           "margin": 0.1}]})["verdict"]
      == "minimum-budget")
OPT = AC.optimism({"splits": 1000, "below_empirical": 225,
                   "certificate_covers": 1000})
check("the naive interval is optimistic", OPT["verdict"] == "naive-optimistic")
check("the certificate covers every split", close(OPT["certificate_coverage"], 1.0))
check("the optimism rate matches the source", close(OPT["below_rate"], 0.225))
check("the certificate audit names its misreadings",
      set(kinds(AC.audit_record({"validation_curve_is_certificate": True,
                                 "mode_is_correctness": True})))
      == {"validation-curve-is-certificate", "mode-is-correctness"})
check("the certificate advice lists six habits", len(AC.advise({})["findings"]) == 6)

# ---- 3. long-horizon delivery (arXiv:2611.05620) ----------------------
P = LH.plan({"plans": [True] * 5})
check("all plans passing is a complete build", P["pass_at_1"] == 1)
check("the plan rate is one", close(P["plan_rate"], 1.0))
P2 = LH.plan({"plans": [True, True, False, True, True]})
check("one failed plan fails the build", P2["pass_at_1"] == 0)
check("the plan rate still separates builds", close(P2["plan_rate"], 0.8))
check("a product that never started fails all plans",
      LH.plan({"plans": [True], "started": False})["pass_at_1"] == 0)
check("a first-grade pass is final",
      LH.grade({"first": "pass"})["verdict"] == "pass-first-grade")
check("three failing grades fail the plan",
      LH.grade({"first": "fail", "regrades": ["fail", "fail", "pass"]})["verdict"]
      == "fail")
check("three passing grades rescue the plan",
      LH.grade({"first": "fail", "regrades": ["pass", "pass", "pass"]})["verdict"]
      == "pass")
check("a split grade stays pending",
      LH.grade({"first": "fail", "regrades": ["fail", "pass"]})["verdict"]
      == "pending")
check("missing evidence forces a regrade",
      LH.grade({"first": "fail", "evidence_ok": False})["verdict"]
      == "regrade-required")
G = LH.gap({"plan_rate": 0.937, "plans": 26, "pass_at_1": 0.485})
check("the reliability gap is in points", close(G["gap_points"], 45.2, 1e-6))
check("a high plan rate with low delivery is the gap",
      G["verdict"] == "reliability-gap")
check("independent completion is the plan rate to the plans",
      close(G["independent_complete"], 0.937 ** 26))
H = LH.horizon({"products": 17, "requests": 241, "plans": 544,
                "compound_share": 0.85})
check("the benchmark is long-horizon", H["verdict"] == "long-horizon")
check("requests per product is reported", close(H["requests_per_product"],
                                                241 / 17, 1e-9))
check("a short benchmark is named",
      LH.horizon({"products": 10, "requests": 20, "plans": 20})["verdict"]
      == "short-horizon")
SP = LH.split({"public_pass1": 0.647, "heldout_pass1": 0.55, "spearman": 0.99})
check("the public subset is harder", close(SP["delta_points"], 9.7, 1e-6))
check("the split preserves the ranking", SP["verdict"] == "faithful-proxy")
check("a diverging ranking is named",
      LH.split({"public_pass1": 0.6, "heldout_pass1": 0.4,
                "spearman": 0.5})["verdict"] == "ranking-diverges")
GQ = LH.grade_quality({"false_fail": 0.002, "false_pass": 0.008,
                       "planted_caught": 34, "planted_total": 34})
check("both error directions are within the protocol", GQ["verdict"] == "reliable")
check("a high wrong-pass rate is unreliable",
      LH.grade_quality({"false_fail": 0.002, "false_pass": 0.02,
                        "planted_caught": 34, "planted_total": 34})["verdict"]
      == "unreliable")
check("a missed planted bug is unreliable",
      LH.grade_quality({"false_fail": 0.001, "false_pass": 0.005,
                        "planted_caught": 33, "planted_total": 34})["verdict"]
      == "unreliable")
check("the long-horizon audit names its misreadings",
      set(kinds(LH.audit_record({"plan_rate_as_pass_at_1": True,
                                 "feedback_between_requests": True})))
      == {"plan-rate-as-pass-at-1", "feedback-between-requests"})
check("the long-horizon advice lists six habits",
      len(LH.advise({})["findings"]) == 6)

# ---- verdict ----------------------------------------------------------
TOTAL = len(RESULTS)
PASSED = sum(RESULTS)
print("\n%d/%d checks passed" % (PASSED, TOTAL))
sys.exit(0 if PASSED == TOTAL else 1)
