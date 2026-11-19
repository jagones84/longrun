#!/usr/bin/env python3
"""v1205 — selective replay, continuation policy, evidence replay (round 136).

Sources:
  * arXiv:2611.23174 "Inference After Coding Agents" — a selected p-value is
    corrected by replaying the agent on subsamples and estimating the selection
    multiplier.
  * arXiv:2611.22888 "Stopping Is Not the Limit" — stops cluster into bursts;
    compaction at the burst plus relabeling impossibility judgments as unproven
    elicits more capability.
  * arXiv:2611.23045 "ForecastGym" — evidence is an experimental variable;
    retrieval time bounds what was knowable and providers change the score.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1205_selective_continuation_evidence.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1205-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import selective_replay as SR      # noqa: E402
from longrun.harness import continuation_policy as CP   # noqa: E402
from longrun.harness import evidence_replay as ER       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. selective replay ------------------------------------------------
lam = SR.multiplier(0.05, 0.126, 0.072)
check("the Card-Krueger rates give a multiplier of 1.687",
      lam is not None and abs(lam - 1.687) < 1e-3, lam)
check("equal rates at any p-value leave the multiplier at one",
      abs(SR.multiplier(0.5, 0.2, 0.2) - 1.0) < 1e-9)
check("a zero p-value has no multiplier", SR.multiplier(0.0, 0.1, 0.1) is None)
check("a negative rate is refused", SR.multiplier(0.05, -0.1, 0.2) is None)
check("a p-value above one is refused", SR.multiplier(1.5, 0.1, 0.2) is None)

c1 = SR.corrected(0.0123, 79, 500, 32, 500)
check("tail 79/500 and body 32/500 correct 0.0123 upward",
      c1["available"] is True and c1["corrected"] > c1["reported"], c1)
check("the reported multiplier is around 2.43", abs(c1["multiplier"] - 2.43) < 0.01, c1)
check("the corrected value is u times the multiplier",
      abs(c1["corrected"] - round(0.0123 * c1["multiplier"], 6)) < 1e-5, c1)
check("a selected analysis is named", "selected-analysis" in kinds(c1), c1)
c2 = SR.corrected(0.5, 100, 500, 100, 500)
check("equal reselection rates detect no selection",
      "no-selection-detected" in kinds(c2), c2)
c3 = SR.corrected(0.2, 0, 0, 10, 100)
check("an empty tail makes the correction unavailable at p = 1",
      c3["available"] is False and c3["corrected"] == 1.0, c3)
check("impossible counts are refused",
      "impossible-counts" in kinds(SR.corrected(0.2, 200, 100, 1, 100)))
check("an invalid p-value is refused",
      "invalid-p-value" in kinds(SR.corrected(0.0, 1, 10, 1, 10)))
c4 = SR.corrected(0.02, 10, 500, 150, 500)
check("a body rate above the tail rate gives negative selection",
      "negatively-selected" in kinds(c4), c4)

check("a corrected p below alpha rejects", SR.gate(0.0433)["reject"] is True)
check("a corrected p above alpha does not reject", SR.gate(0.06)["reject"] is False)
check("a corrected p of exactly alpha rejects", SR.gate(0.05)["reject"] is True)
check("an invalid alpha is refused", "invalid-input" in kinds(SR.gate(0.05, alpha=0)))

al = SR.allocation(640, 0.101, 0.0031)
check("the allocation splits 640 replays with a heavier tail",
      al["tail"] + al["body"] == 640 and al["tail"] > al["body"], al)
check("the allocation is named as Neyman", "neyman-allocation" in kinds(al), al)
al2 = SR.allocation(2, 0.5, 0.5)
check("the floor keeps one replay in each stratum",
      al2["tail"] == 1 and al2["body"] == 1, al2)
check("a budget below two is refused", "invalid-budget" in kinds(SR.allocation(1, 0.5, 0.5)))
al3 = SR.allocation(100, 0.0, 1.0)
check("a degenerate pilot still splits the budget",
      "degenerate-allocation" in kinds(al3), al3)

rs = SR.resampling(200, 2000)
check("a ten-percent subsample is valid", "valid-subsampling" in kinds(rs), rs)
check("the bootstrap is refused for duplicating units",
      "bootstrap-duplicates" in kinds(SR.resampling(200, 2000, replacement=True)))
check("a quarter-size subsample is too large",
      "subsample-too-large" in kinds(SR.resampling(500, 2000)))
check("a subsample larger than the data is refused",
      "invalid-subsample" in kinds(SR.resampling(3000, 2000)))

clean = {"evidence": [{"id": "E1", "retrieved_at": 10, "state_time": 10}],
         "same_query_plan": True, "same_evidence": True, "replay_offline": True}
check("a clean run passes the three requirements",
      "replay-audit-clean" in kinds(SR.audit(clean)), SR.audit(clean))
check("an item retrieved after the state is not knowable",
      "item-not-knowable" in kinds(SR.audit(dict(clean, evidence=[
          {"id": "E1", "retrieved_at": 11, "state_time": 10}]))))
check("a missing retrieval time is named",
      "missing-retrieval-time" in kinds(SR.audit({"evidence": [{"id": "E1"}]})))
check("differing provider query plans are named",
      "source-policy-differs" in kinds(SR.audit(dict(clean, same_query_plan=False))))
check("evidence that differs across arms is named",
      "evidence-not-fixed" in kinds(SR.audit(dict(clean, same_evidence=False))))
check("a replay that searches live is refused",
      "replay-hits-live-search" in kinds(SR.audit(dict(clean, replay_offline=False))))

sc = SR.self_correction({})
check("an undeclared family is named", "family-not-predeclared" in kinds(sc), sc)
check("an uncorrected headline is named", "correction-not-on-headline" in kinds(sc), sc)
sc2 = SR.self_correction({"declared_family": 26, "observed_analyses": 129,
                          "family_fixed_before_data": True,
                          "corrected_value_is_headline": True})
check("a family smaller than the observed analyses is named",
      "family-covers-observed-only" in kinds(sc2), sc2)
check("a consistent self-correction passes",
      "self-correction-consistent" in kinds(SR.self_correction(
          {"declared_family": 30, "observed_analyses": 26,
           "family_fixed_before_data": True, "corrected_value_is_headline": True})))
check("a correction that erases the effect is named",
      "correction-costs-power" in kinds(SR.self_correction(
          {"family_fixed_before_data": True, "corrected_value_is_headline": True,
           "correction_lost_effect": True})))

d1 = SR.detect([{"reported": 0.01, "corrected": 0.20}] * 99)
check("99 reported rejections against 99 corrected non-rejections detect selection",
      d1["reported_rate"] == 1.0 and d1["corrected_rate"] == 0.0, d1)
check("the selection is named", "selection-detected" in kinds(d1), d1)
check("runs without a correction are counted",
      "correction-missing" in kinds(SR.detect([{"reported": 0.01},
                                               {"reported": 0.2, "corrected": 0.3}])))
check("no runs is named", "no-runs" in kinds(SR.detect([])))
check("advise names every missing practice", len(SR.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", SR.advise(
    {k: True for k in ("records_selection", "replays_agent", "replays_on_subsamples",
                       "estimates_both_strata", "allocates_replays", "reports_corrected_p",
                       "checks_self_correction", "fixes_the_evidence")})["findings"] == [])

# ---- 2. continuation policy --------------------------------------------
check("two stops in four responses are a rate of 0.5",
      CP.stop_rate([{"kind": "tool"}, {"kind": "stop"},
                    {"kind": "tool"}, {"kind": "stop"}])["rate"] == 0.5)
check("summaries and retries do not count as responses",
      CP.stop_rate([{"kind": "summary"}, {"kind": "retry"},
                    {"kind": "tool"}])["turns"] == 1)
check("an empty turn log is named", "no-responses" in kinds(CP.stop_rate([])))
b1 = CP.burst([{"kind": "tool"}, {"kind": "stop"}, {"kind": "tool"}, {"kind": "stop"},
               {"kind": "tool"}], window=4, rho=0.5)
check("a burst is detected at the first full window",
      b1["index"] == 3 and b1["rate"] == 0.5, b1)
check("the burst is named", "stop-burst" in kinds(b1), b1)
check("a quiet log has no burst",
      "no-burst" in kinds(CP.burst([{"kind": "tool"}] * 30, window=20)))
check("a one-response window is refused", "invalid-window" in kinds(CP.burst([], window=1)))
check("a rate above one is refused", "invalid-window" in kinds(CP.burst([], rho=1.5)))

g1 = CP.gains([{"bin": "101-200", "gain": 1.57}, {"bin": "301-400", "gain": 0.5},
               {"bin": "501-600", "gain": 0.04}])
check("a falling per-bin gain is named", "gains-diminish" in kinds(g1), g1)
check("the first and last bins are reported", g1["first"] == 1.57 and g1["last"] == 0.04, g1)
check("a flat zero last bin is named",
      "no-gain-in-last-bin" in kinds(CP.gains([{"bin": 1, "gain": 1.0},
                                               {"bin": 2, "gain": 0.0}])))
check("a sustained gain is named",
      "gains-sustained" in kinds(CP.gains([{"bin": 1, "gain": 1.0},
                                           {"bin": 2, "gain": 1.1}])))
check("no bins is named", "no-bins" in kinds(CP.gains([])))

j1 = CP.judgment("Reaching arbitrary code execution is impossible")
check("an impossibility judgment is read", j1["impossible"] is True, j1)
check("the capability is extracted",
      j1["capability"] == "Reaching arbitrary code execution", j1)
check("an ordinary sentence is not a judgment",
      CP.judgment("the agent achieved ACE")["impossible"] is False)
check("empty text is named", "empty-text" in kinds(CP.judgment("")))
rl = CP.relabel("Reaching arbitrary code execution is impossible")
check("the relabeled sentence is an unproven conclusion",
      rl["text"].startswith("I have not yet found a way to achieve"), rl)
check("the relabeling is named", "relabeled-unproven" in kinds(rl), rl)
check("a sentence with no judgment is left alone",
      "nothing-to-relabel" in kinds(CP.relabel("the agent achieved ACE")))

full = {"verified_findings": "the service starts", "environment_state": "container up",
        "achieved_capabilities": "T4 crash", "unsuccessful_attempts": "three patches",
        "remaining_gaps": "T2 primitives", "unproven_conclusions":
        "I have not yet found a way to achieve ACE through the approaches I attempted"}
check("a clean six-field summary is accepted",
      kinds(CP.summary(full)) == ["unproven-relabeled"], CP.summary(full))
check("a missing field is named",
      "summary-field-missing" in kinds(CP.summary(dict(full, remaining_gaps=""))))
check("a judgment inside the facts is named",
      "judgment-in-facts" in kinds(CP.summary(dict(
          full, remaining_gaps="achieving ACE is impossible"))))
check("facts carrying a judgment with no unproven field are named",
      "unproven-field-missing" in kinds(CP.summary(dict(
          full, remaining_gaps="achieving ACE is impossible", unproven_conclusions=""))))
check("clean facts with a relabeled unproven field raise no judgment finding",
      "judgment-in-facts" not in kinds(CP.summary(full)))

pol = {"stop_ends_run": False, "burst_trigger": True,
       "window_resets_after_compaction": True, "window": 20, "rho": 0.2,
       "token_threshold": 850000, "nudge_on_non_trigger": True}
check("a stop-aware policy is accepted",
      kinds(CP.policy(pol)) == ["stop-aware-policy"], CP.policy(pol))
check("a stop that ends the run is named",
      "stop-ends-run" in kinds(CP.policy(dict(pol, stop_ends_run=True))))
check("a missing burst trigger is named",
      "burst-trigger-missing" in kinds(CP.policy(dict(pol, burst_trigger=False))))
check("a window that is not reset is named",
      "window-not-reset" in kinds(CP.policy(dict(pol, window_resets_after_compaction=False))))
check("a missing nudge is named",
      "no-continuation-nudge" in kinds(CP.policy(dict(pol, nudge_on_non_trigger=False))))
check("an invalid window is named",
      "invalid-burst-window" in kinds(CP.policy(dict(pol, window=1))))
check("an empty policy names all five defects", len(CP.policy({})["findings"]) == 5)

cmp1 = CP.compare([{"judgment": True, "turns_to_next_stop": 60, "achieved": False},
                   {"judgment": True, "turns_to_next_stop": 62, "achieved": False},
                   {"judgment": True, "turns_to_next_stop": 70, "achieved": True},
                   {"judgment": True, "turns_to_next_stop": 72, "achieved": False},
                   {"judgment": False, "turns_to_next_stop": 110, "achieved": True},
                   {"judgment": False, "turns_to_next_stop": 112, "achieved": False},
                   {"judgment": False, "turns_to_next_stop": 118, "achieved": True},
                   {"judgment": False, "turns_to_next_stop": 120, "achieved": False}])
check("a judgment shortens the next productive stretch",
      "judgment-shortens-next-stretch" in kinds(cmp1), cmp1)
check("a judgment is associated with lower achievement",
      "judgment-lower-achievement" in kinds(cmp1), cmp1)
check("a capability achieved after the judgment proves it premature",
      "judgment-premature" in kinds(cmp1), cmp1)
check("one group only is named",
      "single-group" in kinds(CP.compare([{"judgment": True, "turns_to_next_stop": 60}])))

m1 = CP.methods([
    {"method": "ReAct", "cap": 3.51}, {"method": "ReSum", "cap": 5.95, "cost": 3.36},
    {"method": "SCoRe", "cap": 6.65, "cost": 2.82},
    {"method": "w/o capability judgment relabeling", "cap": 6.14},
    {"method": "w/o stop-aware compaction", "cap": 5.32}])
check("the best method is SCoRe", m1["findings"][0]["method"] == "SCoRe", m1)
check("SCoRe is above ReSum", "score-above-resum" in kinds(m1), m1)
check("relabeling earns its place", {"kind": "component-needed",
                                     "component": "relabeling",
                                     "delta": 0.51} in m1["findings"], m1)
check("compaction earns its place", any(f.get("component") == "compaction"
                                        for f in m1["findings"]
                                        if f.get("kind") == "component-needed"), m1)
check("SCoRe is cheaper than ReSum", "cheaper-than-resum" in kinds(m1), m1)
check("no methods is named", "no-methods" in kinds(CP.methods([])))
check("advise names every missing practice", len(CP.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", CP.advise(
    {k: True for k in ("continues_after_stop", "detects_stop_bursts", "compacts_on_burst",
                       "separates_unproven", "keeps_turn_accounting",
                       "measures_gain_per_bin", "ablates_components",
                       "reports_cost")})["findings"] == [])

# ---- 3. evidence replay ------------------------------------------------
st = ER.state({"time": 100, "items": [{"id": "E1", "retrieved_at": 90},
                                      {"id": "E2", "retrieved_at": 100}]})
check("a state whose items predate it is valid",
      "state-valid" in kinds(st) and st["items"] == 2, st)
check("an item retrieved later is not knowable",
      "item-not-knowable" in kinds(ER.state({"time": 100, "items": [
          {"id": "E1", "retrieved_at": 101}]})))
check("a missing retrieval time is named",
      "missing-retrieval-time" in kinds(ER.state({"time": 100,
                                                 "items": [{"id": "E1"}]})))
check("a state with no items is named",
      "state-empty" in kinds(ER.state({"time": 100, "items": []})))
check("a state with no time is refused",
      "state-time-missing" in kinds(ER.state({"items": [{"id": "E1"}]})))

fz = ER.freeze({"providers": ["tavily", "exa", "serper", "parallel"],
                "shared_query_plan": True, "shared_follow_up_budget": True,
                "collection_times": [0, 2, 4], "captured_before_resolution": True,
                "results_stored_per_provider": True})
check("a frozen four-provider record is accepted",
      kinds(fz) == ["frozen-record"], fz)
check("a single provider is named", "single-provider" in kinds(ER.freeze({"providers": ["a"]})))
check("differing query plans are named",
      "source-policy-differs" in kinds(ER.freeze(dict(
          providers=["a", "b"], shared_query_plan=False))))
check("differing follow-up budgets are named",
      "follow-up-budget-differs" in kinds(ER.freeze(dict(
          providers=["a", "b"], shared_query_plan=True,
          shared_follow_up_budget=False))))
check("capture after resolution is named",
      "captured-after-resolution" in kinds(ER.freeze(dict(
          providers=["a", "b"], shared_query_plan=True, shared_follow_up_budget=True,
          collection_times=[1], captured_before_resolution=False))))
check("pooled results are named",
      "results-pooled" in kinds(ER.freeze(dict(
          providers=["a", "b"], shared_query_plan=True, shared_follow_up_budget=True,
          collection_times=[1], captured_before_resolution=True))))

lk = ER.leak([{"total": 100, "leaking": 40, "questions": 60, "revealed": 52,
               "undated": 80, "dated_after_retrieval": 7}])
check("post-hoc leakage is named", "post-hoc-leaks" in kinds(lk), lk)
check("a revealed outcome is named", "outcome-revealed" in kinds(lk), lk)
check("undated pages are named", "undated-pages" in kinds(lk), lk)
check("a page dated after retrieval is named",
      "dated-after-retrieval" in kinds(lk), lk)
check("a clean probe is named",
      "no-leak-detected" in kinds(ER.leak([{"total": 100, "leaking": 2,
                                            "questions": 60, "revealed": 3}])))
check("no probe is named", "no-probe" in kinds(ER.leak([])))

s1 = ER.score([{"p": 1.0, "y": 1.0}, {"p": 0.0, "y": 0.0}])
check("perfect forecasts score zero Brier", s1["brier"] == 0.0, s1)
check("perfect forecasts are fully accurate", s1["accuracy"] == 1.0, s1)
s2 = ER.score([{"p": 0.5, "y": 1.0}])
check("a constant half scores 0.25 and is named",
      s2["brier"] == 0.25 and "constant-half" in kinds(s2), s2)
check("an empty forecast set is named", "no-forecasts" in kinds(ER.score([])))
tr = ER.trajectory([{"p": 0.8, "y": 1.0}, {"p": 0.9, "y": 1.0}])
check("the trajectory score averages the states", tr["tbs"] == 0.025, tr)
check("the last state is scored separately", tr["last"] == 0.01, tr)

pr = ER.paired([{"arm": 0.23, "baseline": 0.20}, {"arm": 0.24, "baseline": 0.21},
                {"arm": 0.22, "baseline": 0.19}, {"arm": 0.23, "baseline": 0.20}])
check("a paired arm above the baseline is worse",
      "arm-worse" in kinds(pr) and abs(pr["delta"] - 0.03) < 1e-9, pr)
check("identical arms leave the difference unresolved",
      "difference-unresolved" in kinds(ER.paired(
          [{"arm": 0.2, "baseline": 0.2}, {"arm": 0.3, "baseline": 0.3}])))
check("one question is not enough", "not-enough-questions" in kinds(
    ER.paired([{"arm": 0.2, "baseline": 0.3}])))

src = ER.sources([{"provider": "Tavily", "brier": 0.218},
                  {"provider": "Exa", "brier": 0.213},
                  {"provider": "Serper", "brier": 0.255},
                  {"provider": "Parallel", "brier": 0.212}], model_spread=0.027)
check("the provider spread is 0.043", abs(src["spread"] - 0.043) < 1e-9, src)
check("the provider spread exceeds the model spread",
      "source-exceeds-model" in kinds(src), src)
check("the worst source is Serper",
      {"kind": "worst-source", "provider": "Serper", "brier": 0.255} in src["findings"], src)
check("one source is not a comparison",
      "not-enough-sources" in kinds(ER.sources([{"provider": "a", "brier": 0.2}])))

mem = ER.memory([{"variant": "main", "brier": 0.228, "update": 0.045, "agree": 0.59,
                  "tokens": 9.5},
                 {"variant": "no-memory", "brier": 0.237, "update": 0.084, "agree": 0.50},
                 {"variant": "all-so-far", "brier": 0.232, "update": 0.059, "agree": 0.49,
                  "tokens": 19.5}])
check("memory steadies the updates", "memory-steadies" in kinds(mem), mem)
check("memory agrees with the market more often",
      "memory-agrees-with-market" in kinds(mem), mem)
check("notes cost half of rereading", "notes-cheaper" in kinds(mem), mem)
check("missing variants are named",
      "missing-variants" in kinds(ER.memory([{"variant": "main", "brier": 0.2}])))
check("advise names every missing practice", len(ER.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", ER.advise(
    {k: True for k in ("captures_evidence_live", "bounds_by_retrieval_time",
                       "freezes_provider_results", "shares_query_plan",
                       "replays_offline", "hides_market_price",
                       "compares_with_market", "ablates_memory")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
