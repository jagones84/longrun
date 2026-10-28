#!/usr/bin/env python3
"""Headless one-goal runner used by `harness.probe`.

A probe must not run inside the server process: the candidate skills root and the
scratch workspace are per-process environment variables, and a crash must not take
the operator's service down. So the probe spawns this module in the scratch copy:

    python3 -m longrun.harness.runner --goal "<the task>" --out result.json

**It runs the REAL chat loop** (`agent.chat_once`, the same one the operator's
chat uses), in a scratch session, and writes the resulting execution record:

    {"goal": str, "created": float, "model": str, "error": str,
     "record": { … `harness.record.build` output … }, "reply": str}

Why not `agent.agent_run`: that loop has no tool lane (`apply_agent_action`
answers "unknown action" for every `{"action": "tool"}`), so a record built from
its trace carries no tool names and no failures — the contrast would then report
"every base error fixed" on every probe and Compose would adopt any candidate.
The chat loop persists structured `tool_cards` (tool, ok, exit_code, error), which
is the evidence a contrast needs.

Import order: `longrun.agent.agent` and `longrun.core.server` import each other;
the service breaks the cycle by importing `server` first, and this runner does the
same.
"""
import argparse
import json
import os
import sys
import time
import uuid


def _src_root():
    """`<repo>/src` — the package must be importable from the scratch copy."""
    here = os.path.abspath(__file__)
    for _ in range(4):
        here = os.path.dirname(here)
    return os.path.join(here, "src")


def main(argv=None):
    """Run one goal in the current directory and write the result JSON."""
    ap = argparse.ArgumentParser(prog="longrun.harness.runner")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    src = _src_root()
    if src not in sys.path:
        sys.path.insert(0, src)
    started = time.time()
    payload = {}
    error = ""
    try:
        from longrun.core import server  # noqa: F401 — the cycle needs it imported first
        from longrun.agent import agent as agent_mod
        from longrun.harness import record as record_mod
        from longrun.memory import stores as stores_mod
        sid = "probe-" + ((os.environ.get("LONGRUN_HARNESS_PROBE") or "").strip()
                          or uuid.uuid4().hex[:12])
        sess = {"id": sid, "created": round(started, 3), "model": args.model or "",
                "workspace": os.getcwd(), "messages": [], "tool_cards": [], "injects": []}
        stores_mod.save_session(sess)
        stores_mod.append_message(sess, "user", args.goal)
        reply, model = agent_mod.chat_once(sess, args.goal, args.model)
        payload = {"record": record_mod.build(sid, session=sess),
                   "reply": str(reply or "")[:2000], "model": str(model or "")}
    except BaseException as exc:  # noqa: BLE001 — the probe must learn WHY it failed
        error = "%s: %s" % (type(exc).__name__, exc)
    payload.setdefault("record", None)
    payload.update({"goal": args.goal, "created": round(started, 3), "error": error})
    out = args.out
    try:
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out)
    except OSError as exc:
        print(json.dumps({"ok": False, "steps": 0, "error": "cannot write result: %s" % exc}))
        return 1
    steps = len((payload.get("record") or {}).get("steps") or [])
    print(json.dumps({"ok": not error, "steps": steps, "error": error}))
    return 0 if not error else 1


if __name__ == "__main__":
    sys.exit(main())
