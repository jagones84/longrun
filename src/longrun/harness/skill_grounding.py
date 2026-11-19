#!/usr/bin/env python3
"""Skill grounding — knowledge widens the search, an outside verifier keeps it honest.

Source: arXiv:2611.23203, "Identifying and Repairing Energy Smells with Agent
Skills" (round 138). The skill packages a taxonomy, a static analyzer and an
independent verifier; 68.6% of 258 measured repairs saved energy with a median
saving of 24.9% (`energy_smells_agent_skills_2611.23203.md:28`, `:92`).

  * **progressive disclosure**: a taxonomy index, twelve category cards and 65
    root-cause cards, loaded only when a step needs them (`:60`).
  * **the agent never measures its own work**: a separate input generator and a
    verifier hold the evidence, and every repair is re-measured afterwards
    (`:56`, `:70`).
  * **equivalence before savings**: return value, argument state, printed output
    and files must match (`:70`).
  * **verdicts are typed**: confirmed, partial, mixed, regressed, negligible, and
    inconclusive when the noise floor exceeds 3% (`:70`).
  * **the taxonomy widens the search**, the analyzer adds findings, and wider
    search finds smaller savings (`:94`, `:96`).
  * **rules report patterns without judging**; the agent reviews each (`:62`).

  * `skill(spec)` — the knowledge layers, the tools and the independence rules.
  * `verdict(record)` — a typed outcome from the per-input measurements.
  * `equivalence(record)` — the four observable checks.
  * `session(rows)` — measured repairs, saving share and median.
  * `layers(rows)` — what the taxonomy and the analyzer each buy.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: session records in; findings out.
"""
from __future__ import annotations

import statistics

FORMAT = "longrun-skill-grounding/1"

LAYERS = ("index", "category-cards", "root-cause-cards")

VERDICTS = ("confirmed", "partial", "mixed", "regressed", "negligible", "inconclusive")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def skill(spec):
    """A skill is knowledge plus procedure plus tools, with evidence outside."""
    s = spec or {}
    findings = []
    present = {str(l) for l in (s.get("layers") or ())}
    missing = [l for l in LAYERS if l not in present]
    if missing:
        findings.append({"kind": "no-progressive-disclosure", "missing": missing,
                         "why": "load the detailed cards only when a step needs them"})
    if s.get("verifier_independent") is not True:
        findings.append({"kind": "agent-measures-own-work",
                         "why": "the agent must not choose the inputs that judge its repair"})
    if s.get("generator_independent") is not True:
        findings.append({"kind": "generator-inside-agent"})
    if s.get("edits_repository") is True:
        findings.append({"kind": "skill-edits-repository",
                         "why": "the skill proposes repairs; the developer applies them"})
    if s.get("reverifies_after") is not True:
        findings.append({"kind": "no-verification"})
    if not findings:
        findings.append({"kind": "grounded-skill"})
    return {"format": FORMAT, "findings": findings}


def equivalence(record):
    """Behaviour must match on every observable before energy is compared."""
    r = record or {}
    checks = {"return": r.get("same_return", True), "arguments": r.get("same_args", True),
              "printed": r.get("same_printed", True), "files": r.get("same_files", True)}
    failing = [k for k, ok in checks.items() if ok is not True]
    findings = []
    if failing:
        findings.append({"kind": "not-equivalent", "differing": failing})
    elif r.get("ran") is False:
        findings.append({"kind": "repair-does-not-run"})
    else:
        findings.append({"kind": "equivalent"})
    return {"format": FORMAT, "differing": failing, "findings": findings}


def verdict(record):
    """The typed repair verdict from per-input savings and the noise floor."""
    r = record or {}
    savings = [_num(x) for x in (r.get("savings") or ()) if _num(x) is not None]
    floor = _num(r.get("noise_floor", 0.0))
    if not savings:
        return {"format": FORMAT, "findings": [{"kind": "no-measurements"}]}
    saved = sum(1 for x in savings if x > floor)
    cost = sum(1 for x in savings if x < -floor)
    changed = saved + cost
    if floor is not None and floor > 0.03:
        if saved == len(savings) or cost >= 1:
            label = "confirmed" if cost == 0 else "mixed"
        else:
            label = "inconclusive"
    elif changed == 0:
        label = "negligible"
    elif cost == 0 and saved == len(savings):
        label = "confirmed"
    elif cost == 0:
        label = "partial"
    elif saved == 0:
        label = "regressed"
    else:
        label = "mixed"
    findings = [{"kind": label}]
    if label in ("mixed", "regressed"):
        findings.append({"kind": "repair-costs-energy",
                         "why": "a repair that costs on some input is not a saving"})
    return {"format": FORMAT, "verdict": label, "saves": saved, "costs": cost,
            "measured": len(savings), "findings": findings}


def session(rows):
    """Share of measured repairs that save, and the median saving."""
    data = [r for r in (rows or ()) if r.get("verdict") in VERDICTS]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-repairs"}]}
    saving = [r for r in data if r["verdict"] in ("confirmed", "partial")]
    share = len(saving) / len(data)
    medians = [_num(r.get("median_saving")) for r in saving if _num(r.get("median_saving")) is not None]
    median = statistics.median(medians) if medians else None
    findings = []
    if not saving:
        findings.append({"kind": "no-savings"})
    elif share >= 0.5:
        findings.append({"kind": "repairs-save", "share": round(share, 4),
                         "median": None if median is None else round(median, 4)})
    if any(r["verdict"] == "inconclusive" for r in data):
        findings.append({"kind": "inconclusive-present",
                         "count": sum(1 for r in data if r["verdict"] == "inconclusive")})
    if not findings:
        findings.append({"kind": "savings-below-half"})
    return {"format": FORMAT, "measured": len(data), "saving_share": round(share, 4),
            "median": None if median is None else round(median, 4), "findings": findings}


def layers(rows):
    """What the taxonomy and the analyzer add, and what that costs in size."""
    data = [r for r in (rows or ()) if _num(r.get("smelly")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-sessions"}]}
    by_skill = {}
    for r in data:
        by_skill.setdefault(str(r.get("skill")), []).append(r)
    findings = []
    core = by_skill.get("core") or []
    tax = by_skill.get("core+tax") or []
    full = by_skill.get("full") or []

    def mean(rows, key):
        vals = [_num(r.get(key)) for r in rows if _num(r.get(key)) is not None]
        return sum(vals) / len(vals) if vals else None

    if core and tax and (mean(tax, "smelly") or 0) > (mean(core, "smelly") or 0):
        findings.append({"kind": "taxonomy-widens-search",
                         "core": round(mean(core, "smelly"), 2),
                         "tax": round(mean(tax, "smelly"), 2)})
    if core and full and (mean(full, "smelly") or 0) > (mean(tax, "smelly") if tax else 0):
        findings.append({"kind": "analyzer-adds-findings"})
    if core and tax:
        cs = mean(core, "median_saving")
        ts = mean(tax, "median_saving")
        if cs is not None and ts is not None and ts < cs:
            findings.append({"kind": "wider-search-smaller-savings",
                             "core": round(cs, 2), "tax": round(ts, 2)})
    if not findings:
        findings.append({"kind": "layers-neutral"})
    return {"format": FORMAT, "skills": sorted(by_skill), "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("grounds_in_taxonomy", "model-knowledge-only", "name the defect before repairing it"),
        ("loads_knowledge_lazily", "context-flooded", "index first, cards on demand"),
        ("separates_verifier", "self-graded", "evidence must sit outside the agent"),
        ("checks_equivalence", "savings-only", "a repair that changes behaviour is not a repair"),
        ("measures_against_noise", "no-noise-floor", "difference must exceed a measured floor"),
        ("remeasures_after", "trusts-own-numbers", "the session reports are rechecked"),
        ("compares_layers", "unablated-skill", "taxonomy and analyzer must earn their place"),
        ("reports_inconclusive", "forced-verdict", "an inconclusive measurement is a result"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
