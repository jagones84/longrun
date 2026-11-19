#!/usr/bin/env python3
"""Exfiltration defense — a memory payload has three steps, and every defense
breaks exactly one of them.

Source: arXiv:2605.01970, "Trojan Hippo Bench: A Dynamic Benchmark for Persistent
Memory Attacks and Defenses in LLM Agents" (round 158). A single indirect
injection is written to memory, lies dormant across many benign sessions, and
activates only when the user discusses a sensitive topic, exfiltrating their data
(`trojan_hippo_exfil_2605.01970.txt:176`, `:219`). The undefended attack reaches
85–100% ASR against frontier models across four memory backends and survives 100+
benign sessions (`:116`, `:464`); four memory-layer defenses cut it to 0–5%, and a
provable two-label information-flow policy reaches 0% by construction (`:336`,
`:753`). The part that makes the result usable is the capability-aware analysis:
a single aggregate utility hides that one defense breaks a different workflow than
another, so the paper reports per-flow success and both means (`:416`, `:556`).

This module keeps the three-step chain explicit, refuses an undefined
backend/defense pair instead of scoring it, and reports the security/utility
frontier with the harmonics that expose a structural break.

Formats: `longrun-exfil-defense/1`.
"""

FORMAT = "longrun-exfil-defense/1"

# The attack must (1) be indexed, (2) be retrieved in a sensitive session,
# (3) trigger an exfiltration action (paper §6.1, `:331`).
_STEPS = ("index", "retrieve", "act")

# Defense -> the step it breaks (paper §6.2, `:339`).
_DEFENSES = {
    "user-prompt-only": {"step": "index", "mode": "stores only user messages"},
    "no-untrusted-write": {"step": "index",
                           "mode": "suppresses memory writes in a tainted session"},
    "limit-memory-length": {"step": "retrieve",
                            "mode": "truncates a stored unit below payload length"},
    "provable-policy": {"step": "act",
                        "mode": "blocks sinks once the session is tainted"},
}

# Backend x defense: an undefined pair is skipped, never scored (paper Table 1,
# `:388`).
_APPLICABLE = {
    "explicit": {"user-prompt-only": False, "no-untrusted-write": True,
                 "limit-memory-length": True, "provable-policy": True},
    "mem0": {"user-prompt-only": True, "no-untrusted-write": True,
             "limit-memory-length": True, "provable-policy": True},
    "rag": {"user-prompt-only": True, "no-untrusted-write": True,
            "limit-memory-length": True, "provable-policy": True},
    "context": {"user-prompt-only": True, "no-untrusted-write": True,
                "limit-memory-length": False, "provable-policy": True},
}

# The seven capability flows (paper Table 2, `:424`).
_FLOWS = ("memory_only", "long_memory", "assistant_responses", "untrusted_probe",
          "disable_send", "untrusted_send", "memory_tools")


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def points():
    """The three sequential steps an exfiltration attack must complete."""
    return {"format": FORMAT, "steps": list(_STEPS),
            "note": "a defense that blocks any one step breaks the chain"}


def defenses(record=None):
    """The four memory-layer defenses, or one of them by name."""
    name = str((record or {}).get("defense") or "").strip().lower()
    if name:
        if name not in _DEFENSES:
            return {"format": FORMAT, "verdict": "unknown-defense",
                    "known": sorted(_DEFENSES)}
        d = _DEFENSES[name]
        return {"format": FORMAT, "defense": name, "blocks": d["step"],
                "mode": d["mode"], "verdict": "classified"}
    return {"format": FORMAT, "defenses": [
        {"defense": k, "blocks": v["step"], "mode": v["mode"]}
        for k, v in _DEFENSES.items()]}


def applicability(record):
    """Is this backend/defense pair defined at all?

    `record` = {"backend": "explicit"|"mem0"|"rag"|"context",
                "defense": name} or {"pairs": [{backend, defense}, ...]}
    """
    backend = str(record.get("backend") or "").strip().lower()
    defense = str(record.get("defense") or "").strip().lower()
    if backend and defense:
        if backend not in _APPLICABLE or defense not in _DEFENSES:
            return {"format": FORMAT, "verdict": "unknown-pair"}
        ok = bool(_APPLICABLE[backend].get(defense))
        return {"format": FORMAT, "backend": backend, "defense": defense,
                "verdict": "defined" if ok else "undefined"}
    pairs = [p for p in (record.get("pairs") or []) if isinstance(p, dict)]
    if not pairs:
        return {"format": FORMAT, "verdict": "no-pairs"}
    out = []
    for p in pairs:
        b = str(p.get("backend") or "").lower()
        d = str(p.get("defense") or "").lower()
        ok = bool(_APPLICABLE.get(b, {}).get(d))
        out.append({"backend": b, "defense": d,
                    "verdict": "defined" if ok else "undefined"})
    return {"format": FORMAT, "pairs": out,
            "undefined": sum(1 for r in out if r["verdict"] == "undefined")}


def chain(record):
    """Does the chain complete, and where does a defense break it?

    `record` = {"defense": name (optional), "rates": {"index": 0..1,
                "retrieve": 0..1, "act": 0..1}}
    With rates the result is the joint probability (independent stages); with a
    defense the named step is forced to 0, which is what "blocks by
    construction" means (`:336`).
    """
    rates = record.get("rates") or {}
    defense = str(record.get("defense") or "").strip().lower()
    out = {}
    for step in _STEPS:
        out[step] = _num(rates.get(step), 1.0)
    blocked = None
    if defense:
        if defense not in _DEFENSES:
            return {"format": FORMAT, "verdict": "unknown-defense"}
        blocked = _DEFENSES[defense]["step"]
        out[blocked] = 0.0
    joint = out["index"] * out["retrieve"] * out["act"]
    return {"format": FORMAT, "steps": out, "joint": joint,
            "blocked_at": blocked,
            "verdict": ("blocked" if blocked else
                        "chain-complete" if joint >= 0.5 else "chain-weak")}


def utility(record):
    """Per-flow utility, both means, and the structural break they hide.

    `record` = {"flows": {"memory_only": 0..1, ...}} (subset allowed)
    The harmonic mean is the load-bearing number: one zeroed flow collapses it
    while the arithmetic mean can stay moderate (paper §7.3, `:556`).
    """
    flows = {k: _num(v) for k, v in (record.get("flows") or {}).items()
             if k in _FLOWS}
    if not flows:
        return {"format": FORMAT, "verdict": "no-flows",
                "known": list(_FLOWS)}
    values = list(flows.values())
    am = sum(values) / len(values)
    hm = 0.0 if any(v <= 0 for v in values) else len(values) / sum(1.0 / v for v in values)
    broken = sorted(k for k, v in flows.items() if v <= 0)
    return {"format": FORMAT, "flows": flows, "am": am, "hm": hm,
            "broken": broken,
            "verdict": ("capability-break" if hm == 0 and am > 0
                        else "partial" if broken else "preserved")}


def frontier(record):
    """The non-dominated (ASR, harmonic-utility) points.

    `record` = {"rows": [{"backend", "defense", "asr", "hm"}, ...]}
    A row is dominated when another has both lower ASR and higher HM. The
    frontier is what a deployment chooses from; an aggregate-utility ranking is
    not (`:448`).
    """
    rows = [r for r in (record.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "verdict": "no-rows"}
    norm = [{"backend": r.get("backend"), "defense": r.get("defense"),
             "asr": _num(r.get("asr")), "hm": _num(r.get("hm"))} for r in rows]
    keep = []
    for r in norm:
        dominated = any(
            (o["asr"] <= r["asr"] and o["hm"] >= r["hm"]
             and (o["asr"] < r["asr"] or o["hm"] > r["hm"]))
            for o in norm if o is not r)
        if not dominated:
            keep.append(r)
    keep.sort(key=lambda r: (r["asr"], -r["hm"]))
    return {"format": FORMAT, "frontier": keep, "dominance": len(norm) - len(keep),
            "verdict": "frontier-computed"}


def persistence(record):
    """Does the payload survive time, and is the sweep order-sensitive?

    `record` = {"sweep": [{"n": 0, "asr": ..}, ...], "sd": .., "seeds": ..}
    The paper reports no decay across N up to 100 and attributes the variation to
    session ordering (43% and 33% sd for two backends), not to model noise
    (`:464`, `:470`).
    """
    sweep = [p for p in (record.get("sweep") or []) if isinstance(p, dict)]
    if not sweep:
        return {"format": FORMAT, "verdict": "no-sweep"}
    levels = [_num(p.get("asr")) for p in sweep]
    first, last = levels[0], levels[-1]
    drop = first - last
    sd = record.get("sd")
    out = {"format": FORMAT, "points": len(levels), "first": first,
           "last": last, "drop": drop}
    if sd is not None:
        out["sd"] = _num(sd)
    if drop > 0.10:
        out["verdict"] = "decays"
    elif sd is not None and _num(sd) > 0.25:
        out["verdict"] = "persistent-order-sensitive"
    else:
        out["verdict"] = "persistent"
    return out


def audit_record(record):
    """Check a defense battery's accounting before trusting a comparison."""
    findings = []
    rows = [r for r in (record.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        findings.append("no rows supplied")
    undefined = [r for r in rows
                 if not _APPLICABLE.get(str(r.get("backend") or "").lower(), {})
                 .get(str(r.get("defense") or "").lower(), False)]
    if undefined:
        findings.append("%d row(s) scored on an undefined backend/defense pair"
                        % len(undefined))
    zero_asr = [r for r in rows if _num(r.get("asr")) == 0.0]
    if zero_asr and not any(r.get("hm") is not None for r in zero_asr):
        findings.append("%d zero-ASR row(s) reported without a utility figure; "
                        "a defense that blocks everything also scores zero"
                        % len(zero_asr))
    return {"format": FORMAT, "rows": len(rows), "findings": findings,
            "verdict": "audit-complete"}


def advise(profile):
    """Recommendations from a measured defense profile."""
    findings = []
    if (profile or {}).get("hm") is not None and _num(profile.get("hm")) == 0:
        findings.append("harmonic utility is zero: at least one workflow is "
                        "completely broken, which an aggregate score hides")
    if (profile or {}).get("asr") is not None and _num(profile.get("asr")) > 0:
        findings.append("residual ASR %.2f: the defense does not close the chain"
                        % _num(profile.get("asr")))
    if (profile or {}).get("sd") is not None and _num(profile.get("sd")) > 0.25:
        findings.append("high variance (%.2f) is session ordering, so single-seed "
                        "ASR is not a result" % _num(profile.get("sd")))
    if (profile or {}).get("undefined"):
        findings.append("%s pair(s) are undefined and must not be scored"
                        % profile.get("undefined"))
    if not findings:
        findings.append("no ASR, utility or variance measurement supplied")
    return {"format": FORMAT, "findings": findings}
