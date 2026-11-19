#!/usr/bin/env python3
"""Rubric verification — the verifier is the object, and its errors have a direction.

Source: arXiv:2611.22841, "Verifying Agents in Rubric-Graded Environments"
(round 133). In a rubric-graded environment a verifier assigns a binary
met/unmet judgment to each natural-language criterion against the agent's
deliverables and environment state; both benchmarking and RL depend on that
grade being trustworthy (`rubric_graded_agent_verification_2611.22841.md:50`).

  * **three design principles**: P1 reactive verification (the verifier decides
    which artifacts to open and which tools to call per criterion), P2
    environment alignment (same environment, native formats, read-only), and P3
    domain guidance (a corpus-level channel separate from the criterion) (`:70`,
    `:90`, `:94`).
  * **a text snapshot erases the signal**: serialized evidence loses formula
    structure and layout metadata, and stateful tools leave no trace in text
    (`:190`).
  * **F1 must be on the unmet class**: 66.3% of criteria are met, so an
    always-"met" verifier reaches 66.3% accuracy without finding anything (`:100`).
  * **the dangerous error is over-acceptance**: a false negative credits a
    deficient output and, used as a reward, reinforces it (`:401`).
  * **measured**: Gandalf 0.864 F1 at $9.81 vs Archipelago 0.852 at $46.73 with
    Gemini 3 Flash; 0.883 vs 0.742 with GPT-5.4-Mini; 0.955 vs 0.934 on a
    structurally different environment (`:116`, `:118`, `:154`).
  * **batch size trades accuracy for cost**: 0.858 at b=64, 0.880 at b=16, 0.870
    at b=4, with cost rising from $9.87 to $71.85 (`:142`).
  * **guidance does not raise F1 but makes the verifier stricter**: +2.2pp UNMET,
    precision −0.030, recall +0.024, and no resolved F1 effect (`:138`).

  * `capability(name)` — a verifier-side, architecture-agnostic capability.
  * `verifier(config)` — the three principles and the read-only separation.
  * `errors(rows)` — confusion counts, UNMET F1, over-acceptance vs over-rejection.
  * `batch(rows)` — F1 and cost against criteria per session.
  * `ablation(rows)` — a resolved effect, or a strictness shift with no F1 change.
  * `agreement(rows)` — inter-annotator agreement and the prevalence trap.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: verifier configs and judgment records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-rubric-verification/1"

CAPABILITIES = (
    "metric-recomputation", "visual-presentation", "literal-data-point",
    "structural-inventory", "cross-component-linkage", "labeling-metadata",
    "governance-narrative", "temporal-sequential", "accounting-logic",
)
FORMAT_TOKENS = ("xlsx", "pptx", "pdf", "json", "csv", "excel", "openpyxl",
                 "pandas", "python", "mcp", "sql", "api")
PRINCIPLES = ("reactive", "environment-aligned", "domain-guidance")


def _text(value):
    return str(value).strip() if value is not None else ""


def capability(name, description=""):
    """A capability names what the VERIFIER inspects, never a tool or a format."""
    n = _text(name).lower().replace(" ", "-")
    findings = []
    if n not in CAPABILITIES:
        findings.append({"kind": "unknown-capability", "capability": n})
    if any(tok in n for tok in FORMAT_TOKENS):
        findings.append({"kind": "format-specific-capability", "capability": n,
                         "why": "a capability must be expressible for any verifier architecture"})
    words = len(_text(description).split())
    if description and words < 3:
        findings.append({"kind": "capability-unexplained", "words": words})
    return {"format": FORMAT, "capability": n, "findings": findings}


def verifier(config):
    """The three principles, the read-only separation, and the error direction."""
    c = config or {}
    findings = []
    principles = {str(p) for p in (c.get("principles") or ())}
    if "reactive" not in principles:
        findings.append({"kind": "workflow-verifier",
                         "why": "a fixed verification path cannot cover a rubric of hundreds of criteria"})
    if "environment-aligned" not in principles:
        findings.append({"kind": "serialized-evidence",
                         "why": "flattening the deliverable to text erases formula structure and layout"})
    elif c.get("environment_read_only") is False:
        findings.append({"kind": "verifier-can-modify",
                         "why": "an unrestricted verifier can change what it grades"})
    if "domain-guidance" not in principles:
        findings.append({"kind": "no-guidance",
                         "why": "domain conventions are not in the criterion text"})
    if c.get("guidance_inside_criterion") is True:
        findings.append({"kind": "guidance-in-criterion",
                         "why": "guidance is corpus-level and belongs in its own channel"})
    if c.get("sees_trajectory") is False and c.get("sees_workspace") is False:
        findings.append({"kind": "no-evidence-access",
                         "why": "a verifier that sees neither the trajectory nor the workspace judges blind"})
    return {"format": FORMAT, "principles": sorted(principles), "findings": findings}


def errors(rows):
    """F1 on the unmet class, and the two error directions kept apart."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-measurement"}]}
    tp = sum(1 for r in data if r.get("gold") == "unmet" and r.get("predicted") == "unmet")
    fp = sum(1 for r in data if r.get("gold") == "met" and r.get("predicted") == "unmet")
    fn = sum(1 for r in data if r.get("gold") == "unmet" and r.get("predicted") == "met")
    tn = sum(1 for r in data if r.get("gold") == "met" and r.get("predicted") == "met")
    total = tp + fp + fn + tn
    precision = tp / float(tp + fp) if tp + fp else 0.0
    recall = tp / float(tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    met_share = (tn + fp) / float(total) if total else 0.0
    findings.append({"kind": "unmet-f1", "f1": round(f1, 4),
                     "over_acceptance": fn, "over_rejection": fp})
    if met_share > 0.60:
        findings.append({"kind": "prevalence-distorts-accuracy", "met_share": round(met_share, 4),
                         "why": "an always-met verifier scores the prevalence without finding anything"})
    if fn > fp:
        findings.append({"kind": "over-acceptance-dominates", "fn": fn, "fp": fp,
                         "why": "a false negative credits a deficient output and can reinforce it"})
    return {"format": FORMAT, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "f1": round(f1, 4), "precision": round(precision, 4),
            "recall": round(recall, 4), "findings": findings}


def batch(rows):
    """One session per criterion is precise and expensive; batching trades accuracy for cost."""
    data = list(rows or ())
    usable = [r for r in data if r.get("batch") is not None and r.get("f1") is not None]
    usable.sort(key=lambda r: int(r["batch"]))
    findings = []
    if len(usable) < 3:
        return {"format": FORMAT, "findings": [{"kind": "batch-sweep-missing"}]}
    best = max(usable, key=lambda r: r["f1"])
    findings.append({"kind": "batch-optimum", "batch": best["batch"], "f1": best["f1"]})
    cheapest = min((r for r in usable if r.get("cost") is not None),
                   key=lambda r: r["cost"], default=None)
    if cheapest is not None:
        findings.append({"kind": "cost-at-small-batch",
                         "cost": cheapest.get("cost"), "batch": cheapest.get("batch"),
                         "why": "below the optimum, extra sessions add cost without F1"})
    return {"format": FORMAT, "ladder": [(r["batch"], r["f1"]) for r in usable],
            "findings": findings}


def ablation(rows):
    """A toggle is a finding only when its interval excludes zero."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-ablation"}]}
    effects = [r for r in data if r.get("delta_f1") is not None]
    resolved = [r for r in effects if r.get("ci_low") is not None
                and r.get("ci_high") is not None
                and (r["ci_low"] > 0 or r["ci_high"] < 0)]
    if effects and not resolved:
        findings.append({"kind": "no-resolved-effect",
                         "span": round(max(r["delta_f1"] for r in effects)
                                       - min(r["delta_f1"] for r in effects), 4),
                         "why": "a toggle whose interval includes zero is not a contribution"})
    strict = [r for r in data if r.get("delta_unmet") is not None
              and r.get("delta_precision") is not None]
    if strict and any(r["delta_unmet"] > 0 and r["delta_precision"] < 0
                      and r.get("delta_recall", 0) > 0 for r in strict):
        findings.append({"kind": "guidance-shifts-strictness",
                         "why": "guidance does not raise F1; it trades precision for recall"})
    cost = [r for r in data if r.get("delta_cost") is not None]
    if cost and resolved and not any(r.get("flips_outcome") for r in resolved):
        findings.append({"kind": "cost-without-outcome",
                         "why": "a toggle that only adds cost is not a design principle"})
    return {"format": FORMAT, "findings": findings}


def agreement(rows):
    """Human labels are the ground truth; prevalence decides what accuracy means."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-agreement"}]}
    kappas = [r.get("kappa") for r in data if r.get("kappa") is not None]
    if kappas:
        k = sum(kappas) / len(kappas)
        findings.append({"kind": "agreement-measured", "kappa": round(k, 4)})
        if k < 0.6:
            findings.append({"kind": "labels-disagree", "kappa": round(k, 4),
                             "why": "a verifier cannot be scored against labels that disagree"})
    if not any(r.get("adjudicated") for r in data):
        findings.append({"kind": "labels-single-annotator",
                         "why": "a disagreement needs a senior reviewer, not a vote"})
    if any(r.get("single_rollout") for r in data):
        findings.append({"kind": "single-rollout-corpus",
                         "why": "sensitivity to the rollout distribution is unmeasured"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("reactive_verifier", "workflow-verifier", "a fixed path cannot cover a large rubric"),
        ("environment_alignment", "serialized-evidence", "text serialization erases the signal"),
        ("read_only_separation", "verifier-can-modify", "an unrestricted verifier can change what it grades"),
        ("domain_guidance", "no-guidance", "conventions are not in the criterion text"),
        ("unmet_f1", "accuracy-hides-failures", "prevalence makes accuracy look like skill"),
        ("reports_over_acceptance", "over-acceptance-unpriced", "crediting deficient output is the dangerous error"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
