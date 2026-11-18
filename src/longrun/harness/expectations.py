#!/usr/bin/env python3
"""Expectation–observation consistency — keep a batched plan grounded.

Source: arXiv:2611.02438, "As Expected? Efficient LLM Planning via
Expectation-Observation Consistency Verification" (round 117). A reactive
executor generates one action per step and pays for it; a batched executor
predicts several actions per invocation and is cheaper, but compounds errors
because it ignores intermediate observations. The paper's mechanism is small:

  * each planned action carries an EXPECTATION of its outcome;
  * after the action, the resulting observation is compared with it;
  * consistency permits continued execution;
  * a mismatch triggers early termination and replanning FROM THE CURRENT
    OBSERVATION — the remaining batched steps are not executed.

Measured: comparable task performance with 29–35% lower weighted token usage.
This module is the verifier only: it decides where the batch stops and what is
then unknown. It never predicts an expectation and never calls a model.

Pure: steps in, verdict out.
"""
from __future__ import annotations

FORMAT = "longrun-expectation-consistency/1"


def _norm(value):
    if isinstance(value, str):
        return value.strip()
    return value


def _matches(expected, observed, keys=None):
    """Every declared key must be present and equal; an undeclared key is not judged."""
    if not isinstance(expected, dict):
        return _norm(expected) == _norm(observed)
    if not isinstance(observed, dict):
        return False
    for key in (keys or expected.keys()):
        if key not in observed:
            return False
        if _norm(expected[key]) != _norm(observed[key]):
            return False
    return True


def verify(steps, keys=None):
    """Per-step consistency, the stop point, and what the batch then no longer knows."""
    rows = []
    first_mismatch = None
    for i, step in enumerate(steps or []):
        step = step if isinstance(step, dict) else {}
        if first_mismatch is not None:
            rows.append({"index": i, "status": "not-reached"})
            continue
        if "expect" not in step:
            rows.append({"index": i, "status": "no-expectation",
                         "why": "a batched step without an expectation cannot be verified"})
            first_mismatch = i
            continue
        if "observation" not in step:
            rows.append({"index": i, "status": "missing-observation"})
            first_mismatch = i
            continue
        if _matches(step["expect"], step["observation"], keys):
            rows.append({"index": i, "status": "consistent"})
        else:
            rows.append({"index": i, "status": "mismatch",
                         "expect": step["expect"], "observed": step["observation"]})
            first_mismatch = i
    action = "replan" if first_mismatch is not None else "continue"
    return {"format": FORMAT, "steps": rows, "first_mismatch": first_mismatch,
            "action": action, "replan_from": first_mismatch,
            "not_reached": sum(1 for r in rows if r["status"] == "not-reached")}


def savings(steps, tokens_per_step):
    """What the early stop bought: the steps a reactive executor would still have to pay for."""
    if not isinstance(tokens_per_step, (int, float)):
        return {"format": FORMAT, "saved_tokens": 0, "why": "no per-step cost declared"}
    res = verify(steps)
    saved = res["not_reached"] * tokens_per_step
    return {"format": FORMAT, "not_reached": res["not_reached"],
            "tokens_per_step": tokens_per_step, "saved_tokens": saved,
            "why": "an executor that replans from the current observation skips them"}
