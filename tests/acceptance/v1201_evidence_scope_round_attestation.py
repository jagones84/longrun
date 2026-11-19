#!/usr/bin/env python3
"""v1201 — evidence scope, the between-round decision, and build trust (round 132).

Sources:
  * arXiv:2611.22835 "When Passing Checks Do Not Establish Completion" — a
    finite evidence item is (source, check, phase, operation, witness); a
    requested check is not target entry, a positive witness is not the intended
    operation, and cleanup evidence cannot discharge live forwarding.
  * arXiv:2611.22661 "The Between-Round Decision in Autonomous Research" — a
    Champion that never regresses, factual-only lessons, a four-part decision
    object, code guardrails, and a context ladder that improves monotonically.
  * arXiv:2611.23202 "Agent Trust Infrastructure" — identity from the key hash,
    a federated certificate, attestation of the approved build, per-call policy
    and a signed hash-chained log.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1201_evidence_scope_round_attestation.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1201-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import evidence_scope as ES  # noqa: E402
from longrun.harness.checks import round_controller as RC  # noqa: E402
from longrun.harness.checks import attestation_trust as AT  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. evidence scope ----------------------------------------------------
ev = ES.item("sha-abc", "test_flush", "body", "explicit-flush", "underlying flush called")
check("a complete evidence item binds source, check, phase, operation and witness",
      ev["complete"] is True and ev["findings"] == [], ev)
missing = ES.item("sha-abc", "test_flush", "body", "explicit-flush", "")
check("an item with no witness is incomplete",
      missing["complete"] is False and "witness-missing" in kinds(missing), missing)
bad_phase = ES.item("sha", "c", "sideways", "op", "w")
check("a phase outside the vocabulary is refused",
      "unknown-phase" in kinds(bad_phase), bad_phase)

s1 = ES.scope({"facts": {"exit": 0}, "verdict": "abstain", "authorized_scope": "issue",
               "observed_scope": "issue"})
check("correct facts without a finite verdict are named",
      "facts-without-verdict" in kinds(s1), s1)
s2 = ES.scope({"verdict": "fixed", "authorized_scope": "issue"})
check("a verdict with no facts cannot be audited",
      "verdict-without-facts" in kinds(s2), s2)
s3 = ES.scope({"facts": {"exit": 0}, "verdict": "fixed"})
check("a claim that names no authorized scope is refused",
      "scope-unstated" in kinds(s3), s3)
s4 = ES.scope({"facts": {"exit": 0}, "verdict": "fixed",
               "authorized_scope": "changed-check", "observed_scope": "whole-suite"})
check("a check that ran at one scope is not a claim at another",
      "out-of-scope" in kinds(s4), s4)
s5 = ES.scope({"facts": {"exit": 0}, "verdict": "fixed",
               "authorized_scope": "changed-check", "observed_scope": "changed-check"})
check("a claim inside its scope has no scope finding", s5["findings"] == [], s5)

w1 = ES.witness(ev, "explicit-flush")
check("a witness attributed to the claimed operation holds", w1["attributed"] is True, w1)
w2 = ES.witness(ES.item("sha", "c", "body", "write-side-flush", "underlying flush called"),
                "explicit-flush")
check("a write-side witness is not evidence for explicit forwarding",
      "witness-from-other-operation" in kinds(w2), w2)
w3 = ES.witness(ES.item("sha", "c", "setup", "explicit-flush", "w"), "explicit-flush")
check("a pre-measurement phase cannot witness a measured operation",
      "witness-before-measurement" in kinds(w3), w3)
w4 = ES.witness({"item": {"phase": "body", "operation": "explicit-flush"},
                 "producers": ["write", "cleanup"]}, "explicit-flush")
check("one boolean with two producers cannot bind a claim",
      "positive-witness-ambiguous" in kinds(w4), w4)
w5 = ES.witness({"item": {"phase": "body", "operation": "explicit-flush"}}, "explicit-flush")
check("a witness with no recorded producer is named",
      "witness-not-attributed" in kinds(w5), w5)

o1 = ES.obligation(ES.item("sha", "c", "cleanup", "explicit-flush", "w"), "live-forwarding")
check("cleanup context cannot discharge live forwarding",
      "cleanup-is-not-live" in kinds(o1) and o1["discharged"] is False, o1)
o2 = ES.obligation(ev, "live-forwarding")
check("live explicit forwarding is discharged by a body witness", o2["discharged"] is True, o2)
o3 = ES.obligation(ev, "cleanup-forwarding")
check("a body observation does not discharge the cleanup obligation",
      "cleanup-obligation-unmeasured" in kinds(o3), o3)
o4 = ES.obligation({**ev, "write_only_supported": None}, "write-only-compatibility")
check("a compatibility obligation with no write-only run is unpriced",
      "compatibility-unmeasured" in kinds(o4), o4)
o5 = ES.obligation({**ev, "write_only_supported": False}, "write-only-compatibility")
check("a repair that breaks a write-only sink is named",
      "write-only-broken" in kinds(o5), o5)
o6 = ES.obligation({**ev, "write_only_supported": True}, "write-only-compatibility")
check("a write-only control that still holds discharges the obligation",
      o6["discharged"] is True, o6)
o7 = ES.obligation(ev, "teleportation")
check("an obligation outside the vocabulary is refused",
      "unknown-obligation" in kinds(o7), o7)

r1 = ES.reachability({"target_entered": False, "outcomes": ["unknown", "unknown"]})
check("a check that never reached its target is named",
      "reachability-obstructed" in kinds(r1), r1)
r2 = ES.reachability({"target_entered": True, "outcomes": ["unknown"],
                      "unknown_counted_as_fail": True})
check("a runner error before entry is UNKNOWN, not FAIL",
      "unknown-read-as-fail" in kinds(r2), r2)
r3 = ES.reachability({"target_entered": True, "outcomes": ["pass"],
                      "startup_edited": True})
check("a substituted startup context is a different experiment",
      "altered-context" in kinds(r3), r3)

c1 = ES.classify({"original": "FAIL", "candidate": "PASS", "reference": "PASS"})
check("a candidate that matches the reference is repaired, not a regression",
      c1["label"] == "repaired" and c1["findings"] == [], c1)
c2 = ES.classify({"original": "FAIL", "candidate": "FAIL", "reference": "PASS"})
check("a candidate unchanged from the original is a residual defect",
      c2["label"] == "residual-defect", c2)
c3 = ES.classify({"original": "FAIL", "candidate": "OTHER", "reference": "PASS"})
check("a candidate that matches neither is a new regression",
      c3["label"] == "new-regression", c3)
c4 = ES.classify({"original": "PASS", "candidate": "FAIL", "reference": "PASS",
                  "altered_context": True})
check("an altered context is labelled before any regression claim",
      c4["label"] == "altered-context", c4)
c5 = ES.classify({"original": "FAIL", "candidate": "PASS", "reference": "FAIL"})
check("a check that cannot separate original from reference proves nothing",
      "non-discriminating-check" in kinds(c5), c5)

e1 = ES.explanation({"repair_succeeded": True,
                     "claims": ["iterator equality", "array equality"],
                     "replayed": {"iterator equality": True, "array equality": False}})
check("a successful repair does not certify a false claim in its explanation",
      "repair-success-does-not-certify-explanation" in kinds(e1)
      and e1["unsupported"] == ["array equality"], e1)
e2 = ES.explanation({"repair_succeeded": True, "claims": ["x"], "replayed": {}})
check("an explanation that was never replayed is not evidence",
      "explanation-unreplayed" in kinds(e2), e2)
e3 = ES.explanation({"repair_succeeded": True, "claims": ["x"],
                     "replayed": {"x": True}})
check("a replayed explanation has no finding", e3["findings"] == [], e3)

adv1 = ES.advise({})
check("the evidence-scope advisor names the six failure modes",
      len(adv1["findings"]) == 6, adv1)

# ---- 2. the between-round decision ---------------------------------------
ROUNDS = [
    {"round": 1, "floor": 0.4382, "direction": "lower",
     "candidates": [{"id": "r1a", "metric": 0.4608}, {"id": "r1b", "metric": 0.4609}]},
    {"round": 4, "direction": "lower",
     "candidates": [{"id": "r4a", "metric": 0.4226, "signature": "cross-channel"}]},
    {"round": 5, "direction": "lower",
     "candidates": [{"id": "r5a", "metric": 0.4193}]},
    {"round": 7, "direction": "lower",
     "candidates": [{"id": "r7a", "metric": 0.4172}]},
]
ch = RC.champion(ROUNDS)
check("the Champion is the best verified candidate, not the last",
      ch["champion"]["id"] == "r7a" and ch["champion"]["metric"] == 0.4172, ch)
check("a candidate that does not beat the floor never becomes the Champion",
      [h["id"] for h in ch["history"]] == ["r4a", "r5a", "r7a"], ch["history"])
ch2 = RC.champion([{"round": 1, "candidates": [{"id": "x"}]}])
check("an unverified candidate cannot become a Champion",
      "candidate-without-metric" in kinds(ch2), ch2)

d1 = RC.decision({"mode": "explore", "base": "champion",
                  "instruction": "attack cross-channel dependence toward the 0.42 level",
                  "hard_constraints": [{"text": "keep the split", "check": "split unchanged"}],
                  "rationale": "R4 found the line; R5 moved it"})
check("a well-formed document decision has no finding", d1["findings"] == [], d1)
d2 = RC.decision({"mode": "pivot", "base": "champion", "instruction": "x", "rationale": "y"})
check("a mode outside the vocabulary is refused", "unknown-mode" in kinds(d2), d2)
d3 = RC.decision({"mode": "exploit", "base": "baseline", "instruction": "tune",
                  "rationale": "y"})
check("an exploit on the baseline is refused",
      "exploit-on-baseline" in kinds(d3), d3)
d4 = RC.decision({"mode": "explore", "base": "baseline",
                  "instruction": " ".join(["word"] * 41), "rationale": "y"})
check("an instruction over 40 words is refused",
      "instruction-too-long" in kinds(d4), d4)
d5 = RC.decision({"mode": "exploit", "base": "champion",
                  "instruction": "(1) raise lr (2) add llrd", "rationale": "y"})
check("a recipe is not a goal-level instruction",
      "instruction-is-a-recipe" in kinds(d5), d5)
d6 = RC.decision({"mode": "explore", "base": "baseline", "instruction": "go",
                  "hard_constraints": [{"text": "a", "check": "a"},
                                       {"text": "b", "check": "b"},
                                       {"text": "c", "check": "c"},
                                       {"text": "d", "check": "d"}],
                  "rationale": "y"})
check("more than three hard constraints is refused",
      "too-many-constraints" in kinds(d6), d6)
d7 = RC.decision({"mode": "explore", "base": "baseline", "instruction": "go",
                  "hard_constraints": ["be better"], "rationale": "y"})
check("a constraint with no check is uncheckable",
      "constraint-uncheckable" in kinds(d7), d7)
d8 = RC.decision({"mode": "explore", "base": "baseline", "instruction": "go"})
check("a decision with no rationale is refused",
      "rationale-missing" in kinds(d8), d8)
d9 = RC.decision({"mode": "stop", "base": "champion", "instruction": ""})
check("a stop chooses no base", "stop-with-base" in kinds(d9), d9)

l1 = RC.lesson({"lesson": "R4 scored 0.4226; R5 scored 0.4193", "best_metric": 0.4193,
                "results": [{"metric": 0.4193}]})
check("a factual lesson has no finding", l1["findings"] == [], l1)
l2 = RC.lesson({"lesson": "the gain happened because of cross-channel modelling",
                "best_metric": 0.42, "results": [{"metric": 0.42}]})
check("a lesson that attributes a cause is refused",
      "lesson-attributed" in kinds(l2), l2)
l3 = RC.lesson({"lesson": "tried three", "results": [{"metric": 0.42}]})
check("a lesson with no recorded best metric is incomplete",
      "lesson-without-measurement" in kinds(l3), l3)
l4 = RC.lesson({"lesson": "three candidates", "best_metric": 0.42,
                "results": [{"metric": None}, {"metric": None}]})
check("a failed candidate keeps its diagnosis",
      "failed-candidates-dropped" in kinds(l4), l4)

g1 = RC.guardrails({"mode": "exploit", "base": "champion"},
                   {"has_champion": False, "rounds_total": 10, "rounds_done": 1})
check("a code guardrail starts from the baseline before a Champion exists",
      g1["effective"] == {"mode": "explore", "base": "baseline"}
      and "exploit-before-champion" in kinds(g1), g1)
g2 = RC.guardrails({"mode": "explore", "base": "baseline"},
                   {"has_champion": True, "rounds_total": 10, "rounds_done": 8})
check("the closing 30% allows only refining or stopping",
      g2["effective"] == {"mode": "exploit", "base": "champion"}
      and "closing-phase-explore" in kinds(g2), g2)
g3 = RC.guardrails({"mode": "explore", "base": "champion"},
                   {"has_champion": True, "rounds_total": 10, "rounds_done": 2,
                    "stall_count": 3})
check("a fourth stalled extension becomes a new line",
      g3["effective"] == {"mode": "explore", "base": "baseline"}
      and "stall-forces-new-line" in kinds(g3), g3)
g4 = RC.guardrails({"mode": "stop", "base": ""},
                   {"has_champion": True, "improved_last_two": True})
check("a stop after an improvement is refused",
      g4["effective"] == {"mode": "exploit", "base": "champion"}
      and "stop-after-improvement" in kinds(g4), g4)

LADDER = [{"reads": "none", "score": 0.4299, "direction": "lower"},
          {"reads": "last", "score": 0.4244, "direction": "lower"},
          {"reads": "full", "score": 0.4172, "direction": "lower"}]
cl = RC.context_ladder(LADDER)
check("performance improves monotonically as more evidence is read",
      "context-helps" in kinds(cl) and "full-context-not-read" not in kinds(cl), cl)
cl2 = RC.context_ladder([{"reads": "none", "score": 0.40, "direction": "lower"},
                         {"reads": "full", "score": 0.45, "direction": "lower"}])
check("a ladder where more evidence hurts is named",
      "context-does-not-help" in kinds(cl2), cl2)

pr = RC.progress(ROUNDS)
check("a non-improving round costs nothing already won",
      "unproductive-rounds-free" in kinds(pr) and pr["champion"]["id"] == "r7a", pr)
fr = RC.frontier({"abandoned_champion": True, "frontier_metric": 0.4331,
                  "frontier_reproduced": False})
check("an unreached published number does not outrank a validated Champion",
      "local-evidence-overridden" in kinds(fr), fr)

adv2 = RC.advise({})
check("the round-controller advisor names the six failure modes",
      len(adv2["findings"]) == 6, adv2)

# ---- 3. attestation and accountability -----------------------------------
i1 = AT.identity({"aid": "h1", "key_hash": "h1", "signature_ok": True})
check("a keyed, signed request with an ID derived from the key is valid",
      i1["findings"] == [], i1)
i2 = AT.identity({"aid": "", "key_hash": ""})
check("a request with no key is anonymous",
      "anonymous-request" in kinds(i2), i2)
i3 = AT.identity({"aid": "alice", "key_hash": "h1", "signature_ok": True})
check("a free identifier is not an agent identity",
      "aid-not-key-hash" in kinds(i3), i3)
i4 = AT.identity({"aid": "h1", "key_hash": "h1", "signature_ok": False})
check("an invalid signature is refused", "signature-invalid" in kinds(i4), i4)

FED = ("org1-ca", "org2-ca")
good = {"issuer": "org1-ca", "org": "org1", "ca_org": "org1", "aid": "h1", "key_hash": "h1",
        "not_before": 1, "not_after": 100, "now": 50, "revoked": False,
        "validity_signed": True}
check("a federated, in-window, unrevoked certificate passes",
      AT.certificate(good, FED)["findings"] == [], AT.certificate(good, FED))
check("a certificate from outside the federation is refused",
      "ca-not-federated" in kinds(AT.certificate({**good, "issuer": "org9-ca"}, FED)))
check("a CA that vouches for another organization is refused",
      "issuer-vouches-other-org" in kinds(
          AT.certificate({**good, "org": "org2", "ca_org": "org1"}, FED)))
check("an expired certificate is refused",
      "cert-expired" in kinds(AT.certificate({**good, "now": 101}, FED)))
check("a revoked peer is refused",
      "peer-revoked" in kinds(AT.certificate({**good, "revoked": True}, FED)))
check("an expiry stored outside the signed data is named",
      "validity-outside-signed-payload" in kinds(
          AT.certificate({**good, "validity_signed": False}, FED)))

APPROVED = {"model": "m1", "tools": ["web_search"], "prompt_hash": "p1"}
BUILD = {"model": "m1", "tools": ["web_search"], "prompt_hash": "p1", "host_trusted": True}
check("the approved build passes attestation",
      AT.attestation(BUILD, APPROVED)["findings"] == [], AT.attestation(BUILD, APPROVED))
check("a swapped model is named even with a valid certificate",
      "model-substituted" in kinds(AT.attestation({**BUILD, "model": "m2"}, APPROVED)))
a_tool = AT.attestation({**BUILD, "tools": ["web_search", "poisoned"]}, APPROVED)
check("an extra tool is a tampered build",
      "tool-tampered" in kinds(a_tool) and a_tool["findings"][0]["extra"] == ["poisoned"], a_tool)
check("a swapped system prompt is a tampered build",
      "prompt-tampered" in kinds(AT.attestation({**BUILD, "prompt_hash": "p2"}, APPROVED)))
check("a host-reported measurement is named as a limit",
      "attestation-host-reported" in kinds(
          AT.attestation({**BUILD, "host_trusted": False}, APPROVED)))

check("a cross-organization write is refused at the tool call",
      "cross-org-write" in kinds(
          AT.policy({"kind": "write", "origin_org": "org1", "target_org": "org2"})))
check("a replayed transaction is refused",
      "replay" in kinds(AT.policy({"kind": "write", "origin_org": "org1",
                                   "target_org": "org1", "processed": True})))
check("a bulk export past the cap is refused",
      "bulk-export" in kinds(AT.policy({"kind": "read", "sensitive": True,
                                        "records": 9, "cap": 1})))
check("a request that reads two offices is flagged, not refused",
      "separation-of-duties" in kinds(
          AT.policy({"kind": "read", "offices_read": ["aid", "registrar"]})))
check("a rule cannot separate collusion from legitimate work",
      "policy-cannot-distinguish" in kinds(
          AT.policy({"kind": "read", "observable": "identical"})))

LOG = [{"aid": "h1", "model": "m1", "tool": "db_read", "args_hash": "a1",
        "prev_hash": None, "hash": "e1", "signature_ok": True},
       {"aid": "h1", "model": "m1", "tool": "db_write", "args_hash": "a2",
        "prev_hash": "e1", "hash": "e2", "signature_ok": True}]
ac1 = AT.accountability(LOG)
check("a clean chain is intact but its end is unpinned",
      "chain-broken" not in kinds(ac1) and "chain-end-unpinned" in kinds(ac1), ac1)
check("a broken chain is detected",
      "chain-broken" in kinds(AT.accountability([LOG[0], {**LOG[1], "prev_hash": "e9"}])))
check("an unsigned entry is named",
      "unsigned-entry" in kinds(AT.accountability([{**LOG[0], "signature_ok": False}])))
check("an allowed action with no record is named",
      "no-record" in kinds(AT.accountability([])))

ROWS = [
    {"attack": "A1", "plane": "identity", "containment": 0.20, "targeted": True, "model": "m1", "stopped": 0},
    {"attack": "A1", "plane": "identity", "containment": 1.00, "targeted": True, "model": "m1", "stopped": 1},
    {"attack": "A2", "plane": "identity", "containment": 0.44, "targeted": False, "model": "m2", "stopped": 0},
    {"attack": "A2", "plane": "trust", "containment": 0.61, "targeted": False, "model": "m2", "stopped": 0},
    {"attack": "A3", "plane": "trust", "containment": 0.96, "targeted": False, "model": "m1", "stopped": 1},
    {"attack": "A3", "plane": "trust", "containment": 0.71, "targeted": False, "model": "m2", "stopped": 0},
    {"attack": "B1", "plane": "policy", "benign": 0.91, "targeted": True},
    {"attack": "B2", "plane": "policy", "benign": 0.92, "targeted": True},
    {"attack": "A9", "plane": "policy", "containment": 0.16, "targeted": True, "model": "m1", "stopped": 0},
    {"attack": "A9", "plane": "policy", "containment": 0.71, "targeted": True, "model": "m1", "stopped": 1},
    {"attack": "A5", "plane": "policy", "overhead_us": 174, "targeted": True},
]
me = AT.measure(ROWS)
check("a plane that moves its target is credited with the gain",
      "plane-adds-containment" in kinds(me), me)
check("benign work is retained", "benign-retained" in kinds(me), me)
check("the per-request overhead is measured", "overhead-measured" in kinds(me), me)
check("two models with different stop rates are a model-variance warning",
      "model-variance-misjudges" in kinds(me), me)
check("untargeted cases with no mechanism set a noise band",
      "noise-band" in kinds(me), me)
single = AT.measure([{"attack": "A1", "plane": "identity", "containment": 0.2,
                      "targeted": True, "model": "m1", "stopped": 0},
                     {"attack": "A1", "plane": "identity", "containment": 1.0,
                      "targeted": True, "model": "m1", "stopped": 1}])
check("an evaluation on a single model is named",
      "single-model-evaluation" in kinds(single), single)

adv3 = AT.advise({})
check("the attestation advisor names the six failure modes",
      len(adv3["findings"]) == 6, adv3)

# ---- result ---------------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
