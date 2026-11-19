#!/usr/bin/env python3
"""v1198 — reversibility classes, gain control, history truth (round 129).

Sources:
  * arXiv:2611.22075 "Can You Undo It?" — exact restoration needs recorded
    state, authority to write it back and no outside observation; disclosure is
    R4 and cannot be lowered; a capture-based override needs a confirmed
    capture; a restoration check must preserve later work; the measured replay
    is a coverage/burden trade-off, not a free win.
  * arXiv:2611.20736 "GainCtrl" — the expected positive remaining gain over a
    reference score; one predictor serves ten references by interpolation; T
    uses the attempt's own score and P the retained portfolio; the threshold is
    calibrated under a quality-loss allowance with a full-execution fallback;
    binary rewards collapse the two configurations.
  * arXiv:2611.14654 "Cleaning an Agent's History Hurts When the World Still
    Holds the Error" — the same correct value helps as a truthful note and
    hurts as the agent's own completed action; the record's effect flips sign
    with the world; a policy must be judged against the world.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1198_reversibility_gain_history.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1198-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import reversibility as RV  # noqa: E402
from longrun.harness.checks import gain_control as GC  # noqa: E402
from longrun.harness.checks import history_truth as HT  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. reversibility classes ----------------------------------------------
REC = {"class": "R1",
       "rules": [{"id": "read-path", "when": {"argument": "mode", "equals": "read"},
                  "class": "R0"}]}
CALL = {"tool": "fs.write", "arguments": {"mode": "read", "path": "/tmp/a"}}
out = RV.classify(CALL, REC)
check("a matching ordered rule selects the narrower class",
      out["class"] == "R0" and out["rule"] == "read-path", out)
CALL2 = {"tool": "fs.write", "arguments": {"mode": "write", "path": "/tmp/a"}}
out2 = RV.classify(CALL2, REC)
check("unmatched arguments keep the base class",
      out2["class"] == "R1" and "unmatched-arguments-keep-base" in kinds(out2), out2)
out3 = RV.classify(CALL2, None)
check("an unrecognized call is R4",
      out3["class"] == "R4" and "unclassified-call-defaults-r4" in kinds(out3), out3)

DISC = {"tool": "chat.post", "arguments": {}, "disclosure": True}
REC_D = {"class": "R0", "rules": [{"id": "low", "when": {"argument": "x", "equals": "1"},
                                   "class": "R0"}]}
out4 = RV.classify(DISC, REC_D)
check("a disclosure is R4 even when a rule would lower it",
      out4["class"] == "R4" and "disclosure-not-lowerable" in kinds(out4), out4)

NEG = {"class": "R1", "rules": [{"id": "neg", "when": {"argument": "mode",
                                                       "not_equals": "read"},
                                  "class": "R0"}]}
out5 = RV.classify({"tool": "t", "arguments": {"mode": "write"}}, NEG)
check("a lowering rule must name a positive form, not an absence",
      out5["class"] == "R1", out5)

st = RV.restoration_requirements({"prior_state_recorded": True,
                                  "principal_can_write": False,
                                  "outside_observed": True})
check("exact restoration needs all three requirements",
      st["exact_restoration"] is False
      and "no-authority-to-restore" in kinds(st)
      and "outside-observation" in kinds(st), st)
check("an audit log alone is not restoration",
      "audit-log-is-not-restoration" in kinds(st))
st2 = RV.restoration_requirements({"prior_state_recorded": True,
                                   "principal_can_write": True,
                                   "outside_observed": False})
check("all three requirements make restoration exact",
      st2["exact_restoration"] is True and kinds(st2) == [], st2)

h = RV.hint_class({"read_only": True})
check("a read-only hint maps to R0", h["class"] == "R0", h)
h2 = RV.hint_class({"read_only": False, "open_world": True})
check("an open-world hint maps to R4", h2["class"] == "R4", h2)
h3 = RV.hint_class({"read_only": False, "open_world": False, "destructive": True})
check("a closed-world destructive hint maps to R3", h3["class"] == "R3", h3)
h4 = RV.hint_class({"read_only": False, "open_world": False, "destructive": False})
check("a closed-world non-destructive hint maps to R1", h4["class"] == "R1", h4)
check("the hint mapping cannot express R2",
      "hint-mapping-cannot-express-r2" in kinds(h4))
check("untrusted annotations are flagged",
      "annotations-untrusted" in kinds(RV.hint_class({"read_only": True})))

cap = RV.capture_override("R4", {"class": "R1",
                                 "capture": {"state": "bytes", "restore": "cp",
                                             "retention": "7d", "confirmed": True},
                                 "scope": ["private-file"],
                                 "capture_ref": "cap-1"})
check("a confirmed, bounded capture supports the declared class",
      cap["class"] == "R1" and cap["capture_confirmed"] is True, cap)
cap2 = RV.capture_override("R4", {"class": "R1",
                                  "capture": {"state": "bytes", "restore": "cp",
                                              "retention": "7d", "confirmed": False},
                                  "scope": ["private-file"]})
check("an unconfirmed capture reverts to the underlying class",
      cap2["class"] == "R4" and "capture-unconfirmed-falls-back" in kinds(cap2), cap2)
cap3 = RV.capture_override("R4", {"class": "R1",
                                  "capture": {"state": "bytes", "restore": "cp",
                                              "retention": "7d", "confirmed": True},
                                  "scope": ["private-file", "payments"]})
check("a capture cannot justify an override over payments",
      cap3["class"] == "R4" and "capture-scope-too-broad" in kinds(cap3), cap3)
cap4 = RV.capture_override("R4", {"class": "R1",
                                  "capture": {"state": "bytes", "restore": "cp",
                                              "retention": "7d", "confirmed": True},
                                  "scope": ["private-file"]})
check("a captured decision without a reference is flagged",
      "capture-reference-missing" in kinds(cap4), cap4)

p = RV.policy_for("R4")
check("R4 is never autonomous", p["autonomy"] == "never-autonomous", p)
check("the hook asks for R2-R4 and leaves R0-R1 to the client",
      RV.policy_for("R0")["hook"] == "no-decision"
      and RV.policy_for("R2")["hook"] == "ask"
      and RV.policy_for("R1")["hook"] == "no-decision")

rec = RV.recovery([
    {"policy": "snapshot", "initial_state_matched": True,
     "later_work_preserved": False},
    {"policy": "snapshot", "initial_state_matched": True,
     "later_work_preserved": True},
    {"policy": "guard", "initial_state_matched": False, "deferred": True},
    {"policy": "merge", "initial_state_matched": True,
     "later_work_preserved": True, "state_complete": False},
])
check("a snapshot that erases later work is named",
      rec["policies"]["snapshot"]["erases-later-work"] == 1
      and "erases-later-work" in kinds(rec), rec)
check("deferral is not counted as recovery",
      rec["policies"]["guard"]["deferred"] == 1
      and "deferral-is-not-recovery" in kinds(rec), rec)
check("a partially restoring route is named",
      "recovery-route-partial" in kinds(rec), rec)

rep = RV.replay([
    {"policy": "read-write-proxy", "attack_gated": 18, "attack_denominator": 29,
     "benign_approvals": 1895, "benign_runs": 1209},
    {"policy": "session-guard", "attack_gated": 29, "attack_denominator": 29,
     "benign_approvals": 1904, "benign_runs": 1209,
     "depends_on_web_exposure": True},
], "read-write-proxy")
check("coverage is measured on the attributable denominator",
      rep["policies"]["session-guard"]["coverage"] == 1.0
      and rep["policies"]["read-write-proxy"]["coverage"] == 0.6207, rep)
check("more coverage came with no fewer approval points",
      "coverage-gain-is-not-free" in kinds(rep), rep)
check("the coverage difference is flagged as modelling-dependent",
      "coverage-is-modelling-dependent" in kinds(rep), rep)
check("the denominator is named as selective",
      "attack-coverage-denominator-is-selective" in kinds(rep), rep)

# ---- 2. gain control -------------------------------------------------------
gv = GC.gain_vector(0.62)
check("the gain vector holds ten references",
      len(gv["gains"]) == 10 and gv["gains"][0] == 0.62
      and gv["gains"][6] == 0.02 and gv["gains"][7] == 0.0, gv)
check("only outcomes above the reference contribute",
      gv["gains"][5] == 0.12, gv)

GAINS = [0.70, 0.66, 0.60, 0.52, 0.44, 0.20, 0.14, 0.08, 0.03, 0.0]
ip = GC.interpolate(GAINS, 0.55)
check("the gain at an arbitrary reference is interpolated",
      abs(ip["gain"] - 0.17) < 1e-9 and ip["method"] == "interpolated", ip)
check("a reference of 1 admits no gain",
      GC.interpolate(GAINS, 1.0)["gain"] == 0.0)
check("a gain vector without its grid is refused",
      GC.interpolate([0.20, 0.14], 0.55)["gain"] is None)

r = GC.reference("trajectory", 0.4, 0.7)
check("the trajectory reference is the attempt's own score",
      r["reference"] == 0.4, r)
r2 = GC.reference("portfolio", 0.4, 0.7)
check("the portfolio reference is the retained best",
      r2["reference"] == 0.7, r2)
r3 = GC.reference("portfolio", 0.8, 0.7)
check("a better attempt than the portfolio keeps its own reference",
      r3["reference"] == 0.8, r3)

gains = [0.0] * 5 + [0.20] + [0.14] + [0.0] * 3
d = GC.decide(gains, "trajectory", 0.5, 0.5, 0.17)
check("a gain above the threshold continues", d["decision"] == "continue", d)
d2 = GC.decide(gains, "trajectory", 0.5, 0.5, 0.25)
check("a gain at or below the threshold stops the attempt",
      d2["decision"] == "stop", d2)
d3 = GC.decide(gains, "portfolio", 0.5, 0.7, 0.17)
check("the portfolio reference reads the gain at a different point",
      d3["decision"] == "stop", d3)

be = GC.binary_equivalent([0.0, 0.0, 0.0])
check("with binary rewards and no success the two configurations agree",
      be["equivalent"] is True, be)
be2 = GC.binary_equivalent([0.0, 1.0])
check("a success ends the task, so the equivalence no longer holds",
      be2["equivalent"] is False and be2["succeeded"] is True, be2)
be3 = GC.binary_equivalent([0.0, 0.5])
check("a non-binary reward breaks the equivalence",
      be3["equivalent"] is False, be3)

cal = GC.calibrate([
    {"threshold": 0.01, "quality": {1: 50.0, 2: 49.0},
     "tokens": {1: 100.0, 2: 190.0}},
    {"threshold": 0.5, "quality": {1: 40.0, 2: 38.0},
     "tokens": {1: 60.0, 2: 110.0}},
], {"quality": {1: 50.0, 2: 50.0}, "tokens": {1: 100.0, 2: 200.0}}, 0.05)
check("a threshold outside the allowance is discarded",
      cal["threshold"] == 0.01
      and "allowance-exceeded" in kinds(cal), cal)
cal2 = GC.calibrate([
    {"threshold": 0.5, "quality": {1: 40.0, 2: 38.0},
     "tokens": {1: 60.0, 2: 110.0}},
], {"quality": {1: 50.0, 2: 50.0}, "tokens": {1: 100.0, 2: 200.0}}, 0.05)
check("no surviving threshold falls back to full execution",
      cal2["threshold"] is None and cal2["fallback"] == "full-execution"
      and "fallback-to-full-execution" in kinds(cal2), cal2)
cal3 = GC.calibrate([
    {"threshold": 0.01, "quality": {1: 50.0}, "tokens": {1: 100.0}},
    {"threshold": 0.02, "quality": {1: 50.0}, "tokens": {1: 80.0}},
], {"quality": {1: 50.0}, "tokens": {1: 100.0}}, 0.05)
check("among the survivors the cheapest average cost wins",
      cal3["threshold"] == 0.02, cal3)

fr = GC.frontier([
    {"quality": 40.0, "tokens": 100.0},
    {"quality": 50.0, "tokens": 150.0},
    {"quality": 45.0, "tokens": 200.0},
])
check("a dominated point leaves the frontier",
      len(fr["frontier"]) == 2, fr)
mq = GC.matched_quality([
    {"quality": 40.0, "tokens": 100.0},
    {"quality": 50.0, "tokens": 200.0},
], 45.0)
check("a matched quality is read on the frontier",
      mq["method"] == "interpolated" and mq["cost"] > 100.0
      and mq["cost"] < 200.0, mq)
mq2 = GC.matched_quality([{"quality": 60.0, "tokens": 100.0}], 45.0)
check("a target already met reports the observed point and its surplus",
      mq2["method"] == "observed" and mq2["surplus"] == 15.0, mq2)

v = GC.verdict(27.31, [14.23, 41.54], 0.975)
check("an interval excluding zero resolves away from zero",
      v["verdict"] == "resolved-away-from-zero"
      and v["direction"] == "positive", v)
v2 = GC.verdict(2.38, [-6.35, 11.11], 0.975)
check("an interval including zero is unresolved, not absent",
      v2["verdict"] == "unresolved", v2)
v3 = GC.verdict(-6.43, [-8.88, -3.97])
check("a negative interval resolves in the negative direction",
      v3["direction"] == "negative", v3)

adv = GC.advise({"validation_tasks": 200, "recorded_trajectories": 900,
                 "intermediate_feedback": True, "threshold": 0.01,
                 "checkpoints": [2, 6, 10]})
check("a calibrated controller states its mode and checkpoints",
      adv["mode"] == "trajectory" and adv["checkpoints"] == [2, 6, 10], adv)
check("the environment cost exclusion is always named",
      "environment-cost-excluded" in kinds(adv), adv)
adv2 = GC.advise({})
check("an uncalibrated controller says so",
      "no-validation-tasks" in kinds(adv2)
      and "no-recorded-trajectories" in kinds(adv2), adv2)
adv3 = GC.advise({"best_previous": 0.4, "binary_rewards": False})
check("a portfolio needs a retained best",
      adv3["mode"] == "portfolio", adv3)
adv4 = GC.advise({"binary_rewards": True})
check("binary rewards collapse the two configurations",
      "binary-rewards-collapse-configurations" in kinds(adv4), adv4)

# ---- 3. history truth ------------------------------------------------------
ag = HT.agreement({"receipt": "success"}, {"effect": "absent"})
check("a success receipt over an absent effect is a disagreement",
      ag["agreement"] == "disagreeing"
      and "record-world-disagreement" in kinds(ag), ag)
ag2 = HT.agreement({"receipt": "failure"}, {"effect": "absent"})
check("a failure receipt over an absent effect agrees",
      ag2["agreement"] == "consistent", ag2)
ag3 = HT.agreement({"receipt": "success"}, {"effect": "present"})
check("a success receipt over a present effect agrees",
      ag3["agreement"] == "consistent", ag3)
ag4 = HT.agreement({}, {})
check("an unknown receipt and world cannot be compared",
      ag4["agreement"] == "unknown", ag4)

dva = HT.disclosure_vs_assertion({"discloses": "slot-3", "asserts": "done",
                                  "author": "agent"})
check("a record that both discloses and asserts is flagged",
      "disclosure-and-assertion-coupled" in kinds(dva), dva)
check("the agent's own completed action is named",
      "agent-asserts-completion" in kinds(dva), dva)
dva2 = HT.disclosure_vs_assertion({"discloses": "slot-3", "asserts": None,
                                   "author": "user"})
check("a note that discloses without asserting is not coupled",
      "disclosure-and-assertion-coupled" not in kinds(dva2), dva2)

eff = HT.effect({"original": 0.5013, "falsified": 0.4370,
                 "truthful": 0.6578, "neutral": 0.5057})
check("the truthful note helps by 15.20 points",
      abs(eff["t_minus_n"] - 0.1521) < 1e-6, eff)
check("the falsified record hurts by 6.43 points",
      abs(eff["f_minus_o"] - (-0.0643)) < 1e-6, eff)
check("the gap between the two edits is 21.63 points",
      abs(eff["d"] - 0.2164) < 1e-6, eff)
check("the sign reversal is named",
      "sign-reversal" in kinds(eff), eff)
check("the matched neutral append has its own separate effect",
      "append-effect-is-separate" in kinds(eff), eff)
eff2 = HT.effect({"original": 0.5, "truthful": 0.5})
check("the four arms are all required",
      eff2["d"] is None, eff2)

inter = HT.interaction({"success_present": 0.4885, "success_absent": 0.2846,
                         "failure_present": 0.3846, "failure_absent": 0.4538})
check("the record's effect flips sign with the world",
      inter["effect_when_present"] > 0 > inter["effect_when_absent"]
      and "sign-reversal-with-the-world" in kinds(inter), inter)
check("the interaction is the difference of the two effects",
      abs(inter["interaction"]
          - (inter["effect_when_present"] - inter["effect_when_absent"])) < 1e-9,
      inter)
check("the agreeing cells are close",
      inter["agreeing_cell_gap"] < 0.05, inter)

rc = HT.recheck([
    {"receipt": "success", "effect": "absent", "reissued": 1},
    {"receipt": "success", "effect": "absent", "reissued": 1},
    {"receipt": "success", "effect": "present", "reissued": 0},
    {"receipt": "success", "effect": "present", "reissued": 0},
    {"receipt": "failure", "effect": "present", "reissued": 1},
])
check("the re-issue rate is read per receipt and world",
      rc["cells"]["success/absent"]["reissue_rate"] == 1.0
      and rc["cells"]["success/present"]["reissue_rate"] == 0.0, rc)
check("the re-issue tracks the world",
      "reissue-tracks-the-world" in kinds(rc), rc)
check("a false failure receipt duplicates work",
      "false-failure-receipt-duplicates-work" in kinds(rc), rc)

adv5 = HT.advise({"kind": "compaction", "edits_history": True,
                  "asserts_completion": True, "world_repaired": False})
check("a clean record over a dirty world is named",
      "clean-record-over-dirty-world" in kinds(adv5), adv5)
check("the policy is judged against the world",
      "judge-the-policy-against-the-world" in kinds(adv5), adv5)
check("prevalence is never claimed",
      "prevalence-unmeasured" in kinds(adv5), adv5)
check("an adversary is never bounded",
      "adversary-not-bounded" in kinds(adv5), adv5)
adv6 = HT.advise({"kind": "handoff", "edits_history": True,
                  "world_repaired": True})
check("a repaired world changes the recommendation",
      adv6["recommendation"] == "clean-the-record-after-repair", adv6)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
