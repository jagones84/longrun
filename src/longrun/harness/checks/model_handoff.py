#!/usr/bin/env python3
"""Model handoff — route the step, not the query.

Source: arXiv:2610.07816, "Do I Need the Cloud?" (round 141). Small local models
are attractive agent controllers, but one wrong tool name or argument fails a
whole trajectory, and existing routers decide once per query
(`step_level_model_handoff_2610.07816.md:17`, `:18`). StepGate scores each local
action and escalates only the difficult or risky steps (`:20`, `:22`).

  * **the decision unit is an action**, re-evaluated after every observation
    (`:79`, `:170`).
  * **uncertainty is action-structured**: token, tool margin, schema,
    consistency, state and risk (`:174`, `:181`).
  * **a three-way policy**: local, bounded local verification, cloud, with
    threshold shifts for risk and budget (`:568`, `:578`).
  * **single-step**: 82.7% success at 30.8% escalation against 67.3% local-only
    and 75.4% random at 33.8% (`:287`, `:291`).
  * **multi-turn**: 69.0% trajectory success at 30.0% cloud actions against
    48.0% local-only, 60.0% random and 57.0% query-level; strong-only is 82.0%
    at 100% (`:303`, `:314`).
  * **the gate is calibrated, not guaranteed**: logistic AUROC 0.829, Brier
    0.144, ECE 0.212, and the risk features do not improve task success
    (`:392`, `:394`, `:405`).
  * **routing saturates as the local model approaches the ceiling**: 3B gains
    little over an 88.5% local baseline (`:340`, `:343`).
  * **handoff context is minimized deliberately**, and remote-token count is a
    disclosure proxy, not a privacy guarantee (`:225`, `:415`).

  * `gate(features)` — local / verify / cloud, with risk and budget shifts.
  * `signals(row)` — the six signal families and what is missing.
  * `calibration(rows)` — AUROC, Brier, ECE and the two separate failures.
  * `budget(rows)` — a budget-matched comparison and the headroom it closes.
  * `pareto(rows)` — success maximized, cloud actions minimized.
  * `handoff(packet)` — the six fields of a minimized packet.
  * `recovery(rows)` — recovery per failure type, and why probability is not benefit.
  * `saturate(rows)` — when routing stops paying.
  * `audit(record)` — the guards that make a routing result meaningful.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: features and rows in; decisions out.
"""
from __future__ import annotations

FORMAT = "longrun-model-handoff/1"

SIGNALS = ("token", "margin", "schema", "consistency", "state", "risk")
RISK_TIERS = ("R0", "R1", "R2", "R3")
PACKET_FIELDS = ("subgoal", "tools", "state_summary", "action",
                 "uncertainty", "observations")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gate(features):
    """One step: execute locally, verify locally, or escalate."""
    f = features or {}
    q = _num(f.get("q"))
    if q is None or not 0.0 <= q <= 1.0:
        return {"format": FORMAT, "decision": "invalid-q"}
    risk = str(f.get("risk") or "R0")
    tau_l = _num(f.get("tau_l"))
    tau_c = _num(f.get("tau_c"))
    tau_l = 0.30 if tau_l is None else tau_l
    tau_c = 0.70 if tau_c is None else tau_c
    if risk in ("R2", "R3"):
        tau_l = max(0.0, tau_l - 0.10)
        tau_c = max(0.0, tau_c - 0.15)
    cloud_left = _num(f.get("cloud_left"))
    if q <= tau_l:
        decision = "local"
    elif q >= tau_c:
        decision = "cloud"
    else:
        decision = "verify"
    if decision == "cloud" and cloud_left is not None and cloud_left <= 0:
        decision = "verify"
    return {"format": FORMAT, "decision": decision, "q": q, "risk": risk,
            "tau_l": tau_l, "tau_c": tau_c,
            "note": "schema validity or low uncertainty never grants authorization"}


def signals(row):
    """Six families; a missing one is named rather than assumed."""
    r = row or {}
    present = [name for name in SIGNALS if r.get(name) not in (None, "", False)]
    missing = [name for name in SIGNALS if name not in present]
    return {"format": FORMAT, "present": present, "missing": missing,
            "verdict": "signals-complete" if not missing else "signals-partial"}


def calibration(rows):
    """Ranking and calibration are two different claims."""
    pairs = []
    for row in rows or []:
        p = _num((row or {}).get("p"))
        y = (row or {}).get("y")
        if p is None or y is None:
            continue
        pairs.append((max(0.0, min(1.0, p)), 1 if y else 0))
    if not pairs:
        return {"format": FORMAT, "verdict": "no-pairs"}
    positives = [p for p, y in pairs if y == 1]
    negatives = [p for p, y in pairs if y == 0]
    if positives and negatives:
        wins = sum(1 for a in positives for b in negatives
                   if a > b) + 0.5 * sum(1 for a in positives for b in negatives
                                         if a == b)
        auroc = wins / (len(positives) * len(negatives))
    else:
        auroc = None
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    bins = {}
    for p, y in pairs:
        index = min(9, int(p * 10))
        slot = bins.setdefault(index, [0, 0.0, 0])
        slot[0] += 1
        slot[1] += p
        slot[2] += y
    ece = sum(abs(slot[1] / slot[0] - slot[2] / slot[0]) * slot[0]
              for slot in bins.values()) / len(pairs)
    if auroc is not None and auroc < 0.7:
        verdict = "gate-does-not-rank"
    elif ece > 0.10:
        verdict = "gate-miscalibrated"
    else:
        verdict = "gate-calibrated"
    return {"format": FORMAT, "n": len(pairs), "auroc": auroc,
            "brier": brier, "ece": ece, "verdict": verdict,
            "note": "ranking and calibration are separate; neither bounds misrouting"}


def budget(rows):
    """A budget-matched comparison, and the share of headroom it closes."""
    table = {}
    for row in rows or []:
        method = str((row or {}).get("method") or "")
        success = _num((row or {}).get("success"))
        cloud = _num((row or {}).get("cloud"))
        if not method or success is None or cloud is None:
            continue
        table[method] = {"success": success, "cloud": cloud,
                         "realized": _num((row or {}).get("realized"))}
    local, strong = table.get("local-only"), table.get("strong-only")
    target = next((value for key, value in table.items()
                   if "step" in key.lower()), None)
    if target is None:
        target = next((value for key, value in table.items()
                       if key not in ("local-only", "strong-only")), None)
    if not local or not strong or not target:
        return {"format": FORMAT, "methods": table,
                "verdict": "three-arms-required"}
    headroom = strong["success"] - local["success"]
    closed = ((target["success"] - local["success"]) / headroom
              if headroom > 0 else 0.0)
    realized = target.get("realized")
    budgeted = (abs(realized - target["cloud"]) <= 0.02
                if realized is not None else None)
    if closed >= 0.6:
        verdict = "closes-most-headroom"
    elif closed > 0:
        verdict = "closes-part-of-headroom"
    else:
        verdict = "no-headroom-closed"
    return {"format": FORMAT, "methods": table, "headroom": headroom,
            "headroom_closed": closed,
            "budget_matched": budgeted, "verdict": verdict}


def pareto(rows):
    """Success maximized, cloud actions minimized."""
    clean = []
    for row in rows or []:
        success = _num((row or {}).get("success"))
        cloud = _num((row or {}).get("cloud"))
        if success is None or cloud is None:
            continue
        clean.append({"method": (row or {}).get("method"),
                      "success": success, "cloud": cloud})
    frontier = []
    for row in clean:
        dominated = False
        for other in clean:
            if other is row:
                continue
            if (other["success"] >= row["success"]
                    and other["cloud"] <= row["cloud"]
                    and (other["success"] > row["success"]
                         or other["cloud"] < row["cloud"])):
                dominated = True
                break
        row["efficient"] = not dominated
        if not dominated:
            frontier.append(row["method"])
    return {"format": FORMAT, "rows": clean, "frontier": sorted(frontier)}


def handoff(packet):
    """Escalation transmits a decision packet, not the whole history."""
    p = packet or {}
    missing = [name for name in PACKET_FIELDS if p.get(name) in (None, "", [])]
    findings = [{"kind": "packet-field-missing", "field": name}
                for name in missing]
    if p.get("full_history") is True:
        findings.append({"kind": "context-over-disclosed",
                         "why": "the whole local history crosses the boundary"})
    if p.get("sensitive_literals") is True:
        findings.append({"kind": "sensitive-value-in-packet",
                         "why": "redact or tokenize when the literal is not needed"})
    if not findings:
        findings.append({"kind": "handoff-minimized"})
    return {"format": FORMAT, "findings": findings}


def recovery(rows):
    """Same failure probability, different escalation benefit."""
    clean = []
    for row in rows or []:
        rate = _num((row or {}).get("recovery"))
        count = _num((row or {}).get("count"))
        if rate is None:
            continue
        clean.append({"failure": (row or {}).get("failure"), "recovery": rate,
                      "count": count or 0.0})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    rates = [row["recovery"] for row in clean]
    spread = max(rates) - min(rates)
    order = sorted(clean, key=lambda row: row["recovery"])
    return {"format": FORMAT, "rows": order, "spread": spread,
            "lowest": order[0]["failure"], "highest": order[-1]["failure"],
            "verdict": ("failure-type-matters" if spread > 0.2
                        else "recovery-uniform")}


def saturate(rows):
    """Routing pays until the local model approaches the strong ceiling."""
    clean = []
    for row in rows or []:
        local = _num((row or {}).get("local"))
        routed = _num((row or {}).get("routed"))
        strong = _num((row or {}).get("strong"))
        if local is None or routed is None or strong is None:
            continue
        margin = strong - local
        gain = routed - local
        clean.append({"model": (row or {}).get("model"), "local": local,
                      "routed": routed, "strong": strong,
                      "margin": margin, "gain": gain,
                      "share": gain / margin if margin > 0 else 0.0})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    saturated = [row["model"] for row in clean
                 if row["gain"] < 0.02 or row["margin"] < 0.05]
    return {"format": FORMAT, "rows": clean, "saturated": saturated,
            "verdict": "routing-saturates" if saturated else "routing-headroom"}


def audit(record):
    """The guards that make a routing result meaningful."""
    r = record or {}
    findings = []
    if r.get("step_level") is not True:
        findings.append({"kind": "query-level-baseline",
                         "why": "a query router cannot react to an observation"})
    if r.get("budget_matched") is not True:
        findings.append({"kind": "unmatched-budget",
                         "why": "a success gain without the same cloud rate is not a comparison"})
    if r.get("labels_from_local") is not True:
        findings.append({"kind": "label-leak",
                         "why": "strong-model outputs must not train the failure gate"})
    if r.get("risk_as_authorization") is True:
        findings.append({"kind": "risk-is-not-authorization",
                         "why": "the gate is not an access-control system"})
    if r.get("reports_remote_tokens") is not True:
        findings.append({"kind": "disclosure-unmeasured",
                         "why": "remote tokens are the disclosure-volume proxy"})
    if not findings:
        findings.append({"kind": "handoff-read-correctly"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("routes_per_step", "query-level-router",
         "difficulty changes after every tool result"),
        ("scores_structured_uncertainty", "token-entropy-only",
         "token uncertainty alone reaches 76.9%, not 82.7%"),
        ("calibrates_the_gate", "uncalibrated-threshold",
         "a gate that ranks but misreports its probability breaks the budget"),
        ("matches_the_cloud_budget", "unequal-escalation",
         "every claim is at a declared cloud rate"),
        ("minimizes_the_packet", "sends-full-history",
         "only the fields needed for the decision cross the boundary"),
        ("reports_recovery_by_type", "escalation-rate-only",
         "recovery varies by failure type"),
        ("tests_saturation", "one-model-size",
         "routing stops paying as the local model nears the ceiling"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
