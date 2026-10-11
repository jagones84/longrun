#!/usr/bin/env python3
"""Benchmark CLI (JAG-426 · Domain 3).

    python3 -m benchmarks.run --bench humaneval --tasks tasks.jsonl --out out/humaneval-001
    python3 -m benchmarks.run --bench swebench  --tasks instances.jsonl --out out/swe-001

`humaneval` runs end to end here (adapter -> predictions -> the task's own test).
`swebench` / `gaia` emit a predictions file for their OFFICIAL scorer: their
harnesses (docker images, hidden tests, judge models) are intentionally not
re-implemented in this repo.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks import humaneval                       # noqa: E402
from benchmarks.longrun_adapter import LongrunAdapter  # noqa: E402
from benchmarks.runner import run_suite                # noqa: E402


def _tasks(path):
    return humaneval.load_tasks(path) if path else []


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.run")
    ap.add_argument("--bench", default="humaneval",
                    choices=["humaneval", "swebench", "gaia"])
    ap.add_argument("--tasks", required=True, help="task file (.jsonl)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--base", default=os.environ.get("LONGRUN_BASE", "http://127.0.0.1:8790"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    tasks = _tasks(args.tasks)
    if not tasks:
        print("no tasks in %s" % args.tasks)
        return 2
    adapter = LongrunAdapter(base=args.base, model=args.model)
    prompt_fn = humaneval.prompt_for if args.bench == "humaneval" else None

    out = run_suite(adapter, tasks, args.out, prompt_fn=prompt_fn,
                    limit=args.limit, model=args.model)
    print("wrote %d prediction(s) -> %s" % (out["n"], out["preds"]))

    if args.bench == "humaneval":
        with open(out["preds"], encoding="utf-8") as f:
            preds = [json.loads(ln) for ln in f if ln.strip()]
        sc = humaneval.score(preds, tasks)
        print("humaneval: pass@1 = %s (%d/%d)" % (sc["pass@1"], sc["passed"], sc["n"]))
        with open(os.path.join(args.out, "score.json"), "w", encoding="utf-8") as f:
            json.dump(sc, f, indent=2)
    else:
        print("scoring for %s is done by its OFFICIAL harness, not here." % args.bench)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
