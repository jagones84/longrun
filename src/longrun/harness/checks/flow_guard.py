#!/usr/bin/env python3
"""Flow guard — judge a relay by behaviour and policy, not by text similarity.

Source: arXiv:2611.21520, "Safe Resemblance, Silent Propagation: Limits of
Text-Similarity Guardrails for AI Agent Safety" (round 120). Its measurement:
at the default threshold a BLEU/ROUGE-L/METEOR classifier missed 8 of 19
functional relays while flagging 70 of 192 legitimate replies, and every
completed quotation or template-reuse reply raised a false alert. Recalibrating
for low false positives did not transfer to a new template set.

Two faults the paper names are structural, and this module refuses both:

  * a SURFACE criterion (text overlap) gives no distribution-free guarantee for
    the BEHAVIOURAL target (did the injected procedure induce fresh computations
    downstream?) — so the decision here is behavioural, declared per relay;
  * an OPERATING POINT must be applied directly; ROC interpolation is not a
    threshold. `calibrate()` returns the smallest score cut meeting a target rate
    on the calibration set, and `evaluate()` applies it as-is.

Authorization decides cases no observation-only classifier can: the same visible
transcript can require different decisions under different policies.
"""
from __future__ import annotations

FORMAT = "longrun-flow-guard/1"
DECISIONS = ("allow", "flag", "block")


def judge(relay):
    """Behaviour plus authorization, with the similarity score only as context."""
    rec = relay or {}
    behaviour = rec.get("behaviour") or {}
    policy = rec.get("policy") or {}
    fresh = int(behaviour.get("fresh_computations") or 0)
    functional = fresh >= 1
    authorized = bool(policy.get("quotation_allowed") or policy.get("template_reuse_allowed"))
    score = rec.get("similarity")
    findings = []
    if functional and authorized:
        decision = "flag"
        findings.append({"kind": "authorization-conflict",
                         "why": "fresh computations under a policy that authorizes reuse: "
                                "the relay needs a policy decision, not a score"})
    elif functional:
        decision = "block" if policy.get("block_functional", True) else "flag"
        findings.append({"kind": "functional-propagation",
                         "why": "the injected procedure induced fresh downstream computations"})
    elif authorized:
        decision = "allow"
    else:
        decision = "flag"
        findings.append({"kind": "unauthorized-reuse",
                         "why": "quotation or template reuse without authorization"})
    if isinstance(score, (int, float)):
        if decision == "allow" and score >= (policy.get("alarm_threshold") or 0.9):
            findings.append({"kind": "similarity-false-alarm",
                             "why": "high overlap on an authorized, non-functional relay"})
        if decision == "block" and score < (policy.get("alarm_threshold") or 0.9):
            findings.append({"kind": "similarity-miss",
                             "why": "a functional relay the surface score would not flag"})
    return {"format": FORMAT, "decision": decision, "functional": functional,
            "authorized": authorized, "fresh_computations": fresh,
            "findings": findings}


def calibrate(scores, labels, target_fpr=0.05):
    """The LOWEST score cut whose false-positive rate on THIS set meets the target.

    Lowest cut = most sensitive operating point that respects the budget; every
    candidate is evaluated with the direct rule in ``evaluate``.
    """
    pairs = sorted({float(s) for s in scores or []})
    if not any(not y for y in labels or []):
        return {"format": FORMAT, "threshold": None, "why": "no legitimate examples to calibrate on"}
    for threshold in pairs:
        res = evaluate(scores, labels, threshold)
        if res["false_alert_rate"] is not None and res["false_alert_rate"] <= target_fpr:
            return {"format": FORMAT, "threshold": threshold,
                    "false_alert_rate": res["false_alert_rate"],
                    "miss_rate": res["miss_rate"]}
    return {"format": FORMAT, "threshold": None, "why": "no cut meets the target"}


def evaluate(scores, labels, threshold):
    """Apply the threshold directly — the paper's operating-point rule, no interpolation."""
    tp = fp = fn = tn = 0
    for s, y in zip(scores or [], labels or []):
        alerted = float(s) >= float(threshold)
        if y and alerted:
            tp += 1
        elif y:
            fn += 1
        elif alerted:
            fp += 1
        else:
            tn += 1
    return {"format": FORMAT, "threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "miss_rate": round(fn / (tp + fn), 4) if (tp + fn) else None,
            "false_alert_rate": round(fp / (fp + tn), 4) if (fp + tn) else None}
