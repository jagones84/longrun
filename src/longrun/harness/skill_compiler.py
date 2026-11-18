#!/usr/bin/env python3
"""Skill compilation — verified traces become versioned, cited procedures.

Source: arXiv:2611.01386, "Learning by Doing: Autonomously Compiling and Curating
Agent Skills from Verified Traces" (round 118). The service records every task
attempt as a Trace with ordered events, an outcome and a verification strength;
only verified attempts are evidence; every field of a compiled Skill cites the
events that support it; admission gates decide what becomes active; verified use
outcomes change the search rank; and a conflict removes the Skill from search.

Details taken from the paper's sections, not its abstract:

  * strength follows the VERIFIER's identity, never a strength the caller states
    (Section 5.2, the verification paragraph);
  * restricted content is a reference only — no Skill may contain it (5.3,
    scanners);
  * a scanner stops a proposal carrying instance data or an instruction that
    came from tool output (5.3);
  * admission applies a result group atomically: every change or none (5.4);
  * the search weight is the posterior mean of the success rate with prior mean
    n/(n+1) over n supporting attempt families and strength k (5.4).

This module implements the deterministic half: compile, gate, weight and rank.
It never calls a model and never reads restricted content.

Pure: trace/skills in, verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-compile/1"
OUTCOMES = ("success", "partial", "failure", "abandonment", "unknown")
# Section 5.2: a strength is assigned from who verified, not from what the caller claims.
STRENGTH = {"none": "none", "self": "self-reported", "tool": "independent",
            "human": "independent", "external": "independent"}


def verification(record):
    """The strength the evidence actually has, plus the claim that was ignored."""
    verifier = str((record or {}).get("verifier") or "none")
    strength = STRENGTH.get(verifier, "none")
    stated = (record or {}).get("claimed_strength")
    ignored = stated if stated and stated != strength else None
    return {"verifier": verifier, "strength": strength, "ignored_claim": ignored}


def _scanner(step, restricted_events):
    findings = []
    if step.get("event") in restricted_events:
        findings.append({"kind": "restricted-content", "event": step.get("event"),
                         "why": "content from a restricted resource cannot enter a Skill"})
    text = str(step.get("text") or "")
    low = text.lower()
    for phrase in ("ignore the previous", "ignore previous instructions", "you must now",
                   "system prompt"):
        if phrase in low and step.get("origin") == "tool":
            findings.append({"kind": "instruction-from-tool-output", "event": step.get("event")})
            break
    for term in step.get("instance_terms") or []:
        if term and term in text:
            findings.append({"kind": "instance-data", "event": step.get("event"), "term": term})
            break
    return findings


def compile_skill(record, min_strength="independent"):
    """Compile one Trace into a candidate Skill, or say why it cannot be evidence."""
    rec = record or {}
    findings = []
    ver = verification(rec)
    if rec.get("outcome") != "success":
        findings.append({"kind": "outcome-not-success", "outcome": rec.get("outcome"),
                         "why": "only a successful attempt is evidence for a procedure"})
    if ver["strength"] == "none":
        findings.append({"kind": "unverified-evidence",
                         "why": "no verifier: an agent's own claim is not evidence"})
    elif min_strength == "independent" and ver["strength"] != "independent":
        findings.append({"kind": "verification-below-gate", "strength": ver["strength"]})
    if ver["ignored_claim"]:
        findings.append({"kind": "claimed-strength-ignored", "claimed": ver["ignored_claim"],
                         "why": "strength comes from the verifier's identity"})

    restricted = {e.get("id") for e in rec.get("events") or [] if e.get("restricted")}
    steps, fields = [], {}
    for i, event in enumerate(rec.get("events") or []):
        if event.get("kind") != "action":
            continue
        step = {"text": event.get("text"), "event": event.get("id"),
                "origin": event.get("origin"), "instance_terms": event.get("instance_terms")}
        findings.extend(_scanner(step, restricted))
        if not event.get("id"):
            findings.append({"kind": "field-without-evidence", "text": event.get("text")})
            continue
        steps.append({"instruction": event.get("text"), "evidence": [event["id"]]})
    fields["steps"] = steps
    for field in ("when_to_use", "stop_condition", "outputs"):
        ids = [e["id"] for e in rec.get("evidence") or [] if e.get("field") == field and e.get("id")]
        if ids:
            fields[field] = {"value": rec.get("fields", {}).get(field), "evidence": ids}
    for field in ("when_to_use", "stop_condition"):
        if not fields.get(field):
            findings.append({"kind": "field-without-evidence", "field": field})
    if not steps:
        findings.append({"kind": "no-action-events"})

    blocking = {"outcome-not-success", "unverified-evidence", "verification-below-gate",
                "restricted-content", "instruction-from-tool-output", "instance-data",
                "field-without-evidence", "no-action-events"}
    admitted = not any(f["kind"] in blocking for f in findings)
    skill = {"name": rec.get("task_family") or rec.get("task"),
             "fields": fields, "trace": rec.get("id"),
             "verification": ver["strength"], "attempt_families": rec.get("attempt_families") or 1}
    return {"format": FORMAT, "admitted": admitted, "skill": skill if admitted else None,
            "candidate": skill, "findings": findings, "verification": ver}


def admit_group(candidates, policy=None):
    """Section 5.4: a result group is applied atomically — every change or none."""
    policy = policy or {}
    results = [compile_skill(c, policy.get("min_strength", "independent")) for c in candidates or []]
    rejected = [{"index": i, "findings": r["findings"]}
                for i, r in enumerate(results) if not r["admitted"]]
    if policy.get("conflict") and not policy.get("human_review"):
        rejected.append({"index": -1, "findings": [{"kind": "conflict-requires-review"}]})
    admitted = not rejected
    return {"format": FORMAT, "admitted": admitted,
            "skills": [r["skill"] for r in results if r["admitted"]] if admitted else [],
            "rejected": rejected}


def search_weight(uses, supporting_families, k=2.0):
    """Posterior mean of the success rate; prior mean n/(n+1), prior worth k trials."""
    uses = [u for u in (uses or []) if isinstance(u, dict)]
    trials = [u for u in uses if u.get("verified") and u.get("outcome") in ("success", "failure")]
    s = sum(1 for u in trials if u["outcome"] == "success")
    t = len(trials)
    n = max(0, int(supporting_families or 0))
    if t + k == 0:
        return 0.0
    prior = n / (n + 1)
    return round((s + k * prior) / (t + k), 4)


def rank(skills, k=2.0):
    """Higher weight first; a conflicted Skill is not returned at all."""
    rows = []
    for s in skills or []:
        if s.get("conflict"):
            continue
        rows.append({"name": s.get("name"),
                     "weight": search_weight(s.get("uses"), s.get("attempt_families"), k)})
    rows.sort(key=lambda r: (-r["weight"], str(r["name"])))
    return {"format": FORMAT, "ranked": rows,
            "excluded": sorted(s.get("name") for s in skills or [] if s.get("conflict"))}
