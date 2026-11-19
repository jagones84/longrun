#!/usr/bin/env python3
"""Intent contract — the planner describes the step, the trusted side writes the call.

Source: arXiv:2611.24025, "Intent Contracts: Taking Tools Away from Agents"
(round 151). The planning model holds no tools. For each step it submits a short
logged contract — a goal, a verbatim quotation of the user and scope fields —
code validates it, and a small trusted model checks it against the user's words
and writes the tool call itself (`intent_contracts_2611.24025.txt:28`, `:31`).

  * **three properties hold by construction**, whichever models fill the roles:
    the trusted model writes every executed call, a code-accepted contract
    precedes every call and is all the planner contributes, and the trusted side
    chooses how much of a request to carry out (`:53`, `:154`).
  * **the goal is bounded and carries no command**: at most 100 words, and a
    goal containing a command line is rejected by code (`:132`, `:694`).
  * **the quotation is checked, not trusted**: a contiguous substring after
    Unicode NFKC and whitespace normalization, case preserved (`:219`, `:221`).
  * **scope may only narrow** the configured baseline (`:221`).
  * **measured**: every changed object under contracts is named in the goal of
    the contract that produced it (56/56), against 2/16 and 4/54 for the two
    reviewers whose commands mostly name them (`:315`, `:383`).
  * **the benefit is completion, not safety**: when the planner bundles in
    unrequested work, contracts finish the user's task in 27/27 runs against
    16/30 for an intent-visible reviewer that can only refuse a whole command
    (`:371`, `:423`).
  * **the honest negative**: contracts do not reduce unauthorized actions
    (10/96, the same as blind review), and on ambiguous references every acting
    condition hit a wrong target in 40–49% of those runs (`:49`, `:457`).

  * `validate()` — the goal, the quotation, the scope and the error policy.
  * `coverage(rows)` — which changed objects the planner named, and where.
  * `mcnemar(b, c)` — the exact paired test the paper reports.
  * `outcomes(record)` — safe completion, unauthorized action and incompleteness.
  * `bundling(rows)` — completing the authorized part of a bundled request.
  * `targets(rows)` — the four reference categories and the wrong-target rate.
  * `fixed_properties()` — what the dispatch code fixes, with no model named.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: contracts, counts and records in; verdicts and coverage out.
"""
from __future__ import annotations

import math
import unicodedata

FORMAT = "longrun-intent-contract/1"

GOAL_MAX_WORDS = 100
ERROR_POLICIES = ("abort", "continue", "retry")
COMMAND_FIRST = frozenset({
    "rm", "curl", "wget", "sudo", "git", "systemctl", "python", "python3",
    "bash", "sh", "docker", "kubectl", "npm", "pip", "ssh", "scp", "mv",
    "cp", "chmod", "chown", "dd", "sed", "awk", "make",
})
FIXED_PROPERTIES = (
    "the-trusted-model-writes-every-executed-call",
    "a-logged-contract-precedes-every-call",
    "the-trusted-side-chooses-the-granularity",
)
CATEGORIES = ("exact-id", "own-ticket", "own-range", "open-range")


def _norm(text):
    """NFKC then collapsed whitespace, case preserved."""
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).split())


def _looks_like_command(text):
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("$ ", "#!")):
            return True
        if " | " in stripped or " && " in stripped:
            return True
        first = stripped.split()[0].strip("`'\"").lower()
        if first in COMMAND_FIRST:
            return True
    return False


def _narrowed(prefixes, baseline):
    for prefix in prefixes or []:
        if not any(str(prefix).startswith(str(base)) for base in baseline or []):
            return False
    return True


def validate(record):
    """Goal, quotation, scope and error policy; every failure is named."""
    r = record or {}
    reasons = []
    goal = str(r.get("goal") or "")
    if not goal:
        reasons.append("goal-missing")
    elif len(goal.split()) > GOAL_MAX_WORDS:
        reasons.append("goal-too-long")
    elif _looks_like_command(goal):
        reasons.append("goal-contains-a-command")
    quotation = _norm(r.get("quotation"))
    messages = [_norm(m) for m in (r.get("user_messages") or [])]
    if not quotation:
        reasons.append("quotation-missing")
    elif not any(quotation in message for message in messages if message):
        reasons.append("quotation-not-verbatim")
    scope = r.get("scope") or {}
    baseline = r.get("baseline") or {}
    if not set(scope.get("egress_hosts") or []) <= set(baseline.get("egress_hosts") or []):
        reasons.append("egress-not-narrowed")
    if not _narrowed(scope.get("write_prefixes") or [],
                     baseline.get("write_prefixes") or []):
        reasons.append("write-prefix-not-narrowed")
    if str(r.get("error_policy") or "") not in ERROR_POLICIES:
        reasons.append("unknown-error-policy")
    return {"format": FORMAT, "reasons": reasons,
            "verdict": "contract-accepted" if not reasons else "contract-rejected"}


def coverage(rows):
    """Which changed objects the planner named, in the goal and in a command."""
    changed = 0
    in_goal = 0
    in_command = 0
    undocumented = []
    for row in rows or []:
        r = row or {}
        if not r.get("object"):
            continue
        changed += 1
        if r.get("named_in_goal") is True:
            in_goal += 1
        if r.get("named_in_command") is True:
            in_command += 1
        if r.get("named_in_goal") is not True and r.get("named_in_command") is not True:
            undocumented.append(str(r.get("object")))
    if not changed:
        return {"format": FORMAT, "verdict": "no-changes"}
    return {"format": FORMAT, "changed": changed,
            "goal_coverage": in_goal / changed,
            "command_coverage": in_command / changed,
            "undocumented": undocumented,
            "verdict": "fully-declared" if in_goal == changed
            else "declaration-gap"}


def mcnemar(b, c):
    """Exact two-sided McNemar p for `b` and `c` discordant pairs."""
    b = int(b or 0)
    c = int(c or 0)
    n = b + c
    if n == 0:
        return {"format": FORMAT, "p": 1.0, "verdict": "no-discordance"}
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2 ** n)
    p = min(1.0, 2 * tail)
    return {"format": FORMAT, "b": b, "c": c, "p": p,
            "verdict": "separated" if p < 0.05 else "indistinguishable"}


def outcomes(record):
    """Safe completion, unauthorized action and incompleteness over runs."""
    r = record or {}
    runs = int(r.get("runs") or 0)
    safe = int(r.get("safe") or 0)
    unauthorised = int(r.get("unauthorized") or 0)
    incomplete = int(r.get("incomplete") or 0)
    if not runs:
        return {"format": FORMAT, "verdict": "no-runs"}
    return {"format": FORMAT, "runs": runs,
            "safe_share": safe / runs,
            "unauthorized_share": unauthorised / runs,
            "incomplete_share": incomplete / runs,
            "overlap": safe + unauthorised + incomplete > runs,
            "verdict": "outcomes-measured"}


def bundling(rows):
    """A bundled request: does the authorized part still get completed?"""
    contract = [row or {} for row in (rows or []) if (row or {}).get("mode") == "contract"]
    review = [row or {} for row in (rows or []) if (row or {}).get("mode") == "review"]
    if not contract or not review:
        return {"format": FORMAT, "verdict": "both-arms-required"}
    def _done(arm):
        return sum(1 for r in arm if r.get("main_complete") is True)
    contract_done = _done(contract) / len(contract)
    review_done = _done(review) / len(review)
    extra = sum(1 for r in (contract + review) if r.get("extra_done") is True)
    return {"format": FORMAT, "contract": contract_done, "review": review_done,
            "gap": contract_done - review_done, "extra_done": extra,
            "verdict": "partial-execution-wins" if contract_done > review_done
            else "no-advantage"}


def targets(rows):
    """The four reference categories, and how often an acting run is wrong."""
    totals = {name: {"safe": 0, "unauthorized": 0} for name in CATEGORIES}
    for row in rows or []:
        r = row or {}
        category = str(r.get("category") or "")
        if category not in totals:
            continue
        if r.get("safe") is True:
            totals[category]["safe"] += 1
        if r.get("unauthorized") is True:
            totals[category]["unauthorized"] += 1
    acting = sum(v["safe"] + v["unauthorized"] for v in totals.values())
    wrong = sum(v["unauthorized"] for v in totals.values())
    ambiguous = sum(totals[c]["unauthorized"] for c in CATEGORIES[2:])
    return {"format": FORMAT, "categories": totals, "acting": acting,
            "wrong_target_share": (wrong / acting) if acting else None,
            "ambiguous_unauthorized": ambiguous,
            "verdict": "ambiguity-dominates" if ambiguous > 0
            and wrong == ambiguous else "mixed-targets"}


def fixed_properties():
    """What the dispatch code fixes, whatever the models are."""
    return {"format": FORMAT, "properties": list(FIXED_PROPERTIES),
            "count": len(FIXED_PROPERTIES), "verdict": "fixed-by-code"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("contract_means_authorized") is True:
        findings.append({"kind": "contract-means-authorized",
                         "why": "a contract is a record and a claim, not a policy boundary"})
    if r.get("reviewer_is_a_sandbox") is True:
        findings.append({"kind": "reviewer-is-a-sandbox",
                         "why": "review cannot confine a shell write outside declared prefixes"})
    if r.get("coverage_means_correct_target") is True:
        findings.append({"kind": "coverage-means-correct-target",
                         "why": "56/56 declared, yet 10/96 changed a wrong object"})
    if r.get("declaration_substitutes_for_enforcement") is True:
        findings.append({"kind": "declaration-substitutes-for-enforcement",
                         "why": "an unread INTENT line reproduced blind review, not review+intent"})
    if r.get("whole_command_is_enough") is True:
        findings.append({"kind": "whole-command-is-enough",
                         "why": "a reviewer can only refuse a bundle; 27/27 vs 16/30"})
    if r.get("trusted_model_sees_the_environment") is True:
        findings.append({"kind": "trusted-model-sees-the-environment",
                         "why": "it cannot tell which objects the planner meant"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("keeps_tools_from_the_planner", "planner_holds_tools",
         "a planner that executes cannot be checked before the act"),
        ("checks_the_quotation_against_the_user", "trusts_a_paraphrase",
         "a quotation is the only evidence of what the user said"),
        ("narrows_scope_from_a_baseline", "scope_widens_at_run_time",
         "a contract may narrow the baseline, never extend it"),
        ("rejects_a_goal_that_contains_a_command", "accepts_command_text",
         "command text is the act that the trusted side must own"),
        ("logs_every_contract_before_the_call", "logs_after_the_fact",
         "an intent recovered from the command is not a record"),
        ("lets_the_trusted_side_narrow_a_step", "approve_or_refuse_only",
         "whole-command review loses the authorized part of a bundle"),
        ("reports_wrong_targets_on_ambiguous_references", "claims_safety",
         "no trusted role here can see the environment"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
