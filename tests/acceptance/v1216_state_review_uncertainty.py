#!/usr/bin/env python3
"""v1216 — state–evidence handoff, evidence review, uncertainty context (round 147).

Sources:
  * arXiv:2611.24357 "Semantic Context Handoff" — the typed semantic state, the
    sparse delta and deterministic reconciliation, acknowledgement as
    visibility-only, ranked revision-aware recovery, its caps, locality, the
    exact McNemar comparison and the token/time benefit.
  * arXiv:2611.24353 "When Figures Disagree with Text" — the four nested
    outcomes, the aided arms, shortlist recall and the oracle gap, the
    evidence-type split, assertion against diagnosis, the instrument checks,
    the near-miss taxonomy and the repeat band.
  * arXiv:2611.24351 "Tell Me How Sure You Are" — the paired uncertainty delta,
    the alignment control, the evidence budget, harmful flips, the correctness
    probe, downstream entropy and prompt sensitivity.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1216_state_review_uncertainty.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1216-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import state_evidence as SE    # noqa: E402
from longrun.harness import evidence_review as ER   # noqa: E402
from longrun.harness import uncertainty_context as UC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. state–evidence handoff (SCH) -----------------------------------
st = SE.state([
    {"id": "c1", "kind": "constraint"},
    {"id": "f1", "kind": "fact"},
    {"id": "h1", "kind": "hypothesis"},
    {"id": "w1", "kind": "work", "status": "open"},
    {"id": "w2", "kind": "work", "status": "completed"},
])
check("a typed state is valid", st["verdict"] == "state-valid")
check("the kinds are counted", st["counts"] == {"constraint": 1, "fact": 1,
                                                "hypothesis": 1, "work": 2})
check("a duplicate id is named",
      SE.state([{"id": "a", "kind": "fact"}, {"id": "a", "kind": "fact"}])
      ["verdict"] == "state-invalid")
check("an unknown kind is named",
      SE.state([{"id": "a", "kind": "vibe"}])["bad_kind"] == ["a"])
check("an invalid work status is named",
      SE.state([{"id": "w", "kind": "work", "status": "done"}])["bad_status"] == ["w"])

BASE = [{"id": "f1", "kind": "fact", "support": ["4"]},
        {"id": "w1", "kind": "work", "status": "open"}]
add = SE.apply_delta({"state": BASE, "evidence_ids": ["4", "7"],
                      "delta": {"ops": [{"op": "add_fact", "id": "f2",
                                         "support": ["7"]}]}})
check("a supported fact is added", add["verdict"] == "delta-applied")
check("the new fact is in the state",
      any(e["id"] == "f2" for e in add["state"]))
check("an unknown evidence id is rejected",
      SE.apply_delta({"state": BASE, "evidence_ids": [],
                      "delta": {"ops": [{"op": "add_fact", "id": "f2",
                                         "support": ["9"]}]}})["rejected"][0]
      ["reason"] == "unknown-evidence")
check("a duplicate id is rejected",
      SE.apply_delta({"state": BASE, "evidence_ids": ["4"],
                      "delta": {"ops": [{"op": "add_fact", "id": "f1",
                                         "support": ["4"]}]}})["rejected"][0]
      ["reason"] == "duplicate-id")
check("completion without evidence is rejected",
      SE.apply_delta({"state": BASE, "evidence_ids": [],
                      "delta": {"ops": [{"op": "complete_work", "id": "w1"}]}})
      ["rejected"][0]["reason"] == "completion-without-evidence")
completed = SE.apply_delta({"state": BASE, "evidence_ids": ["4"],
                            "delta": {"ops": [{"op": "complete_work", "id": "w1",
                                               "support": ["4"]}]}})
check("completion with evidence is applied", completed["verdict"] == "delta-applied")
check("the work item is marked completed",
      [e for e in completed["state"] if e["id"] == "w1"][0]["status"] == "completed")
check("reopening a completed item is allowed",
      SE.apply_delta({"state": completed["state"], "evidence_ids": ["4"],
                      "delta": {"ops": [{"op": "reopen_work", "id": "w1"}]}})
      ["verdict"] == "delta-applied")
check("reopening an open item is rejected",
      SE.apply_delta({"state": BASE, "evidence_ids": ["4"],
                      "delta": {"ops": [{"op": "reopen_work", "id": "w1"}]}})
      ["rejected"][0]["reason"] == "reopen-not-closed")
check("revising a hypothesis is not a fact revision",
      SE.apply_delta({"state": [{"id": "h1", "kind": "hypothesis"}],
                      "evidence_ids": [],
                      "delta": {"ops": [{"op": "revise_fact", "id": "h1"}]}})
      ["rejected"][0]["reason"] == "not-a-fact")
check("dropping a fact removes it",
      SE.apply_delta({"state": BASE, "evidence_ids": ["4"],
                      "delta": {"ops": [{"op": "drop_fact", "id": "f1"}]}})["state"]
      == [{"id": "w1", "kind": "work", "status": "open"}])
check("an unknown op is rejected",
      SE.apply_delta({"state": BASE, "evidence_ids": [],
                      "delta": {"ops": [{"op": "rewrite_all"}]}})["rejected"][0]
      ["reason"] == "unknown-op")

ack = SE.acknowledge({"pending": ["5", "6"], "acknowledge": ["5"],
                      "archive": ["5", "4"]})
check("an acknowledged step leaves pending", ack["pending"] == ["6"])
check("the archived record stays", "5" in ack["archived"])
check("acknowledgement is visibility, not deletion",
      ack["verdict"] == "visibility-not-deletion")

RECOVER = {
    "state": [
        {"id": "f1", "kind": "fact", "support": ["7"]},
        {"id": "w1", "kind": "work", "status": "completed", "support": ["9"]},
        {"id": "w2", "kind": "work", "status": "open", "support": ["14"]},
    ],
    "evidence": [
        {"step": "3", "safety": True},
        {"step": "7", "path": "a.py", "terms": ["zero"]},
        {"step": "9", "terms": ["matrix"]},
        {"step": "14", "path": "a.py", "terms": ["zero"]},
        {"step": "40", "terms": ["zero", "matrix"]},
        {"step": "48", "terms": ["zero"]},
        {"step": "49", "terms": ["zero"]},
        {"step": "50", "terms": ["zero"]},
    ],
    "terms": ["zero", "matrix"], "paths": ["a.py"],
    "pending": ["48"], "revision": True,
}
rec = SE.recover(RECOVER)
steps = {row["step"]: row["route"] for row in rec["selected"]}
check("active support is recovered", steps.get("7") == "support")
check("open-work support is recovered", steps.get("14") == "support")
check("revision activates completed-work provenance", steps.get("9") == "revision")
check("an orphan with two term matches is recovered", steps.get("40") == "orphan")
check("a safety record is recovered", steps.get("3") == "safety")
check("recent records fill the tail", steps.get("50") == "recent")
check("pending evidence is excluded", "48" not in steps)
check("the excluded pending step is named", rec["excluded_pending"] == ["48"])
no_rev = SE.recover(dict(RECOVER, revision=False))
check("without revision the completed provenance is not a route",
      "revision" not in {row["route"] for row in no_rev["selected"]})
check("no evidence is not a recovery",
      SE.recover({"state": [], "evidence": []})["verdict"] == "nothing-to-recover")
capped = SE.recover(dict(RECOVER, caps={"steps": 3}))
check("the global step cap is applied", len(capped["selected"]) == 3)

loc = SE.locality([{"age": 20}] * 13 + [{"age": 5}] * 6 + [{"age": 2}])
check("the mean age is reported", close(loc["mean_age"], 14.6))
check("the share older than three steps is 95%", close(loc["over_three"], 0.95))
check("the share older than ten steps is 65%", close(loc["over_ten"], 0.65))
check("recovery reaches far back", loc["verdict"] == "non-local-recovery")
check("a recent-only replay is local",
      SE.locality([{"age": 1}, {"age": 2}])["verdict"] == "local-recovery")
check("no replays is not a locality claim",
      SE.locality([])["verdict"] == "no-replays")

check("a bounded replay with no pending is bounded",
      SE.budget({"state_chars": 10000, "replay_chars": 9000, "steps": 10})
      ["verdict"] == "bounded")
check("an uncapped pending tail is named",
      SE.budget({"state_chars": 10000, "replay_chars": 9000, "steps": 10,
                 "pending_chars": 5000})["verdict"] == "bounded-replay-unbounded-total")
check("an exceeded cap is named",
      SE.budget({"state_chars": 13000, "pending_chars": 1, "pending_cap": 100})
      ["verdict"] == "budget-exceeded")

m1 = SE.paired({"only_a": 15, "only_b": 4})
check("15 against 4 discordant pairs gives p 0.0192", close(m1["p"], 0.0192, 1e-4))
check("the paired improvement is named", m1["verdict"] == "paired-improvement")
m2 = SE.paired({"only_a": 14, "only_b": 4})
check("14 against 4 gives p 0.0309", close(m2["p"], 0.0309, 1e-4))
check("no discordant pairs is a null",
      SE.paired({"only_a": 0, "only_b": 0})["verdict"] == "no-discordant-pairs")
check("a reversal is inconclusive",
      SE.paired({"only_a": 2, "only_b": 9})["verdict"] == "paired-inconclusive")

ben = SE.benefit([
    {"arm": "baseline", "pass_at_1": 0.8378, "tokens": 367900, "time_s": 400.2},
    {"arm": "sch", "pass_at_1": 0.8689, "tokens": 208600, "time_s": 237.1},
])
check("the token reduction is 43.3%", close(ben["arms"]["sch"]["token_reduction"],
                                            1 - 208600 / 367900, 1e-6))
check("the time reduction is 40.8%", close(ben["arms"]["sch"]["time_reduction"],
                                           1 - 237.1 / 400.2, 1e-6))
check("the best pass rate is named", ben["best"] == "sch")
check("no arms is not a benefit", SE.benefit([])["verdict"] == "no-arms")

check("the audit names summary-only",
      "summary-only" in kinds(SE.audit({"summary_only": True})))
check("the audit names recency-only",
      "recency-only" in kinds(SE.audit({"recency_only": True})))
check("the audit names deletion-as-visibility",
      "deletion-as-visibility" in kinds(SE.audit({"deletion_as_visibility": True})))
check("the audit names provenance-as-entailment",
      "provenance-as-entailment" in kinds(SE.audit({"provenance_as_entailment": True})))
check("an empty profile raises seven checks", len(SE.advise({})["findings"]) == 7)
check("a complete profile raises none",
      SE.advise({k: True for k in (
          "separates_state_from_evidence", "proposes_sparse_deltas",
          "keeps_state_non_self_sufficient", "keeps_acknowledged_evidence_addressable",
          "reopens_completed_work_on_failure", "ranks_recovery_with_fallbacks",
          "accounts_for_pending_evidence")})["findings"] == [])

# ---- 2. evidence review (figures versus text) --------------------------
check("four outcomes are defined", len(ER.outcomes()["outcomes"]) == 4)
check("three steps are defined", len(ER.outcomes()["steps"]) == 3)

paper = ([{}] * 569 + [{"mention": True}] * 494
         + [{"mention": True, "concern": True}] * 335
         + [{"diagnose": True}] * 47)
pr = ER.rates(paper)
check("the paper's S1 is 60.62%", close(pr["S1"], 876 / 1445, 1e-9))
check("the paper's S2 is 26.44%", close(pr["S2"], 382 / 1445, 1e-9))
check("the paper's S3 is 3.25%", close(pr["S3"], 47 / 1445, 1e-9))
check("the rates are nested", pr["nested_ok"] is True)
check("an empty cohort is not a rate", ER.rates([])["verdict"] == "no-reviews")

aided = ER.aided([
    {"arm": "unprompted", "rate": 0.0430},
    {"arm": "named", "rate": 0.2043},
    {"arm": "consistency", "rate": 0.0699},
    {"arm": "shortlist", "rate": 0.0484},
])
check("naming the figure is decisive", aided["decisive"] == "named")
check("the naming gain is 16.13 points", close(aided["decisive_delta"], 0.1613, 1e-9))
check("an aid of 16 points counts", aided["verdict"] == "aid-helps")
check("an aid of 3 points is inert",
      ER.aided([{"arm": "unprompted", "rate": 0.04},
                {"arm": "consistency", "rate": 0.07}])["verdict"] == "aid-inert")
check("a missing baseline is named", ER.aided([{"arm": "named", "rate": 0.2}])
      ["verdict"] == "no-baseline")

short = ER.shortlist({"recall_at_3": 0.3441, "recall_at_5": 0.5753,
                      "end_to_end": 0.0484, "unprompted": 0.0430,
                      "named": 0.2043})
check("the shortlist recovers 3.3% of the oracle gain",
      close(short["share_recovered"], (0.0484 - 0.0430) / (0.2043 - 0.0430), 1e-9))
check("a 34% shortlist recall is a selection limit",
      short["verdict"] == "selection-limit")

etype = ER.evidence_type([
    {"evidence": "figure_only", "arm": "text_only", "rate": 0.0},
    {"evidence": "figure_only", "arm": "unprompted", "rate": 0.017},
    {"evidence": "figure_only", "arm": "named", "rate": 0.158},
    {"evidence": "also_text", "arm": "text_only", "rate": 0.061},
    {"evidence": "also_text", "arm": "named", "rate": 0.288},
])
check("a figure-only contradiction needs the pixels",
      etype["verdict"] == "pixels-required")
check("the text-supported group is reported",
      close(etype["groups"]["also_text"]["text_only"], 0.061))

ass = ER.assertion([
    {"arm": "unprompted", "rubric": 0.0430, "panel": 0.2258},
    {"arm": "named", "rubric": 0.2043, "panel": 0.4409},
    {"arm": "consistency", "rubric": 0.0699, "panel": 0.5376},
])
check("asserting a conflict is not diagnosing it",
      ass["verdict"] == "assertion-not-diagnosis")
check("the largest panel-minus-rubric gap is reported",
      close(ass["max_gap"], (0.5376 - 0.2258) - (0.0699 - 0.0430), 1e-9))

inst = ER.instrument({"primary": 0.0325, "replay": 0.0274,
                      "human_precision": 0.526, "human_recall": 1.0})
check("a 52.6% human precision is a lenient rubric",
      inst["verdict"] == "rubric-lenient")
check("the human-confirmed upper bound is 1.71%",
      close(inst["human_confirmed_upper_bound"], 0.0325 * 0.526, 1e-9))
check("a precise instrument is supported",
      ER.instrument({"primary": 0.03, "human_precision": 0.9})["verdict"]
      == "rubric-supported")

nm = ER.near_miss([{"label": "wrong_target", "count": 523},
                   {"label": "wrong_relation", "count": 107},
                   {"label": "quote", "count": 7}])
check("wrong target dominates the near misses",
      nm["verdict"] == "wrong-target-dominates")
check("the wrong-relation share is 16.8%",
      close(nm["shares"]["wrong_relation"], 107 / 637, 1e-9))
check("no near misses is not a taxonomy",
      ER.near_miss([])["verdict"] == "no-near-misses")

check("an 0.87-point shift is inside a 3.5-point band",
      ER.noise({"repeat_band_s3": -0.035, "delta_s3": 0.0087})["verdict"]
      == "within-noise")
check("a 10-point shift is beyond it",
      ER.noise({"repeat_band_s3": -0.035, "delta_s3": 0.10})["verdict"]
      == "beyond-noise")

check("the audit names mentions-as-verification",
      "mentions-as-verification" in kinds(ER.audit({"mentions_as_verification": True})))
check("the audit names guided-as-autonomous",
      "guided-as-autonomous" in kinds(ER.audit({"guided_as_autonomous": True})))
check("the audit names a missing repeat band",
      "no-repeat-band" in kinds(ER.audit({"no_repeat_band": True})))
check("the audit names text-only extrapolation",
      "text-only-extrapolation" in kinds(ER.audit({"text_only_extrapolation": True})))
check("an empty profile raises seven checks", len(ER.advise({})["findings"]) == 7)
check("a complete profile raises none",
      ER.advise({k: True for k in (
          "reveals_the_target", "scores_the_specific_claim",
          "keeps_the_rendered_source", "reports_by_evidence_type",
          "separates_assertion_from_diagnosis", "validates_the_rubric",
          "measures_the_repeat_band")})["findings"] == [])

# ---- 3. uncertainty context -------------------------------------------
sun = UC.paired({"aux": 0.6066, "aux_unc": 0.8684})
check("SUN K=10 is +26.18 points", close(sun["delta_pp"], 26.18, 1e-6))
check("a positive paired delta helps", sun["verdict"] == "uncertainty-helps")
check("an equal score is no gain",
      UC.paired({"aux": 0.5, "aux_unc": 0.5})["verdict"] == "no-gain")
check("a lower score hurts",
      UC.paired({"aux": 0.5, "aux_unc": 0.45})["verdict"] == "hurts")
check("a missing arm is refused",
      UC.paired({"aux": 0.5})["verdict"] == "insufficient-input")

al = UC.alignment([
    {"model": "Qwen3-32B", "none": 0.3902, "true": 0.6562, "shuffled": 0.4609},
    {"model": "Llama-3.1-8B", "none": 0.5630, "true": 0.6800, "shuffled": 0.5398},
    {"model": "Phi-4-14B", "none": 0.3846, "true": 0.6439, "shuffled": 0.4694},
])
check("true beats no uncertainty by 26.60 points on Qwen",
      close(al["rows"][0]["true_minus_none"], 26.60, 1e-6))
check("true beats shuffled by 14.02 points at the margin",
      close(al["smallest_margin_pp"], 14.02, 1e-6))
check("alignment is required", al["verdict"] == "alignment-required")
check("a mixed result is partial",
      UC.alignment([{"model": "m", "none": 0.5, "true": 0.52,
                     "shuffled": 0.60}])["verdict"] == "alignment-partial")

sub = UC.subset([
    {"model": "Qwen3-32B", "k": 3, "delta_pp": 7.09},
    {"model": "Qwen3-32B", "k": 5, "delta_pp": 2.17},
    {"model": "Qwen3-32B", "k": 8, "delta_pp": 19.62},
    {"model": "Qwen3-32B", "k": 10, "delta_pp": 26.18},
    {"model": "Llama-3.1-8B", "k": 3, "delta_pp": 3.63},
    {"model": "Llama-3.1-8B", "k": 5, "delta_pp": -0.18},
    {"model": "Llama-3.1-8B", "k": 8, "delta_pp": 4.69},
    {"model": "Llama-3.1-8B", "k": 10, "delta_pp": 5.93},
])
check("the gain grows with the evidence budget", sub["verdict"] == "gain-grows-with-k")
check("Qwen's 26.18-point gain is the best",
      close(sub["trends"]["Qwen3-32B"]["largest_delta"], 26.18))

fl = UC.flips({"aux_flips": 13, "aux_unc_flips": 3})
check("the harmful transitions fall by 76.9%", close(fl["reduction"], 10 / 13, 1e-9))
check("uncertainty sanitises the mixed set", fl["verdict"] == "uncertainty-sanitizes")
check("no flips is not a sanitising claim",
      UC.flips({"aux_flips": 0, "aux_unc_flips": 0})["verdict"] == "no-flips-to-reduce")

cor = UC.correctness([
    {"model": "Qwen3-32B", "features": "blip", "auroc": 0.8002},
    {"model": "Phi-4-14B", "features": "blip", "auroc": 0.8150},
    {"model": "Qwen2-VL-7B", "features": "confidence", "auroc": 0.6388},
])
check("the best AUROC is Phi-4's 0.815", close(cor["best"]["auroc"], 0.8150))
check("upstream uncertainty predicts correctness",
      cor["verdict"] == "uncertainty-predicts-correctness")
check("a 0.60 AUROC is weak",
      UC.correctness([{"model": "m", "features": "f", "auroc": 0.60}])["verdict"]
      == "weak-signal")
check("a 0.50 AUROC is chance",
      UC.correctness([{"model": "m", "features": "f", "auroc": 0.50}])["verdict"]
      == "chance")

ent = UC.entropy([
    {"transition": "incorrect->correct", "delta_h": 0.0125},
    {"transition": "incorrect->correct", "delta_h": 0.0457},
    {"transition": "correct->incorrect", "delta_h": -0.0089},
])
check("a corrected decision need not lower entropy",
      ent["verdict"] == "decisions-improve-without-entropy-drop")
check("only improvements are counted", ent["improvements"] == 2)

sen = UC.sensitivity([{"gain_pp": 10.40}, {"gain_pp": 3.33}, {"gain_pp": 10.14}])
check("the gain survives every prompt", sen["verdict"] == "gain-direction-stable")
check("a 50% split is prompt-dependent",
      UC.sensitivity([{"gain_pp": 9.3}, {"gain_pp": -1.9}])["verdict"]
      == "prompt-dependent")
check("the range is reported",
      close(UC.sensitivity([{"gain_pp": 1}, {"gain_pp": -2}])["min_pp"], -2.0))

check("the audit names aggregate-only",
      "aggregate-only" in kinds(UC.audit({"aggregate_only": True})))
check("the audit names a missing alignment control",
      "no-alignment-control" in kinds(UC.audit({"no_alignment_control": True})))
check("the audit names a missing paired design",
      "no-paired-design" in kinds(UC.audit({"no_paired_design": True})))
check("the audit names entropy-as-correctness",
      "entropy-as-correctness" in kinds(UC.audit({"entropy_as_correctness": True})))
check("an empty profile raises seven checks", len(UC.advise({})["findings"]) == 7)
check("a complete profile raises none",
      UC.advise({k: True for k in (
          "communicates_source_uncertainty", "holds_the_evidence_fixed",
          "keeps_the_source_representation", "controls_the_alignment",
          "reports_paired_deltas", "probes_downstream_correctness",
          "reports_downstream_entropy")})["findings"] == [])

# ---- 4. the three modules are independent and pure ---------------------
check("state–evidence names its format", SE.FORMAT == "longrun-state-evidence/1")
check("evidence review names its format", ER.FORMAT == "longrun-evidence-review/1")
check("uncertainty context names its format",
      UC.FORMAT == "longrun-uncertainty-context/1")
check("the work lifecycle has three states",
      SE.WORK_STATES == ("open", "blocked", "completed"))
check("the review outcomes are the paper's four", ER.OUTCOMES ==
      ("omit", "mention", "concern", "diagnose"))
check("the three steps are named", ER.STEPS == ("discover", "align", "verify"))

passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
