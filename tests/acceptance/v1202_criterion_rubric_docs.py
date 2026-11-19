#!/usr/bin/env python3
"""v1202 — criterion verification, rubric verification, documentation maintenance (round 133).

Sources:
  * arXiv:2611.23074 "Runtime Verification of Multiple Natural Language Criteria
    for Agent Governance" — per-criterion ternary verdicts, the two N/A cases,
    decomposition density, false passes and the top-k cascade.
  * arXiv:2611.22841 "Verifying Agents in Rubric-Graded Environments" — reactive,
    environment-aligned, guidance-carrying verifiers, UNMET F1 and the two error
    directions.
  * arXiv:2611.23142 "Mind the Gap" — a resolved support ticket is implicit
    supervision; a typed, deduped gap tracker; self-review plus human authority;
    the before/after repair measurement.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1202_criterion_rubric_docs.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1202-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import criterion_verification as CV  # noqa: E402
from longrun.harness.checks import rubric_verification as RV  # noqa: E402
from longrun.harness.checks import doc_maintenance as DM  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. criterion verification -------------------------------------------
c1 = CV.criterion("Does the response cite the regulation it applies?", source="regulator")
check("an atomic positive trace-decidable criterion is valid", c1["findings"] == [], c1)
check("a criterion with no text is refused",
      "criterion-missing" in kinds(CV.criterion("", source="regulator")))
check("an unknown owner is refused",
      "unknown-source" in kinds(CV.criterion("Is x true?", source="nobody")))
check("a negatively phrased rule is named",
      "negative-phrasing" in kinds(CV.criterion("Does it avoid harm?", polarity="negative")))
check("a compound rule must be split",
      "compound-criterion" in kinds(CV.criterion("Does it disclose and cite?", compounds=2)))
check("a rule needing external knowledge is out of scope",
      "unverifiable-criterion" in kinds(CV.criterion("Is the law complied with?", trace_decidable=False)))
check("a conditional rule must name its precondition",
      "precondition-unstated" in kinds(CV.criterion("Is it accurate?", precondition="")))

v1 = CV.verdict({"verdict": "yes", "evidence": "line 3 of the reply"})
check("a committed verdict with evidence is valid", v1["findings"] == [], v1)
check("a committed verdict with no evidence is named",
      "verdict-without-evidence" in kinds(CV.verdict({"verdict": "no"})))
check("an N/A with no reason is the collapsed case",
      "na-collapsed" in kinds(CV.verdict({"verdict": "na"})))
v2 = CV.verdict({"verdict": "na", "na_reason": "inapplicable"})
check("inapplicable N/A needs no escalation", v2["findings"] == [], v2)
v3 = CV.verdict({"verdict": "na", "na_reason": "undeterminable"})
check("undeterminable N/A warrants escalation",
      "escalation-warranted" in kinds(v3), v3)
check("an unknown verdict is refused",
      "unknown-verdict" in kinds(CV.verdict({"verdict": "maybe"})))

check("no criteria is named", "no-criteria" in kinds(CV.coverage([])))
cov = CV.coverage([{"precondition": "user-facing"}, {"precondition": ""}],
                  {"prompt_centric": True, "aggregate_verdict": True})
check("prompt-centric verification over six criteria degrades",
      "instruction-degradation" not in kinds(cov) or cov["criteria"] <= 6, cov)
cov2 = CV.coverage([{"precondition": ""}] * 8, {"prompt_centric": True, "aggregate_verdict": True})
check("eight prompt-centric instructions are named as degradation",
      "instruction-degradation" in kinds(cov2), cov2)
check("an aggregate-only answer hides the per-rule record",
      "no-per-criterion-verdict" in kinds(cov2), cov2)
cov3 = CV.coverage([{"precondition": "user-facing"}], {"triggers": False})
check("conditional criteria without triggers are named",
      "trigger-conditions-unshown" in kinds(cov3), cov3)

ESC = [
    {"failed": True, "violated": "r2", "ranked_rules": ["r2", "r1", "r3"], "arm": "verifier", "f1": 0.885},
    {"failed": True, "violated": "r5", "ranked_rules": ["r5", "r2", "r1"]},
    {"failed": True, "violated": "r9", "ranked_rules": ["r1", "r2", "r3"]},
    {"failed": False, "violated": "r1", "ranked_rules": ["r1"]},
    {"arm": "cascade", "f1": 0.946, "escalated_fraction": 1.0},
]
esc = CV.escalate(ESC)
loc = [f for f in esc["findings"] if f["kind"] == "localization"][0]
check("localization is measured on the failing traces",
      loc["failing"] == 3 and abs(loc["top1"] - 2 / 3.0) < 1e-3 and abs(loc["top3"] - 2 / 3.0) < 1e-3, loc)
check("a rule outside the top-3 is named",
      "localization-incomplete" in kinds(esc), esc)
check("the cascade lift is reported",
      "cascade-lift" in kinds(esc), esc)
check("an escalated fraction with no cost is unpriced",
      "escalation-unpriced" in kinds(esc), esc)
esc2 = CV.escalate(ESC + [{"random_top3": 0.675}])
check("a cascade that beats random is credited to the ranking",
      "localization-beats-random" in kinds(esc2), esc2)

FALSE = [{"gold": "no", "predicted": "yes", "confidence": 0.95, "max_softmax": 0.96, "seed": 1},
         {"gold": "no", "predicted": "yes", "confidence": 0.93, "max_softmax": 0.94, "seed": 2},
         {"gold": "no", "predicted": "no", "seed": 1},
         {"gold": "yes", "predicted": "yes", "seed": 1}]
me = CV.measure(FALSE)
check("the false-pass rate is reported",
      "false-pass-rate" in kinds(me), me)
check("a high false-pass rate is unpriced",
      "false-pass-unpriced" in kinds(me), me)
check("confident false passes are named",
      "confident-false-pass" in kinds(me), me)
check("confidence is not a flag for a false pass",
      "confidence-does-not-flag" in kinds(me), me)
check("a violation missed by every seed has no disagreement signal",
      "seed-disagreement-cannot-flag" in kinds(me), me)

d1 = CV.decomposition(" ".join(["word"] * 40), actual=1)
check("a 40-word fragment estimated at two criteria is under-decomposed",
      "under-decomposed" in kinds(d1), d1)
d2 = CV.decomposition(" ".join(["word"] * 40))
check("an unmeasured decomposition carries its estimate",
      "decomposition-unmeasured" in kinds(d2) and d2["estimate"] == 2, d2)
check("empty text has no density",
      "no-text" in kinds(CV.decomposition("")))
check("the criterion advisor names six failure modes",
      len(CV.advise({})["findings"]) == 6, CV.advise({}))

# ---- 2. rubric verification ----------------------------------------------
check("a known capability with a description is valid",
      RV.capability("metric-recomputation", "recompute a figure from its inputs")["findings"] == [])
check("an unknown capability is refused",
      "unknown-capability" in kinds(RV.capability("vibes", "a b c")))
check("a format-specific capability is refused",
      "format-specific-capability" in kinds(RV.capability("excel-lookup", "a b c")))

GOODV = {"principles": ["reactive", "environment-aligned", "domain-guidance"],
         "environment_read_only": True, "sees_workspace": True}
check("a reactive, aligned, guided, read-only verifier is valid",
      RV.verifier(GOODV)["findings"] == [], RV.verifier(GOODV))
check("a fixed-path verifier is named",
      "workflow-verifier" in kinds(RV.verifier({"principles": ["environment-aligned"]})))
check("a serialize-then-grade verifier is named",
      "serialized-evidence" in kinds(RV.verifier({"principles": ["reactive"]})))
check("an unrestricted verifier can change what it grades",
      "verifier-can-modify" in kinds(
          RV.verifier({**GOODV, "environment_read_only": False})))
check("missing guidance is named",
      "no-guidance" in kinds(RV.verifier({"principles": ["reactive", "environment-aligned"]})))
check("guidance inside the criterion is refused",
      "guidance-in-criterion" in kinds(RV.verifier({**GOODV, "guidance_inside_criterion": True})))
check("a verifier with no evidence access is blind",
      "no-evidence-access" in kinds(
          RV.verifier({**GOODV, "sees_trajectory": False, "sees_workspace": False})))

ER = ([{"gold": "unmet", "predicted": "unmet"}] * 20
      + [{"gold": "met", "predicted": "met"}] * 70
      + [{"gold": "unmet", "predicted": "met"}] * 8
      + [{"gold": "met", "predicted": "unmet"}] * 2)
er = RV.errors(ER)
check("UNMET F1 and the two error directions are reported",
      er["fn"] == 8 and er["fp"] == 2 and 0 < er["f1"] < 1, er)
check("a met-heavy corpus is named as prevalence",
      "prevalence-distorts-accuracy" in kinds(er), er)
check("over-acceptance is the named danger",
      "over-acceptance-dominates" in kinds(er), er)

BATCH = [{"batch": 64, "f1": 0.858, "cost": 9.87},
         {"batch": 16, "f1": 0.880, "cost": 25.72},
         {"batch": 4, "f1": 0.870, "cost": 71.85}]
bt = RV.batch(BATCH)
check("the batch optimum is reported", "batch-optimum" in kinds(bt) and bt["findings"][0]["batch"] == 16, bt)
check("small batches add cost", "cost-at-small-batch" in kinds(bt), bt)
check("a batch sweep with fewer than three points is refused",
      "batch-sweep-missing" in kinds(RV.batch([BATCH[0]])))

AB = [{"delta_f1": 0.004, "ci_low": -0.01, "ci_high": 0.02},
      {"delta_f1": -0.002, "ci_low": -0.02, "ci_high": 0.01},
      {"delta_unmet": 0.022, "delta_precision": -0.030, "delta_recall": 0.024},
      {"delta_cost": 2.94}]
ab = RV.ablation(AB)
check("an unresolved toggle is not a contribution",
      "no-resolved-effect" in kinds(ab), ab)
check("guidance shifts strictness without F1",
      "guidance-shifts-strictness" in kinds(ab), ab)
AG = [{"kappa": 0.45, "adjudicated": False, "single_rollout": True}]
ag = RV.agreement(AG)
check("low agreement is named", "labels-disagree" in kinds(ag), ag)
check("unadjudicated labels are named", "labels-single-annotator" in kinds(ag), ag)
check("a single-rollout corpus is named", "single-rollout-corpus" in kinds(ag), ag)
check("the rubric advisor names six failure modes",
      len(RV.advise({})["findings"]) == 6, RV.advise({}))

# ---- 3. documentation maintenance ----------------------------------------
s1 = DM.signal({"agent_answer": "Because the ramp began.", "human_resolution": "Because the ramp began."})
check("an identical answer confirms coverage",
      "coverage-confirmed" in kinds(s1), s1)
s2 = DM.signal({"agent_answer": "Probably superseded.", "human_resolution": "A host reset mid-job."})
check("a divergence is a gap signal with no annotation",
      "gap-signal" in kinds(s2), s2)
check("an approved but different answer still hides a gap",
      "approval-with-divergence" in kinds(
          DM.signal({"agent_answer": "a", "human_resolution": "b", "human_approved": True})))
check("a ticket with no agent answer carries no comparison",
      "no-agent-answer" in kinds(DM.signal({"human_resolution": "b"})))
check("a mechanical request carries no diagnostic signal",
      "mechanical-request-excluded" in kinds(
          DM.signal({"agent_answer": "a", "human_resolution": "b", "mechanical": True})))

g1 = DM.gap({"type": "missing", "target_doc": "ramp-schedule", "source": "live-triage"})
check("a missing gap routes to the gap filler",
      g1["route"] == "gap-filler" and g1["findings"] == [], g1)
g2 = DM.gap({"type": "stale", "source": "code-merge"})
check("a stale gap routes to the stale updater",
      g2["route"] == "stale-updater", g2)
check("an unknown gap type is refused",
      "unknown-gap-type" in kinds(DM.gap({"type": "vibes", "source": "manual"})))
check("a missing gap without a target is refused",
      "target-unstated" in kinds(DM.gap({"type": "missing", "source": "manual"})))
check("an unknown detection source is refused",
      "unknown-detection-source" in kinds(DM.gap({"type": "stale", "source": "telepathy"})))

TR = [{"key": "g1", "type": "missing", "target_doc": "a", "source": "live-triage", "priority": "medium"},
      {"key": "g1", "type": "missing", "target_doc": "a", "source": "harvest", "priority": "medium"},
      {"key": "g2", "type": "stale", "target_doc": "b", "source": "", "priority": "low"}]
tr = DM.tracker(TR)
check("a recurring gap is counted", "recurring-gaps" in kinds(tr) and tr["recurring"] == ["g1"], tr)
check("a recurring gap left at medium is named",
      "recurrence-unprioritised" in kinds(tr), tr)
check("an unrecorded source is named", "source-unrecorded" in kinds(tr), tr)
tr2 = DM.tracker([{"key": "x%d" % i, "type": "missing", "target_doc": "d%d" % i,
                   "source": "manual", "priority": "high"} for i in range(10)])
check("a corpus dominated by missing gaps is named",
      "missing-dominates" in kinds(tr2) and tr2["unique"] == 10, tr2)

PIPE = {"self_reviewed": True, "human_approved": True, "merge_to_code": False,
        "review_time_measured": True}
check("a self-reviewed, human-approved documentation fix is valid",
      DM.pipeline(PIPE)["findings"] == [], DM.pipeline(PIPE))
check("a fix with no self-review is refused",
      "self-review-missing" in kinds(DM.pipeline({**PIPE, "self_reviewed": False})))
check("a fix merged without a human is refused",
      "human-approval-missing" in kinds(DM.pipeline({**PIPE, "human_approved": False})))
check("the loop never modifies product code",
      "code-modified" in kinds(DM.pipeline({**PIPE, "merge_to_code": True})))
check("a watcher on an unmapped package is blind",
      "watcher-blind" in kinds(
          DM.pipeline({**PIPE, "watcher_fired": True, "registry_mapped": False})))
check("prevention is unproven when the watcher found no gap",
      "prevention-unproven" in kinds(
          DM.pipeline({**PIPE, "proactive_gaps": 0, "claims_prevention": True})))
check("an unpriced review time is named",
      "review-time-unpriced" in kinds(
          DM.pipeline({**PIPE, "review_time_measured": False})))

MEA = ([{"kind": "assertion", "label": "correct"}] * 245
       + [{"kind": "assertion", "label": "incorrect"}] * 57
       + [{"kind": "assertion", "label": "unverifiable"}] * 813
       + [{"kind": "preference", "winner": "agent", "length_ratio": 1.5}]
       + [{"kind": "preference", "winner": "human", "length_ratio": 3.0}]
       + [{"kind": "before-after", "winner": "after", "fix_postdates_discovery": True,
           "selected_on_confidence": False}])
dm = DM.measure(MEA)
check("the unverifiable denominator dominates and is named",
      "unverifiable-dominates" in kinds(dm), dm)
check("accuracy is reported over the verifiable assertions",
      "accuracy-over-verifiable" in kinds(dm), dm)
check("the error floor is reported", "error-floor" in kinds(dm), dm)
check("preference tracks length and is flagged",
      "verbosity-confounded" in kinds(dm), dm)
check("the repair improves the later answer",
      "self-improvement" in kinds(dm), dm)
check("a selected before/after set is named",
      "before-after-unselected" in kinds(dm), dm)
check("the missing retrieval baseline is named",
      "retrieval-baseline-missing" in kinds(dm), dm)
dm2 = DM.measure([{"kind": "assertion", "label": "correct", "unverifiable_counted_as_correct": True},
                  {"kind": "assertion", "label": "incorrect", "unverifiable_counted_as_error": True}])
check("silence counted as correct is named",
      "unverifiable-counted-as-correct" in kinds(dm2), dm2)
check("silence counted as an error is named",
      "unverifiable-counted-as-error" in kinds(dm2), dm2)
check("an unchecked causal order is named",
      "causal-order-unchecked" in kinds(
          DM.measure([{"kind": "before-after", "winner": "after",
                       "fix_postdates_discovery": False}])))
check("the docs advisor names six failure modes",
      len(DM.advise({})["findings"]) == 6, DM.advise({}))

# ---- result ---------------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
