#!/usr/bin/env python3
"""Memory write channels — a write is a trigger plus a write authority.

Source: arXiv:2606.04329, "From Untrusted Input to Trusted Memory: A Systematic
Study of Memory Poisoning Attacks in LLM Agents" (round 158). The paper's result
is that memory poisoning is not one attack but four write channels, each
distinguished by what INITIATES a write and what DECIDES its content: an explicit
instruction (C1), a standing system-prompt retention policy (C2), a compaction
threshold (C3), and an experience-to-procedure synthesis (C4)
(`mempoison_channels_2606.04329.txt:103`, `:136`). Nine structural
vulnerabilities across the model, the prompt and the architecture make those
channels exploitable (`:186`), and six attack classes follow from them
(`:278`). The measured result is a design tension: the agents that write and
retrieve memory more aggressively are proportionally easier to poison, with
average ASR 66.67% on the permissive agent against 34.25% on the conservative
one (`:445`, `:451`), and prompt-injection detectors cover the strong-signal
attacks far better than the weak-signal ones (`:543`).

This module turns that into decisions: classify a write event into a channel,
name the vulnerabilities it exploits, score exposure and retrieval persistence,
and state how much of a detector's coverage is structural rather than tuned.

Formats: `longrun-memory-channel/1`.
"""

FORMAT = "longrun-memory-channel/1"

# trigger -> authority -> channel. A channel is defined by these two fields, not
# by the input source (the paper states this explicitly: `:166`).
_CHANNELS = {
    "instruction": {"channel": "C1", "name": "explicit instruction-executed write",
                    "kind": "direct"},
    "policy": {"channel": "C2", "name": "system prompt-driven write",
               "kind": "inferred"},
    "compaction": {"channel": "C3", "name": "compaction-driven write",
                   "kind": "inferred"},
    "experience": {"channel": "C4", "name": "experience-to-procedure write",
                   "kind": "inferred"},
}

# The nine structural vulnerabilities, with the layer and the channels they
# reach (paper Table 1, `:263`).
_VULNS = {
    "V-M1": {"layer": "model", "name": "instruction-data boundary blindness",
             "channels": ["C1"]},
    "V-M2": {"layer": "model", "name": "source attribution failure",
             "channels": ["C2", "C3"]},
    "V-P1": {"layer": "prompt", "name": "write policy under-specification",
             "channels": ["C2"]},
    "V-P2": {"layer": "prompt", "name": "compaction without source filtering",
             "channels": ["C3"]},
    "V-S1": {"layer": "system", "name": "no write-path validation",
             "channels": ["C1", "C2", "C3"]},
    "V-S2": {"layer": "system", "name": "shared multi-source context",
             "channels": ["C1", "C2", "C3"]},
    "V-S3": {"layer": "system", "name": "manipulable compaction trigger",
             "channels": ["C3"]},
    "V-S4": {"layer": "system", "name": "no validation for skill creation",
             "channels": ["C4"]},
    "V-S5": {"layer": "system", "name": "self-improvement as amplification",
             "channels": ["C4"]},
}

# Six attack classes: signal strength, channel, vulnerabilities (paper Table 2,
# `:470`).
_ATTACKS = {
    "explicit-command": {"signal": "strong", "channel": "C1",
                         "vulns": ["V-M1", "V-S1", "V-S2"]},
    "conditional-command": {"signal": "strong", "channel": "C1",
                            "vulns": ["V-M1", "V-S1", "V-S2"]},
    "salience-compaction": {"signal": "strong", "channel": "C3",
                            "vulns": ["V-M2", "V-P2", "V-S3"]},
    "policy-fact": {"signal": "weak", "channel": "C2",
                    "vulns": ["V-M2", "V-P1", "V-S1"]},
    "false-precedent": {"signal": "weak", "channel": "C2",
                        "vulns": ["V-M2", "V-P1", "V-S1"]},
    "skill-procedure": {"signal": "weak", "channel": "C4",
                        "vulns": ["V-S4", "V-S5"]},
}

_TRIGGERS = ("instruction", "policy", "compaction", "experience")


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def channels():
    """The four write channels, by trigger and authority."""
    return {"format": FORMAT, "channels": [
        {"channel": c["channel"], "name": c["name"], "trigger": t,
         "authority": "instruction" if t == "instruction" else "model",
         "kind": c["kind"]}
        for t, c in _CHANNELS.items()]}


def vulnerabilities():
    """The nine structural vulnerabilities and the channels they reach."""
    return {"format": FORMAT, "vulnerabilities": [
        {"id": v, "layer": d["layer"], "name": d["name"],
         "channels": list(d["channels"])}
        for v, d in _VULNS.items()]}


def classify(record):
    """Classify a memory write by its trigger (and, optionally, its authority).

    `record` = {"trigger": one of instruction|policy|compaction|experience,
                "authority": "instruction"|"model" (optional)}
    The authority must agree with the trigger: an instruction channel whose
    content is decided by the model is not C1, and a policy channel decided by
    the instruction is C1. That disagreement is the failure the paper calls out
    when it says the channels are distinguished by trigger and authority, not by
    the input (`:166`).
    """
    trigger = str(record.get("trigger") or "").strip().lower()
    if trigger not in _CHANNELS:
        return {"format": FORMAT, "verdict": "unknown-trigger",
                "trigger": trigger, "known": list(_TRIGGERS)}
    authority = str(record.get("authority") or
                    ("instruction" if trigger == "instruction" else "model"))
    expected = "instruction" if trigger == "instruction" else "model"
    ch = _CHANNELS[trigger]
    vulns = [v for v, d in _VULNS.items() if ch["channel"] in d["channels"]]
    out = {"format": FORMAT, "channel": ch["channel"], "name": ch["name"],
           "kind": ch["kind"], "trigger": trigger, "authority": authority,
           "vulnerabilities": vulns}
    if authority != expected:
        out["verdict"] = "authority-mismatch"
        out["expected_authority"] = expected
        out["channel"] = "C1" if authority == "instruction" else ch["channel"]
    else:
        out["verdict"] = "classified"
    return out


def taxonomy(record=None):
    """The six attack classes, or one class looked up by name."""
    name = str((record or {}).get("attack") or "").strip().lower()
    if name:
        if name not in _ATTACKS:
            return {"format": FORMAT, "verdict": "unknown-attack",
                    "attack": name, "known": sorted(_ATTACKS)}
        d = _ATTACKS[name]
        return {"format": FORMAT, "attack": name, "signal": d["signal"],
                "channel": d["channel"], "vulnerabilities": list(d["vulns"]),
                "verdict": "classified"}
    return {"format": FORMAT, "attacks": [
        {"attack": k, "signal": d["signal"], "channel": d["channel"],
         "vulnerabilities": list(d["vulns"])}
        for k, d in _ATTACKS.items()]}


def exposure(record):
    """Attack success and retrieval persistence from per-class counts.

    `record` = {"rows": [{"attack": name, "asr": 0..1, "rsr": 0..1}, ...]}
    ASR is the write success and RSR the later-session influence, conditioned on
    a written entry (paper eq. 1 and 2, `:427`, `:442`). Both are reported with
    the number of classes they average: an average over two classes is not the
    pooled rate, and the module refuses to imply it is.
    """
    rows = [r for r in (record.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "verdict": "no-rows"}
    asr = [_num(r.get("asr")) for r in rows]
    rsr = [_num(r.get("rsr")) for r in rows if r.get("rsr") is not None]
    best = max(rows, key=lambda r: _num(r.get("asr")))
    worst = min(rows, key=lambda r: _num(r.get("asr")))
    strong = [_num(r.get("asr")) for r in rows
              if _ATTACKS.get(str(r.get("attack")), {}).get("signal") == "strong"]
    weak = [_num(r.get("asr")) for r in rows
            if _ATTACKS.get(str(r.get("attack")), {}).get("signal") == "weak"]
    out = {"format": FORMAT, "classes": len(rows),
           "mean_asr": sum(asr) / len(asr),
           "mean_rsr": (sum(rsr) / len(rsr)) if rsr else None,
           "worst": worst.get("attack"), "best": best.get("attack"),
           "spread": _num(best.get("asr")) - _num(worst.get("asr"))}
    if strong and weak:
        out["strong_mean"] = sum(strong) / len(strong)
        out["weak_mean"] = sum(weak) / len(weak)
        out["signal_gap"] = out["strong_mean"] - out["weak_mean"]
    out["verdict"] = "measured"
    return out


def coverage(record):
    """Detector coverage split by signal strength (paper Table 4, `:545`).

    `record` = {"rows": [{"defense": name, "strong": 0..1, "weak": 0..1,
                          "tpr": 0..1, "fpr": 0..1}, ...]}
    A detector can look adequate on the pooled number and still leave weak-signal
    attacks uncovered; the gap is the decision-relevant quantity, and a drop of
    more than 20 points is flagged `weak-signal-blind` because no threshold on a
    content detector separates the two populations (paper §6-C).
    """
    rows = [r for r in (record.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "verdict": "no-rows"}
    out = []
    for r in rows:
        strong = _num(r.get("strong"))
        weak = _num(r.get("weak"))
        gap = strong - weak
        row = {"defense": r.get("defense"), "strong": strong, "weak": weak,
               "gap": gap}
        if r.get("tpr") is not None:
            row["tpr"] = _num(r.get("tpr"))
        if r.get("fpr") is not None:
            row["fpr"] = _num(r.get("fpr"))
        row["verdict"] = ("weak-signal-blind" if gap > 0.20
                          else "covers-weak" if weak >= 0.80 else "partial")
        out.append(row)
    worst = max(out, key=lambda r: r["gap"])
    return {"format": FORMAT, "defenses": out, "largest_gap": worst["defense"],
            "gap": worst["gap"],
            "verdict": "measured"}


def cost(record):
    """The capability/security tension in one number.

    `record` = {"conservative": {"asr": .., "rsr": ..},
                "permissive": {"asr": .., "rsr": ..}}
    The paper's interpretation is that the permissive agent pays for its utility
    with exposure (`:509`). The module reports the exposure premium and the
    persistence premium separately, because a write rate and a retrieval rate can
    move in opposite directions.
    """
    cons = record.get("conservative") or {}
    perm = record.get("permissive") or {}
    if not cons or not perm:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    a = _num(perm.get("asr")) - _num(cons.get("asr"))
    r = _num(perm.get("rsr")) - _num(cons.get("rsr"))
    return {"format": FORMAT, "asr_premium": a, "rsr_premium": r,
            "verdict": ("permissive-costs-more" if a > 0 and r > 0
                        else "mixed" if a > 0 or r > 0 else "no-premium")}


def audit_record(record):
    """Self-check a set of write events before any of it is trusted."""
    events = [e for e in (record.get("events") or []) if isinstance(e, dict)]
    findings = []
    if not events:
        findings.append("no events supplied")
    unknown = [e for e in events
               if str(e.get("trigger") or "").lower() not in _CHANNELS]
    if unknown:
        findings.append("%d event(s) with an unknown trigger" % len(unknown))
    direct = [e for e in events
              if str(e.get("trigger") or "").lower() == "instruction"]
    if direct:
        findings.append("%d explicit-instruction write(s) (C1, highest-authority "
                        "path)" % len(direct))
    compaction = [e for e in events
                  if str(e.get("trigger") or "").lower() == "compaction"]
    if compaction:
        findings.append("%d compaction-driven write(s); the trigger is "
                        "attacker-influenceable by payload length" % len(compaction))
    return {"format": FORMAT, "events": len(events), "findings": findings,
            "verdict": "audit-complete"}


def advise(profile):
    """Recommendations from a measured exposure and coverage profile."""
    findings = []
    asr = _num((profile or {}).get("mean_asr"), None) if (profile or {}).get("mean_asr") is not None else None
    if asr is not None and asr >= 0.30:
        findings.append("write exposure is high (%.2f); tighten the retention "
                        "policy before adding retrieval features" % asr)
    if (profile or {}).get("signal_gap") is not None:
        if _num(profile.get("signal_gap")) > 0.20:
            findings.append("the detector is strong-signal only; weak-signal "
                            "attacks need a write-path check, not a content one")
    if (profile or {}).get("asr_premium") is not None:
        if _num(profile.get("asr_premium")) > 0:
            findings.append("the permissive write policy costs %.2f ASR; price "
                            "that against its utility gain" % _num(profile.get("asr_premium")))
    if (profile or {}).get("largest_gap"):
        findings.append("largest coverage gap: %s" % profile.get("largest_gap"))
    if not findings:
        findings.append("no exposure, coverage or cost measurement supplied")
    return {"format": FORMAT, "findings": findings}
