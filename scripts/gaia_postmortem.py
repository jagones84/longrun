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
    "empty-args": r"missing_args|empty_args",
}


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


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
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
        if "--json" in sys.argv:
            print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
