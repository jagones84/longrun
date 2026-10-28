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
import shutil
import sys
import time
import uuid

MAX_EVIDENCE_CHARS = 1536 * 1024


def _copy_workspace(source):
    """Seed the writable work dir from the frozen read-only workspace copy."""
    source = str(source or "")
    if not source or not os.path.isdir(source):
        raise RuntimeError("workspace source is unavailable")
    shutil.copytree(source, os.getcwd(), dirs_exist_ok=True, symlinks=False)


def evidence_line(payload, max_chars=MAX_EVIDENCE_CHARS):
    """One transport line; an oversized record is refused, never half-parsed."""
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded, False
    error = str(payload.get("error") or "evidence exceeded the transport bound")
    reduced = {"record": None, "goal": payload.get("goal"),
               "created": payload.get("created"), "error": error,
               "record_truncated": True, "probe_id": payload.get("probe_id"),
               "snapshot": payload.get("snapshot")}
    return json.dumps(reduced, ensure_ascii=True, sort_keys=True), True


def prepare_rules(workspace, snapshot, guardrail=None):
    """Apply probe-only text through the same rule owner as the real chat loop.

    The launcher must box CONFIG_DIR and PROJECTS_DIR before this module imports
    rules. Project rules do not live at the workspace root.
    """
    from longrun.memory import rules
    for scope in ("global", "project"):
        text = str((snapshot or {}).get(scope) or "")
        if text.strip():
            rules.append(scope, text, ws=workspace)
    if guardrail:
        with open(guardrail, encoding="utf-8") as f:
            rules.append("project", f.read(), ws=workspace)


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
    ap.add_argument("--rules")
    ap.add_argument("--guardrail")
    ap.add_argument("--workspace-from")
    ap.add_argument("--gateway-socket")
    ap.add_argument("--gateway-port", type=int, default=0)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    src = _src_root()
    if src not in sys.path:
        sys.path.insert(0, src)
    started = time.time()
    payload = {}
    error = ""
    shim = None
    try:
        if args.workspace_from:
            _copy_workspace(args.workspace_from)
        if args.gateway_socket:
            from longrun.harness import unixshim
            shim = unixshim.Shim(args.gateway_socket)
            started_relay = shim.start(port=args.gateway_port)
            if not started_relay.get("ok"):
                raise RuntimeError("gateway relay unavailable")
        from longrun.core import server  # noqa: F401 — the cycle needs it imported first
        from longrun.agent import agent as agent_mod
        from longrun.harness import record as record_mod
        from longrun.memory import stores as stores_mod
        if args.rules:
            with open(args.rules, encoding="utf-8") as f:
                prepare_rules(os.getcwd(), json.load(f), args.guardrail)
        sid = "probe-" + ((os.environ.get("LONGRUN_HARNESS_PROBE") or "").strip()
                          or uuid.uuid4().hex[:12])
        sess = {"id": sid, "created": round(started, 3), "model": args.model or "",
                "workspace": os.getcwd(), "messages": [], "tool_cards": [], "injects": []}
        stores_mod.save_session(sess)
        stores_mod.append_message(sess, "user", args.goal)
        reply, model = agent_mod.chat_once(sess, args.goal, args.model)
        payload = {"record": record_mod.build(sid, session=sess),
                   "reply": str(reply.get("content") if isinstance(reply, dict)
                                else reply or "")[:2000], "model": str(model or "")}
    except BaseException as exc:  # noqa: BLE001 — the probe must learn WHY it failed
        error = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if shim is not None:
            shim.stop()
    payload.setdefault("record", None)
    payload.update({"goal": args.goal, "created": round(started, 3), "error": error,
                    "snapshot": str(os.environ.get("LONGRUN_H2_SNAPSHOT") or ""),
                    "probe_id": str(os.environ.get("LONGRUN_HARNESS_PROBE") or "")})
    if args.out:
        try:
            from longrun.util.fswrite import write_json
            write_json(args.out, payload)
        except OSError:
            pass
    steps = len((payload.get("record") or {}).get("steps") or [])
    encoded, truncated = evidence_line(payload)
    print("H2_RESULT " + encoded)
    print(json.dumps({"ok": not error and not truncated, "steps": steps, "error": error}))
    return 0 if not error and not truncated else 1


if __name__ == "__main__":
    sys.exit(main())
