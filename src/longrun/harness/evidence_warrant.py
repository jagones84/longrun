#!/usr/bin/env python3
"""Evidence warrant — old evidence is not automatically admissible in a new context.

Source: arXiv:2611.23990, "SCAFFOLD: Toward Warrant-Preserving Evidence Transport
for Reusable LLM-Agent Skills" (round 151). A skill that succeeded yesterday may
be executable today without being justified today: tests may cover only
observable clauses, oracles may be absent, evaluations may inherit the same
wrong specification, and permissions may change between validation and
invocation (`scaffold_evidence_2611.23990.txt:8`, `:13`).

  * **the unit is a prospective claim**: a Warranted Reuse Claim
    `WRC = <s, c, phi, E, A, D>` — skill, context, proposition, evidence,
    assumptions, defeaters — not a scalar (`:15`, `:94`).
  * **applicability is tri-valued**: `App` is 1, 0 or `?`, and `?` is not
    positive evidence (`:95`, `:99`).
  * **transport is premise-bound**: `WPET = Support and every premise in R(e, phi)
    preserved`; a soundness claim needs a completeness assumption (`:133`,
    `:139`).
  * **authorization is defeasible**: hard prohibitions dominate, then required
    evidence, then unresolved uncertainty, else test/review (`:181`, `:184`).
  * **transport is not symmetric and not compositional**: a read-only
    evaluation does not license a write, and pairwise transport needs the full
    premise set stable (`:147`, `:151`).
  * **selective retesting is conditional**: full retesting costs `|V|k`, selective
    costs `|I|k + h`, so the saving is positive only if `h < (|V|-|I|)k` (`:269`,
    `:287`).
  * **honest boundary**: this is a propositon and a reporting protocol; no
    experiment was run, and an incomplete premise set transports under a false
    premise (`:33`, `:161`).

  * `wrc(record)` — the claim record, refused when it is only a score.
  * `admissibility(items)` — tri-valued support with the usable set.
  * `transport(items)` — the directed, claim-specific judgment.
  * `authorize(record)` — hard prohibitions, requirements, unresolved uncertainty.
  * `provenance(record)` — dependence and the variance-equivalent sample size.
  * `composition(record)` — a two-hop transport and what breaks it.
  * `selective(record)` — the cost condition for selective revalidation.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: claims, evidence items and premises in; admissibility and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-evidence-warrant/1"

WRC_FIELDS = ("skill", "context", "proposition", "evidence", "assumptions",
              "defeaters")
VERDICTS = ("valid", "invalid", "unresolved")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tri(value):
    if value is True or value == 1 or value == "true":
        return 1
    if value is False or value == 0 or value == "false":
        return 0
    return None


def wrc(record):
    """Build the claim record; a scalar confidence is not a warrant."""
    r = record or {}
    if r.get("score_only") is True:
        return {"format": FORMAT, "verdict": "not-a-warrant"}
    optional_empty = ("assumptions", "defeaters")
    missing = [name for name in WRC_FIELDS
               if r.get(name) in (None, "", {}, [])
               and not (name in optional_empty and r.get(name) == [])]
    if missing:
        return {"format": FORMAT, "verdict": "incomplete-claim",
                "missing": missing}
    return {"format": FORMAT, "verdict": "claim-recorded",
            "fields": {name: r.get(name) for name in WRC_FIELDS}}


def admissibility(items):
    """App in {1, 0, ?}: support plus every premise preserved."""
    rows = [item or {} for item in (items or [])]
    usable = []
    counts = {"admissible": 0, "disconfirmed": 0, "unresolved": 0}
    for index, item in enumerate(rows):
        if item.get("support") is not True:
            counts["disconfirmed"] += 1
            continue
        premises = item.get("premises") or {}
        values = [_tri(v) for v in premises.values()]
        if any(v == 0 for v in values):
            counts["disconfirmed"] += 1
        elif any(v is None for v in values) or not premises:
            counts["unresolved"] += 1
        else:
            counts["admissible"] += 1
            usable.append(index)
    if not rows:
        return {"format": FORMAT, "verdict": "no-evidence"}
    return {"format": FORMAT, "items": len(rows), **counts, "usable": usable,
            "verdict": "admissibility-computed"}


def transport(items):
    """The directed judgment: valid only if every item is admissible."""
    result = admissibility(items)
    if result["verdict"] == "no-evidence":
        return {"format": FORMAT, "verdict": "unresolved"}
    if result["disconfirmed"]:
        verdict = "invalid"
    elif result["unresolved"]:
        verdict = "unresolved"
    else:
        verdict = "valid"
    return {"format": FORMAT, "verdict": verdict,
            "usable": result["usable"], "counts": {
                k: result[k] for k in ("admissible", "disconfirmed", "unresolved")}}


def authorize(record):
    """Hard prohibitions, then required evidence, then unresolved uncertainty."""
    r = record or {}
    hard = list(r.get("hard") or [])
    if hard:
        return {"format": FORMAT, "decision": "deny", "hard": hard,
                "verdict": "hard-prohibition"}
    required = set(r.get("required") or [])
    satisfied = set(r.get("satisfied") or [])
    unresolved = list(r.get("unresolved") or [])
    missing = sorted(required - satisfied)
    if missing:
        return {"format": FORMAT, "decision": "test/review", "missing": missing,
                "verdict": "evidence-missing"}
    if unresolved:
        return {"format": FORMAT, "decision": "test/review",
                "unresolved": unresolved, "verdict": "uncertainty-unresolved"}
    return {"format": FORMAT, "decision": "allow", "verdict": "allowed"}


def provenance(record):
    """Dependence among evidence sources and its variance-equivalent size."""
    r = record or {}
    n = int(r.get("n") or 0)
    rho = _num(r.get("rho"))
    if n <= 0 or rho is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if not -1.0 <= rho < 1.0:
        return {"format": FORMAT, "verdict": "rho-out-of-range"}
    effective = n / (1 + (n - 1) * rho)
    return {"format": FORMAT, "n": n, "rho": rho, "effective_n": effective,
            "dependence": "dependent" if rho > 0 else "independent-or-negative",
            "verdict": "dependence-disclosed"}


def composition(record):
    """Two-hop transport: admissible in c3 only under the stated conditions."""
    r = record or {}
    steps = int(r.get("steps") or 0)
    if steps < 2:
        return {"format": FORMAT, "verdict": "not-a-chain"}
    reasons = []
    if r.get("premises_stable") is not True:
        reasons.append("premises-not-stable")
    if r.get("same_interpretation") is not True:
        reasons.append("interpretation-drift")
    if r.get("unrecorded_defeaters") is True:
        reasons.append("unrecorded-defeater")
    if r.get("latent_dependency") is True:
        reasons.append("latent-dependency")
    return {"format": FORMAT, "steps": steps, "reasons": reasons,
            "verdict": "admissible-in-target" if not reasons
            else "reassess-transport"}


def selective(record):
    """Full retesting against selective retesting, with their cost condition."""
    r = record or {}
    obligations = int(r.get("obligations") or 0)
    changed = int(r.get("changed") or 0)
    per_check = _num(r.get("per_check"))
    map_cost = _num(r.get("map_cost")) or 0.0
    if obligations <= 0 or per_check is None or per_check <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if not 0 <= changed <= obligations:
        return {"format": FORMAT, "verdict": "changed-out-of-range"}
    full = obligations * per_check
    selective_cost = changed * per_check + map_cost
    saving = full - selective_cost
    return {"format": FORMAT, "full": full, "selective": selective_cost,
            "saving": saving, "retained": obligations - changed,
            "verdict": "selective-cheaper" if saving > 0
            else "mapping-too-costly"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("evidence_means_claim_true") is True:
        findings.append({"kind": "evidence-means-claim-true",
                         "why": "admissibility is not truth of the claim"})
    if r.get("compliance_means_goal_met") is True:
        findings.append({"kind": "compliance-means-goal-met",
                         "why": "a monitored pass covers only the checked clauses"})
    if r.get("transport_is_symmetric") is True:
        findings.append({"kind": "transport-is-symmetric",
                         "why": "a read-only evaluation does not license a write"})
    if r.get("premises_assumed_complete") is True:
        findings.append({"kind": "premises-assumed-complete",
                         "why": "a hidden dependency transports under a false premise"})
    if r.get("provenance_diversity_is_correctness") is True:
        findings.append({"kind": "provenance-diversity-is-correctness",
                         "why": "shared evaluator error survives independent-looking checks"})
    if r.get("ledger_is_a_safety_certificate") is True:
        findings.append({"kind": "ledger-is-a-safety-certificate",
                         "why": "the ledger records decisions, not future safety"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("states_the_claim_before_reuse", "reuses_on_a_score",
         "a quality label is not a prospective claim"),
        ("names_the_premises_of_reuse", "assumes_the_context_is_the_same",
         "an unnamed premise cannot be checked"),
        ("treats_unknown_as_unresolved", "treats_unknown_as_pass",
         "an unresolved check is not positive evidence"),
        ("keeps_negative_evidence_as_a_defeater", "filters_failures_out",
         "discarding a failing test hides an adverse finding"),
        ("recomputes_prohibitions_before_the_decision", "checks_at_validation_time",
         "a policy change between check and use invalidates the check"),
        ("reports_transport_as_directional", "assumes_symmetry",
         "evidence for a read does not license a write"),
        ("prices_the_dependency_map", "claims_selective_revalidation_is_free",
         "the saving is positive only if the map is cheaper than the tests"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
