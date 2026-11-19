#!/usr/bin/env python3
"""Complexity frontier — a bracket says what is known and where the gap is.

Source: arXiv:2611.23080, "Colombo: A Frontier-to-Frontier Autoresearch System
for Oracle-Based Optimization" (round 137). The system's field model is a map of
settings, each carrying the best supported upper and lower bounds and the status
of the gap between them (`colombo_autoresearch_oracle_2611.23080.md:37`, `:81`).

  * **a bound is valid only on its declared domain and regime**, and a setting's
    display status is its LEAST-resolved regime (`:81`, `:119`).
  * **only supported bounds move the bracket**: a candidate or an unreviewed
    argument stays in the research record (`:179`, `:185`).
  * **review then formal certification gate memory**: unresolved placeholders or
    custom axioms block certification (`:221`, `:269`).
  * **algorithm and hard family co-ascend**: a family solved below its lower
    bound exposes structure; a counterexample to a guarantee exposes an
    information limit (`:325`, `:331`).
  * **a failed attempt is retained as an inconclusive record**, never promoted
    (`:301`).
  * **measured**: 56 works across six task classes, with optimal or near-optimal
    rates in more than fifty settings (`:37`, `:343`).

  * `bracket(regimes)` — per-regime status and the setting aggregate.
  * `frontier(rows)` — the current gap and what would close it.
  * `coascent(record)` — algorithm vs hard family, and what each outcome proves.
  * `evidence(record)` — domain, review and certification before admission.
  * `memory(rows)` — certified, provisional and failed records.
  * `round(rows)` — supported components vs open obligations.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: bounds, obligations and records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-complexity-frontier/1"

STATUSES = ("optimal", "near-optimal", "open", "upper-only", "lower-only", "uncharacterized")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(upper, lower, log_tolerance=0.0):
    if upper is None and lower is None:
        return "uncharacterized"
    if upper is None:
        return "lower-only"
    if lower is None:
        return "upper-only"
    if upper == lower:
        return "optimal"
    if upper < lower:
        return "inconsistent"
    if upper - lower <= float(log_tolerance):
        return "near-optimal"
    return "open"


def bracket(regimes):
    """The per-regime bracket and the setting's least-resolved status."""
    rows = list(regimes or ())
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-regimes"}]}
    seen = []
    findings = []
    for r in rows:
        upper = _num(r.get("upper"))
        lower = _num(r.get("lower"))
        if r.get("upper") in (None, "unknown"):
            upper = None
        if r.get("lower") in (None, "unknown"):
            lower = None
        status = _status(upper, lower, r.get("log_tolerance", 0.0))
        seen.append({"domain": r.get("domain"), "status": status,
                     "upper": upper, "lower": lower})
        if status == "inconsistent":
            findings.append({"kind": "upper-below-lower", "domain": r.get("domain"),
                             "why": "the supported bounds contradict each other"})
    order = [STATUSES.index(s["status"]) if s["status"] in STATUSES else len(STATUSES)
             for s in seen]
    worst = seen[max(range(len(seen)), key=lambda i: order[i])]["status"]
    if worst not in STATUSES:
        worst = "uncharacterized"
    findings.append({"kind": "setting-%s" % worst})
    return {"format": FORMAT, "regimes": seen, "status": worst, "findings": findings}


def frontier(rows):
    """Which regimes are unresolved and what a candidate would close."""
    data = list(rows or ())
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-frontier"}]}
    unresolved = [r for r in data if (r.get("status") or "open") != "optimal"]
    findings = []
    if not unresolved:
        findings.append({"kind": "frontier-closed"})
    else:
        findings.append({"kind": "frontier-open", "regimes": len(unresolved)})
    candidate = [r for r in data if r.get("candidate") is not None]
    if candidate:
        reach = [r for r in candidate if r.get("candidate_closes") is True]
        if reach:
            findings.append({"kind": "candidate-reaches-frontier", "regimes": len(reach)})
        else:
            findings.append({"kind": "candidate-misses-frontier",
                             "why": "a candidate on a resolved regime adds no bound"})
    return {"format": FORMAT, "unresolved": len(unresolved), "findings": findings}


def coascent(record):
    """A family beaten by an algorithm, or an algorithm broken by a family."""
    r = record or {}
    upper = _num(r.get("algorithm_upper"))
    lower = _num(r.get("family_lower"))
    findings = []
    if upper is not None and lower is not None and upper < lower:
        findings.append({"kind": "exploitable-structure",
                         "why": "a family solved below its lower bound means the bound was loose"})
    counter = r.get("counterexample")
    if counter:
        findings.append({"kind": "information-limit", "counterexample": counter,
                         "why": "the guarantee fails on an admissible instance"})
    if r.get("matched") is True:
        findings.append({"kind": "matched-bounds"})
    if not findings:
        findings.append({"kind": "no-progress"})
    return {"format": FORMAT, "findings": findings}


def evidence(record):
    """A bound enters the bracket only with a domain, review and certification."""
    r = record or {}
    findings = []
    if not r.get("domain"):
        findings.append({"kind": "missing-domain",
                         "why": "a bound is only valid on its declared regime"})
    if r.get("side") not in ("upper", "lower"):
        findings.append({"kind": "untyped-bound"})
    if r.get("reviewed") is not True:
        findings.append({"kind": "unreviewed-claim"})
    if r.get("certified") is not True:
        findings.append({"kind": "uncertified-claim",
                         "why": "a placeholder or a custom axiom is not a proof"})
    if r.get("placeholders"):
        findings.append({"kind": "proof-placeholder",
                         "count": len(r.get("placeholders") or ())})
    if r.get("transfer") is True and not r.get("transfer_checked"):
        findings.append({"kind": "transfer-unchecked",
                         "why": "a result moved between settings must be re-checked"})
    if not findings:
        findings.append({"kind": "bound-admissible"})
    return {"format": FORMAT, "findings": findings}


def memory(rows):
    """Certified findings, provisional records and retained failures."""
    data = list(rows or ())
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-records"}]}
    findings = []
    for r in data:
        status = str(r.get("status") or "")
        if status == "provisional" and r.get("in_bracket") is True:
            findings.append({"kind": "provisional-in-bracket", "id": r.get("id"),
                             "why": "only certified results move the bracket"})
        if status == "failed" and r.get("as_finding") is True:
            findings.append({"kind": "failure-as-finding", "id": r.get("id"),
                             "why": "a failed attempt is an inconclusive record"})
        if status not in ("certified", "provisional", "failed"):
            findings.append({"kind": "unknown-status", "id": r.get("id")})
    counts = {s: sum(1 for r in data if r.get("status") == s)
              for s in ("certified", "provisional", "failed")}
    if not findings:
        findings.append({"kind": "memory-consistent", "counts": counts})
    return {"format": FORMAT, "counts": counts, "findings": findings}


def round(rows):
    """Supported components and open obligations after integration."""
    data = list(rows or ())
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-obligations"}]}
    supported = [r for r in data if r.get("supported") is True]
    open_items = [r for r in data if r.get("supported") is not True]
    findings = []
    if any(r.get("composition") is True and r.get("supported") is not True for r in data):
        findings.append({"kind": "composition-unproved",
                         "why": "an unproved composition step is itself an obligation"})
    if open_items:
        findings.append({"kind": "round-incomplete", "open": len(open_items)})
    else:
        findings.append({"kind": "round-complete", "supported": len(supported)})
    if any(r.get("target_reached") is True for r in data) and open_items:
        findings.append({"kind": "target-claimed-with-open-work"})
    return {"format": FORMAT, "supported": len(supported), "open": len(open_items),
            "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("tracks_upper_and_lower", "single-sided-claim", "a gap needs both sides"),
        ("scopes_each_bound", "unscoped-bound", "state the domain where the bound holds"),
        ("shows_least_resolved", "best-regime-display", "display the weakest relevant regime"),
        ("separates_provisional", "provisional-as-known", "candidates stay out of the bracket"),
        ("certifies_claims", "unverified-proof", "review then an independent check"),
        ("retains_failures", "discards-failures", "a failed attempt is evidence about method"),
        ("pairs_attack_and_defence", "one-sided-search", "algorithms and hard cases co-ascend"),
        ("marks_unproved_composition", "silent-composition", "an unproved step is an obligation"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
