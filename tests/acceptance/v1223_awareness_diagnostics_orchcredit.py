#!/usr/bin/env python3
"""v1223 — harness awareness, agent diagnostics, orchestration credit (round 154).

Sources:
  * arXiv:2611.05391 — the bounded verified snapshot, the frozen route cost, regret,
    host revalidation, the A/B/C ablation and the Wilson intervals.
  * arXiv:2611.04507 — the 45-type taxonomy, finding admissibility, the scope and
    severity arithmetic, Signal grouping, run updates and occurrence matching.
  * arXiv:2611.07495 — the exact interaction expansion, the visit-count remainder,
    the certified update, leaps, complementarity and the controlled-task gains.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1223_awareness_diagnostics_orchcredit.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1223-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import awareness as AW            # noqa: E402
from longrun.harness import diagnostics as DG          # noqa: E402
from longrun.harness import orchestration_credit as OC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. harness awareness (arXiv:2611.05391) --------------------------
OBS = [
    {"route": "alpha", "ok": True, "ms": 100},
    {"route": "beta", "ok": False, "ms": 100},
    {"route": "alpha", "ok": True, "ms": 100},
    {"route": "beta", "ok": False, "ms": 100},
    {"route": "alpha", "ok": False, "ms": 100},
    {"route": "beta", "ok": False, "ms": 100},
    {"route": "alpha", "ok": True, "ms": 100},
]
R = AW.reduce(OBS)
check("the reducer emits one row per route", len(R["rows"]) == 2)
check("the reducer records the window", R["rows"][0]["n"] == 4)
check("successes are counted", R["rows"][0]["s"] == 3)
check("the EWMA is the rolling mean here", close(R["rows"][0]["latency_ewma"], 100.0))
check("a healthy route is closed", R["rows"][0]["circuit"] == "CLOSED")
check("three consecutive failures open the circuit",
      R["rows"][1]["circuit"] == "OPEN")
check("the open route keeps its failure count", R["rows"][1]["consec_fail"] == 3)
check("the last error is recorded", R["rows"][1]["last_error"] == "probe-failed")
check("no observations is a verdict", AW.reduce([])["verdict"] == "no-observations")
CA = AW.cost(R["rows"][0])
CB = AW.cost(R["rows"][1])
check("cost adds the failure penalty", close(CA["cost_ms"], 100 + 10000 * 0.25))
check("an open circuit adds its own penalty",
      close(CB["cost_ms"], 100 + 10000 * 1.0 + 10000))
check("an empty window is priced at one half",
      close(AW.cost({"route": "x", "n": 0, "s": 0,
                     "latency_ewma": 10})["cost_ms"], 5010.0))
BEST = AW.best(R["rows"])
check("the healthy route is the observable best", BEST["best"] == ["alpha"])
check("best reports the minimum cost", close(BEST["cost_ms"], 2600.0))
check("choosing the best costs no regret",
      close(AW.regret(R["rows"], "alpha")["regret_ms"], 0.0))
check("choosing the open route is excess cost",
      close(AW.regret(R["rows"], "beta")["regret_ms"], 17500.0))
check("waiting carries the deferral and the miss",
      close(AW.regret(R["rows"], "wait")["regret_ms"], 10500 - 2600))
check("an unknown route is refused",
      AW.regret(R["rows"], "gamma")["verdict"] == "unknown-route")
ROWS = [
    {"route": "alpha", "n": 6, "s": 6, "latency_ewma": 100, "circuit": "CLOSED",
     "observed_at": 9000, "secret": "leak"},
    {"route": "beta", "n": 4, "s": 1, "latency_ewma": 100, "circuit": "DEGRADED",
     "observed_at": 1000},
]
S = AW.snapshot(ROWS, now=10000, max_age_ms=2000)
check("a fresh row survives the bound", len(S["rows"]) == 1)
check("the stale row is dropped with a reason", S["dropped"][0]["reason"] == "stale")
check("the snapshot is redacted", S["redacted"] == 1 and "secret" not in S["rows"][0])
check("the snapshot is dispatchable", S["dispatchable"] is True)
check("the freshness bound travels with it", close(S["freshness_bound_ms"], 2000.0))
check("an all-stale snapshot is refused",
      AW.snapshot([{"route": "a", "observed_at": 0}], now=10000,
                  max_age_ms=100)["verdict"] == "stale-snapshot")
check("a neutral envelope is not verified state",
      AW.snapshot(ROWS[:1], verified=False)["verdict"] == "neutral-envelope")
check("the projection is bounded",
      AW.snapshot(ROWS + [{"route": "c"}, {"route": "d"}], max_rows=2)["omitted"] == 2)
D = AW.choose(S, "alpha")
check("a verified choice is dispatched", D["dispatched"] is True)
check("the host keeps dispatch", D["host_dispatches"] is True)
check("the model cannot edit state", D["model_may_edit_state"] is False)
check("a stale snapshot cannot dispatch",
      AW.choose(AW.snapshot([], now=1), "alpha")["reason"] == "snapshot-not-verified")
check("an ineligible action is refused",
      AW.choose(S, "gamma")["reason"] == "ineligible-action")
check("revalidation can refuse open circuits",
      AW.choose(S, "alpha", current=[{"route": "alpha", "circuit": "OPEN"}])["reason"]
      == "revalidation-refused")
check("wait is always eligible", AW.choose(S, "wait")["dispatched"] is True)
W = AW.wilson(50, 72)
check("the Wilson interval matches the paper's lower edge", close(W["low"], 0.5806, 0.002))
check("the Wilson interval matches the paper's upper edge", close(W["high"], 0.7889, 0.002))
W2 = AW.wilson(69, 72)
check("the completion interval is 88.5–98.6%", close(W2["low"], 0.8847, 0.002)
      and close(W2["high"], 0.9859, 0.002))
AB = AW.ablate([
    {"model": "m1", "condition": "A", "regret": 4900, "completed": False},
    {"model": "m1", "condition": "B", "regret": 4300, "completed": False},
    {"model": "m1", "condition": "C", "regret": 100, "completed": True},
    {"model": "m2", "condition": "A", "regret": 4750, "completed": True},
    {"model": "m2", "condition": "B", "regret": 4200, "completed": True},
    {"model": "m2", "condition": "C", "regret": 160, "completed": True},
])
check("the B→C mean difference is reported", close(AB["deltas"]["B_to_C"], 4120.0))
check("the A→C mean difference is reported", close(AB["deltas"]["A_to_C"], 4695.0))
check("completion counts travel with the means",
      AB["completion"]["C"]["done"] == 2 and AB["completion"]["C"]["n"] == 2)
check("every model improves under verified state",
      AB["per_model_consistent"] == [True, True])
check("the ablation verdict is a consistent gain",
      AB["verdict"] == "verified-state-dominates")
check("an empty ablation is a verdict", AW.ablate([])["verdict"] == "no-arms")
check("trust separation passes by default", kinds(AW.authority({})) == ["trust-separated"])
AUTH = AW.authority({"model_writes_telemetry": True, "model_dispatches": True,
                     "unbounded_snapshot": True, "missing_freshness": True,
                     "neutral_state_marked_verified": True})
check("every authority violation is named", len(AUTH["findings"]) == 5)
check("the awareness audit names its misreadings",
      set(kinds(AW.audit({"regret_read_as_duration": True,
                          "envelope_shape_is_the_gain": True})))
      == {"regret-read-as-duration", "envelope-shape-is-the-gain"})
check("the awareness advice lists six habits", len(AW.advise({})["findings"]) == 6)

# ---- 2. agent diagnostics (arXiv:2611.04507) --------------------------
TAX = DG.taxonomy()
check("the taxonomy has eight families", len(TAX["families"]) == 8)
check("the taxonomy has 45 types", TAX["total"] == 45)
check("the family counts are 5/6/8/8/5/3/6/4",
      [f["count"] for f in TAX["families"]] == [5, 6, 8, 8, 5, 3, 6, 4])
F = DG.finding({"type": "invalid_arguments", "nature": "defect",
                "component": "create_payment",
                "evidence": {"contract": "amount_cents required",
                             "invocation": "amount: 100"},
                "consequence": 40, "session": "s1"})
check("a finding with requirement and violation is admissible",
      F["admissible"] is True and F["family"] == "tool")
check("an unknown type is refused", DG.finding({"type": "nope"})["verdict"]
      == "unknown-type")
check("an unknown nature is refused",
      DG.finding({"type": "invalid_arguments", "nature": "vibes"})["verdict"]
      == "unknown-nature")
check("a missing evidence half is named",
      DG.finding({"type": "invalid_arguments", "nature": "defect",
                  "evidence": {"contract": "x"}})["missing"] == ["invocation"])
check("missing telemetry proves nothing",
      DG.finding({"type": "false_success", "nature": "defect",
                  "evidence": {"missing-telemetry": True}})["verdict"]
      == "insufficient-evidence")
check("a risk needs a reachable path",
      DG.finding({"type": "untrusted_instruction", "nature": "risk",
                  "evidence": {"policy": "p", "action": "a"},
                  "potential": 25})["verdict"] == "unreachable-path")
check("a reachable risk is admissible",
      DG.finding({"type": "untrusted_instruction", "nature": "risk",
                  "evidence": {"policy": "p", "action": "a"},
                  "potential": 25, "reachability": "ordinary"})["admissible"] is True)
check("scope at one session is isolated", DG.scope(1)["points"] == 0)
check("scope at two sessions is limited", DG.scope(2)["points"] == 3)
check("scope at four sessions is repeated", DG.scope(4)["band"] == "repeated")
check("scope at eleven sessions is broad", DG.scope(11)["points"] == 12)
check("scope above a hundred is widespread", DG.scope(101)["points"] == 15)
SC = DG.scope(5, 30)
check("the share band agrees with the count band", SC["share_points"] == 7)
check("the share needs twenty sessions", DG.scope(2, 10)["share_points"] is None)
SEV = DG.severity({"consequence": 40, "affected": 5, "analyzed": 30})
check("the paper's example scores 47", close(SEV["severity"], 47.0))
check("47 is a high display level", SEV["level"] == "high")
SR = DG.severity({"potential": 30, "reachability": "ordinary",
                  "affected": 5, "analyzed": 30})
check("risk rounds the reachable potential up", close(SR["scores"]["risk"], 31.0))
SI = DG.severity({"waste": 20, "affected": 5, "analyzed": 30})
check("waste is a separate nature", close(SI["scores"]["inefficiency"], 27.0))
SM = DG.severity({"consequence": 20, "potential": 85, "reachability": "public",
                  "waste": 65, "affected": 101})
check("a Signal takes the maximum over natures", close(SM["severity"], 100.0))
check("the maximum saturates at the cap", SM["level"] == "critical")
check("severity without a nature is refused",
      DG.severity({"affected": 3})["verdict"] == "no-nature")
G = DG.group([
    {"admissible": True, "component": "c", "type": "invalid_arguments",
     "session": "s1", "nature": "defect"},
    {"admissible": True, "component": "c", "type": "invalid_arguments",
     "session": "s2", "nature": "defect"},
    {"admissible": True, "component": "c", "type": "invalid_arguments",
     "root": "arg-builder", "session": "s1", "nature": "defect",
     "action": "normalise", "check": "valid-payment"},
    {"admissible": True, "component": "c", "type": "invalid_arguments",
     "root": "arg-builder", "session": "s2", "nature": "inefficiency",
     "action": "normalise", "check": "valid-payment"},
])
check("a shared label alone does not merge", len(G["signals"]) == 3)
check("the label-only refusals are counted", G["label_only_merges_refused"] == 2)
check("a shared root merges occurrences", G["signals"][2]["occurrences"] == 2)
check("the merged Signal counts distinct sessions", G["signals"][2]["sessions"] == 2)
check("the merged Signal carries both natures",
      G["signals"][2]["natures"] == ["defect", "inefficiency"])
check("the merged action is not duplicated", G["signals"][2]["actions"] == ["normalise"])
U = DG.update({"occurrences": 2, "root": "r"},
              {"resolved": True, "checked": ["affected"]})
check("one checked side is not a fix", U["verdict"] == "single-run-cannot-establish-fix")
U2 = DG.update({"occurrences": 2, "root": "r"},
               {"resolved": True, "checked": ["affected", "previously_succeeding"]})
check("both checks establish the fix", U2["fix_established"] is True)
check("a different root opens a separate issue",
      DG.update({"root": "r"}, {"root": "r2"})["verdict"] == "separate-issue")
check("unresolved evidence accumulates",
      DG.update({"occurrences": 2}, {"new_occurrences": 3})["occurrences"] == 5)
PRED = [
    {"session": "s1", "component_type": "tool", "component": "Policy_Tool",
     "types": ["invalid_arguments", "wrong_tool"]},
    {"session": "s1", "component_type": "tool", "component": "other",
     "types": ["wrong_tool"]},
]
REF = [
    {"session": "s1", "component_type": "tool", "component": "policy tool",
     "types": ["invalid_arguments"]},
    {"session": "s2", "component_type": "tool", "component": "other",
     "types": ["wrong_tool"]},
]
M = DG.match(PRED, REF)
check("component names normalise", M["matched"] == 1)
check("precision is one of two", close(M["precision"], 0.5))
check("recall is one of two", close(M["recall"], 0.5))
check("F1 is one half", close(M["f1"], 0.5))
M2 = DG.match(PRED, [REF[0], REF[0]])
check("the matcher is one-to-one", M2["matched"] == 1)
COV = DG.coverage(
    [{"session": "s1", "component_type": "tool", "component": "a",
      "types": ["t1"], "occurrences": 1}],
    [{"session": "s1", "component_type": "tool", "component": "a",
      "types": ["t1"], "occurrences": 2},
     {"session": "s2", "component_type": "tool", "component": "b",
      "types": ["t2"], "occurrences": 1}])
check("coverage counts any match", close(COV["covered_any"], 0.5))
check("half coverage is measured per Signal", close(COV["covered_half"], 0.5))
check("the diagnostics audit names its misreadings",
      set(kinds(DG.audit({"missing_telemetry_is_proof": True,
                          "one_run_proves_fix": True})))
      == {"missing-telemetry-is-proof", "one-run-proves-fix"})
check("the diagnostics advice lists six habits", len(DG.advise({})["findings"]) == 6)

# ---- 3. orchestration credit (arXiv:2611.07495) ------------------------
O = OC.orders({"decisions": [{"rho": 1.2, "return": 10},
                             {"rho": 0.8, "return": 20}],
               "true_gain": -2.8})
check("the first order is the weighted return", close(O["order1"], -2.0))
check("the second order carries the pair", close(O["order2"], -0.8))
check("the expansion reproduces the true gain", O["exact"] is True)
O3 = OC.orders({"decisions": [{"rho": 1.1, "return": 1},
                              {"rho": 1.1, "return": 1},
                              {"rho": 0.9, "return": 1}]})
check("the third order is the triple product", close(O3["orders"][2], -0.001))
check("the orders sum exactly", close(O3["sum"], 0.089))
check("an empty record is refused", OC.orders({})["verdict"] == "no-decisions")
BND = OC.bound(4, 1.0, 2.0)
check("beta is half the visit count times eta", close(BND["beta"], 2.5))
check("the remainder matches the binomial tail", close(BND["epsilon"], 3.1875))
check("the first-order tail is the exponential form",
      close(BND["first_order_tail"], 11.114987921406946, 1e-6))
check("a smaller step shrinks the remainder",
      close(OC.bound(4, 0.5, 1.0)["epsilon"], 0.1767578125))
Z = OC.z2({"eta": 1.0, "decisions": [{"rho": 1.2, "return": 10},
                                     {"rho": 0.8, "return": 20}]})
check("mu1 is the first-order statistic", close(Z["mu1"], -2.0))
check("mu2 is the pairwise statistic", close(Z["mu2"], -0.8))
check("Z2 matches the expansion at eta one", close(Z["z2"], -2.8))
CERT = OC.certify({"eta": 0.5, "K": 2, "gbar": 1.0, "delta": 0.05,
                   "candidates": 1, "z2_samples": [100.0] * 10,
                   "is_samples": [100.0] * 10})
check("the truncated bound subtracts the remainder",
      close(CERT["epsilon"], 0.015625))
check("a large certificate is accepted", CERT["decision"] == "accept")
check("the certificate takes the larger bound", close(CERT["lower"], CERT["lower_truncated"])
      or close(CERT["lower"], CERT["lower_is"]))
LOW = OC.certify({"eta": 0.5, "K": 2, "gbar": 1.0, "delta": 0.05,
                  "candidates": 1, "z2_samples": [1.0] * 10,
                  "is_samples": [1.0] * 10})
check("a small certificate retains the policy", LOW["decision"] == "retain")
check("too few samples cannot certify",
      OC.certify({"eta": 0.5, "K": 1, "gbar": 1.0, "z2_samples": [1.0]})["verdict"]
      == "too-few-samples")
SEL = OC.select([{"name": "reference", "lower": 0.0},
                 {"name": "step-1", "lower": 2.0},
                 {"name": "leap", "lower": 0.5}])
check("the largest positive certificate is selected", SEL["selected"] == "step-1")
check("a nonpositive grid keeps the reference",
      OC.select([{"name": "x", "lower": -1.0}])["verdict"] == "retained")
DET = OC.detect({"bis": 6.59375, "delta": 0.05, "candidates": 1, "gain": 1.0,
                 "n": 60000})
check("the detection size follows the bound", close(DET["n_minus_one"], 56487.95, 1.0))
check("a large validation detects", DET["detectable"] is True)
check("a tiny validation cannot",
      OC.detect({"bis": 6.59375, "delta": 0.05, "gain": 1.0, "n": 100})["detectable"]
      is False)
LP = OC.leaps({"paired": [100.0, 100.0, 100.0], "gbar": 1.0, "delta": 0.05})
check("a leap is certified on paired returns", LP["decision"] == "accept")
check("a leap needs at least two pairs",
      OC.leaps({"paired": [1.0]})["verdict"] == "too-few-pairs")
CP = OC.complementarity({"p": 1 / 3, "step": 1.0})
check("the first-order gain is zero at p one third", close(CP["first_order"], 0.0))
check("the joint gain is the paper's 4s²/27", close(CP["joint"], 0.14814814814814814))
check("the joint move crosses the threshold", CP["crosses"] is True)
check("the trap is named", CP["verdict"] == "first-order-stationary")
CP2 = OC.complementarity({"p": 0.5, "step": 1.0})
check("away from the trap the first order already gains", close(CP2["first_order"], 0.25))
check("controlled complementarity reproduces 0.148",
      close(OC.controlled({"task": "complementarity", "step": 1.0})["gain"],
            0.14814814814814814))
check("redundancy at step one gains 0.0064",
      close(OC.controlled({"task": "redundancy", "step": 1.0})["gain"], 0.0064))
RED = OC.controlled({"task": "redundancy", "step": 0.5})["gain"]
check("redundancy at half a step gains 0.0096", close(RED, 0.0096))
check("the evidence threshold is a binomial tail",
      close(OC.controlled({"task": "evidence-threshold", "n": 6, "q": 0.3})["gain"],
            0.165690, 1e-6))
check("an unknown controlled task is refused",
      OC.controlled({"task": "nope", "step": 1.0})["verdict"] == "unknown-task")
check("the credit audit names its misreadings",
      set(kinds(OC.audit({"per_decision_credits_add": True,
                          "validation_reused_for_fitting": True})))
      == {"per-decision-credits-add", "validation-reused-for-fitting"})
check("the credit advice lists six habits", len(OC.advise({})["findings"]) == 6)

# ---- verdict ----------------------------------------------------------
TOTAL = len(RESULTS)
PASSED = sum(RESULTS)
print("\n%d/%d checks passed" % (PASSED, TOTAL))
sys.exit(0 if PASSED == TOTAL else 1)
