#!/usr/bin/env python3
"""Skill capsules — compile one completed invocation into a replayable fast path.

Source: arXiv:2611.10022, "How Much Skill Orchestration Can LLM Agents Compile
Away?" (round 120). A reusable skill still makes the model re-interpret it and
reconstruct its orchestration on every invocation. SkillCache compiles ONE
completed invocation into a parameterized capsule of programs and natural-language
steps, replays the capsule before reuse, and lets a plan executor return control
to the model only where the capsule cannot decide — keeping the source skill for
recovery.

The paper's warning is the reason this module refuses to guess: zero-shot
compilation, without execution evidence, produced plans that were brittle because
of incorrect assumptions about runtime bindings. So:

  * a capsule is built from a REAL invocation record, never from the skill text;
  * every argument bound to a value of that request becomes a named slot;
  * a step whose outcome is not deterministic is marked "judge" and always
    returns control;
  * a replay whose precondition no longer holds is INVALID, not silently reused.

Pure: invocation in, capsule/replay decision out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-capsule/1"
CONTROLS = ("reuse", "return-control", "invalid")


def compile_capsule(invocation, skill=None):
    """Compile one completed invocation; unparameterised bindings are a finding."""
    inv = invocation or {}
    sk = skill if isinstance(skill, dict) else ({"id": skill} if skill else {})
    steps_in = [s for s in inv.get("steps") or [] if isinstance(s, dict)]
    bindings = {str(k): str(v) for k, v in (inv.get("bindings") or {}).items()}
    params = {str(k): str(v) for k, v in (inv.get("params") or {}).items()}
    findings = []
    steps = []
    for i, step in enumerate(steps_in):
        if step.get("kind") == "judge" or step.get("deterministic") is False:
            steps.append({"index": i, "op": "judge", "why": step.get("why") or "model judgement",
                          "expectation": step.get("expectation")})
            continue
        tool = step.get("tool") or step.get("action")
        args = dict(step.get("args") or {})
        slots = []
        for key, value in list(args.items()):
            text = str(value)
            hit = next((p for p, v in params.items() if v == text), None)
            if hit:
                args[key] = {"slot": hit}
                slots.append(hit)
            elif any(b and b in text for b in bindings.values()):
                findings.append({"kind": "unparameterised-binding", "step": i,
                                 "arg": key,
                                 "why": "a value of this request is hard-coded in the capsule"})
        steps.append({"index": i, "op": "call", "tool": tool, "args": args,
                      "slots": slots, "output": step.get("output"),
                      "expectation": step.get("expectation")})
    capsule = {"skill": sk.get("id") or inv.get("skill"),
               "slots": sorted(params), "steps": steps,
               "preconditions": list(inv.get("preconditions") or []),
               "source_skill": sk.get("path") or inv.get("skill_path")}
    controls = [s["index"] for s in steps if s["op"] == "judge"]
    capsule["controls"] = controls
    capsule["safe"] = not findings
    return {"format": FORMAT, "ok": not findings, "capsule": capsule,
            "findings": findings, "control_steps": controls}


def applies(capsule, request):
    """Does this request match the capsule's declared slots at all?"""
    need = set((capsule or {}).get("slots") or [])
    have = set(str(k) for k in (request or {}).get("params", {}) or {})
    return {"format": FORMAT, "applies": need <= have, "missing": sorted(need - have)}


def replay(capsule, state):
    """Reuse, return control, or invalid — never a silent best effort."""
    cap = capsule or {}
    st = state or {}
    if cap.get("safe") is False:
        return {"format": FORMAT, "decision": "invalid", "return_at": None,
                "why": "the capsule embeds a value of the invocation it was built from"}
    have = set(str(k) for k in st.get("params", {}) or {})
    missing = sorted(set(cap.get("slots") or []) - have)
    if missing:
        return {"format": FORMAT, "decision": "invalid", "return_at": None,
                "why": "the request does not bind %s" % ", ".join(missing), "missing": missing}
    unmet = [p for p in cap.get("preconditions") or [] if p not in set(st.get("holds") or [])]
    if unmet:
        return {"format": FORMAT, "decision": "invalid", "return_at": None,
                "why": "precondition no longer holds: %s" % ", ".join(unmet),
                "unmet": unmet}
    plan = []
    for step in cap.get("steps") or []:
        if step["op"] == "judge":
            return {"format": FORMAT, "decision": "return-control", "return_at": step["index"],
                    "why": step.get("why"), "plan": plan,
                    "source_skill": cap.get("source_skill")}
        plan.append({"tool": step.get("tool"), "args": step.get("args")})
    return {"format": FORMAT, "decision": "reuse", "return_at": None,
            "plan": plan, "source_skill": cap.get("source_skill")}


def savings(capsule, per_step_tokens, model_tokens):
    """What replaying the capsule avoids: the model work a from-scratch run pays."""
    reuse = replay(capsule, {"params": {s: "<bound>" for s in (capsule or {}).get("slots") or []},
                             "holds": (capsule or {}).get("preconditions") or []})
    if reuse["decision"] != "reuse":
        return {"format": FORMAT, "saved_tokens": 0, "why": "the capsule does not replay unattended"}
    executed = len(reuse["plan"])
    saved = max(0, int(model_tokens or 0) - executed * int(per_step_tokens or 0))
    return {"format": FORMAT, "saved_tokens": saved, "executed_steps": executed,
            "why": "the model writes no orchestration for the replayed steps"}


def qualify(capsule, examples=None, checks=None):
    """The host's three admission gates, in order (paper §5.3) — none of them calls the model.

    Gate 1 structure and dataflow: a step reads only declared slots, one program writes each
    output, and no program reads an output before the program that produces it.
    Gate 2 program checks: the build/parse result the compiler recorded per program.
    Gate 3 end-to-end replay: every output a warm run would consume has a recorded example.
    A candidate that fails is repaired, then replaced by the written procedure, then by the
    source skill alone — never admitted on trust.
    """
    cap = capsule or {}
    ex = {str(k) for k in (examples or {})}
    chk = {str(k): bool(v) for k, v in (checks or {}).items()}
    steps = [s for s in cap.get("steps") or [] if isinstance(s, dict)]
    declared = {str(x) for x in cap.get("slots") or []}
    outputs = {str(s.get("output")) for s in steps
               if s.get("op") == "call" and s.get("output") is not None}
    produced = {}
    findings = []
    for i, step in enumerate(steps):
        if step.get("op") != "call":
            continue
        for key, val in (step.get("args") or {}).items():
            slot = val.get("slot") if isinstance(val, dict) else None
            if slot and slot not in declared and slot not in outputs:
                findings.append({"gate": 1, "kind": "undeclared-slot", "step": i, "slot": slot,
                                 "why": "the program reads a value the capsule never declares"})
        out = step.get("output")
        if out is not None:
            out = str(out)
            if out in produced:
                findings.append({"gate": 1, "kind": "two-writers", "step": i, "binding": out,
                                 "why": "two programs write the same binding"})
            produced.setdefault(out, i)
    for i, step in enumerate(steps):
        if step.get("op") != "call":
            continue
        for key, val in (step.get("args") or {}).items():
            slot = val.get("slot") if isinstance(val, dict) else None
            if slot in produced and produced[slot] >= i:
                findings.append({"gate": 1, "kind": "read-before-write", "step": i, "binding": slot,
                                 "why": "a program reads a binding before the program that writes it"})
    if findings:
        return {"format": FORMAT, "ok": False, "gate": 1, "findings": findings,
                "failed_steps": sorted({f["step"] for f in findings})}
    bad = sorted(t for t, ok in chk.items() if not ok)
    if bad:
        return {"format": FORMAT, "ok": False, "gate": 2,
                "findings": [{"gate": 2, "kind": "program-check-failed", "tool": t,
                              "why": "the program does not parse or build in the task image"}
                             for t in bad],
                "failed_steps": [i for i, s in enumerate(steps)
                                 if s.get("op") == "call" and str(s.get("tool")) in bad]}
    failed = []
    for i, step in enumerate(steps):
        if step.get("op") != "call":
            continue
        out = step.get("output")
        if out is not None and str(out) not in ex:
            failed.append({"gate": 3, "kind": "replay-missing-example", "index": i,
                           "tool": step.get("tool"), "binding": str(out),
                           "why": "replay has no recorded value for this output"})
    return {"format": FORMAT, "ok": not failed, "gate": 3, "findings": failed,
            "failed_steps": [f["index"] for f in failed]}


def deoptimize(capsule, failed_step, skill_path=None):
    """Only the failing step leaves the compiled path (paper §6.2); the rest stays compiled."""
    cap = capsule or {}
    steps = cap.get("steps") or []
    try:
        at = int(failed_step)
    except (TypeError, ValueError):
        return {"format": FORMAT, "decision": "invalid", "why": "the failing step must be an index"}
    if not 0 <= at < len(steps):
        return {"format": FORMAT, "decision": "invalid", "why": "no step %d in this capsule" % at}
    plan = []
    for step in steps[:at]:
        if step.get("op") != "call":
            return {"format": FORMAT, "decision": "return-control", "return_at": step.get("index"),
                    "why": "a control point precedes the failed program", "plan": plan,
                    "source_skill": cap.get("source_skill")}
        plan.append({"tool": step.get("tool"), "args": step.get("args")})
    target = steps[at]
    return {"format": FORMAT, "decision": "return-control", "return_at": at,
            "hand_over": {"tool": target.get("tool"), "why": "program_failed",
                          "source": skill_path or cap.get("source_skill") or cap.get("skill")},
            "resume_after": at + 1, "plan": plan,
            "why": "the failed program leaves the compiled path; later programs do not",
            "source_skill": cap.get("source_skill")}


def payback(compile_tokens, cold_tokens, warm_tokens):
    """How many reuses repay the compile call: k / (m0 - mzero), the paper's §7.6 rule."""
    saved = int(cold_tokens or 0) - int(warm_tokens or 0)
    cost = int(compile_tokens or 0)
    if saved <= 0:
        return {"format": FORMAT, "reuses": None, "saved_per_reuse": saved,
                "why": "a warm run does not use fewer tokens than a cold one"}
    return {"format": FORMAT, "reuses": round(cost / saved, 2), "saved_per_reuse": saved,
            "why": "compile cost divided by the tokens one reuse avoids"}
