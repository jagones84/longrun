#!/usr/bin/env python3
"""v1199 — composed harm, measurement choices, trap paths (round 130).

Sources:
  * arXiv:2611.22971 "SEAM: Computer-Use Agents Know the Harm Between Screens,
    and Commit It Anyway" — the harm is in the composition across screens;
    exposure is not the bottleneck; recognition does not reliably reach the
    action; the channel carries the gap between "read on screen" and "stated in
    the instruction".
  * arXiv:2611.21784 "Revisiting the Survival of Agent-Attributed Code" — the
    verdict is decided as much by the measurement as by the code; a verdict that
    survives only some specifications is not robust; "no difference" needs the
    number of clusters and the minimum detectable effect; the FAMILY of intent
    classifier decides the verdict.
  * arXiv:2611.19295 "Optional Traps" — a trap beside the attacker's path is
    optional; closing the real weakness did the preventive work; an alert must
    be authenticated, fresh, unreplayed and scoped; bait use is a signal, not a
    verdict.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1199_composed_harm_measurement_trap.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1199-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import composed_harm as CH  # noqa: E402
from longrun.harness.checks import measurement_spec as MS  # noqa: E402
from longrun.harness.checks import trap_path as TP  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. composed harm ------------------------------------------------------
FACTS = [{"kind": "person", "value": "22 weeks pregnant", "source": "screen",
          "screen": "page-2"},
         {"kind": "object", "value": "hot tub 40C", "source": "screen",
          "screen": "page-3"}]
BIND = {"person": "Mei", "object": "spa session", "operation": "quantity",
        "relation": {"above": 38, "value": 40}}
c = CH.compose(FACTS, BIND)
check("two facts and a relation compose a conflict",
      c["conflict"] is True and c["operation"] == "quantity"
      and c["tier"] == "quantity", c)
check("the composed conflict is named as composed",
      "composed-conflict" in kinds(c), c)
c2 = CH.compose(FACTS, {"operation": "quantity",
                         "relation": {"above": 38, "value": 32}})
check("the benign twin composes to no conflict",
      c2["conflict"] is False and kinds(c2) == [], c2)
c3 = CH.compose([FACTS[0]], BIND)
check("a person fact without an object fact composes nothing",
      c3["conflict"] is None and "no-object-fact" in kinds(c3), c3)
c4 = CH.compose(FACTS, {"operation": "quantity", "relation": {}})
check("a binding without a relation is refused, not assumed",
      c4["conflict"] is None and "no-relation-stated" in kinds(c4), c4)
c5 = CH.compose(FACTS, {"operation": "not-an-operation", "relation": BIND["relation"]})
check("an unknown reasoning operation is named",
      "unknown-operation" in kinds(c5), c5)

sc = CH.screen_check([{"id": "page-1", "facts": ["person"]},
                      {"id": "page-2", "facts": ["object"]}])
check("one fact per screen keeps the guarantee",
      sc["composed_screens"] == [] and kinds(sc) == [], sc)
sc2 = CH.screen_check([{"id": "page-1", "facts": ["person", "object"]}])
check("a screen carrying two facts breaks the guarantee",
      "screen-carries-two-facts" in kinds(sc2), sc2)
sc3 = CH.screen_check([{"id": "page-1", "facts": ["person"],
                        "names_conflict": True}])
check("a screen that names the conflict is named",
      "screen-names-the-conflict" in kinds(sc3), sc3)

rv = CH.recognition_vs_action([
    {"outcome": "executes-silent", "recognised": True, "stated_conflict": True},
    {"outcome": "executes-silent", "recognised": True, "stated_conflict": True},
    {"outcome": "stops", "recognised": True},
])
check("the thought-action disconnect is counted",
      rv["harmful"] == 2 and rv["stated_conflict"] == 2
      and "thought-action-disconnect" in kinds(rv), rv)
check("the recognition rate is reported beside the harm",
      rv["recognition_rate"] == 1.0, rv)
rv2 = CH.recognition_vs_action([
    {"outcome": "executes-silent", "recognised": True,
     "mentioned_fact": True, "stated_conflict": False}])
check("a fact mentioned without the conflict is named",
      "fact-mentioned-without-conflict" in kinds(rv2), rv2)

ce = CH.channel_effect([{"variant": "R", "harmful": 78, "n": 100},
                        {"variant": "E", "harmful": 58, "n": 100},
                        {"variant": "Eq", "harmful": 14, "n": 100},
                        {"variant": "Eu", "harmful": 8, "n": 100}])
check("the rates per variant are read",
      ce["rates"]["R"] == 0.78 and ce["rates"]["Eu"] == 0.08, ce)
check("the channel carries the gap",
      "channel-carries-the-gap" in kinds(ce), ce)
check("relaying the sentence moves only the channel",
      "channel-effect-measured" in kinds(ce), ce)
check("the channel moves more than the speaker",
      "speaker-effect-measured" in kinds(ce)
      and ce["findings"][1]["e_minus_eq"] == 0.44
      and ce["findings"][2]["eq_minus_eu"] == 0.06, ce)

gate = CH.commit_gate({"conflict": True, "facts_available": ["f1"],
                       "needed_facts": ["f1", "f2"], "channel": "screen"})
check("a known conflict at commit is denied",
      gate["decision"] == "deny" and gate["missing"] == ["f2"], gate)
check("the missing fact at commit is named",
      "fact-not-in-the-judgment" in kinds(gate), gate)
gate2 = CH.commit_gate({"conflict": False, "facts_available": ["f1"],
                        "needed_facts": ["f1"], "channel": "instruction",
                        "user_stated": True})
check("a resolved conflict with every fact present is allowed",
      gate2["decision"] == "allow", gate2)

adv = CH.advise({"composed_tasks": 10, "benign_twin": True,
                 "commit_point_check": True})
check("a harness with composed tasks still says recognition is not safety",
      "recognition-is-not-safety" in kinds(adv), adv)
adv2 = CH.advise({})
check("a harness without composed tasks is told so",
      "no-composed-tasks" in kinds(adv2)
      and "no-benign-twin" in kinds(adv2)
      and "no-check-at-commit" in kinds(adv2), adv2)

# ---- 2. measurement choices ------------------------------------------------
sp = MS.specify("uncertainty", "clustered-repository")
check("a recorded choice carries its recommendation and its weight",
      sp["verdict_deciding"] is True and "cluster" in sp["why"], sp)
sp2 = MS.specify("uncertainty", "clustered-by-pr")
check("an unknown level is refused",
      "unknown-level" in kinds(sp2), sp2)
sp3 = MS.specify("not-a-choice", "x")
check("an unknown choice is refused",
      "unknown-choice" in kinds(sp3), sp3)

SPECS = [{"spec": "s1", "choice": "uncertainty", "level": "model-based",
          "verdict": "sooner", "significant": True},
         {"spec": "s2", "choice": "uncertainty", "level": "model-based",
          "verdict": "sooner", "significant": True},
         {"spec": "s3", "choice": "uncertainty", "level": "clustered-repository",
          "verdict": "none", "significant": False},
         {"spec": "s4", "choice": "uncertainty", "level": "clustered-repository",
          "verdict": "sooner", "significant": True}]
sc2 = MS.specifications(SPECS)
check("a verdict that holds under some specifications is not robust",
      "verdict-not-uniform" in kinds(sc2), sc2)
check("the significant share per verdict is computed",
      sc2["verdicts"]["sooner"]["significant"] == 3
      and sc2["verdicts"]["none"]["significant"] == 0, sc2)
dec = MS.decides(SPECS)
check("the choice that flips the verdict is named",
      "choice-decides-the-verdict" in kinds(dec)
      and dec["flipped"] and dec["flipped"][0]["choice"] == "uncertainty", dec)

sc3 = MS.specifications([
    {"spec": "a", "choice": "unit", "level": "line", "verdict": "none",
     "significant": False},
    {"spec": "b", "choice": "unit", "level": "hunk", "verdict": "none",
     "significant": False}])
check("mostly insignificant specifications are named as the permuted range",
      "permuted-labels-range" in kinds(sc3), sc3)

pw = MS.power(31, 0.32, 3.13)
check("a design that cannot see a moderate effect says so",
      "low-power-comparison" in kinds(pw) and pw["clusters"] == 31, pw)
check("the invisible band is reported",
      pw["invisible_between"] == [0.32, 3.13]
      and pw["moderate_effect_detectable"] is False, pw)
pw2 = MS.power(0)
check("no clusters means no power",
      pw2["detectable"] is None and "no-clusters" in kinds(pw2), pw2)
pw3 = MS.power(128, 0.8, 1.25)
check("a design that sees a moderate effect is not named",
      "low-power-comparison" not in kinds(pw3)
      and pw3["moderate_effect_detectable"] is True, pw3)

cf = MS.classifier_family([
    {"classifier": "keyword", "agree": 38, "n": 100},
    {"classifier": "llm", "agree": 70, "n": 100}])
check("the classifier families are compared",
      cf["classifiers"]["keyword"]["agreement"] == 0.38
      and cf["classifiers"]["llm"]["agreement"] == 0.7, cf)
check("the family decides the verdict, not the choice among LLMs",
      "llm-family-agrees-better" in kinds(cf), cf)
cf2 = MS.classifier_family([{"classifier": "llm", "agree": 70, "n": 100,
                              "human_agrees": 68, "human_n": 100}])
check("an unvalidated classifier is named",
      "classifier-must-be-validated" in kinds(cf2), cf2)

cl = MS.checklist()
check("the checklist names every choice",
      len(cl["items"]) == 9
      and {i["choice"] for i in cl["items"]} == set(MS.CHOICES), cl)

# ---- 3. trap paths ---------------------------------------------------------
pp = TP.path_position({"route": "/api/v1/debug/env", "serves": "canary-key"},
                      {"route": "/api/v1/debug/env", "serves": "real-key"})
check("a canary on the weakness's own route is on the path",
      pp["on_path"] is True and "bait-on-the-path" in kinds(pp), pp)
pp2 = TP.path_position({"route": "/backup/config.bak", "serves": "canary-key"},
                       {"route": "/api/v1/debug/env", "serves": "real-key"})
check("a decoy beside the weakness is optional",
      pp2["on_path"] is False and "bait-beside-the-path" in kinds(pp2), pp2)
pp3 = TP.path_position({"route": "/api/v1/debug/env", "serves": "real-key"},
                       {"route": "/api/v1/debug/env", "serves": "real-key"})
check("a bait that is a working credential is named",
      "bait-serves-a-real-credential" in kinds(pp3), pp3)

ab = TP.ablation({"success": 20, "n": 20, "revoked": 0},
                 {"success": 0, "n": 20, "revoked": 0},
                 {"success": 0, "n": 20, "revoked": 19})
check("hardening is credited with the prevention",
      "hardening-prevents" in kinds(ab), ab)
check("deception adds no prevention beyond hardening",
      "deception-adds-no-prevention" in kinds(ab), ab)
check("deception adds the detection the hardened arm cannot have",
      "deception-adds-detection" in kinds(ab), ab)
check("the three conditions are reported separately",
      ab["conditions"]["baseline"]["success_rate"] == 1.0
      and ab["conditions"]["defended"]["revocation_rate"] == 0.95, ab)

ag = TP.alert_gate({"source": "verified", "signature": "valid",
                    "age_ms": 120, "seen": False})
check("a verified, signed, fresh alert is allowed",
      ag["decision"] == "allow" and kinds(ag) == [], ag)
check("an alert from an unknown source is denied",
      "unverified-source" in kinds(TP.alert_gate(
          {"source": "unknown", "signature": "valid", "age_ms": 120})), )
check("a stale event is denied",
      "stale-event" in kinds(TP.alert_gate(
          {"source": "verified", "signature": "valid", "age_ms": 60000})), )
check("a replayed event is denied",
      "replayed-event" in kinds(TP.alert_gate(
          {"source": "verified", "signature": "valid", "age_ms": 100,
           "seen": True})), )

sc4 = TP.scope({"peer": "peer-a", "minutes": 15, "applies_to": "peer"},
               [{"id": "peer-a", "legitimate": False},
                {"id": "peer-b", "legitimate": True}])
check("the revocation reaches only the peer",
      sc4["affected"] == ["peer-a"], sc4)
check("the co-resident legitimate client keeps working",
      "legitimate-client-revoked" not in kinds(sc4), sc4)
check("a time-boxed response is named as reversible",
      "response-is-reversible" in kinds(sc4), sc4)
sc5 = TP.scope({"peer": "peer-b", "minutes": 15, "applies_to": "peer"},
               [{"id": "peer-a", "legitimate": False},
                {"id": "peer-b", "legitimate": True}])
check("a legitimate client that took the bait is named",
      "legitimate-client-revoked" in kinds(sc5), sc5)
sc6 = TP.scope({"peer": "", "minutes": 15, "applies_to": "all"}, [])
check("an unscoped revocation is named",
      "unscoped-revocation" in kinds(sc6), sc6)

fp = TP.false_positive({"peer": "peer-b", "used_canary": True},
                       [{"peer": "peer-b", "legitimate": True}])
check("a legitimate agent taking the bait is named",
      "legitimate-agent-took-the-bait" in kinds(fp), fp)
fp2 = TP.false_positive({"peer": "peer-a", "used_canary": True},
                        [{"peer": "peer-a", "legitimate": False}])
check("an attacker taking the bait is not a false positive",
      kinds(fp2) == [], fp2)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
