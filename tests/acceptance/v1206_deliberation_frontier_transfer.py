#!/usr/bin/env python3
"""v1206 — deliberation audit, complexity frontier, work transfer (round 137).

Sources:
  * arXiv:2611.22905 "Think Before You Code" — typed deliberation artifacts,
    metadata F1 below 0.2, design-choice blindness, grounding dominates.
  * arXiv:2611.23080 "Colombo" — a bracket per regime, least-resolved display,
    review and certification before memory, adversarial co-ascent.
  * arXiv:2611.23216 "Higher-Scoring Coding Models Did Not Get More Work Done"
    — a model switch with person fixed effects, a ceiling, and a null that is a
    bound.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1206_deliberation_frontier_transfer.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1206-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import deliberation_audit as DA  # noqa: E402
from longrun.harness.checks import complexity_frontier as CF  # noqa: E402
from longrun.harness.checks import work_transfer as WT  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. deliberation audit ----------------------------------------------
good = {"type": "trade off argument",
        "summary": "Choosing between Map and BTreeMap changes lookup cost on large key sets",
        "tags": ["performance_issue"], "metadata": {"options compared": "Map vs BTreeMap",
                                                    "comparison axes": "lookup latency",
                                                    "preferred option": "BTreeMap"}}
check("a complete trade-off artifact is accepted",
      kinds(DA.artifact(good)) == ["artifact-valid"], DA.artifact(good))
check("an unknown type is named",
      "unknown-type" in kinds(DA.artifact(dict(good, type="vibe"))))
check("a type with no tags is named",
      "no-tags" in kinds(DA.artifact(dict(good, tags=[]))))
check("a tag that is not snake case is named",
      "tag-not-snake-case" in kinds(DA.artifact(dict(good, tags=["Performance Issue"]))))
check("a missing summary is named",
      "no-summary" in kinds(DA.artifact(dict(good, summary=""))))
check("a generic summary is named",
      "generic-summary" in kinds(DA.artifact(dict(good, summary="improve the code"))))
check("a missing metadata field is named",
      "metadata-missing" in kinds(DA.artifact(dict(good, metadata={"options compared": "a b"}))))
check("an extra metadata key is named",
      "metadata-extra-keys" in kinds(DA.artifact(dict(
          good, metadata={"options compared": "a b", "comparison axes": "c",
                          "preferred option": "d", "notes": "x"}))))

m1 = DA.match(["problem statement", "trade off argument", "design decision"],
              ["problem statement", "proposed solution"])
check("type precision counts what the model added",
      abs(m1["precision"] - 0.5) < 1e-9, m1)
check("type recall counts what the model missed",
      abs(m1["recall"] - 0.3333) < 1e-3, m1)
check("a missed type space is named", "types-missed" in kinds(m1), m1)
check("an identical type set is fully matched",
      DA.match(["a", "b"], ["b", "a"])["f1"] == 1.0)
check("an empty side is refused", "empty-side" in kinds(DA.match([], ["a"])))

t1 = DA.tags(["performance_issue", "regression"], ["performance_issue"])
check("tag precision is 1 when every predicted tag is right",
      t1["precision"] == 1.0, t1)
check("tag recall falls with a missed tag", abs(t1["recall"] - 0.5) < 1e-9, t1)
check("an empty tag set is refused", "empty-tag-set" in kinds(DA.tags([], ["a"])))

md = DA.metadata(["Map", "BTreeMap", "balanced tree"], ["hash map", "tree"])
check("unrelated metadata values give a hard F1 of zero",
      md["hard_f1"] == 0.0 and "metadata-gap" in kinds(md), md)
md2 = DA.metadata(["Map", "lookup latency", "BTreeMap"], ["Map", "lookup latency"])
check("matching metadata is scored as matched",
      md2["hard_f1"] > 0.6 and "metadata-matched" in kinds(md2), md2)
check("the soft score exceeds the hard score",
      md["soft_f1"] >= md["hard_f1"], md)
check("empty metadata is refused", "empty-metadata" in kinds(DA.metadata([], ["a"])))

s1 = DA.summary(0.86, 0.45)
check("a high summary score over narrow coverage is penalised",
      abs(s1["adjusted"] - 0.387) < 1e-9, s1)
check("narrow coverage is named", "narrow-coverage" in kinds(s1), s1)
check("a high raw score with a low adjusted score is generic",
      "generic-summary" in kinds(s1), s1)
s2 = DA.summary(0.7, 0.9)
check("a grounded summary is reported as evidence",
      "summary-evidence" in kinds(s2) and "generic-summary" not in kinds(s2), s2)
check("an invalid score is refused", "invalid-score" in kinds(DA.summary(1.5, 0.5)))

ab = DA.ablation([
    {"setting": "orig", "type_f1": 0.35, "tag_f1": 0.32, "summary": 0.85},
    {"setting": "noctx", "type_f1": 0.11, "tag_f1": 0.29, "summary": 0.20},
    {"setting": "bm25", "type_f1": 0.45, "tag_f1": 0.45, "summary": 0.60},
    {"setting": "few", "type_f1": 0.33, "tag_f1": 0.40, "summary": 0.85}])
check("no context collapses the type score", "grounding-required" in kinds(ab), ab)
check("keyword retrieval trades meaning for labels",
      "keyword-trades-meaning" in kinds(ab), ab)
check("few-shot buys labels without meaning",
      "few-shot-labels-only" in kinds(ab), ab)
check("no ablations is named", "no-rows" in kinds(DA.ablation([])))

a1 = DA.audit({"types": ["problem statement", "proposed solution"],
               "metadata_f1": 0.05, "summary_score": 0.9, "grounded": False})
check("a missing trade-off is named",
      {"kind": "design-choice-missing", "type": "trade off argument"} in a1["findings"], a1)
check("a missing design decision is named",
      {"kind": "design-choice-missing", "type": "design decision"} in a1["findings"], a1)
check("a similar summary over missing structure is named",
      "structure-missing-under-similar-summary" in kinds(a1), a1)
check("ungrounded reasoning is named", "ungrounded-reasoning" in kinds(a1), a1)
check("a full record is audited",
      kinds(DA.audit({"types": ["trade off argument", "design decision"],
                      "metadata_f1": 0.5, "summary_score": 0.7,
                      "grounded": True})) == ["deliberation-audited"])
check("advise names every missing practice", len(DA.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", DA.advise(
    {k: True for k in ("records_artifact_types", "fills_metadata", "covers_tradeoffs",
                       "grounds_in_code", "uses_hybrid_retrieval",
                       "penalises_by_coverage", "separates_type_and_summary",
                       "checks_ablation")})["findings"] == [])

# ---- 2. complexity frontier ---------------------------------------------
br = CF.bracket([{"domain": "d1", "upper": 2, "lower": 2},
                 {"domain": "d2", "upper": 3, "lower": 2}])
check("a matched regime is optimal", br["regimes"][0]["status"] == "optimal", br)
check("an unmatched regime is open", br["regimes"][1]["status"] == "open", br)
check("the setting shows its least-resolved regime", br["status"] == "open", br)
check("the aggregate names the regime", "setting-open" in kinds(br), br)
check("a logarithmic allowance gives near-optimal",
      CF.bracket([{"domain": "d", "upper": 2.05, "lower": 2.0,
                   "log_tolerance": 0.1}])["regimes"][0]["status"] == "near-optimal")
check("a missing lower bound is upper-only",
      CF.bracket([{"domain": "d", "upper": 2, "lower": None}])["regimes"][0]["status"]
      == "upper-only")
check("a missing upper bound is lower-only",
      CF.bracket([{"domain": "d", "upper": None, "lower": 2}])["regimes"][0]["status"]
      == "lower-only")
check("both sides missing is uncharacterized",
      CF.bracket([{"domain": "d", "upper": None, "lower": None}])["status"]
      == "uncharacterized")
check("an upper below the lower is inconsistent",
      "upper-below-lower" in kinds(CF.bracket([{"domain": "d", "upper": 1, "lower": 2}])))
check("an empty bracket is refused", "no-regimes" in kinds(CF.bracket([])))

fr = CF.frontier([{"status": "optimal"}, {"status": "open", "candidate": 0.1,
                                         "candidate_closes": True}])
check("an open frontier is counted", "frontier-open" in kinds(fr), fr)
check("a candidate that closes an open regime reaches it",
      "candidate-reaches-frontier" in kinds(fr), fr)
check("a candidate that does not close the gap adds nothing",
      "candidate-misses-frontier" in kinds(CF.frontier(
          [{"status": "open", "candidate": 0.1}])))
check("a closed frontier is named",
      "frontier-closed" in kinds(CF.frontier([{"status": "optimal"}])))
check("no frontier is named", "no-frontier" in kinds(CF.frontier([])))

check("a family solved below its bound exposes structure",
      "exploitable-structure" in kinds(CF.coascent(
          {"algorithm_upper": 1.0, "family_lower": 2.0})))
check("a counterexample exposes an information limit",
      "information-limit" in kinds(CF.coascent({"counterexample": "instance x"})))
check("matched bounds are named", "matched-bounds" in kinds(CF.coascent({"matched": True})))
check("no interaction is named", "no-progress" in kinds(CF.coascent({})))

check("a bound without a domain is refused",
      "missing-domain" in kinds(CF.evidence({"side": "upper"})))
check("an untyped bound is refused", "untyped-bound" in kinds(CF.evidence({})))
check("an unreviewed claim is refused",
      "unreviewed-claim" in kinds(CF.evidence({"domain": "d", "side": "upper"})))
check("an uncertified claim is refused",
      "uncertified-claim" in kinds(CF.evidence({"domain": "d", "side": "upper",
                                                "reviewed": True})))
check("a proof placeholder blocks admission",
      "proof-placeholder" in kinds(CF.evidence(
          {"domain": "d", "side": "upper", "reviewed": True, "certified": True,
           "placeholders": ["sorry"]})))
check("an unchecked transfer is named",
      "transfer-unchecked" in kinds(CF.evidence(
          {"domain": "d", "side": "lower", "reviewed": True, "certified": True,
           "transfer": True})))
check("a complete bound is admissible",
      kinds(CF.evidence({"domain": "d", "side": "upper", "reviewed": True,
                         "certified": True})) == ["bound-admissible"])

mem = CF.memory([{"id": "a", "status": "certified"},
                 {"id": "b", "status": "provisional", "in_bracket": True},
                 {"id": "c", "status": "failed", "as_finding": True}])
check("a provisional record cannot enter the bracket",
      "provisional-in-bracket" in kinds(mem), mem)
check("a failure cannot be promoted to a finding",
      "failure-as-finding" in kinds(mem), mem)
check("the counts are reported", mem["counts"]["certified"] == 1, mem)
check("an unknown status is named",
      "unknown-status" in kinds(CF.memory([{"id": "x", "status": "maybe"}])))
check("consistent memory is named",
      "memory-consistent" in kinds(CF.memory([{"id": "a", "status": "certified"}])))
check("no records is named", "no-records" in kinds(CF.memory([])))

r1 = CF.round([{"id": "p", "supported": True},
               {"id": "q", "supported": False, "composition": True}])
check("an unproved composition step is an obligation",
      "composition-unproved" in kinds(r1), r1)
check("an incomplete round is named", "round-incomplete" in kinds(r1), r1)
check("a completed round is named",
      "round-complete" in kinds(CF.round([{"id": "p", "supported": True}])))
check("a target claimed with open work is named",
      "target-claimed-with-open-work" in kinds(CF.round(
          [{"supported": True, "target_reached": True}, {"supported": False}])))
check("no obligations is named", "no-obligations" in kinds(CF.round([])))
check("advise names every missing practice", len(CF.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", CF.advise(
    {k: True for k in ("tracks_upper_and_lower", "scopes_each_bound",
                       "shows_least_resolved", "separates_provisional",
                       "certifies_claims", "retains_failures",
                       "pairs_attack_and_defence", "marks_unproved_composition")})["findings"] == [])

# ---- 3. work transfer ---------------------------------------------------
wt = WT.transfer([{"upgrade": "fable-suspension", "benchmark_gain": 10.8,
                   "work_delta": 1.4, "ci_low": -1.4, "ci_high": 4.3},
                  {"upgrade": "opus-4.6-4.7", "benchmark_gain": 10.9,
                   "work_delta": -4.1, "ci_low": -9.7, "ci_high": 1.6}])
check("an interval across zero leaves the transfer unobserved",
      "transfer-unobserved" in kinds(wt), wt)
check("a set with no supported row names the gap",
      "benchmark-gain-not-in-work" in kinds(wt), wt)
check("a positive interval supports the transfer",
      "transfer-supported" in kinds(WT.transfer(
          [{"benchmark_gain": 5, "work_delta": 2.0, "ci_low": 0.5, "ci_high": 3.5}])))
check("a gain with a ruled-out zero is named",
      "gain-absent-and-ruled-out" in kinds(WT.transfer(
          [{"benchmark_gain": 11, "work_delta": -2.0, "ci_low": -3.0, "ci_high": -0.5}])))
check("a row without an interval is named",
      "no-interval" in kinds(WT.transfer([{"benchmark_gain": 5, "work_delta": 1.0}])))
check("no measurements is named", "no-measurements" in kinds(WT.transfer([])))

pool = WT.pool([{"work_delta": -0.9, "ci_low": -1.9, "ci_high": 0.2}] * 5)
check("five identical negative changes pool to the same value",
      abs(pool["delta"] + 0.9) < 1e-6, pool)
check("identical rows pool to a negative estimate", "pooled-negative" in kinds(pool), pool)
check("all rows negative is named", "all-negative" in kinds(pool), pool)
check("opposite rows pool across zero",
      "pooled-null" in kinds(WT.pool(
          [{"work_delta": -2.0, "ci_low": -4.0, "ci_high": 0.0},
           {"work_delta": 2.0, "ci_low": 0.0, "ci_high": 4.0}])))
check("positive rows pool positive",
      "pooled-positive" in kinds(WT.pool(
          [{"work_delta": 2.0, "ci_low": 0.5, "ci_high": 3.5}] * 3)))
check("no poolable rows is named",
      "no-poolable-rows" in kinds(WT.pool([{"work_delta": 1.0}])))

ce = WT.ceiling(0.945)
check("an outcome near its ceiling is named", "ceiling-leaves-no-room" in kinds(ce), ce)
check("a ceiling requires an open outcome", "needs-open-outcome" in kinds(ce), ce)
check("an open outcome satisfies the ceiling rule",
      "open-outcome-reported" in kinds(WT.ceiling(0.945, open_outcome="merged within one hour")))
check("an outcome with headroom is named",
      "headroom-present" in kinds(WT.ceiling(0.5)))
check("an invalid rate is refused", "invalid-rate" in kinds(WT.ceiling(1.5)))

full = {"developer_fixed_effects": True, "calendar_fixed_effects": True,
        "placebo": True, "same_developers": True, "control_group": True,
        "pre_period_similar": True}
check("a sound design is accepted", kinds(WT.design(full)) == ["design-sound"], WT.design(full))
check("a missing developer fixed effect is named",
      "no-developer-fixed-effects" in kinds(WT.design(dict(full, developer_fixed_effects=False))))
check("a missing calendar control is named",
      "no-calendar-control" in kinds(WT.design(dict(full, calendar_fixed_effects=False))))
check("a missing placebo is named", "no-placebo" in kinds(WT.design(dict(full, placebo=False))))
check("pooled developers are named",
      "different-developers" in kinds(WT.design(dict(full, same_developers=False))))
check("an empty design names all six defects", len(WT.design({})["findings"]) == 6)

rv = WT.reversal({"p0": {"delta": -2.6}, "p1": {"delta": 1.4},
                  "p3": {"delta": 1.4}, "p2": {"delta": 0.0}})
check("the reversal contrast averages the two treated phases",
      rv["reversal"] == 1.4, rv)
check("a flat placebo is named", "placebo-flat" in kinds(rv), rv)
check("a non-flat placebo is named",
      "placebo-not-flat" in kinds(WT.reversal(
          {"p0": {"delta": -5.0}, "p1": {"delta": 1.4}, "p3": {"delta": 1.4}})))
check("a non-suspension reference is named",
      "reference-not-suspension" in kinds(WT.reversal(
          {"p2": {"delta": 1.0}, "p1": {"delta": 1.0}, "p3": {"delta": 1.0}})))
check("a missing phase is refused",
      "missing-phase" in kinds(WT.reversal({"p1": {"delta": 1.0}})))

pc = WT.pooled_comparison([
    {"comparison": "pooled", "delta": -2.6},
    {"comparison": "calendar", "delta": -2.3},
    {"comparison": "same developer", "delta": -2.1},
    {"comparison": "same developer and repo", "delta": -0.9}])
check("pooling inflates the lead", "pooling-inflates-lead" in kinds(pc), pc)
check("the lead shrinks as the comparison narrows",
      "lead-shrinks-with-control" in kinds(pc), pc)
check("one comparison is not enough",
      "not-enough-comparisons" in kinds(WT.pooled_comparison(
          [{"comparison": "pooled", "delta": -2.6}])))

pw = WT.power(30, 3, available=300)
check("a 3-point effect with sd 30 needs about 1570 developers",
      pw["needed"] == 1570, pw)
check("300 developers are underpowered", "underpowered" in kinds(pw), pw)
check("2000 developers are powered",
      "powered" in kinds(WT.power(30, 3, available=2000)))
check("an invalid input is refused", "invalid-power-input" in kinds(WT.power(0, 3)))
check("advise names every missing practice", len(WT.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", WT.advise(
    {k: True for k in ("reports_work_outcome", "holds_person_fixed", "has_control_group",
                       "uses_placebo", "checks_ceiling", "reports_interval",
                       "measures_actual_use", "estimates_power")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
