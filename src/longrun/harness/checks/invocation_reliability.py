#!/usr/bin/env python3
"""Invocation reliability — a wrong call poisons every step that follows.

Source: arXiv:2608.26189, "Invocation-Level Reliability of Tool-Using Agents"
(round 139). Selection errors and argument errors are different failures, and a
single aggregate success score shows neither; by depth 6 about 70% of a small
model's clean-context capability is lost to its own earlier mistakes
(`invocation_reliability_tools_2608.26189.md:30`, `:132`).

  * **local vs global correctness**: `p_t` is measured under a teacher-forced
    history and `g_t` inside the model's own free-running trajectory; the net
    propagation loss is `L_t = 1 - g_t/p_t` (`:72`, `:74`).
  * **`L_1 = 0` by construction** is the cheapest wiring check (`:132`).
  * **scoring against a fixed gold trajectory pins severity to 1 and makes
    recovery unobservable** once the gold value is unreachable (`:171`, `:173`).
  * **conditional-on-state scoring** credits a call that continues correctly
    from the value the model actually holds (`:185`).
  * **terminal errors cannot propagate**, so their share is reported beside
    `L_t` (`:161`).
  * **rule-following is measurable directly**: `P(first | even) - P(first | odd)`
    separates deriving the rule from ignoring or inverting it (`:204`).

  * `rates(rows)` — `p`, `g`, `L` per depth.
  * `wiring(rows)` — the `L_1 = 0` check.
  * `severity(rows)` — `pi = 1 - P(ok|poisoned)/P(ok|clean)`.
  * `recovery(rows)` — returns to an on-track value.
  * `scoring(rows)` — gold-agreement against conditional scoring.
  * `terminal(rows)` — terminal-error share and the bound it sets.
  * `discrimination(rows)` — the parity statistic.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: step records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-invocation-reliability/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(rows, key):
    data = [r for r in rows if r.get(key) is not None]
    if not data:
        return None
    return sum(1 for r in data if r.get(key) == "ok") / len(data)


def rates(rows, depth=None):
    """Local and global correctness at one depth, and the propagation loss."""
    data = [r for r in (rows or ()) if depth is None or r.get("depth") == depth]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-steps"}]}
    p = _rate(data, "local")
    g = _rate(data, "global")
    if p is None or g is None or p <= 0:
        return {"format": FORMAT, "findings": [{"kind": "rates-unmeasured"}]}
    loss = 1.0 - g / p
    findings = []
    if loss > 0.1:
        findings.append({"kind": "propagation", "loss": round(loss, 4),
                         "why": "earlier mistakes lower the free-running rate"})
    elif loss > 0:
        findings.append({"kind": "mild-propagation", "loss": round(loss, 4)})
    else:
        findings.append({"kind": "no-propagation"})
    return {"format": FORMAT, "steps": len(data), "p": round(p, 4), "g": round(g, 4),
            "loss": round(loss, 4), "findings": findings}


def wiring(rows):
    """At depth 1 both arms see the same prompt, so L must be exactly zero."""
    one = [r for r in (rows or ()) if r.get("depth") == 1]
    if not one:
        return {"format": FORMAT, "findings": [{"kind": "no-depth-one"}]}
    out = rates(one)
    if out.get("loss") == 0:
        return {"format": FORMAT, "findings": [{"kind": "wiring-ok"}]}
    return {"format": FORMAT, "findings": [{"kind": "wiring-broken",
                                            "loss": out.get("loss"),
                                            "why": "the two arms are not identical at depth 1"}]}


def severity(rows):
    """P(ok | poisoned) over P(ok | clean)."""
    poisoned = [r for r in (rows or ()) if r.get("poisoned") is True]
    clean = [r for r in (rows or ()) if r.get("poisoned") is False]
    if not poisoned or not clean:
        return {"format": FORMAT, "findings": [{"kind": "severity-unmeasured"}]}
    pc = _rate(clean, "outcome")
    pp = _rate(poisoned, "outcome")
    if pc is None or pp is None or pc <= 0:
        return {"format": FORMAT, "findings": [{"kind": "severity-unmeasured"}]}
    pi = 1.0 - pp / pc
    findings = []
    if pp == 0:
        findings.append({"kind": "severity-pinned", "pi": 1.0,
                         "why": "no poisoned step succeeded, so the boundary value is forced"})
    elif len(poisoned) < 20:
        findings.append({"kind": "severity-uninformative", "steps": len(poisoned)})
    else:
        findings.append({"kind": "severity-interior", "pi": round(pi, 4)})
    return {"format": FORMAT, "pi": round(pi, 4), "poisoned_steps": len(poisoned),
            "findings": findings}


def recovery(rows):
    """A poisoned context returns on-track only if the gold value is derivable."""
    data = [r for r in (rows or ()) if r.get("poisoned") is True
            and r.get("next_outcome") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "recovery-unmeasured"}]}
    returned = sum(1 for r in data if r.get("next_outcome") == "ok")
    findings = []
    if returned == 0 and not any(r.get("gold_derivable") is True for r in data):
        findings.append({"kind": "recovery-unobservable", "steps": len(data),
                         "why": "the gold value is information the model never received"})
    elif returned > 0:
        findings.append({"kind": "recovery-observed", "rate": round(returned / len(data), 4)})
    else:
        findings.append({"kind": "recovery-clearly-zero"})
    return {"format": FORMAT, "steps": len(data), "returned": returned,
            "findings": findings}


def scoring(rows):
    """Gold-agreement against conditional-on-state scoring."""
    data = [r for r in (rows or ()) if r.get("gold_ok") is not None
            and r.get("conditional_ok") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-scored-steps"}]}
    gold = sum(1 for r in data if r.get("gold_ok") is True) / len(data)
    cond = sum(1 for r in data if r.get("conditional_ok") is True) / len(data)
    findings = []
    if gold == 0 and cond > 0:
        findings.append({"kind": "gold-pins-severity", "gold": gold, "conditional": round(cond, 4),
                         "why": "the reference is unreachable after a divergence"})
    elif cond > gold:
        findings.append({"kind": "conditional-credit", "gold": round(gold, 4),
                         "conditional": round(cond, 4)})
    else:
        findings.append({"kind": "scoring-agrees"})
    return {"format": FORMAT, "gold": round(gold, 4), "conditional": round(cond, 4),
            "findings": findings}


def terminal(rows):
    """An error on the final step cannot propagate, so its share bounds the loss."""
    data = [r for r in (rows or ()) if r.get("depth") is not None and r.get("outcome") is not None]
    errors = [r for r in data if r.get("outcome") != "ok"]
    if not errors:
        return {"format": FORMAT, "findings": [{"kind": "no-errors"}]}
    terminal = sum(1 for r in errors if r.get("step") == r.get("depth") - 1)
    share = terminal / len(errors)
    findings = []
    if share > 0.3:
        findings.append({"kind": "terminal-share-high", "share": round(share, 4),
                         "why": "a fixed-depth measurement understates propagation"})
    else:
        findings.append({"kind": "terminal-share-reported", "share": round(share, 4)})
    return {"format": FORMAT, "errors": len(errors), "terminal": terminal,
            "share": round(share, 4), "findings": findings}


def discrimination(rows):
    """P(first-listed | even) minus P(first-listed | odd) for a parity rule."""
    even = [r for r in (rows or ()) if r.get("parity") == "even"]
    odd = [r for r in (rows or ()) if r.get("parity") == "odd"]
    if not even or not odd:
        return {"format": FORMAT, "findings": [{"kind": "no-parity-split"}]}
    pe = sum(1 for r in even if r.get("first") is True) / len(even)
    po = sum(1 for r in odd if r.get("first") is True) / len(odd)
    stat = pe - po
    findings = []
    if stat >= 0.8:
        findings.append({"kind": "rule-derived", "stat": round(stat, 4)})
    elif stat > 0.1:
        findings.append({"kind": "rule-followed", "stat": round(stat, 4)})
    elif stat >= -0.1:
        findings.append({"kind": "rule-ignored", "stat": round(stat, 4)})
    else:
        findings.append({"kind": "rule-anticorrelated", "stat": round(stat, 4),
                         "why": "the model inverts the rule it was given"})
    return {"format": FORMAT, "stat": round(stat, 4), "even": round(pe, 4),
            "odd": round(po, 4), "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("scores_invocations", "task-success-only", "separate selection from arguments"),
        ("measures_both_arms", "free-running-only", "a teacher-forced arm isolates context decay"),
        ("checks_depth_one", "no-wiring-check", "L1 must be zero by construction"),
        ("scores_conditionally", "gold-only", "gold pins severity once it is unreachable"),
        ("reports_terminal_share", "aggregate-only", "final-step errors cannot propagate"),
        ("tests_rule_following", "assumes-task-performed", "condition on the rule's input"),
        ("reports_error_position", "pooled-errors", "where an error lands decides its cost"),
        ("freezes_the_suite", "moving-measurement", "the analysis must be a function of frozen data"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
