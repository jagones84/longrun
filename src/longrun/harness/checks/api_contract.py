#!/usr/bin/env python3
"""API usage contract — prove every well-behaved caller, not one call sequence.

Source: arXiv:2611.15207, "Pre-QED: Environment Specifications for Agentic
Verification" (round 115). A fuzz harness exercises one call sequence, so a proof
over it covers one usage scenario. The paper argues the bottleneck has moved from
HOW to prove to WHAT to prove: extract the API's usage contract, express the
illegal call orders in temporal logic, and make the harness model every legal
usage.

This module is the deterministic checker half of that idea, with a deliberately
small temporal vocabulary named as such:

  requires_before(call, before)  — a call needs a successful predecessor;
  forbidden_before(call, before) — a call must never come before another;
  no_duplicate(call)             — a call that may happen once;
  declared calls                 — anything outside the contract is reported.

`check(contract, sequence)` returns every violation with its position, and a
coverage line: which declared calls the sequence actually exercised. It never
claims more than the rules state.

Pure: contract and sequence in, violations out.
"""
from __future__ import annotations

FORMAT = "longrun-api-contract/1"
RULE_TYPES = ("requires_before", "forbidden_before", "no_duplicate")


def _calls(sequence):
    out = []
    for item in sequence or ():
        if isinstance(item, dict):
            out.append(str(item.get("call") or item.get("tool") or ""))
        else:
            out.append(str(item))
    return out


def _declared(contract):
    return {str(c) for c in ((contract or {}).get("calls") or ())}


def check(contract, sequence):
    contract = contract or {}
    names = _calls(sequence)
    declared = _declared(contract)
    rules = [r for r in (contract.get("rules") or ()) if isinstance(r, dict)
             and r.get("type") in RULE_TYPES]
    violations = []
    seen = {}
    for i, name in enumerate(names):
        seen[name] = seen.get(name, 0) + 1
        if declared and name not in declared:
            violations.append({"index": i, "call": name, "rule": "declared-calls",
                               "why": "call not in the declared contract"})
        before = names[:i]
        ok_before = [n for j, n in enumerate(before)
                     if not (isinstance(sequence[j], dict)
                             and (sequence[j].get("ok") is False
                                  or (isinstance(sequence[j].get("exit_code"), int)
                                      and sequence[j]["exit_code"] != 0)))]
        for rule in rules:
            if str(rule.get("call")) != name:
                continue
            need = [str(x) for x in (rule.get("before") or ())]
            if rule["type"] == "requires_before":
                missing = [n for n in need if n not in ok_before]
                if missing:
                    violations.append({"index": i, "call": name, "rule": rule["type"],
                                       "why": "missing successful predecessor(s): %s"
                                              % ", ".join(missing)})
            elif rule["type"] == "forbidden_before":
                hit = [n for n in need if n in before]
                if hit:
                    violations.append({"index": i, "call": name, "rule": rule["type"],
                                       "why": "came after forbidden predecessor(s): %s"
                                              % ", ".join(hit)})
            elif rule["type"] == "no_duplicate" and seen[name] > 1:
                violations.append({"index": i, "call": name, "rule": rule["type"],
                                   "why": "call repeated (occurrence %d)" % seen[name]})
    exercised = sorted(set(names) & declared) if declared else sorted(set(names))
    unexercised = sorted(declared - set(names)) if declared else []
    return {"format": FORMAT, "violations": violations, "calls": len(names),
            "exercised": exercised, "unexercised": unexercised,
            "verdict": "pass" if not violations else "violations"}
