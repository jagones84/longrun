#!/usr/bin/env python3
"""Step-level counterfactual intervention over ONE recorded tool call (HD-1).

CausalFlow (arXiv:2605.25338) turns a failed trace into an attribution by
re-executing a step with ONE fact changed and comparing the outcome: a step
whose intervention flips the result carries the responsibility. Longrun logged
the steps but could not run the intervention — every explanation it wrote was
correlational (`.agent/docs/plans/2026-11/2026-11-13_harness-debugging.md` HD-1).

This module is the deterministic half of that instrument: it builds the
intervention request for a card and compares the two observations. Execution
belongs to the ONE gated door (`api_v02.gated_call`), so a counterfactual runs
under the same policy, approvals and workspace as a normal call.

Two boundaries are deliberate:

* **Read-only tools only.** Re-executing a write is not a counterfactual, it is
  a duplicate effect. The scope/approval gate is not asked to decide that.
* **The live tree is the environment.** Nothing is frozen or restored, so the
  result is labelled `live-tree`; a writer card from the prefix is reported as
  a caveat, never hidden.

Pure: no server import, no model, no store write.
"""
import json

# The tools whose execution has no environment effect: re-running one with a
# different argument changes only what the agent OBSERVES. Deliberately a list,
# not a heuristic — a new read-only tool is added here in the same commit.
READ_ONLY = frozenset(("fs.read", "glob", "glob.list", "diff"))

MAX_ARGS = 20


def plan(card, change):
    """The intervention request for `card`, or `{"error": ...}`.

    `change` is the argument patch: either the flat patch itself
    (`{"path": "other.py"}`) or `{"args": {...}}`. It must differ from the card's
    recorded arguments — a counterfactual that changes nothing is a re-run.
    """
    if not isinstance(card, dict) or not str(card.get("tool") or "").strip():
        return {"error": "a recorded card is required"}
    tool = str(card.get("tool")).strip()
    if tool not in READ_ONLY:
        return {"error": "tool %r is not read-only: re-executing it would duplicate "
                         "a side effect instead of testing one fact" % tool}
    if not isinstance(change, dict):
        return {"error": "change must be an object of arguments"}
    if "args" in change and not isinstance(change.get("args"), dict):
        return {"error": "change.args must be an object"}
    patch = change.get("args") if isinstance(change.get("args"), dict) else change
    if not isinstance(patch, dict) or not patch:
        return {"error": "the change is empty: a counterfactual must change one fact"}
    raw = card.get("args")
    if isinstance(raw, dict):
        base = dict(raw)
    elif isinstance(raw, str):
        try:
            base = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {"error": "the card's args are not JSON"}
    else:
        base = {}
    if not isinstance(base, dict):
        return {"error": "the card's args are not an object"}
    changed = {k: v for k, v in patch.items() if base.get(k) != v}
    if not changed:
        return {"error": "the change does not differ from the recorded arguments"}
    args = dict(base)
    args.update(changed)
    if len(args) > MAX_ARGS:
        return {"error": "too many arguments (%d > %d)" % (len(args), MAX_ARGS)}
    return {"tool": tool, "args": args, "changed": sorted(changed),
            "original_args": base}


def _view(ok, exit_code, error, result):
    text = str(result or "")
    return {"ok": bool(ok), "exit_code": exit_code,
            "error": str(error or "")[:200], "result": text[:400],
            "result_chars": len(text)}


def compare(card, result, observation=""):
    """Same / different observation between the card and the re-execution.

    `result` is the raw tool dict; `observation` is what the SAME renderer the
    chat loop uses would have persisted into the card's `result` (the loop stores
    the rendered observation when the tool has no `stdout` — fs.read's payload is
    `content`). Comparison is on the FULL text, never on the truncated view the
    response carries: a diff that exists past 400 chars still counts.
    """
    if not isinstance(result, dict):
        return {"same": False, "changed": ["missing-result"],
                "verdict": "no-result",
                "before": _view(card.get("ok"), card.get("exit_code"),
                                card.get("error"), card.get("result")),
                "after": None}
    seen = observation or result.get("stdout") or result.get("content") \
        or result.get("result") or ""
    before = {"ok": bool(card.get("ok")), "exit_code": card.get("exit_code"),
              "error": str(card.get("error") or ""),
              "result": str(card.get("result") or "")}
    after = {"ok": bool(result.get("ok")), "exit_code": result.get("exit_code"),
             "error": str(result.get("stderr") or result.get("error") or ""),
             "result": str(seen)}
    changed = [k for k in ("ok", "exit_code", "error", "result")
               if before[k] != after[k]]
    return {"same": not changed, "changed": changed,
            "verdict": "same-observation" if not changed else "different-observation",
            "before": _view(before["ok"], before["exit_code"], before["error"],
                            before["result"]),
            "after": _view(after["ok"], after["exit_code"], after["error"],
                           after["result"])}
