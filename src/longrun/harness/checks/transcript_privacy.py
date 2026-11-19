#!/usr/bin/env python3
"""Transcript privacy — hide the value, keep the structure the agent needs.

Source: arXiv:2607.17147, "SlotGuard" (round 144). Tool outputs, shell logs and
file reads enter provider-bound transcripts, so ordinary debugging can ship a
credential upstream (`slotguard_transcript_privacy_2607.17147.txt:11`, `:31`,
`:68`). Naive redaction removes the structure agents act on: path syntax, file
extensions, URI grammar and credential shape (`:127`, `:133`).

  * **two surfaces**: structural bindings (paths, roots, hosts, emails, entities)
    and secret values, which fail differently and need different treatments
    (`:100`, `:114`, `:121`).
  * **typed, suffix-aware slots**: replace the longest trusted root, suppress the
    sensitive middle, keep a bounded task-relevant suffix and the extension
    (`:166`, `:170`).
  * **format-preserving synthetic secrets**: sample from the secret's format
    class instead of emitting a generic label (`:180`, `:187`).
  * **a session entity graph** links embedded, derived and later references
    (`:196`, `:219`).
  * **guarded rebinding**: a handle is restored only if it exists, has the
    expected type, and is in scope; traversal, spoofing and metacharacters are
    rejected (`:240`, `:243`).
  * **measured**: 20,814 sensitive characters to 0; credential leakage 23.5% for
    placeholders or FPS alone, 0.0% with the graph; task success 89.5–100%
    against 2.5% for generic redaction; 14.424 µs per turn (`:37`, `:225`,
    `:235`, `:315`).

  * `suffix(path, roots)` — the suffix-aware structural slot.
  * `slot(value, kind, index)` — one typed placeholder.
  * `bind(value, kind, session_key)` — a session-stable identifier.
  * `rebind(handle, table, scope)` — guarded local restoration.
  * `graph(pairs)` — the entity graph's link classes.
  * `leak(rows)` — literal, categorical and reconstructive leakage.
  * `compatibility(rows)` — task success and invalid handles.
  * `overhead(rows)` — the hot path.
  * `audit(record)` — the failure modes the boundary must not hide.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: values in; handles and verdicts out.
"""
from __future__ import annotations

import hashlib
import hmac
import re

FORMAT = "longrun-transcript-privacy/1"

KINDS = ("repo_root", "email", "host", "branch", "sensitive_doc", "secret")
LINK_CLASSES = ("exact", "embedded", "derived", "reference")
_META = re.compile(r"[;|&$`<>]")


def _norm_roots(roots):
    return [str(r) for r in (roots or []) if str(r).strip()]


def suffix(path, roots=None):
    """Longest root to a typed slot, middle suppressed, suffix and extension kept."""
    raw = str(path or "")
    if not raw:
        return {"format": FORMAT, "verdict": "empty-path"}
    roots = _norm_roots(roots)
    matched = ""
    for root in sorted(roots, key=len, reverse=True):
        if raw.startswith(root):
            matched = root
            break
    if not matched:
        return {"format": FORMAT, "verdict": "root-unknown", "path": raw}
    rest = raw[len(matched):].lstrip("/")
    parts = [p for p in rest.split("/") if p]
    if not parts:
        return {"format": FORMAT, "verdict": "root-only", "root": matched}
    filename = parts[-1]
    directory = parts[-2] if len(parts) >= 2 else ""
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    sensitive = bool(re.search(r"(secret|key|credential|layoff|salary|passwd)", raw, re.I))
    slot_name = "[SENSITIVE_DOC_1]" if sensitive else "[FILE_1]"
    tail = "/".join(part for part in (directory, slot_name) if part)
    if ext:
        tail += "." + ext
    return {"format": FORMAT, "verdict": "slot", "root": matched,
            "root_slot": "[REPO_ROOT_1]", "suffix": tail,
            "rewritten": "[REPO_ROOT_1]/" + tail,
            "extension": ext, "sensitive": sensitive,
            "path_shaped": True}


def slot(value, kind, index=1):
    """One typed placeholder; an unknown kind is refused rather than guessed."""
    if kind not in KINDS:
        return {"format": FORMAT, "verdict": "unknown-kind", "known": list(KINDS)}
    label = {"repo_root": "REPO_ROOT", "email": "EMAIL", "host": "HOST",
             "branch": "BRANCH", "sensitive_doc": "SENSITIVE_DOC",
             "secret": "FPS"}[kind]
    return {"format": FORMAT, "verdict": "slotted", "kind": kind,
            "handle": "[%s_%d]" % (label, int(index)), "kind_label": label}


def bind(value, kind, session_key):
    """A session-stable identifier; fresh keys prevent cross-session matching."""
    raw = str(value or "")
    if not raw.strip():
        return {"format": FORMAT, "verdict": "empty-value"}
    if not str(session_key or ""):
        return {"format": FORMAT, "verdict": "no-session-key"}
    digest = hmac.new(str(session_key).encode("utf-8"),
                      ("%s|%s" % (kind, raw)).encode("utf-8"),
                      hashlib.sha256).hexdigest()[:8]
    return {"format": FORMAT, "verdict": "bound", "kind": kind,
            "handle": "[%s_%s]" % (kind.upper(), digest)}


def rebind(handle, table, scope=None):
    """Restore a handle only when it is known, typed and in scope."""
    h = str(handle or "")
    entry = (table or {}).get(h)
    if entry is None:
        return {"format": FORMAT, "verdict": "rejected", "reason": "unknown-handle"}
    raw = str((entry or {}).get("value") or "")
    if ".." in raw:
        return {"format": FORMAT, "verdict": "rejected", "reason": "traversal"}
    if any(ch in raw for ch in (";", "|", "&", "$", "`")):
        return {"format": FORMAT, "verdict": "rejected", "reason": "metacharacters"}
    kind = entry.get("kind")
    if kind is not None and kind not in KINDS:
        return {"format": FORMAT, "verdict": "rejected", "reason": "type-mismatch"}
    if scope:
        prefix = str(scope)
        if not raw.startswith(prefix):
            return {"format": FORMAT, "verdict": "rejected", "reason": "out-of-scope"}
    return {"format": FORMAT, "verdict": "rebound", "value": raw,
            "kind": kind}


def graph(pairs):
    """Classify the links a session entity graph would record."""
    rows = []
    for pair in pairs or []:
        raw = str((pair or {}).get("raw") or "")
        variant = str((pair or {}).get("variant") or "")
        if not raw or not variant:
            continue
        if variant == raw:
            cls = "exact"
        elif raw in variant or variant in raw:
            cls = "embedded"
        elif raw.split("/")[-1] in variant or raw.split("@")[0] in variant:
            cls = "derived"
        else:
            cls = "reference"
        rows.append({"raw": raw, "variant": variant, "class": cls})
    covered = {row["class"] for row in rows}
    return {"format": FORMAT, "rows": rows, "classes": sorted(covered),
            "verdict": "graph-covers" if "embedded" in covered or "derived" in covered
            else "graph-exact-only"}


def leak(rows):
    """Literal characters, categorical labels and reconstructible exposures."""
    literal = categorical = reconstructive = 0
    for row in rows or []:
        r = row or {}
        literal += int(r.get("literal_chars") or 0)
        if r.get("category_label") is True:
            categorical += 1
        if r.get("reconstructive") is True:
            reconstructive += 1
    if literal == 0 and reconstructive == 0 and categorical == 0:
        verdict = "leak-free"
    elif literal == 0 and reconstructive == 0:
        verdict = "categorical-only"
    else:
        verdict = "residual-leakage"
    return {"format": FORMAT, "literal_chars": literal,
            "categorical_labels": categorical,
            "reconstructive": reconstructive, "verdict": verdict}


def compatibility(rows):
    """Task success and handle validity against the raw transcript."""
    clean = []
    for row in rows or []:
        method = str((row or {}).get("method") or "")
        success = _float((row or {}).get("success"))
        raw = _float((row or {}).get("raw"))
        invalid = _float((row or {}).get("invalid_handles")) or 0.0
        if not method or success is None:
            continue
        clean.append({"method": method, "success": success, "raw": raw,
                      "invalid_handles": invalid,
                      "gap": (raw - success) if raw is not None else None})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    protected = [r for r in clean if r["method"].lower() != "raw"]
    best = max(protected or clean, key=lambda r: r["success"])
    return {"format": FORMAT, "rows": clean, "best": best,
            "verdict": "structure-preserved" if best["success"] >= 0.85
            and best["invalid_handles"] <= 0.05 else "structure-lost"}


def overhead(rows):
    """The deterministic rewrite must stay off the hot path's critical budget."""
    values = []
    for row in rows or []:
        us = _float((row or {}).get("micros"))
        if us is not None:
            values.append(us)
    if not values:
        return {"format": FORMAT, "verdict": "no-samples"}
    values.sort()
    median = values[len(values) // 2]
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return {"format": FORMAT, "median_us": median, "p95_us": p95,
            "verdict": "hot-path-ok" if median < 1000 else "hot-path-slow"}


def audit(record):
    """What a transcript boundary must not hide from its own operator."""
    r = record or {}
    findings = []
    if r.get("generic_replacement") is True:
        findings.append({"kind": "generic-replacement",
                         "why": "it erases type and location cues the agent needs"})
    if r.get("suffix_preserved") is False:
        findings.append({"kind": "suffix-lost",
                         "why": "the extension and safe suffix are the execution cue"})
    if r.get("seg_for_split") is not True:
        findings.append({"kind": "split-exposure-unguarded",
                         "why": "split and embedded values need the entity graph"})
    if r.get("semantic_detector_sync") is True:
        findings.append({"kind": "semantic-detector-on-hot-path",
                         "why": "742 ms warm, so it must stay optional and advisory"})
    if r.get("fail_closed_claimed") is True:
        findings.append({"kind": "fail-closed-overclaimed",
                         "why": "the finite checks do not establish it"})
    if not findings:
        findings.append({"kind": "boundary-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("interposes_on_tool_output", "user-prompts-only",
         "credentials enter through shell and file observations"),
        ("keeps_typed_structure", "generic-placeholders",
         "PATH and API_KEY destroy the execution cue"),
        ("preserves_suffix", "full-path-redaction",
         "the extension and safe suffix carry the task signal"),
        ("uses_format_preserving_secrets", "category-labels",
         "a label discloses the credential type even with the value hidden"),
        ("tracks_cross_turn_references", "single-span-redaction",
         "split and derived exposures remain reconstructible"),
        ("rebinds_locally_with_scope", "restore_anywhere",
         "a handle must resolve only in the trusted runtime"),
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
