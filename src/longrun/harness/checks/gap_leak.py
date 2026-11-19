#!/usr/bin/env python3
"""Information gaps — minimizing data does not minimize what the agent can reach.

Source: arXiv:2611.22223, "GapLeak: When Privacy-Preserving LLM-based Web Agents
Become a Privacy Risk" (round 127). Data minimization and least privilege narrow
the AUTHORIZED scope, not the REACHABLE one. A form field that no authorized
source can supply opens an information gap; a goal-driven agent escalates to a
reachable but unauthorized source, accumulates context, and submits it when the
page's guidance makes it look necessary (§3.2). The measured effect: ~37% average
unauthorized disclosure, the gap is the primary driver (removing it cuts
disclosure by >50%), and an instruction-level least-privilege defence leaves
disclosure in 77% of completed tasks while dropping task success to 30% (§1).
**Submission-time verification** — an independent check of each field before
submission, required fields always kept — removes over 96% of the disclosure
without further hurting success (§4.6, Table 3).

  * `gap(requested, authorized, reachable)` — the fields where the authorized and
    reachable scopes diverge, each named.
  * `disclosure(form, policy, third_party)` — values outside the minimal-
    disclosure policy, and third-party values separately.
  * `verify(form, summary, required)` — the STV filter: required fields are kept,
    an optional field survives only if its name or value is derivable from the
    summary, everything else is cleared with a reason.
  * `compare(before, after)` — the disclosure counts and the reduction.

Derivability is a deterministic proxy (name in the summary, or the value present
in it); the paper's verifier is an independent LLM. The module says so.
"""
from __future__ import annotations

FORMAT = "longrun-gap-leak/1"


def _set(value):
    return {str(v) for v in (value or [])}


def gap(requested, authorized, reachable):
    """Fields requested but absent from the authorized scope and present in reach."""
    authorised = _set(authorized)
    reach = _set(reachable)
    open_fields = sorted(f for f in _set(requested)
                         if f not in authorised and f in reach)
    findings = [{"kind": "information-gap", "field": f,
                 "why": "no authorized source supplies it; a reachable one does"}
                for f in open_fields]
    return {"format": FORMAT, "gap": open_fields, "findings": findings,
            "why": "the divergence between authorized and reachable scope"}


def _derivable(field, value, summary):
    name = str(field).casefold()
    if name in {str(k).casefold() for k in (summary or {})}:
        return True
    text = str(value or "").strip().casefold()
    return bool(text) and any(text == str(v).strip().casefold()
                              for v in (summary or {}).values())


def disclosure(form, policy, third_party=()):
    """Values outside the minimal-disclosure policy, third-party ones counted apart."""
    form = form if isinstance(form, dict) else {}
    allowed = _set(policy)
    third = _set(third_party)
    outside = sorted(str(f) for f in form if str(f) not in allowed)
    third_rows = sorted(f for f in outside if f in third)
    findings = []
    if outside:
        findings.append({"kind": "over-disclosure", "fields": outside,
                         "why": "submitted beyond what the task minimally requires"})
    if third_rows:
        findings.append({"kind": "third-party-disclosure", "fields": third_rows,
                         "why": "these values belong to people who never consented"})
    total = len(form) or 1
    return {"format": FORMAT, "outside_policy": outside, "third_party": third_rows,
            "disclosure_rate": round(len(outside) / total, 4),
            "findings": findings,
            "why": "the boundary is the minimal-disclosure policy, not the visit"}


def verify(form, summary, required):
    """Submission-time verification: required kept, optional kept only if derivable."""
    form = form if isinstance(form, dict) else {}
    required = _set(required)
    kept, cleared, findings = {}, [], []
    for field, value in form.items():
        field = str(field)
        if field in required:
            kept[field] = value
            continue
        if _derivable(field, value, summary):
            kept[field] = value
            continue
        cleared.append(field)
        findings.append({"kind": "cleared-unauthorized-field", "field": field,
                         "why": "neither its name nor its value is in the summary"})
    missing = sorted(required - set(kept))
    for field in missing:
        findings.append({"kind": "required-field-missing", "field": field,
                         "why": "verification never drops a required field silently"})
    return {"format": FORMAT, "kept": kept, "cleared": sorted(cleared),
            "preserved_required": not missing, "findings": findings,
            "why": "required fields are always authorized to keep task success"}


def compare(before, after):
    """Disclosure counts before and after the filter."""
    def outside(form, policy):
        return len([f for f in (form or {}) if str(f) not in _set(policy)])

    b = outside(before.get("form") if isinstance(before, dict) else before,
                (before or {}).get("policy") if isinstance(before, dict) else ())
    a = outside(after.get("form") if isinstance(after, dict) else after,
                (after or {}).get("policy") if isinstance(after, dict) else ())
    return {"format": FORMAT, "before": b, "after": a,
            "reduction": None if not b else round((b - a) / b, 4),
            "findings": [] if a < b else [{"kind": "no-reduction"}],
            "why": "a filter that removes nothing is not a defence"}
