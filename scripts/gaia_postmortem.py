#!/usr/bin/env python3
"""Post-mortem of ONE GAIA `.eval`: why each sample passed or failed.

A score is not a diagnosis. This walks the transcript of every sample and counts the
FAILURE SIGNATURES a harness can produce, so a run can be read one sample at a time:

    python3 scripts/gaia_postmortem.py .agent/BENCHMARKS/runs/gaia/<file>.eval

Signatures are the ones the arms actually produced on 2026-11-01:
  reject      the harness refused an action ("That was not a valid action")
  no-missing  a tool call missed a REQUIRED argument
  dns         a network call had no DNS (offline sandbox)
  tool-fail   any `[tool] exit=… ok=False`
  stuck       the harness's own "YOU ARE STUCK" nudge
  closure     closure-check bounces
  promise     the turn ended on a promise instead of an answer
Usage: `--json` for the machine-readable form.
"""
import json
import re
import sys

from inspect_ai.log import read_eval_log

SIGS = {
    "reject": r"That was not a valid action",
    "no-missing": r"missing REQUIRED",
    "dns": r"dns resolution failed|Temporary failure in name resolution",
    "tool-fail": r"ok=False",
    "stuck": r"YOU ARE STUCK",
    "closure": r"Closure check \(harness",
    "evidence": r"EVIDENCE GATE",
    "empty-args": r"missing_args|empty_args",
}

_TOOL_RE = re.compile(r'"action"\s*:\s*"tool"\s*,\s*"tool"\s*:\s*"([\w.\-]+)"')


def forensic(path):
    """Read one arm's own record of a trial (the container is gone; this is it).

    `benchmarks/inspect_arms.py` lifts `/tmp/lr/forensic.json` (longrun: every
    message, every durable event, the plan, the workspace listing) or
    `/tmp/oc/forensic.json` (openclaw: the exec envelope and its error log) out of
    the sandbox before Inspect destroys it. Without this, a lost sample can only be
    explained by paying for a re-run.
    """
    try:
        rec = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    msgs = rec.get("messages") or []
    body = "\n".join(str(m.get("content") or "") for m in msgs)
    kinds = {}
    for e in rec.get("events") or []:
        k = e.get("kind") or "?"
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "path": path,
        "turns": rec.get("turns") or sum(1 for m in msgs if m.get("role") == "assistant"),
        "tools": _TOOL_RE.findall(body),
        "signatures": {k: len(re.findall(p, body)) for k, p in SIGS.items()},
        "events": kinds,
        "plan": rec.get("plan"),
        "messages": msgs,
        "err_log": rec.get("err_log") or "",
        "answer": rec.get("answer") or rec.get("final") or "",
    }


def dump_messages(msgs, limit=8):
    """The transcript, message by message: what the harness and the model said."""
    for i, m in enumerate(msgs):
        role = m.get("role")
        text = str(m.get("content") or "")
        head = " ".join(text.split())[:limit * 60]
        print("      [%03d %s] %s" % (i, role, head))


def texts(msg):
    c = msg.content
    if isinstance(c, str):
        return [c]
    out = []
    for p in c:
        t = type(p).__name__
        if t == "ContentText":
            out.append(p.text or "")
        elif t == "ContentReasoning":
            out.append("")  # a scratchpad is not the transcript
    return out


def analyse(path):
    log = read_eval_log(path)
    rows = []
    for s in log.samples or []:
        body = "\n".join(t for m in (s.messages or []) for t in texts(m))
        score = {k: v.value for k, v in (s.scores or {}).items()}
        out = (s.output.completion if s.output else "") or ""
        counts = {k: len(re.findall(p, body)) for k, p in SIGS.items()}
        assistant = sum(1 for m in (s.messages or []) if m.role == "assistant")
        # the tool names that failed, from the harness's own observation lines
        failed_tools = sorted(set(re.findall(r"\[([\w.]+)\] exit=\d+ ok=False", body)))
        rows.append({
            "id": s.id,
            "score": score.get("gaia_scorer"),
            "target": (s.target if isinstance(s.target, str) else
                       getattr(s.target, "text", "") or ""),
            "answer": out.strip()[:160],
            "assistant_turns": assistant,
            "signatures": {k: v for k, v in counts.items() if v},
            "failed_tools": failed_tools,
        })
    return {
        "file": path.split("/")[-1],
        "accuracy": (log.results.scores[0].metrics["accuracy"].value
                     if log.results and log.results.scores else None),
        "samples": rows,
    }


def _find_forensic(folder, sample_id):
    """The arm's own record for this sample, under either arm's prefix."""
    import os
    for arm in ("longrun", "openclaw"):
        p = os.path.join(folder, "%s-%s.json" % (arm, sample_id))
        if os.path.exists(p):
            return forensic(p)
    return None


def main():
    args = sys.argv[1:]
    fore = None
    if "--forensic" in args:
        i = args.index("--forensic")
        fore = args[i + 1] if i + 1 < len(args) else None
    paths = [a for a in args if not a.startswith("--") and a != fore]
    if not paths:
        print(__doc__)
        return 2
    for p in paths:
        rep = analyse(p)
        print("=== %s  accuracy=%s" % (rep["file"], rep["accuracy"]))
        for r in rep["samples"]:
            print("  %s %s  turns=%d  %s" % (
                r["score"], r["id"][:8], r["assistant_turns"],
                json.dumps(r["signatures"]) if r["signatures"] else "-"))
            print("     answer: %r" % r["answer"])
            if r["failed_tools"]:
                print("     failed tools: %s" % ", ".join(r["failed_tools"]))
            f = _find_forensic(fore, r["id"]) if fore else None
            if f:
                # The harness's own account: what it ran, what broke, where it stopped.
                print("     arm record: turns=%s tools=%s" % (
                    f["turns"], json.dumps(f["tools"][:14])))
                sig = {k: v for k, v in f["signatures"].items() if v}
                if sig:
                    print("     arm signatures: %s" % json.dumps(sig))
                if f["events"]:
                    print("     events: %s" % json.dumps(f["events"]))
                plan = f["plan"] or {}
                nodes = (plan.get("nodes") if isinstance(plan, dict) else None) or []
                if nodes:
                    print("     plan: %d node(s), %d open" % (
                        len(nodes),
                        sum(1 for n in nodes
                            if str(n.get("status") or "") not in ("done", "superseded"))))
                if "--dump" in args:
                    dump_messages(f["messages"])
        if "--json" in sys.argv:
            print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
