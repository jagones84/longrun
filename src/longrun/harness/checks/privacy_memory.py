#!/usr/bin/env python3
"""Privacy memory — a typed placeholder, not an asterisk.

Source: arXiv:2605.09530, "MemPrivacy" (round 144). Cloud-side memory turns one
exposure into a persistent one, and aggressive masking removes the semantics
memory needs (`memprivacy_edge_cloud_2605.09530.txt:16`, `:18`, `:97`). MemPrivacy
detects privacy spans on the edge, replaces them with typed placeholders, and
restores the raw values locally (`:122`, `:128`).

  * **a constrained objective**: minimise leakage subject to a utility-loss
    tolerance (`:253`, `:259`).
  * **four levels with default handling policies**: PL1 preferences, PL2
    identifiable, PL3 high-harm, PL4 immediately exploitable credentials; PL2 is
    disallowed in long-term memory by default, PL3 only under necessity, PL4
    prohibited (`:346`, `:382`, `:1895`).
  * **a configurable threshold λ**: protect every span with level ≥ λ, so a user
    can mask only PL4 (`:321`, `:1848`).
  * **consistent placeholders across sessions** from a local mapping database,
    restored on the way back (`:325`, `:337`).
  * **measured**: extraction F1 85.97% on the dense benchmark and 94.48% out of
    distribution; utility loss 0.71–1.60% at PL2–PL4 and ≤0.89% at PL4 alone;
    irreversible masking costs 16.99–41.87 points (`:634`, `:771`, `:737`).

  * `levels()` / `classify(level)` — the taxonomy and its policies.
  * `sanitize(spans, threshold)` — typed replacement under a policy.
  * `restore(text, mapping)` — the local way back.
  * `extraction(rows)` — precision / recall / F1 across text, level and type.
  * `utility(rows)` — the drop against no protection, and its tolerance.
  * `leakage(rows)` — remaining exposure, by session and value.
  * `threshold(rows)` — the loosest policy that stays within the tolerance.
  * `audit(record)` — what makes a placeholder scheme unsafe.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: spans and rows in; typed replacements and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-privacy-memory/1"

LEVELS = {
    "PL1": {"label": "low-sensitivity", "long_term_memory": "permitted",
            "storage": "summaries", "model": "may personalize"},
    "PL2": {"label": "identifiable", "long_term_memory": "disallowed-by-default",
            "storage": "controlled", "model": "avoid verbatim exposure"},
    "PL3": {"label": "highly-sensitive", "long_term_memory": "not-permitted",
            "storage": "strict-minimization", "model": "do not collect"},
    "PL4": {"label": "confidential", "long_term_memory": "prohibited",
            "storage": "zero-retention", "model": "refuse and advise rotation"},
}
ORDER = ("PL1", "PL2", "PL3", "PL4")


def _rank(level):
    return ORDER.index(level) if level in ORDER else None


def levels():
    """The table, copied so a caller cannot mutate the module constant."""
    return {name: dict(row) for name, row in LEVELS.items()}


def classify(level):
    row = LEVELS.get(str(level))
    if row is None:
        return {"format": FORMAT, "verdict": "unknown-level", "known": list(ORDER)}
    return {"format": FORMAT, "level": str(level), **row}


def sanitize(spans, threshold="PL2"):
    """Replace every span at or above the threshold with a typed placeholder."""
    lam = _rank(str(threshold))
    if lam is None:
        return {"format": FORMAT, "verdict": "unknown-threshold"}
    counters = {}
    mapping = {}
    kept = []
    replaced = []
    for span in spans or []:
        s = span or {}
        text = str(s.get("text") or "")
        level = str(s.get("level") or "")
        kind = str(s.get("type") or "Info")
        rank = _rank(level)
        if not text or rank is None:
            continue
        if rank < lam:
            kept.append({"text": text, "level": level, "type": kind})
            continue
        counters[kind] = counters.get(kind, 0) + 1
        handle = "<%s_%d>" % (kind, counters[kind])
        mapping[handle] = {"value": text, "level": level, "type": kind}
        replaced.append({"handle": handle, "level": level, "type": kind})
    verdict = ("nothing-protected" if not replaced
               else "typed-masked")
    return {"format": FORMAT, "threshold": threshold, "mapping": mapping,
            "replaced": replaced, "kept": kept, "verdict": verdict}


def restore(text, mapping):
    """Put the raw values back locally; an unknown handle is reported, not guessed."""
    out = str(text or "")
    restored = 0
    unresolved = []
    for handle, entry in (mapping or {}).items():
        if handle in out:
            out = out.replace(handle, str((entry or {}).get("value") or ""))
            restored += 1
    for token in _handles(out):
        unresolved.append(token)
    return {"format": FORMAT, "text": out, "restored": restored,
            "unresolved": unresolved,
            "verdict": "restored" if not unresolved else "unresolved-handles"}


def _handles(text):
    out = []
    buf = ""
    depth = 0
    for ch in str(text or ""):
        if ch == "<":
            buf, depth = "<", 1
        elif ch == ">" and depth:
            buf += ">"
            out.append(buf)
            buf, depth = "", 0
        elif depth:
            buf += ch
    return out


def extraction(rows):
    """Three fields per span; a jointly wrong span is not a partial success."""
    text_ok = level_ok = type_ok = 0
    for row in rows or []:
        r = row or {}
        if r.get("text_ok") is True:
            text_ok += 1
        if r.get("level_ok") is True:
            level_ok += 1
        if r.get("type_ok") is True:
            type_ok += 1
    scores = [text_ok, level_ok, type_ok]
    f1 = sum(scores) / (3.0 * len(rows)) if rows else 0.0
    return {"format": FORMAT, "n": len(rows), "text": text_ok,
            "level": level_ok, "type": type_ok, "f1": f1,
            "verdict": "extraction-strong" if f1 >= 0.8 else "extraction-weak"}


def utility(rows):
    """Utility loss against no protection, and whether it fits the tolerance."""
    clean = []
    for row in rows or []:
        method = str((row or {}).get("method") or "")
        protected = _float((row or {}).get("protected"))
        none = _float((row or {}).get("none"))
        if not method or protected is None or none is None:
            continue
        clean.append({"method": method, "protected": protected, "none": none,
                      "drop": none - protected})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    best = min(clean, key=lambda r: r["drop"])
    worst = max(clean, key=lambda r: r["drop"])
    return {"format": FORMAT, "rows": clean, "best": best, "worst": worst,
            "verdict": "within-tolerance" if best["drop"] <= 0.016
            else "utility-loss-high",
            "masking_collapse": worst["drop"] >= 0.20}


def leakage(rows):
    """Exposed values and sessions, with the residual named."""
    values = sessions = protected = 0
    for row in rows or []:
        r = row or {}
        exposed = int(r.get("exposed_values") or 0)
        values += exposed
        if exposed:
            sessions += 1
        protected += int(r.get("protected_values") or 0)
    return {"format": FORMAT, "exposed_values": values,
            "exposed_sessions": sessions, "protected_values": protected,
            "verdict": "zero-exposure" if values == 0 else "exposure-residual"}


def threshold(rows, tolerance=0.016):
    """The strongest protection whose utility loss stays inside the tolerance."""
    clean = []
    for row in rows or []:
        level = str((row or {}).get("threshold") or "")
        loss = _float((row or {}).get("loss"))
        if level not in ORDER or loss is None:
            continue
        clean.append({"threshold": level, "loss": loss,
                      "protected_share": _float((row or {}).get("protected_share"))})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    clean.sort(key=lambda r: _rank(r["threshold"]))
    viable = [r for r in clean if r["loss"] <= tolerance]
    if not viable:
        return {"format": FORMAT, "rows": clean, "verdict": "no-viable-threshold"}
    best = viable[0]
    return {"format": FORMAT, "rows": clean, "chosen": best["threshold"],
            "loss": best["loss"], "verdict": "threshold-chosen"}


def audit(record):
    """What makes a placeholder scheme unsafe to deploy."""
    r = record or {}
    findings = []
    if r.get("local_mapping_db") is not True:
        findings.append({"kind": "no-local-mapping",
                         "why": "restoration needs a local mapping, never the cloud"})
    if r.get("untyped_placeholder") is True:
        findings.append({"kind": "untyped-placeholder",
                         "why": "semantic type is what keeps memory useful"})
    if r.get("irreversible") is True:
        findings.append({"kind": "irreversible-masking",
                         "why": "it removes the semantics memory retrieves on"})
    if r.get("pl4_retained") is True:
        findings.append({"kind": "pl4-retained",
                         "why": "credentials must never enter model context or logs"})
    if r.get("general_extractor_for_privacy") is True:
        findings.append({"kind": "general-extractor",
                         "why": "utility collapses when the extractor is not privacy-tuned"})
    if not findings:
        findings.append({"kind": "memory-privacy-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("extracts_before_cloud", "sanitizes-at-the-provider",
         "the boundary must run on the trusted side"),
        ("keeps_type_information", "generic-placeholders",
         "untyped placeholders lose memory utility"),
        ("restores_locally", "no-restoration",
         "the user sees raw values only locally"),
        ("persists_the_mapping", "per-turn-mapping",
         "cross-session consistency needs a local database"),
        ("offers_a_threshold", "one-size-fits-all",
         "users differ in what they consider private"),
        ("never_stores_credentials", "pl4-in-memory",
         "PL4 is immediately exploitable and must be refused"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
