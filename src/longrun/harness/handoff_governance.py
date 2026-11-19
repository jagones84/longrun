#!/usr/bin/env python3
"""Handoff governance — a deterministic gate, and the halt it earns must be attributed.

Source: arXiv:2609.34017, "Maat" (round 140). Multi-agent systems lose work at
the seams: a defect produced by one agent is accepted as context by the next
(`maat_handoff_contract_2609.34017.md:16`, `:20`). Maat inserts a deterministic
validator on selected edges, comparing each handoff with a **versioned anchor**
— the contract, limits, entities and rules the workflow is authorized to obey —
and keeps every language model out of the validation path (`:23`, `:152`).

  * **seven gates and requirement primitives**: G1 plan, G2 handoff, G3 depth,
    G4 role, G5 survival, G6 breaker, G7 entity consistency, plus domain rules
    (`:179`, `:184`).
  * **structural validity is not contract validity**: a well-formed payload can
    still break a price, a limit or a jurisdiction rule (`:107`).
  * **determinism is not correctness**: a misconfigured rule fails the same way
    every time; anchor and configuration are part of the measured system
    (`:109`, `:544`).
  * **a halt is a catch only when attributable**: the v2 audit found 37% of
    governed halts were false alarms, and once they are counted as failed work
    the governed arm scores below the ungoverned arm in four of six workflows
    (`:32`, `:386`, `:517`).
  * **silence is not evidence**: a check that did not fire may be unexercised,
    pre-empted, self-corrected, misconfigured, or truly negative (`:783`).

  * `anchor(rules, version)` — the versioned contract, checked for completeness.
  * `validate(handoff, anchor, mode)` — one handoff against one anchor, three postures.
  * `attribute(halts)` — caught / genuine / escalation / false alarm, and the rate.
  * `compare(pairs)` — a paired gain and whether it survives attribution.
  * `coverage(checks)` — the five silence states and what a silence proves.
  * `posture(profile)` — warn first, intervene only once the anchor is calibrated.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: handoffs in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-handoff-governance/1"

GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
MODES = ("off", "warn", "intervene")
RULE_KINDS = ("required", "limit", "allowed", "identity", "sum", "residency")
SILENCE_STATES = ("not-exercised", "pre-empted", "self-corrected",
                  "misconfigured", "true-negative")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _field(fields, path):
    """Read a dotted path; a missing key is None, never a KeyError."""
    cur = fields
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _empty(value):
    return value is None or value == "" or value == [] or value == {}


def _check_rule(rule, fields, state):
    """Return a finding dict when the rule fires, else None."""
    kind = rule.get("kind")
    rid = rule.get("id") or kind
    gate = rule.get("gate") or ("G7" if kind == "identity" else
                                "G2" if kind == "required" else "REQ")
    if kind == "required":
        if _empty(_field(fields, rule.get("field"))):
            return {"rule": rid, "gate": gate, "kind": "missing-field",
                    "field": rule.get("field")}
        return None
    if kind == "limit":
        value = _num(_field(fields, rule.get("field")))
        cap = _num(rule.get("max"))
        if value is None or cap is None:
            return {"rule": rid, "gate": gate, "kind": "limit-unreadable",
                    "field": rule.get("field")}
        if value > cap:
            return {"rule": rid, "gate": gate, "kind": "limit-exceeded",
                    "field": rule.get("field"), "value": value, "max": cap}
        return None
    if kind == "allowed":
        value = _field(fields, rule.get("field"))
        allowed = rule.get("values") or []
        if value not in allowed:
            return {"rule": rid, "gate": gate, "kind": "value-not-allowed",
                    "field": rule.get("field"), "value": value}
        return None
    if kind == "identity":
        key = rule.get("field")
        value = _field(fields, key)
        prior = (state or {}).get(key)
        if prior is not None and value is not None and value != prior:
            return {"rule": rid, "gate": gate, "kind": "identity-drift",
                    "field": key, "was": prior, "now": value}
        return None
    if kind == "sum":
        total = _num(_field(fields, rule.get("field")))
        parts = _field(fields, rule.get("parts"))
        if total is None or not isinstance(parts, list):
            return {"rule": rid, "gate": gate, "kind": "reconciliation-unreadable",
                    "field": rule.get("field")}
        nums = [_num(p) for p in parts]
        if any(n is None for n in nums):
            return {"rule": rid, "gate": gate, "kind": "reconciliation-unreadable",
                    "field": rule.get("field")}
        if abs(total - sum(nums)) > 1e-9 * max(1.0, abs(total)):
            return {"rule": rid, "gate": gate, "kind": "sum-mismatch",
                    "field": rule.get("field"), "total": total,
                    "sum": sum(nums)}
        return None
    if kind == "residency":
        value = _field(fields, rule.get("field") or "region")
        allowed = rule.get("values") or []
        if value not in allowed:
            return {"rule": rid, "gate": gate, "kind": "residency-violation",
                    "field": rule.get("field") or "region", "value": value}
        return None
    return {"rule": rid, "gate": gate, "kind": "unknown-rule-kind",
            "detail": str(kind)}


def _normalize_rules(rules):
    out = []
    for i, rule in enumerate(rules or []):
        if not isinstance(rule, dict):
            continue
        row = dict(rule)
        if not row.get("id"):
            row["id"] = "R%d" % (i + 1)
        out.append(row)
    return out


def anchor(rules, version=1):
    """A versioned anchor: what the workflow is authorized to preserve or obey."""
    norm = _normalize_rules(rules)
    findings = []
    if version in (None, "", 0):
        findings.append({"kind": "unversioned-anchor",
                         "why": "the contract version is part of the measured system"})
    if not norm:
        findings.append({"kind": "anchor-empty",
                         "why": "without a rule nothing can be validated"})
    seen = {}
    for rule in norm:
        rid = rule.get("id")
        if rid in seen:
            findings.append({"kind": "duplicate-rule-id", "rule": rid})
        seen[rid] = True
        if rule.get("kind") not in RULE_KINDS:
            findings.append({"kind": "unknown-rule-kind", "rule": rid,
                             "detail": str(rule.get("kind"))})
    if not findings:
        findings.append({"kind": "anchor-versioned"})
    return {"format": FORMAT, "version": version, "rules": norm,
            "kinds": sorted(seen), "findings": findings}


def validate(handoff, anchor_doc, mode="warn", state=None):
    """One handoff against one anchor, in one of three postures.

    `off` runs unchecked; `warn` records would-block findings and continues;
    `intervene` blocks. An illegal finding never changes the state.
    """
    if mode not in MODES:
        return {"format": FORMAT, "verdict": "invalid-mode", "mode": mode,
                "findings": []}
    rules = (anchor_doc or {}).get("rules") or []
    fields = (handoff or {}).get("fields") or {}
    findings = []
    if mode != "off":
        for rule in rules:
            hit = _check_rule(rule, fields, state)
            if hit:
                hit["blocking"] = bool(rule.get("blocking", True))
                findings.append(hit)
    blocking = [f for f in findings if f.get("blocking")]
    if mode == "off":
        verdict = "pass"
    elif mode == "warn":
        verdict = "warn" if findings else "pass"
    else:
        verdict = "block" if blocking else ("warn" if findings else "pass")
    return {"format": FORMAT, "mode": mode, "verdict": verdict,
            "checked": mode != "off", "findings": findings,
            "would_block": len(blocking)}


def attribute(halts):
    """A halt counts as a catch only when the defect behind it is verified."""
    counts = {"injected": 0, "genuine": 0, "escalation": 0, "false-alarm": 0}
    unknown = 0
    for halt in halts or []:
        kind = (halt or {}).get("kind")
        if kind in counts:
            counts[kind] += 1
        else:
            unknown += 1
    total = sum(counts.values()) + unknown
    caught = counts["injected"] + counts["genuine"]
    fa_rate = counts["false-alarm"] / total if total else 0.0
    attributable = caught / total if total else 0.0
    if not total:
        verdict = "no-halts"
    elif fa_rate <= 0.10:
        verdict = "halts-attributable"
    elif fa_rate > 0.25:
        verdict = "halts-unattributed"
    else:
        verdict = "halts-mixed"
    return {"format": FORMAT, "counts": counts, "unknown": unknown,
            "total": total, "caught": caught, "false_alarm_rate": fa_rate,
            "attributable_share": attributable, "verdict": verdict,
            "penalty": "a false alarm stops correct work and must be scored as failed work"}


def compare(pairs, flat_band=0.02):
    """A paired gain, and whether it survives counting unattributed halts."""
    rows = []
    for pair in pairs or []:
        off = _num((pair or {}).get("off"))
        gov = _num((pair or {}).get("governed"))
        lb = _num((pair or {}).get("governed_lower_bound"))
        if off is None or gov is None:
            continue
        lb = gov if lb is None else lb
        rel = (gov - off) / off if off else 0.0
        rel_lb = (lb - off) / off if off else 0.0
        rows.append({"benchmark": pair.get("benchmark"), "off": off,
                     "governed": gov, "lower_bound": lb,
                     "delta": gov - off, "relative": rel,
                     "relative_lower_bound": rel_lb})
    if not rows:
        return {"format": FORMAT, "rows": [], "verdict": "no-pairs"}
    mean_rel = sum(r["relative"] for r in rows) / len(rows)
    mean_lb = sum(r["relative_lower_bound"] for r in rows) / len(rows)
    improved = sum(1 for r in rows if r["relative"] > flat_band)
    dissolved = sum(1 for r in rows if r["relative"] > flat_band
                    and r["relative_lower_bound"] <= 0)
    if all(abs(r["relative"]) <= flat_band for r in rows):
        verdict = "flat"
    elif mean_rel > 0 and mean_lb <= 0:
        verdict = "attribution-corrects-the-gain"
    elif mean_lb > 0 and dissolved == 0:
        verdict = "gain-holds"
    else:
        verdict = "mixed"
    return {"format": FORMAT, "rows": rows, "mean_relative": mean_rel,
            "mean_relative_lower_bound": mean_lb, "improved": improved,
            "dissolved": dissolved, "verdict": verdict}


def coverage(checks):
    """What a non-firing rule proves: five distinct silence states."""
    tally = {state: 0 for state in SILENCE_STATES}
    bad = []
    for check in checks or []:
        state = (check or {}).get("state")
        if state in tally:
            tally[state] += 1
        else:
            bad.append((check or {}).get("rule"))
    total = sum(tally.values())
    if not total:
        verdict = "no-checks"
    elif tally["misconfigured"] or tally["pre-empted"]:
        verdict = "silence-is-not-evidence"
    elif tally["not-exercised"] == total:
        verdict = "rules-unexercised"
    elif tally["true-negative"] + tally["self-corrected"] == total:
        verdict = "silence-supported"
    else:
        verdict = "silence-partial"
    return {"format": FORMAT, "tally": tally, "unknown": bad,
            "alertable": tally["not-exercised"] + tally["misconfigured"]
                         + tally["pre-empted"],
            "verdict": verdict}


def posture(profile):
    """Warn first; intervene only once the anchor has been exercised."""
    p = profile or {}
    trials = _num(p.get("trials")) or 0.0
    fa = _num(p.get("false_alarm_rate")) or 0.0
    versioned = p.get("anchor_versioned") is not False
    reasons = []
    if trials < 20:
        reasons.append("anchor-unexercised")
    if fa > 0.10:
        reasons.append("false-alarms-too-high")
    if not versioned:
        reasons.append("anchor-unversioned")
    mode = "warn" if reasons else "intervene"
    return {"format": FORMAT, "mode": mode, "reasons": reasons,
            "note": "only intervention can skip downstream model calls, "
                    "but only a calibrated anchor makes the halt attributable"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("versions_the_anchor", "unversioned-anchor",
         "engine, anchor and configuration are one measured object"),
        ("gates_each_handoff", "final-only-verification",
         "verify at the seam, not only the final artefact"),
        ("keeps_the_validator_deterministic", "judge-in-the-loop",
         "an LLM judge inherits the failure modes it must catch"),
        ("attributes_every_halt", "halt-counted-as-catch",
         "a false alarm stops correct work"),
        ("scores_the_lower_bound", "credited-gain",
         "count unattributed halts as failed work"),
        ("exercises_rules_on_live_payloads", "silence-read-as-correct",
         "not exercised, pre-empted and misconfigured are not true negatives"),
        ("warns_before_it_intervenes", "intervene-on-day-one",
         "a new anchor is calibrated in warn mode"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
