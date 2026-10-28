#!/usr/bin/env python3
"""Headless one-goal runner used by `harness.probe`.

A probe must not run inside the server process: the candidate skills root and the
scratch workspace are per-process environment variables, and a crash must not take
the operator's service down. So the probe spawns this module in the scratch copy:

    python3 -m longrun.harness.runner --goal "<the task>" --out result.json

Contract: it writes ONE JSON object to `--out` and prints nothing else that
matters:

    {"goal": str, "created": float, "model": str,
     "actions": [{tool, args, observation, error, exit_code, ts}]}

`actions` is the loop's own trace, which `harness.record.from_actions` turns into
the same record shape the chat path produces — one record shape, never a second.
"""
import argparse
import json
import os
import sys
import time


def main(argv=None):
    """Run one goal in the current directory and write the result JSON."""
    ap = argparse.ArgumentParser(prog="longrun.harness.runner")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src"))
    from longrun.agent import agent as agent_mod
    started = time.time()
    try:
        result = agent_mod.agent_run(args.goal, args.max_steps, args.model,
                                     workspace=os.getcwd())
        actions = result.get("trace") or result.get("actions") or []
        model = result.get("model") or args.model or ""
        error = ""
    except Exception as exc:  # noqa: BLE001 — the probe must learn WHY it failed
        actions, model, error = [], args.model or "", "%s: %s" % (type(exc).__name__, exc)
    payload = {"goal": args.goal, "created": started, "model": model,
               "actions": actions, "error": error}
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, args.out)
    print(json.dumps({"ok": not error, "steps": len(actions), "error": error}))
    return 0 if not error else 1


if __name__ == "__main__":
    sys.exit(main())
