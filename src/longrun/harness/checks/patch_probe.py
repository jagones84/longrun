#!/usr/bin/env python3
"""Patch probes — replaying the trigger is not the invariant.

Source: arXiv:2611.20514, "Beyond the Patch: Reconstructing an Incomplete-Fix
Patch Bypass in LLM Agent Frameworks with Control-Gated, Benign Probes" (round
126). A patched boundary at one version can still be violated through a distinct
sibling path: PraisonAI's CVE-2026-40287 fix gated the local-tool path, the
`tool_override` path stayed open, and the residual was later assigned
CVE-2026-44334 (a "patch bypass") and closed one version later (§V-A). The
method that catches this is small and the gate is the point: a verdict is
admitted only when an authorized POSITIVE CONTROL passes in the same run, a
non-violation means "no violation observed under this probe, version and
configuration" (never "secure"), and a stale marker is not an effect.

  * `verdict(control_ok, effect_seen, token_ok=True)` — three states, gated.
  * `compare(b0, m)` — a same-version divergence where the original trigger looks
    fixed and the sibling path still violates; different versions are reported
    as such, not as a bypass.
  * `provenance(runs, advisory)` — the first version observed to hold, against
    the advisory's claim; a CVE with no recorded fixed version is named.
  * `validate(runs)` — per-path controls, per-run tokens, observer presence: the
    three ways a harness can fake a non-violation.

This module does not install packages or run probes; it decides what a run's
records mean.
"""
from __future__ import annotations

FORMAT = "longrun-patch-probe/1"
VIOLATION, NO_VIOLATION, INCONCLUSIVE = "VIOLATION", "NO_VIOLATION_OBSERVED", "INCONCLUSIVE"


def verdict(control_ok, effect_seen, token_ok=True):
    """A non-violation is admitted only behind a passing control and a fresh token."""
    findings = []
    if not control_ok:
        findings.append({"kind": "control-failed",
                         "why": "a boundary that breaks all input must not look fixed"})
        return {"format": FORMAT, "verdict": INCONCLUSIVE, "findings": findings}
    if effect_seen and not token_ok:
        findings.append({"kind": "stale-marker",
                         "why": "a leftover marker is not an effect from this run"})
        return {"format": FORMAT, "verdict": INCONCLUSIVE, "findings": findings}
    if effect_seen:
        return {"format": FORMAT, "verdict": VIOLATION, "findings": [],
                "why": "the invariant was violated under this probe"}
    return {"format": FORMAT, "verdict": NO_VIOLATION, "findings": [],
            "why": "no violation observed under this probe, version and configuration"}


def compare(b0, m):
    """Original trigger vs a sibling path at the SAME version."""
    b0 = b0 if isinstance(b0, dict) else {}
    m = m if isinstance(m, dict) else {}
    findings = []
    if b0.get("version") != m.get("version"):
        findings.append({"kind": "different-versions",
                         "b0": b0.get("version"), "sibling": m.get("version"),
                         "why": "a before/after result is not a same-version bypass"})
        return {"format": FORMAT, "divergence": False, "findings": findings}
    if b0.get("verdict") == NO_VIOLATION and m.get("verdict") == VIOLATION:
        findings.append({"kind": "incomplete-fix", "version": b0.get("version"),
                         "b0_path": b0.get("path"), "sibling_path": m.get("path"),
                         "why": "the reported trigger is blocked and the invariant is not"})
        return {"format": FORMAT, "divergence": True, "findings": findings,
                "why": "replaying the PoC would call this boundary fixed"}
    return {"format": FORMAT, "divergence": False, "findings": findings,
            "why": "no same-version split between the two paths"}


def provenance(runs, advisory=None):
    """The first version observed to hold, named against the advisory's claim."""
    rows = [r for r in (runs or []) if isinstance(r, dict)]
    violations = sorted(str(r.get("version")) for r in rows
                        if r.get("verdict") == VIOLATION)
    holds = sorted(str(r.get("version")) for r in rows
                   if r.get("verdict") == NO_VIOLATION)
    advisory = advisory or {}
    findings = []
    if not holds:
        findings.append({"kind": "no-observed-fix",
                         "why": "no tested version admitted a non-violation"})
    if not advisory.get("fixed_version"):
        findings.append({"kind": "no-recorded-fix",
                         "why": "the advisory records no fixed version; the "
                                "observation is the only provenance"})
    elif holds and str(advisory["fixed_version"]) != holds[0]:
        findings.append({"kind": "metadata-disagrees",
                         "advisory": advisory["fixed_version"], "observed": holds[0]})
    return {"format": FORMAT, "violating": violations, "holding": holds,
            "first_observed_fix": holds[0] if holds else None,
            "findings": findings,
            "why": "a non-violation covers the tested probe, version and configuration only"}


def validate(runs):
    """Per-path controls, per-run tokens, observer presence."""
    findings = []
    for run in runs or ():
        if not isinstance(run, dict):
            continue
        ref = {"boundary": run.get("boundary"), "path": run.get("path"),
               "token": run.get("token")}
        if run.get("control_ok") is not True:
            findings.append({"kind": "control-missing", **ref})
        if not run.get("token"):
            findings.append({"kind": "token-missing", **ref,
                             "why": "without a per-run token a stale marker counts"})
        if not run.get("observer"):
            findings.append({"kind": "observer-missing", **ref,
                             "why": "an effect nobody can observe is not measured"})
    return {"format": FORMAT, "valid": not findings, "findings": findings,
            "runs": len([r for r in (runs or []) if isinstance(r, dict)])}
