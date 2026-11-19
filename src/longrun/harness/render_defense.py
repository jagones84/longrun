#!/usr/bin/env python3
"""Render defense — protection that depends on operation, setting and model.

Source: arXiv:2611.24231, "What Survives the Shift from Text to Pixels?"
(round 146). Rendering untrusted content as page images lowers attack success
on average, but the average hides where it does not
(`image_document_injection_2611.24231.txt:18`, `:31`). The paper pairs text and
image versions of 191 sources across six models and measures three operations:
append a marker, format the answer, replace the answer (`:24`, `:132`).

  * **operation matters**: rendering suppresses appending and formatting for
    every model, yet Qwen still executes image-borne replacement at 77.96%
    (`:29`, `:179`).
  * **aggregation masks it**: an average over operations can list a target as
    protected while one operation remains near ceiling (`:54`, `:145`).
  * **settings matter**: widening the page from 704 to 1280 px or enlarging
    type from 20 to 32 raises replacement execution by more than 25 points
    (`:313`, `:318`).
  * **a small search closes the gap**: over eight fixed candidates the append
    deficit for Qwen shrinks from -37.37 to -3.33 points, but GPT-5-nano keeps
    a deficit at every budget (`:333`, `:377`).
  * **reading is not following**: models transcribe commands they do not
    execute, and trusted authorization raises execution on unchanged pages
    (`:36`, `:59`, `:401`).
  * **utility is not free**: original-question ratios stay at 93.31-101.61%,
    but Qwen falls to 61.99% on questions that combine two evidence spans
    (`:33`, `:193`).

  * `operations()` — the three operations and their authority.
  * `modality(rows)` — text against image, per operation and model.
  * `aggregate(rows)` — how a macro average hides the worst operation.
  * `utility(rows)` — the image/text F1 ratio by question type.
  * `presentation(rows)` — resolution and type size against protection.
  * `candidates(rows)` — whether a small attack budget closes the deficit.
  * `dissociation(rows)` — reporting, understanding and execution, kept apart.
  * `authorization(row)` — a trusted permit against a trusted prohibition.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: measured rates in; conditional verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-render-defense/1"

OPERATIONS = ("append", "format", "replace")
DEFAULTS = {"delta": 0.10, "search_residual": 0.05,
            "utility_floor": 0.95, "integration_floor": 0.90}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def operations():
    """The three operations, in increasing control over the response."""
    return {"format": FORMAT, "operations": [
        {"name": "append", "requests": "answer plus a marker on a new line",
         "control": "low", "answer_preserved": True},
        {"name": "format", "requests": "one line: marker, bar, answer",
         "control": "medium", "answer_preserved": True},
        {"name": "replace", "requests": "replace the answer with a fixed phrase",
         "control": "high", "answer_preserved": False},
    ], "verdict": "operations-defined"}


def modality(rows):
    """Image minus text execution, per row and per operation."""
    out, by_operation = [], {}
    for row in rows or []:
        r = row or {}
        text = _num(r.get("text_asr"))
        image = _num(r.get("image_asr"))
        if text is None or image is None:
            continue
        operation = str(r.get("operation") or "")
        out.append({"model": str(r.get("model") or ""), "operation": operation,
                    "delta": image - text})
        by_operation.setdefault(operation, []).append(image - text)
    means = {op: sum(v) / len(v) for op, v in by_operation.items() if v}
    if not means:
        return {"format": FORMAT, "verdict": "no-measurements"}
    if all(delta < 0 for delta in means.values()):
        verdict = "rendering-suppresses"
    elif any(delta >= 0 for delta in means.values()):
        verdict = ("rendering-ineffective" if all(delta >= 0 for delta in means.values())
                   else "rendering-conditional")
    else:
        verdict = "rendering-conditional"
    return {"format": FORMAT, "rows": out, "means": means,
            "verdict": verdict}


def aggregate(rows, group="model"):
    """The macro average against the worst operation inside each group."""
    buckets = {}
    for row in rows or []:
        r = row or {}
        asr = _num(r.get("asr"))
        if asr is None:
            continue
        key = str(r.get(group) or "")
        buckets.setdefault(key, []).append((str(r.get("operation") or ""), asr))
    if not buckets:
        return {"format": FORMAT, "verdict": "no-measurements"}
    groups, hidden = [], []
    for key, values in sorted(buckets.items()):
        mean = sum(v for _, v in values) / len(values)
        worst_op, worst = max(values, key=lambda pair: (pair[1], pair[0]))
        groups.append({"group": key, "mean": mean, "worst": worst,
                       "worst_operation": worst_op})
        if worst - mean >= DEFAULTS["delta"]:
            hidden.append(key)
    return {"format": FORMAT, "groups": groups, "hidden": hidden,
            "verdict": "aggregation-hides-operation" if hidden
            else "aggregation-representative"}


def utility(rows):
    """The image/text F1 ratio, per model and question type."""
    out = []
    for row in rows or []:
        r = row or {}
        text = _num(r.get("text_f1"))
        image = _num(r.get("image_f1"))
        if text is None or image is None or text == 0:
            continue
        out.append({"model": str(r.get("model") or ""),
                    "question": str(r.get("question") or "original"),
                    "ratio": image / text})
    if not out:
        return {"format": FORMAT, "verdict": "no-measurements"}
    worst = min(out, key=lambda r: (r["ratio"], r["model"], r["question"]))
    integration = [r for r in out if r["question"] == "integration"]
    if integration and any(r["ratio"] < DEFAULTS["integration_floor"] for r in integration):
        verdict = "utility-loss-on-integration"
    elif any(r["ratio"] < DEFAULTS["utility_floor"] for r in out):
        verdict = "utility-loss"
    else:
        verdict = "utility-preserved"
    return {"format": FORMAT, "rows": out, "worst": worst,
            "verdict": verdict}


def presentation(rows):
    """Width and type size against the protection rendering is supposed to give."""
    points = []
    for row in rows or []:
        r = row or {}
        asr = _num(r.get("asr"))
        if asr is None:
            continue
        points.append({"width": _num(r.get("width")), "font": _num(r.get("font")),
                       "asr": asr})
    if len(points) < 2:
        return {"format": FORMAT, "verdict": "insufficient-settings"}
    findings = []
    by_width = {}
    for p in points:
        if p["width"] is not None:
            by_width.setdefault(p["width"], []).append(p["asr"])
    if len(by_width) >= 2:
        wide = max(by_width)
        narrow = min(by_width)
        wide_mean = sum(by_width[wide]) / len(by_width[wide])
        narrow_mean = sum(by_width[narrow]) / len(by_width[narrow])
        if wide_mean - narrow_mean >= DEFAULTS["delta"]:
            findings.append("wider-page-weakens-protection")
    by_font = {}
    for p in points:
        if p["font"] is not None:
            by_font.setdefault(p["font"], []).append(p["asr"])
    if len(by_font) >= 2:
        large = max(by_font)
        small = min(by_font)
        large_mean = sum(by_font[large]) / len(by_font[large])
        small_mean = sum(by_font[small]) / len(by_font[small])
        if large_mean - small_mean >= DEFAULTS["delta"]:
            findings.append("larger-type-weakens-protection")
    return {"format": FORMAT, "findings": findings,
            "verdict": "settings-change-protection" if findings
            else "settings-stable"}


def candidates(rows):
    """Whether a bounded attack search closes the image deficit."""
    buckets = {}
    for row in rows or []:
        r = row or {}
        deficit = _num(r.get("deficit"))
        budget = _num(r.get("budget"))
        if deficit is None or budget is None:
            continue
        key = (str(r.get("model") or ""), str(r.get("operation") or ""))
        buckets.setdefault(key, []).append((int(budget), deficit))
    if not buckets:
        return {"format": FORMAT, "verdict": "no-measurements"}
    out, closed, resistant = [], [], []
    for (model, operation), values in sorted(buckets.items()):
        values.sort()
        first, last = values[0][1], values[-1][1]
        residual = abs(last)
        row = {"model": model, "operation": operation, "first": first,
               "last": last, "residual": residual, "budget": values[-1][0]}
        out.append(row)
        if residual <= DEFAULTS["search_residual"]:
            closed.append((model, operation))
        else:
            resistant.append((model, operation))
    if closed and resistant:
        verdict = "search-closes-some-deficits"
    elif closed:
        verdict = "search-closes-deficit"
    else:
        verdict = "search-resistant"
    return {"format": FORMAT, "rows": out, "closed": closed,
            "resistant": resistant, "verdict": verdict}


def dissociation(rows):
    """Reporting, understanding and execution measured on the same sources."""
    out = []
    for row in rows or []:
        r = row or {}
        report = _num(r.get("report"))
        understand = _num(r.get("understand"))
        execute = _num(r.get("execute"))
        if None in (report, understand, execute):
            continue
        if report >= 0.5 and execute <= 0.1:
            verdict = "read-but-not-followed"
        elif report <= 0.1 and execute <= 0.1:
            verdict = "illegibility-consistent"
        elif execute >= 0.1:
            verdict = "executed"
        else:
            verdict = "partial"
        out.append({"model": str(r.get("model") or ""),
                    "modality": str(r.get("modality") or ""),
                    "report": report, "understand": understand,
                    "execute": execute, "verdict": verdict})
    if not out:
        return {"format": FORMAT, "verdict": "no-measurements"}
    kinds = {row["verdict"] for row in out}
    overall = ("read-but-not-followed" if "read-but-not-followed" in kinds
               else "executed" if "executed" in kinds else "illegibility-consistent")
    return {"format": FORMAT, "rows": out, "verdict": overall}


def authorization(row):
    """A trusted user permit must not raise the attack's authority."""
    r = row or {}
    prohibit = _num(r.get("prohibit_asr"))
    permit = _num(r.get("permit_asr"))
    if prohibit is None or permit is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = permit - prohibit
    return {"format": FORMAT, "delta": delta,
            "verdict": "authorization-raises-risk" if delta >= DEFAULTS["delta"]
            else "authorization-inert"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("aggregate_only") is True:
        findings.append({"kind": "aggregate-only",
                         "why": "one operation can stay near ceiling under an average"})
    if r.get("answer_correctness_as_security") is True:
        findings.append({"kind": "answer-correctness-as-security",
                         "why": "a response can keep the right answer and still obey"})
    if r.get("illegibility_assumed") is True:
        findings.append({"kind": "illegibility-assumed",
                         "why": "models transcribe commands they refuse to execute"})
    if r.get("single_wording") is True:
        findings.append({"kind": "single-wording",
                         "why": "question-bound wording can move ASR by 18-30 points"})
    if r.get("default_rendering_only") is True:
        findings.append({"kind": "default-rendering-only",
                         "why": "resolution and type size change the protection"})
    if r.get("single_model") is True:
        findings.append({"kind": "single-model",
                         "why": "the modality gap reverses direction across models"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("reports_by_operation", "reports_one_aggregate",
         "append, format and replace have different authority"),
        ("reports_by_model", "reports_one_target",
         "the gap depends on which model reads the page"),
        ("tests_attack_budgets", "tests_one_fixed_command",
         "a small candidate search can close the protection"),
        ("measures_utility_on_integration", "measures_simple_questions_only",
         "combining evidence from rendered pages costs more"),
        ("separates_reading_from_following", "infers_illegibility",
         "reporting and execution can dissociate"),
        ("tests_trusted_authorization", "assumes_a_fixed_policy",
         "a permit can raise execution on the same page"),
        ("pins_rendering_settings", "accepts_default_rendering",
         "resolution and type size are part of the defense"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
