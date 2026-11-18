#!/usr/bin/env python3
"""Longrun CLI — command the harness from the terminal.

Usage:
  python3 forge.py chat "message" [--session ID] [--model ALIAS] [--stream] [--new]
                          # no --session: this CLI's current session (printed as "session: ID")
  python3 forge.py agent "goal" [--max-steps N]
  python3 forge.py plan show [--session ID] | plan generate "goal" | plan toggle ID [--session ID]
  python3 forge.py tasks ls | tasks add "title" | tasks done ID | tasks set ID STATUS
  python3 forge.py tools ls | tools call <tool> '<json-args>' | tools running | tools cancel JOB
  python3 forge.py approvals ls | approvals show ID | approvals approve ID | approvals deny ID | approvals rm ID | approvals clear
  python3 forge.py runs ls | runs show RUN_ID | runs summary | runs trace RUN_ID
                          | runs node RUN_ID '<json>' | control pause|resume|abort RUN_ID
  python3 forge.py sessions ls | sessions new "title" [--workspace DIR] | sessions rm ID
                         | sessions fork ID [--at N] [--title T] [--model M]
                         | sessions use ID | sessions current | sessions history [ID]
                         | sessions card HANDLE (one tool card of the current session)
                         | sessions counterfactual HANDLE --arg k=v (re-run one read-only call)
                         | sessions tree [ID] | sessions graph [ID]
                         | sessions export [ID] [--profile share|audit] [--out FILE]
                          | sessions backtrace [ID] [--card HANDLE]
                          | sessions transport [ID] [--budget N] | sessions stopping [ID]
                          | sessions reset ID | sessions clear ID | sessions model "SID MODEL"
  python3 forge.py docs status|plan "request"|spec "request"|approve|reject|unlock [--session ID]
  python3 forge.py context show [--session ID] | context compact [--session ID]
                          | context preview "message" [--session ID] | context items [--session ID]
  python3 forge.py checkpoints ls | checkpoints create "label" [--session ID]
                         | checkpoints show CP_ID | checkpoints rollback CP_ID
                         | checkpoints rm CP_ID | checkpoints prune
  python3 forge.py setup run PLAN.json [--workspace DIR] [--reuse] [--state DIR]
  python3 forge.py invariants | manifest
  python3 forge.py skills stale [--json] | skills value FILE.json | skills repair FILE.json --map old=new
  python3 forge.py reuse audit FILE.json [--allow t1,t2] | principals check FILE.json
  python3 forge.py residency plan FILE.json --capacity N [--current SID]
  python3 forge.py procedure run FILE.json | intent check|audit FILE.json
  python3 forge.py handoff audit FILE.json
  python3 forge.py approvals audit FILE.json | autonomy check FILE.json | skills prune FILE.json
  python3 forge.py memory surface FILE.json | teams audit FILE.json | toolgraph build|feedback FILE.json
  python3 forge.py memory boundary|conflicts FILE.json | instructions audit FILE.json
  python3 forge.py memory ledger FILE.json | episodes audit FILE.json | contract check FILE.json
  python3 forge.py recovery adjudicate FILE.json | effects coverage|verify FILE.json | context cost FILE.json
  python3 forge.py commit decide FILE.json | expectations verify FILE.json | governance decide FILE.json
  python3 forge.py capsule compile|replay FILE.json | flow judge FILE.json | selfdirected audit FILE.json
  python3 forge.py harnessevo diagnose|admit FILE.json | contextpipeline deliver FILE.json | stepzero extract FILE.json
  python3 forge.py harnessrecord audit FILE.json | conduct score FILE.json | completion check FILE.json
  python3 forge.py skillret calibrate FILE.json | ruleret closure FILE.json | skillquality profile FILE.json
  python3 forge.py opspolicy realize FILE.json | execpolicy confirm FILE.json
  python3 forge.py skilladapter bind FILE.json | intake admit FILE.json
  python3 forge.py memcredit arbitrate FILE.json | lessongate probe FILE.json | seclattice admit FILE.json
  python3 forge.py optmemory continuity FILE.json | detour classify FILE.json | patchprobe compare FILE.json
  python3 forge.py poison trace FILE.json | boundary evaluate FILE.json | gapleak verify FILE.json
  python3 forge.py binding alignment FILE.json | gateway utility FILE.json | scoring advise FILE.json
  python3 forge.py routing show | routing update '{"chat":"qwen"}'
  python3 forge.py eval tasks | eval run [--task ID] [--model ALIAS] [--max-steps N] [--no-save]
  python3 forge.py voice status | voice stt "text" | voice tts "text"
  python3 forge.py status | models [ls|ensure ALIAS] | providers [ls|add|rm|default|rm-model]
                          | self | selfcheck | sandbox | mcp [tools|ls|add|remove|reload|local-file] | hooks
  python3 forge.py agents ls | agents new NAME [--role R] [--model M] [--reports-to AX]
                          | agents set AX [...] | agents rm AX
  python3 forge.py jobs ls | jobs new "goal" [--to AX] [--blocked-by JN,JN] [--mode m]
                          | jobs run JN | jobs wake | jobs get JN
  python3 forge.py routines ls | routines new "goal" --agent AX [--every N]
                          | routines enable|disable|rm RID
  python3 forge.py market [ls|sources|status|installed] | market sync [--source S] [--wait]
                          | market remote <query> [--source S] | market import <source> <slug>
                          | market install <id> [--overwrite] | market rm <id> [--files]
  python3 forge.py roles show|set|clear|reset --session SID_OR_AX
  python3 forge.py index [status|build|search] | knowledge [status|notebooks|create|add|search|discover|import|research]
                          | research [ls|set|active] | embedding [models|active|set|add|remove|costs|cost-test]
  python3 forge.py feed | events [--since N] [--limit N]
  python3 forge.py memory store <kind> <content> | search <query> [--kind K] [--semantic]
  python3 forge.py subagent spawn <goal> [--max-steps N] | collect <id> | status [id]
  python3 forge.py meta run [--n-candidates N] | status | best
  python3 forge.py blackboard post <topic> <content> [--tags T] | get [--id I] [--topic T] | search <q>
  python3 forge.py acp server <method> '[params]' | connect <name> <url> [--token T]
  python3 forge.py swarm <goal> [--n-workers N] [--max-steps N]
  python3 forge.py paperclip-bot   # Paperclip adapter child: envelope on stdin, NDJSON on stdout
Environment:
  LONGRUN_URL (default http://127.0.0.1:8790)
  LONGRUN_TOKEN (bearer token, optional)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# The service authenticates from the gitignored `.env` (JAG-492 through
# `providers.load_env`). The CLI must read the SAME place — otherwise every
# terminal command answers `unauthorized` while the server works, which is how
# this was found. One loader, no second parser.
try:
    _SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
    from longrun.model import providers as _providers
    _providers.load_env()
except Exception:  # noqa: BLE001 — a missing catalogue must not break the CLI
    pass

BASE = os.environ.get("LONGRUN_URL", "http://127.0.0.1:8790").rstrip("/")
TOKEN = os.environ.get("LONGRUN_TOKEN")


def _q(value):
    """URL-encode a query value (JAG-246: raw spaces/'&' made urlopen raise)."""
    return urllib.parse.quote("" if value is None else str(value), safe="")


def req(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": "HTTP %d" % e.code}
    except urllib.error.URLError as e:
        return {"error": "cannot reach Longrun at %s (%s)" % (BASE, e.reason)}
    except Exception as e:  # noqa: BLE001
        # JAG-246: a malformed URL (bad char, bad port) must return an error dict,
        # never a raw traceback out of the CLI.
        return {"error": "request failed: %s" % e}


# ---------------------------------------------------------- current session --
# The CLI had no memory: a bare `chat` asked the server for a NEW session and threw
# its id away, so a session created with `sessions new` stayed empty and the turn
# landed in an anonymous row (`stores.get_or_create_session(None)`). One small
# per-machine pointer fixes the operator's flow ("lanciare sessioni e vedere che
# fanno"); `chat --new` keeps the old one-shot semantics. `LONGRUN_CLI_STATE`
# overrides the file so tests never touch the real data home.
_CLI_STATE_ENV = "LONGRUN_CLI_STATE"

# A turn is not bounded by 5 minutes: measured 2026-11-16 20:48:37 on session
# `b7329cccf94c` — the CLI's 300 s socket timeout closed the connection and the
# server's `watch_client` (httpapi.py) read that as "the client is gone" and
# ABORTED the running turn. A long delegation must be waited on, not killed.
_LONG_TIMEOUT = 6 * 3600


def _state_path():
    override = os.environ.get(_CLI_STATE_ENV)
    if override:
        return override
    from longrun.util import paths
    return os.path.join(paths.DATA_DIR, "cli_session.json")


def _current_session():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return str((json.load(f) or {}).get("session") or "")
    except (OSError, ValueError):
        return ""


def _set_current_session(sid):
    sid = str(sid or "").strip()
    if not sid:
        return
    p = _state_path()
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"session": sid, "ts": time.time()}, f)
        os.replace(tmp, p)
    except OSError:
        pass  # a read-only home must not break the command


def _clear_current_session(sid=""):
    """Drop the pointer (only when it names `sid`, or unconditionally with "")."""
    try:
        if sid and _current_session() != sid:
            return
        os.remove(_state_path())
    except OSError:
        pass


def _chat_ref(explicit, required=True):
    """The session a chat/inspection command targets: a session id OR an agent id (AX).

    2026-11-18 (operator: "parlare con i miei agenti"): `--session A50` was taken
    LITERALLY, so the turn went to a session named "A50" and vanished from the rail
    — the same class as the "empty session" report. An unknown AX now fails loudly
    instead of inventing a row.
    """
    ref = str(explicit or "").strip() or _current_session()
    if not ref:
        if required:
            _no_current_session()
        return ""
    if re.match(r"^A\d+$", ref):
        a = _agent_row(req("GET", "/api/agents/tree"), ref)
        sid = (a or {}).get("session")
        if not sid:
            print("error: no agent %s in the org chart" % ref, file=sys.stderr)
            sys.exit(1)
        return sid
    return ref


def _no_current_session():
    print("no current session — run `sessions new` or `sessions use ID`", file=sys.stderr)
    sys.exit(2)


def sse(path):
    """Consume an SSE endpoint, printing deltas live."""
    r = urllib.request.Request(BASE + path, headers={
        "Accept": "text/event-stream",
        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    ev, data = None, []
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif line == "" and ev:
                    payload = "\n".join(data)
                    data = []
                    yield ev, payload
                    ev = None
    except KeyboardInterrupt:
        return


def _brief(value, n=140):
    """One line, bounded — for args/results on the live stream."""
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"


# The render events the WebUI draws as cards, and the one-line shape the CLI
# prints for each. 2026-11-18 (operator: "vederli real time … con tutto il flusso
# di informazioni"): `--stream` used to print chat.delta only, although the server
# sends every one of these on the SAME turn stream (httpapi.chat_stream_gen passes
# `_emit` to `chat_once`). The CLI was discarding the flow, not missing it.
_STREAM_RENDER = {
    "tool.call":        lambda d: "\n→ %s %s" % (d.get("tool") or "?",
                                                 _brief(d.get("args") or {})),
    "tool.result":      lambda d: "  ← %s ok=%s%s%s" % (
        d.get("tool") or "?", d.get("ok"),
        (" exit=" + str(d.get("exit_code"))) if d.get("exit_code") not in (None, "") else "",
        ("  " + _brief(d.get("error") or d.get("result") or d.get("observation"), 100))
        if (d.get("error") or d.get("result") or d.get("observation")) else ""),
    "tool.output":      lambda d: "  | %s" % _brief(d.get("text"), 120),
    "harness.inject":   lambda d: "\n[harness%s] %s" % (
        (":" + str(d.get("inject_kind"))) if d.get("inject_kind") else "",
        _brief(d.get("text"), 180)),
    "harness.drop":     lambda d: "\n[harness] dropped %s" % _brief(d.get("kind") or d, 120),
    "approval.request": lambda d: "\n[approval] %s needs approval (id %s)" % (
        d.get("tool") or "?", d.get("id") or ""),
    "approval.resolved": lambda d: "[approval] %s %s" % (
        d.get("tool") or "?", d.get("status") or ""),
    "plan.incomplete":  lambda d: "\n[plan] incomplete: %s step(s) still open" % d.get("open"),
    "plan.continuing":  lambda d: "\n[plan] continuing",
    "plan.stopped":     lambda d: "\n[plan] stopped: %s" % _brief(d.get("reason") or "", 120),
    "verify.run":       lambda d: "\n[verify] %s %s ok=%s" % (
        d.get("tool") or "?", d.get("path") or "", d.get("ok")),
    "hitl.request":     lambda d: "\n[hitl] %s" % _brief(d.get("question") or d, 160),
}


def stream_chat(path):
    """Stream one chat turn; return the session id the server adopted (or "").

    Prints the model's text (reasoning dimmed) AND the render events the WebUI
    draws as cards — tool calls, results, harness injects, approvals, plan and
    verify notes — so the terminal shows the same flow as the chat.
    """
    adopted = ""
    for ev, payload in sse(path):
        try:
            d = json.loads(payload) if payload and payload != "{}" else {}
        except json.JSONDecodeError:
            continue
        if ev == "chat.run":
            # The FIRST frame carries the id the server is writing to — the one a
            # bare `chat` used to throw away (the "empty session" report).
            adopted = str((d or {}).get("session") or adopted)
            continue
        if ev == "chat.delta":
            # JAG-243: the ANSI codes were missing the ESC byte, so `--stream`
            # printed the literal "[90m…think[0m". Use \x1b to actually dim it.
            if d.get("channel") == "think":
                sys.stdout.write("\x1b[90m…think\x1b[0m ")
            sys.stdout.write(d.get("text", ""))
            sys.stdout.flush()
        elif ev in _STREAM_RENDER:
            print(_STREAM_RENDER[ev](d or {}))
            sys.stdout.flush()
        elif ev == "error":
            print("\n[error] %s" % d.get("error"), file=sys.stderr)
        elif ev == "done":
            print()
    return adopted


def cmd_chat(args):
    # `--session` > current pointer; `--new` forces a fresh session (old behaviour).
    # An agent id (AX) resolves to the agent's session, so "talk to A50" needs no lookup.
    sid = "" if getattr(args, "new", False) else _chat_ref(args.session, required=False)
    if args.stream:
        url = "/api/chat/stream?message=%s" % _q(args.message)
        if sid:
            url += "&session=" + _q(sid)
        if args.model:
            url += "&model=" + _q(args.model)
        if sid:
            print("session: %s" % sid)
        adopted = stream_chat(url)
        got = adopted or sid
        if got:
            _set_current_session(got)
            print("session: %s" % got)
        return
    out = req("POST", "/api/chat", {"message": args.message, "session": sid or None,
                                    "model": args.model}, timeout=_LONG_TIMEOUT)
    if out.get("error"):
        print("error:", out["error"], file=sys.stderr)
        sys.exit(1)
    got = str(out.get("session") or "").strip() or sid
    if got:
        _set_current_session(got)      # never lose the transcript's address again
        print("session: %s" % got)
    if out.get("reasoning"):
        print("[thinking]", out["reasoning"][:600], "\n")
    print(out.get("reply", ""))


def cmd_agent(args):
    url = "/api/agent/run?goal=%s&max_steps=%d%s" % (
        _q(args.goal), args.max_steps, "&model=" + _q(args.model) if args.model else "")
    try:
        for ev, payload in sse(url):
            try:
                d = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                continue
            if ev == "agent.iteration":
                print("\n── iteration %s/%s ──" % (d.get("i"), d.get("of")))
            elif ev == "agent.think":
                pass  # already streamed via agent.thought below
            elif ev == "agent.thought":
                print("🧠 thought:", d.get("thought", ""))
                print("⚡ action:", d.get("action"))
            elif ev == "agent.observation":
                print("👁 observation:", d.get("observation"))
            elif ev == "agent.note":
                print("📝 note:", d.get("text"))
            elif ev == "agent.finish":
                print("\n🏁 finish:", d.get("summary", ""))
            elif ev == "error":
                print("[error]", d.get("error"), file=sys.stderr)
    except KeyboardInterrupt:
        pass


def cmd_plan(args):
    sid = getattr(args, "session", None)
    if args.action == "show":
        # JAG-244: the plan is PER SESSION (the persistent task graph). Without
        # `?session=` the server returns the empty default, so `plan show` always
        # looked empty. Pass the session through.
        url = "/api/plan" + ("?session=" + _q(sid) if sid else "")
        plan = req("GET", url)
        print("GOAL:", plan.get("goal") or "(none)")
        for i, s in enumerate(plan.get("steps", []), 1):
            print(" %d. [%s] %s %s" % (i, "x" if s.get("done") else " ",
                                       s.get("title", ""), "(" + s.get("id", "") + ")"))
    elif args.action == "generate":
        out = req("POST", "/api/plan/generate", {"goal": args.goal})
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        for s in out.get("plan", {}).get("steps", []):
            print(" •", s.get("title"))
    elif args.action == "toggle":
        print(json.dumps(req("POST", "/api/plan/toggle", {"id": args.id, "session": sid}),
                         indent=2, ensure_ascii=False))
    elif args.action == "set":
        steps = json.loads(args.steps) if args.steps else []
        print(json.dumps(req("POST", "/api/plan",
                             {"goal": args.goal, "steps": steps, "session": sid}),
                         indent=2, ensure_ascii=False))


def cmd_tasks(args):
    if args.action == "ls":
        out = req("GET", "/api/tasks")
        for t in out.get("tasks", []):
            print(" [%s] %s (%s)" % (t.get("status", "?"), t.get("title"), t.get("id")))
        if out.get("remaining"):
            print("\nRemaining:")
            for r in out["remaining"]:
                print("  -", r)
    elif args.action == "add":
        print(json.dumps(req("POST", "/api/tasks", {"title": args.value}), indent=2))
    elif args.action == "done":
        print(json.dumps(req("PATCH", "/api/tasks", {"id": args.value, "status": "done"}), indent=2))
    elif args.action == "set":
        print(json.dumps(req("PATCH", "/api/tasks", {"id": args.value, "status": args.status}), indent=2))


def cmd_status(_):
    print(json.dumps(req("GET", "/api/status"), indent=2))


def cmd_sandbox(_):
    print(json.dumps(req("GET", "/api/sandbox?force=1"), indent=2))


def cmd_tools(args):
    if args.action == "ls":
        out = req("GET", "/api/tools")
        for t in out.get("tools", []):
            print(" %-9s enabled=%-5s approval=%-8s auto=%d :: %s"
                  % (t["name"], t["enabled"], t["approval"], len(t.get("auto_approve") or []),
                     (t.get("description") or "")[:70]))
        print("\nsandbox: %s (isolated=%s)" % (out.get("sandbox", {}).get("backend"),
                                               out.get("sandbox", {}).get("isolated")))
    elif args.action == "call":
        try:
            tool_args = json.loads(args.value2) if args.value2 else {}
        except json.JSONDecodeError as e:
            print("bad json args:", e, file=sys.stderr)
            sys.exit(2)
        out = req("POST", "/api/tools/call", {"tool": args.value, "args": tool_args})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "running":
        print(json.dumps(req("GET", "/api/tools/running"), indent=2, ensure_ascii=False))
    elif args.action == "cancel":
        print(json.dumps(req("POST", "/api/tools/cancel", {"job": args.value}),
                         indent=2, ensure_ascii=False))
    # 2026-11-17: the policy WRITE verbs (policy/runtime/verifier/…/approvals) are
    # gone. Operator: "can you change it by CLI? i think not otherwise an agent can
    # run the cli and auto change its approval policy — its anti secure". The CLI
    # READS the policy (`tools ls`); it never writes it — the server refuses such a
    # write when the body carries a session, and no CLI path does.


def cmd_approvals(args):
    if args.action == "audit":
        # Round 112 (arXiv:2611.19237): refusal safety vs authorization
        # completeness over caller-supplied decision/call/dispatch/effect records.
        from longrun.harness import approval_audit
        if not args.value:
            print("usage: approvals audit FILE.json", file=sys.stderr)
            sys.exit(2)
        try:
            with open(args.value, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad file:", e, file=sys.stderr)
            sys.exit(2)
        rows = doc.get("records") if isinstance(doc, dict) else doc
        out = approval_audit.audit(rows or [])
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out.get("verdict") == "clean" else 1)
    if args.action == "ls":
        out = req("GET", "/api/approvals")
        print("stats:", json.dumps(out.get("stats", {})))
        for a in out.get("approvals", []):
            print(" [%-13s] %-9s %-10s %s" % (a["status"], a["tool"], a["id"], a["summary"][:70]))
    elif args.action == "show":
        print(json.dumps(req("GET", "/api/approvals/" + args.value), indent=2, ensure_ascii=False))
    elif args.action in ("approve", "deny"):
        out = req("POST", "/api/approvals/" + args.value,
                  {"decision": args.action, "by": "cli"})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "rm":
        print(json.dumps(req("DELETE", "/api/approvals/" + args.value),
                         indent=2, ensure_ascii=False))
    elif args.action == "clear":
        params = "?keep_pending=0" if getattr(args, "all", False) else ""
        if args.status:
            params += ("&" if params else "?") + "status=" + _q(args.status)
        print(json.dumps(req("DELETE", "/api/approvals" + params),
                         indent=2, ensure_ascii=False))


def cmd_runs(args):
    if args.action == "ls":
        for r in req("GET", "/api/agent/runs").get("runs", []):
            print(" [%-9s] %-16s steps=%-2s %s" % (r["status"], r["id"], r["steps"],
                                                   (r.get("goal") or "")[:60]))
    elif args.action == "summary":
        print(json.dumps(req("GET", "/api/runs"), indent=2, ensure_ascii=False))
    elif args.action == "trace":
        print(json.dumps(req("GET", "/api/runs/%s/trace" % args.value), indent=2, ensure_ascii=False))
    elif args.action == "node":
        try:
            body = json.loads(args.value2) if args.value2 else {}
        except json.JSONDecodeError as e:
            print("bad json:", e, file=sys.stderr)
            sys.exit(2)
        print(json.dumps(req("POST", "/api/runs/%s/graph/nodes" % args.value, body),
                         indent=2, ensure_ascii=False))
    else:
        print(json.dumps(req("GET", "/api/agent/runs/" + args.value), indent=2, ensure_ascii=False))


def cmd_control(args):
    out = req("POST", "/api/agent/control", {"runId": args.value2, "action": args.value})
    print(json.dumps({k: out.get(k) for k in ("id", "status", "goal")}, indent=2))


def cmd_memory(args):
    if args.action == "ledger":
        # Round 115 (arXiv:2611.20927): apply claims/forgets, then answer queries.
        from longrun.memory import fact_ledger
        if not args.value:
            print("usage: memory ledger FILE.json", file=sys.stderr)
            sys.exit(2)
        try:
            with open(args.value, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad file:", e, file=sys.stderr)
            sys.exit(2)
        led = fact_ledger.Ledger()
        for claim in doc.get("claims") or []:
            led.apply(claim)
        for item in doc.get("forgets") or []:
            if isinstance(item, dict):
                led.forget(item.get("key"), item.get("ts"))
            else:
                led.forget(item)
        out = {"applied": led.applied, "verify": led.verify(), "evidence": {}}
        for q in doc.get("queries") or []:
            key = q.get("key") if isinstance(q, dict) else q
            at = q.get("as_of") if isinstance(q, dict) else None
            out["evidence"][key] = led.resolve(key, at)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["verify"]["verdict"] == "holds" else 1)
    if args.action in ("boundary", "conflicts"):
        if not args.value:
            print("usage: memory %s FILE.json" % args.action, file=sys.stderr)
            sys.exit(2)
        try:
            with open(args.value, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad file:", e, file=sys.stderr)
            sys.exit(2)
        if args.action == "boundary":
            # Round 114 (arXiv:2611.19264): coherent evidence or a refusal.
            from longrun.memory import read_boundary
            out = read_boundary.validate(doc.get("reads") or [], doc.get("expected_epoch"))
        else:
            # Round 114 (arXiv:2611.22461): keep contradictions, rank the values.
            from longrun.memory import conflict_surface
            out = conflict_surface.render(doc.get("claims") or [],
                                          cap=doc.get("cap") if isinstance(doc, dict) else None)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        if args.action == "boundary":
            sys.exit(0 if out.get("consistent") else 1)
        return
    if args.action == "surface":
        # Round 113 (arXiv:2611.22179): rules first, patterns second, facts last.
        from longrun.memory import rule_surface
        if not args.value:
            print("usage: memory surface FILE.json [--budget N]", file=sys.stderr)
            sys.exit(2)
        try:
            with open(args.value, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad file:", e, file=sys.stderr)
            sys.exit(2)
        hits = doc.get("hits") if isinstance(doc, dict) else doc
        out = rule_surface.render(hits or [], budget_tokens=getattr(args, "budget", None))
        print(out["text"])
        print("\ncounts:", json.dumps(out["counts"]))
        return
    if args.action == "store":
        out = req("POST", "/api/memory", {"kind": args.value, "content": args.value2})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "forget":
        out = req("DELETE", "/api/memory?target=" + _q(args.value))
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "purge":
        out = req("POST", "/api/memory", {"action": "purge"})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "search":
        query = args.value
        params = "?query=%s&limit=%d" % (_q(query), args.limit)
        if args.kind:
            params += "&kind=" + _q(args.kind)
        if args.semantic:
            params += "&semantic=1"
        out = req("GET", "/api/memory" + params)
        for r in out.get("results", []):
            print(" [%.3f] %s" % (r.get("score", 0), r.get("content", "")[:120]))


def cmd_episodes(args):
    """Round 115 (arXiv:2611.13254): validate a fault episode record and name controls."""
    from longrun.harness import fault_episode
    if not getattr(args, "file", None):
        print("usage: episodes audit FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = fault_episode.audit(doc)
    out["controls"] = fault_episode.controls(doc)["controls"]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["verdict"] == "complete" else 1)


def cmd_contract(args):
    """Round 115 (arXiv:2611.15207): a declared call-order contract vs a sequence."""
    from longrun.harness import api_contract
    if not getattr(args, "file", None):
        print("usage: contract check FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = api_contract.check(doc.get("contract") or {}, doc.get("sequence") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["verdict"] == "pass" else 1)


def cmd_recovery(args):
    """Round 116 (arXiv:2610.41453): what a timeout lets you re-issue safely."""
    from longrun.harness import effect_recovery
    if not getattr(args, "file", None):
        print("usage: recovery adjudicate|trace FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "trace":
        out = effect_recovery.trace_safety(doc.get("trace") or [], doc.get("capabilities") or {})
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["verdict"] == "clean" else 1)
    out = effect_recovery.adjudicate(doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["certificate"] in ("goal-satisfied", "safe-stop") else 1)


def cmd_effects(args):
    """Round 116 (arXiv:2610.35981): effect-typed tools — coverage or trace safety."""
    from longrun.harness import effect_types
    if args.action == "coverage" and getattr(args, "live", False):
        # Round 119: the live catalog itself, declarations from registry.TOOL_EFFECTS.
        import longrun.tools.registry as _reg
        catalog = {}
        for row in _reg.catalog():
            catalog[row["name"]] = {"effect": row.get("effect"),
                                    "idempotent": row.get("idempotent"),
                                    "reads": row.get("reads") or [],
                                    "writes": row.get("writes") or []}
        out = effect_types.coverage(catalog)
        out["source"] = "live-catalog"
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["verdict"] in ("typed", "partial") else 1)
    if not getattr(args, "file", None):
        print("usage: effects coverage|verify FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "coverage":
        out = effect_types.coverage(doc.get("catalog") or {})
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["verdict"] == "typed" else 1)
    out = effect_types.verify_trace(doc.get("trace") or [], doc.get("catalog") or {})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["verdict"] == "safe" else 1)


def _context_cost(args):
    """Round 116 (arXiv:2611.22238): price a run, or compare two policies, in money."""
    from longrun.harness import context_cost
    path = getattr(args, "file", None) or getattr(args, "value", None)
    if not path:
        print("usage: context cost FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    prices = doc.get("prices")
    if "runs" in doc:
        out = context_cost.screen(doc.get("runs") or {}, prices, doc.get("baseline") or "baseline")
    elif "treatment" in doc:
        out = context_cost.compare(doc.get("baseline") or {}, doc["treatment"], prices,
                                   doc.get("label") or "treatment")
    else:
        out = context_cost.run_cost(doc.get("run") or doc, prices)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("verdict") not in ("more-expensive", "no-baseline") else 1)


def cmd_commit(args):
    """Round 117 (arXiv:2611.19663): repair, replan or abandon, by damage depth."""
    from longrun.plan import commitment
    if not getattr(args, "file", None):
        print("usage: commit decide|diagnose FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = commitment.worth_diagnosis(doc) if args.action == "diagnose" else commitment.decide(doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if args.action == "diagnose":
        sys.exit(0 if out["worth"] else 1)
    sys.exit(0 if out["decision"] in ("repair", "replan", "abandon") else 1)


def cmd_expectations(args):
    """Round 117 (arXiv:2611.02438): does the batch still match its expectations?"""
    from longrun.harness import expectations
    if not getattr(args, "file", None):
        print("usage: expectations verify|savings FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    steps = doc.get("steps") or []
    if args.action == "savings":
        out = expectations.savings(steps, doc.get("tokens_per_step"))
    else:
        out = expectations.verify(steps, doc.get("keys"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("action", "continue") == "continue" else 1)


def cmd_governance(args):
    """Round 117 (arXiv:2611.06682): ready, waiting or forbidden from an ontology."""
    from longrun.harness import governance
    if not getattr(args, "file", None):
        print("usage: governance decide|check FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "check":
        out = governance.check_ontology(doc.get("ontology") or {})
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["verdict"] == "consistent" else 1)
    out = governance.decide(doc.get("call") or {}, doc.get("ontology") or {}, doc.get("state") or {})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["decision"] == "ready" else 1)


def cmd_capsule(args):
    """Round 120 (arXiv:2611.10022): compile one invocation into a replayable capsule."""
    from longrun.harness import skill_cache
    if not getattr(args, "file", None):
        print("usage: capsule compile|replay|savings FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "compile":
        out = skill_cache.compile_capsule(doc.get("invocation") or doc, doc.get("skill"))
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["ok"] else 1)
    cap = doc.get("capsule") or {}
    if args.action == "savings":
        out = skill_cache.savings(cap, doc.get("tokens_per_step"), doc.get("model_tokens"))
    else:
        out = skill_cache.replay(cap, doc.get("state") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("decision") in ("reuse", None) else 1)


def cmd_flow(args):
    """Round 120 (arXiv:2611.21520): judge a relay by behaviour and policy."""
    from longrun.harness import flow_guard
    if not getattr(args, "file", None):
        print("usage: flow judge|calibrate|evaluate FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "judge":
        out = flow_guard.judge(doc.get("relay") or doc)
    elif args.action == "calibrate":
        out = flow_guard.calibrate(doc.get("scores") or [], doc.get("labels") or [],
                                   doc.get("target_fpr", 0.05))
    else:
        out = flow_guard.evaluate(doc.get("scores") or [], doc.get("labels") or [],
                                  doc.get("threshold"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("decision") in ("allow", None) else 1)


def cmd_selfdirected(args):
    """Round 120 (arXiv:2611.23219): was the improvement loop the agent's own?"""
    from longrun.harness import self_directed
    if not getattr(args, "file", None):
        print("usage: selfdirected audit|transfer FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = (self_directed.transfer(doc) if args.action == "transfer"
           else self_directed.audit(doc))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("verdict") in ("self-directed", "improved", None) else 1)


def cmd_harnessevo(args):
    """Round 121 (arXiv:2611.22299): attribute a failure and gate a harness edit."""
    from longrun.harness import harness_evolution
    if not getattr(args, "file", None):
        print("usage: harnessevo diagnose|admit|bloat FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "diagnose":
        out = harness_evolution.diagnose(doc)
    elif args.action == "bloat":
        out = harness_evolution.bloat(doc.get("rules") or doc)
    else:
        out = harness_evolution.admit(doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("attribution") in ("harness", None)
             and out.get("decision") in ("merge", "route", "keep", None) else 1)


def cmd_contextpipeline(args):
    """Round 121 (arXiv:2610.36114): measure what a tool result loses before delivery."""
    from longrun.harness import context_pipeline
    if not getattr(args, "file", None):
        print("usage: contextpipeline boundaries | deliver|profile FILE.json", file=sys.stderr)
        sys.exit(2)
    if args.action == "boundaries":
        print(json.dumps(context_pipeline.boundaries(), indent=2, ensure_ascii=False))
        sys.exit(0)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "deliver":
        out = context_pipeline.deliver(doc.get("payload") or doc,
                                       doc.get("budget", 0), doc.get("mode", "prefix"))
    else:
        out = context_pipeline.profile(doc.get("runs") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("ok", True) else 1)


def cmd_stepzero(args):
    """Round 121 (arXiv:2611.01953): gate the first processing of an opaque carrier."""
    from longrun.harness import step_zero
    if not getattr(args, "file", None):
        print("usage: stepzero peek|extract|bind FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    budget = doc.get("budget", step_zero.DEFAULT_BUDGET)
    if args.action == "peek":
        out = step_zero.peek(doc.get("members") or doc, budget)
    elif args.action == "extract":
        out = step_zero.extract(doc.get("members") or doc, budget,
                                doc.get("protect"), bool(doc.get("allow_overwrite")))
    else:
        out = step_zero.bind_write(doc.get("declared_name"), doc.get("body_sha"),
                                   doc.get("declared_sha"), doc.get("protect"),
                                   bool(doc.get("allow_overwrite")))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("decision") in ("safe", "commit", "write", None) else 1)


def cmd_harnessrecord(args):
    """Round 122 (arXiv:2610.40917): is the harness that ran described, and did it stay in envelope?"""
    from longrun.harness import harness_record
    if not getattr(args, "file", None):
        print("usage: harnessrecord audit|degradation|drift FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "audit":
        out = harness_record.audit(doc)
    elif args.action == "degradation":
        out = harness_record.degradation(doc.get("changes") or doc,
                                         doc.get("declared") or {})
    else:
        out = harness_record.drift(doc.get("declared") or {},
                                  doc.get("observed") or {})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("ok") is not False and out.get("decision") != "block" else 1)


def cmd_conduct(args):
    """Round 122 (arXiv:2611.06116): score the action log, then compare it with the message."""
    from longrun.harness import conduct_audit
    if not getattr(args, "file", None):
        print("usage: conduct score|stated|matrix FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "score":
        out = conduct_audit.score(doc.get("episode") or doc)
    elif args.action == "stated":
        out = conduct_audit.stated(doc.get("episode") or doc)
    else:
        out = conduct_audit.matrix(doc.get("rows") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("outcome") in ("correct", None) and out.get("agrees") is not False else 1)


def cmd_completion(args):
    """Round 122 (arXiv:2611.21407): an exit status is not a deliverable."""
    from longrun.harness import completion_gate
    if not getattr(args, "file", None):
        print("usage: completion check|ladder FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = (completion_gate.ladder(doc.get("rows") or doc) if args.action == "ladder"
           else completion_gate.check(doc.get("run") or doc))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("complete") is not False else 1)


def cmd_skillret(args):
    """Round 123 (arXiv:2611.01115): retrieval calibrated by matched execution comparisons."""
    from longrun.harness import skill_retrieval
    if not getattr(args, "file", None):
        print("usage: skillret calibrate|rank|apply FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "calibrate":
        out = skill_retrieval.calibrate(doc.get("pairs") or doc)
    elif args.action == "rank":
        out = skill_retrieval.rank(doc.get("candidates") or doc,
                                   doc.get("learned") or {})
    else:
        out = skill_retrieval.apply(doc.get("learned") or {}, doc.get("skill"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("write") is not False else 1)


def cmd_ruleret(args):
    """Round 123 (arXiv:2611.01042): closure-based rule retrieval under a context budget."""
    from longrun.harness import rule_retrieval
    if not getattr(args, "file", None):
        print("usage: ruleret closure|audit FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "closure":
        out = rule_retrieval.closure(doc.get("rules") or [], doc.get("seeds") or [],
                                     doc.get("budget"))
    else:
        out = rule_retrieval.audit(doc.get("selection") or [], doc.get("rules") or [],
                                   doc.get("seeds") or [], doc.get("budget"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("ok") is not False and out.get("decision") != "refuse" else 1)


def cmd_skillquality(args):
    """Round 123 (arXiv:2610.38147): nine-dimension skill profile, execution-free estimate."""
    from longrun.harness import skill_quality
    if not getattr(args, "file", None):
        print("usage: skillquality profile|predict FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "profile":
        out = skill_quality.profile(doc.get("skill") or doc)
    else:
        out = skill_quality.predict(doc.get("skill") or {}, doc.get("references") or [],
                                    doc.get("k", 3))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("verdict") in ("complete", "partial", None) else 1)


def cmd_opspolicy(args):
    """Round 124 (arXiv:2611.15006): harness as an operational policy, per-model affinity."""
    from longrun.harness import operational_policy
    if not getattr(args, "file", None):
        print("usage: opspolicy realize|ground|affinity|route FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "realize":
        out = operational_policy.realize(doc.get("output") or doc, doc.get("tools") or [],
                                         doc.get("guidance"))
    elif args.action == "ground":
        out = operational_policy.ground(doc.get("claim") or {}, doc.get("observations") or [],
                                        doc.get("required") or ())
    elif args.action == "affinity":
        out = operational_policy.affinity(doc.get("rows") or [], doc.get("baseline", "default"))
    else:
        out = operational_policy.route(doc.get("models") or [],
                                       doc.get("learned") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    blocked = out.get("decision") == "diagnose" or out.get("supported") is False
    sys.exit(1 if blocked else 0)


def cmd_execpolicy(args):
    """Round 124 (arXiv:2611.21688): reversal, frozen-panel replacement, amortization."""
    from longrun.harness import execution_policy
    if not getattr(args, "file", None):
        print("usage: execpolicy reversal|confirm|efficiency|amortize FILE.json",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "reversal":
        out = execution_policy.reversal(doc.get("declared") or {}, doc.get("measured") or {})
    elif args.action == "confirm":
        out = execution_policy.confirm(doc.get("panel") or [], doc.get("candidate"),
                                       doc.get("margin", 0.005))
    elif args.action == "efficiency":
        out = execution_policy.efficiency(doc.get("rows") or [])
    else:
        out = execution_policy.amortize(doc.get("acquisition_s"), doc.get("gain_per_task_s"),
                                        doc.get("tasks"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("decision") == "retain" else 0)


def cmd_skilladapter(args):
    """Round 124 (arXiv:2611.17007): adapter binding, preload re-check, evidence expiry."""
    from longrun.harness import skill_adapter
    if not getattr(args, "file", None):
        print("usage: skilladapter bind|recheck|expire|maintain FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "bind":
        out = skill_adapter.bind(doc.get("skill") or {}, doc.get("adapters") or [],
                                 doc.get("context") or {})
    elif args.action == "recheck":
        out = skill_adapter.recheck(doc.get("preloaded") or [], doc.get("inputs") or {})
    elif args.action == "expire":
        out = skill_adapter.expire(doc.get("adapters") or [], doc.get("today"),
                                   doc.get("ttl_days", 30))
    else:
        out = skill_adapter.maintain(doc.get("entries") or [], doc.get("events") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if args.action == "bind" and not out.get("changes") else 0)


def cmd_intake(args):
    """Round 124 (transcript OrcsMi2-IcM): deterministic gate, mandate, shadow-first work."""
    from longrun.harness import intake_gate
    if not getattr(args, "file", None):
        print("usage: intake admit|mandate|subscribe|preset|shadow FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "admit":
        out = intake_gate.admit(doc.get("trigger") or {}, doc.get("policy") or {})
    elif args.action == "mandate":
        out = intake_gate.mandate(doc.get("ticket") or {}, doc.get("today"))
    elif args.action == "subscribe":
        out = intake_gate.subscribe(doc.get("events") or [], doc.get("owned") or {})
    elif args.action == "preset":
        out = intake_gate.preset(doc.get("base") or {}, doc.get("strip") or [],
                                 doc.get("background_shell_s", 5))
    else:
        out = intake_gate.shadow(doc.get("actions") or [], doc.get("confirmed", False))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("decision") == "ignore" or out.get("valid") is False else 0)


def cmd_memcredit(args):
    """Round 125 (arXiv:2611.15600): memory arbitrated by decision utility, not relevance."""
    from longrun.harness import memory_credit
    if not getattr(args, "file", None):
        print("usage: memcredit credit|arbitrate|sparsity FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "credit":
        out = memory_credit.credit(doc.get("candidate") or {}, doc.get("reference") or [])
    elif args.action == "arbitrate":
        out = memory_credit.arbitrate(doc.get("candidates") or [], doc.get("budget"),
                                      doc.get("min_credit", 0.0))
    else:
        out = memory_credit.sparsity(doc.get("rows") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("findings") and args.action == "arbitrate"
             and not out.get("selected") else 0)


def cmd_lessongate(args):
    """Round 125 (arXiv:2611.14326): a lesson is committed only after its probes pass."""
    from longrun.harness import lesson_gate
    if not getattr(args, "file", None):
        print("usage: lessongate hypothesis|trial|probe FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "hypothesis":
        out = lesson_gate.hypothesis(doc.get("lesson") or doc)
    elif args.action == "trial":
        out = lesson_gate.trial(doc.get("lesson") or {}, doc.get("state"),
                                doc.get("persist", False))
    else:
        out = lesson_gate.probe(doc.get("lesson") or {}, doc.get("results") or {})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("decision") in ("commit", None) and out.get("applied") is not False
             and out.get("valid") is not False else 1)


def cmd_seclattice(args):
    """Round 125 (arXiv:2611.13960): product taint lattice, attenuation, provenance ledger."""
    from longrun.harness import security_lattice
    if not getattr(args, "file", None):
        print("usage: seclattice admit|attenuate|write|read|effect FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "admit":
        out = security_lattice.admit(doc.get("label") or {}, doc.get("action"))
    elif args.action == "attenuate":
        out = security_lattice.attenuate(doc.get("parent") or {}, doc.get("child") or {})
    elif args.action == "write":
        out = security_lattice.ledger_write(doc.get("ledger") or {}, doc.get("path"),
                                            doc.get("actor") or {})
    elif args.action == "read":
        out = security_lattice.ledger_read(doc.get("ledger") or {}, doc.get("path"),
                                           doc.get("actor") or {})
    else:
        out = security_lattice.admit_effect(doc.get("actor") or {}, doc.get("effect"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("allowed") is False or out.get("valid") is False
             or out.get("found") is False else 0)


def cmd_optmemory(args):
    """Round 126 (arXiv:2611.18856): the optimizer's memory of why a harness was edited."""
    from longrun.harness import optimizer_memory
    if not getattr(args, "file", None):
        print("usage: optmemory record|continuity|advantage FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "record":
        out = optimizer_memory.record(doc.get("memory") or {}, doc.get("edit") or {})
    elif args.action == "continuity":
        out = optimizer_memory.continuity(doc.get("memory") or {},
                                          doc.get("target") or {})
    else:
        out = optimizer_memory.advantage(doc.get("pairs") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    blocked = any(f["kind"] in ("no-root-cause", "not-significant", "no-pairs")
                  for f in (out.get("findings") or []))
    sys.exit(1 if blocked else 0)


def cmd_detour(args):
    """Round 126 (arXiv:2611.20844): success, attainment, residual work, detour."""
    from longrun.harness import detour
    if not getattr(args, "file", None):
        print("usage: detour attainment|residual|progress|classify|rank FILE.json",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "attainment":
        out = detour.attainment(doc.get("success"), doc.get("charged"), doc.get("optimum"))
    elif args.action == "residual":
        out = detour.residual(doc.get("success"), doc.get("wrong"), doc.get("remaining"))
    elif args.action == "progress":
        out = detour.progress(doc.get("success"), doc.get("residual"),
                              doc.get("optimum"), doc.get("charged"))
    elif args.action == "classify":
        out = detour.classify(doc.get("episodes") or doc)
    else:
        out = detour.rank_models(doc.get("episodes") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if any(f["kind"] in ("below-optimum", "no-optimum")
                      for f in (out.get("findings") or [])) else 0)


def cmd_patchprobe(args):
    """Round 126 (arXiv:2611.20514): control-gated verdicts, sibling paths, provenance."""
    from longrun.harness import patch_probe
    if not getattr(args, "file", None):
        print("usage: patchprobe verdict|compare|provenance|validate FILE.json",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "verdict":
        out = patch_probe.verdict(doc.get("control_ok"), doc.get("effect_seen"),
                                  doc.get("token_ok", True))
    elif args.action == "compare":
        out = patch_probe.compare(doc.get("b0") or {}, doc.get("sibling") or {})
    elif args.action == "provenance":
        out = patch_probe.provenance(doc.get("runs") or [], doc.get("advisory") or {})
    else:
        out = patch_probe.validate(doc.get("runs") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("valid") is not False and out.get("verdict") != "INCONCLUSIVE"
             else 1)


def cmd_poison(args):
    """Round 127 (arXiv:2611.09721): a payload's lifecycle through agent memory."""
    from longrun.harness import memory_poison
    if not getattr(args, "file", None):
        print("usage: poison trace|descendants FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "trace":
        out = memory_poison.trace(doc.get("run") or doc)
    else:
        out = memory_poison.descendants(doc.get("store") or {}, doc.get("poisoned") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("isr") == 0 or out.get("br") == 0 else 0)


def cmd_boundary(args):
    """Round 127 (arXiv:2611.21259): identity, authorization and propagation at a seam."""
    from longrun.harness import trust_boundary
    if not getattr(args, "file", None):
        print("usage: boundary evaluate|classify FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "evaluate":
        out = trust_boundary.evaluate(doc.get("call") or doc)
    else:
        out = trust_boundary.classify(doc.get("outcome") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("decision") == "deny" else 0)


def cmd_gapleak(args):
    """Round 127 (arXiv:2611.22223): information gap, disclosure, submission-time filter."""
    from longrun.harness import gap_leak
    if not getattr(args, "file", None):
        print("usage: gapleak gap|disclosure|verify|compare FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "gap":
        out = gap_leak.gap(doc.get("requested") or [], doc.get("authorized") or [],
                           doc.get("reachable") or [])
    elif args.action == "disclosure":
        out = gap_leak.disclosure(doc.get("form") or {}, doc.get("policy") or [],
                                  doc.get("third_party") or [])
    elif args.action == "verify":
        out = gap_leak.verify(doc.get("form") or {}, doc.get("summary") or {},
                              doc.get("required") or [])
    else:
        out = gap_leak.compare(doc.get("before") or {}, doc.get("after") or {})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out.get("preserved_required") is False else 0)


def cmd_binding(args):
    """Round 128 (arXiv:2611.21577): a tool advertisement is not a provider identity."""
    from longrun.harness import provider_binding
    if not getattr(args, "file", None):
        print("usage: binding alignment|pressure|bind|resolve|outcomes|judge|sweep FILE.json",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action in ("alignment", "pressure"):
        out = getattr(provider_binding, args.action)(doc.get("advert") or {},
                                                     doc.get("reference") or {})
    elif args.action == "bind":
        out = provider_binding.bind(doc.get("advert") or doc, doc.get("expected_provider"))
    elif args.action == "resolve":
        out = provider_binding.resolve(doc.get("candidates") or [], doc.get("reference"),
                                       doc.get("authorized_provider"))
    elif args.action in ("outcomes", "judge"):
        out = getattr(provider_binding, args.action)(doc.get("trials") or [])
    else:
        out = provider_binding.sweep(doc.get("rows") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if (args.action == "bind" and not out.get("provider_bound"))
             or (args.action == "resolve" and out.get("decision") != "bound") else 0)


def cmd_gateway(args):
    """Round 128 (arXiv:2611.19123): code mode, stubs, router and fallback accounting."""
    from longrun.harness import gateway_shape
    if not getattr(args, "file", None):
        print("usage: gateway utility|delta|holm|claim|stub|hints|fallback|advise FILE.json",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "utility":
        out = gateway_shape.utility(doc.get("cell") or doc)
    elif args.action == "delta":
        out = gateway_shape.paired_delta(doc.get("base") or [], doc.get("candidate") or [],
                                         resamples=doc.get("resamples") or 2000)
    elif args.action == "holm":
        out = gateway_shape.holm(doc.get("pvalues") or [])
    elif args.action == "claim":
        out = gateway_shape.claim(doc.get("delta"), doc.get("ci") or [0.0, 0.0],
                                  doc.get("p_adjusted"))
    elif args.action == "stub":
        out = gateway_shape.stub(doc.get("tool") or doc)
    elif args.action == "hints":
        out = gateway_shape.hint_effect(doc.get("hinted") or {}, doc.get("bare") or {})
    elif args.action == "fallback":
        out = gateway_shape.compare_fallbacks(doc.get("unbounded") or {},
                                             doc.get("bounded") or {})
    else:
        out = gateway_shape.advise(doc.get("profile") or doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0)


def cmd_scoring(args):
    """Round 128 (arXiv:2611.20335): pointwise, setwise or candidate attention."""
    from longrun.harness import scoring_mode
    if not getattr(args, "file", None):
        print("usage: scoring depends|reversal|select|paired|advise|binary|learn FILE.json",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "depends":
        out = scoring_mode.depends_on_candidates(doc.get("mode"))
    elif args.action == "reversal":
        out = scoring_mode.reversal(doc.get("pair") or doc)
    elif args.action == "select":
        out = scoring_mode.select(doc.get("mode"), doc.get("scores") or {})
    elif args.action == "paired":
        out = scoring_mode.paired_success(doc.get("instances") or [])
    elif args.action == "advise":
        out = scoring_mode.advise(doc.get("task"), doc.get("candidates") or 16)
    elif args.action == "binary":
        out = scoring_mode.binary_diagnostic(doc.get("gold_yes_rate"),
                                             doc.get("predicted_yes"))
    else:
        out = scoring_mode.learnability(doc.get("mode"), doc.get("relational_share"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0)


def cmd_instructions(args):
    """Round 114 (arXiv:2611.13709): explicit context-file directives vs the cards."""
    from longrun.harness import instruction_audit
    if not getattr(args, "file", None):
        print("usage: instructions audit FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = instruction_audit.audit(doc.get("text") or "", doc.get("cards") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["verdict"] == "clean" else 1)


def cmd_teams(args):
    """Round 113 (arXiv:2611.17820): the safety lead + published safety specs audit."""
    from longrun.harness import team_safety
    if not getattr(args, "file", None):
        print("usage: teams audit FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = team_safety.audit(doc)
    out["brief"] = team_safety.brief(doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["verdict"] == "covered" else 1)


def cmd_toolgraph(args):
    """Round 113 (arXiv:2611.20569): compile the tool dependency graph, or ask it."""
    from longrun.harness import tool_graph
    if not getattr(args, "file", None):
        print("usage: toolgraph %s FILE.json" % args.action, file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    graph = tool_graph.build(doc.get("catalog") or [], doc.get("transitions") or [],
                             doc.get("probes") or [])
    if args.action == "build":
        print(json.dumps({k: v for k, v in graph.items() if k != "nodes"}, indent=2,
                         ensure_ascii=False))
        return
    print(json.dumps(tool_graph.feedback(graph, doc.get("goal") or "",
                                         doc.get("candidate") or "",
                                         doc.get("state_types") or []),
                     indent=2, ensure_ascii=False))


def cmd_subagent(args):
    if args.action == "spawn":
        body = {"goal": args.value}
        if args.max_steps:
            body["max_steps"] = args.max_steps   # omitted -> config/subagents.yaml
        out = req("POST", "/api/subagent/spawn", body)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "collect":
        out = req("POST", "/api/subagent/collect", {"id": args.value, "timeout": 120})
        print(json.dumps({k: v for k, v in out.items() if k in ("ok", "status", "summary", "steps")}, indent=2))
    elif args.action == "status":
        url = "/api/subagent"
        if args.value:
            url += "?id=" + _q(args.value)
        print(json.dumps(req("GET", url), indent=2))


def cmd_meta(args):
    if args.action == "run":
        out = req("POST", "/api/meta", {"action": "run", "n_candidates": args.n_candidates})
        print("Candidates: %d" % len(out.get("results", [])))
        print("Frontier: %d" % len(out.get("frontier", [])))
        for r in out.get("frontier", []):
            print(" %s quality=%.3f cost=%d tok" % (r.get("label"), r.get("quality"), r.get("cost_tokens")))
        print("\nsaved to:", out.get("saved_to"))
    elif args.action == "status":
        print(json.dumps(req("GET", "/api/meta"), indent=2))
    elif args.action == "best":
        print(json.dumps(req("GET", "/api/meta?action=best"), indent=2))


def cmd_blackboard(args):
    if args.action == "post":
        out = req("POST", "/api/blackboard", {"topic": args.value, "content": args.value2,
                                                 "tags": [t.strip() for t in (args.tags or "").split(",") if t]})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "get":
        url = "/api/blackboard?limit=%d" % args.limit
        if args.id:
            url += "&id=" + _q(args.id)
        if args.topic:
            url += "&topic=" + _q(args.topic)
        out = req("GET", url)
        entries = out.get("entries", out.get("thread", [out]))
        for e in (entries if isinstance(entries, list) else [entries]):
            if isinstance(e, dict) and e.get("content"):
                print(" [%s] %s (%s) content: %s" % (e.get("topic"), e.get("id"), e.get("tags", ""), e["content"][:150]))
    elif args.action == "search":
        out = req("GET", "/api/blackboard?query=%s&limit=%d" % (_q(args.value), args.limit))
        for e in out.get("entries", []):
            print(" [%s] %s" % (e.get("topic"), e.get("content", "")[:120]))
    elif args.action == "stats":
        out = req("GET", "/api/blackboard")
        print(json.dumps(out.get("stats", {}), indent=2))
    elif args.action == "watch":
        print("watching blackboard (Ctrl-C to stop)…")
        for ev, payload in sse("/api/blackboard/watch"):
            print("%-14s %s" % (ev, (payload or "")[:160]))


def cmd_acp(args):
    if args.action == "server":
        try:
            params = json.loads(args.value2) if args.value2 else {}
        except json.JSONDecodeError:
            params = {}
        out = req("POST", "/api/acp", {"jsonrpc": "2.0", "id": "cli",
                                         "method": args.value, "params": params})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "connect":
        out = req("POST", "/api/acp/connect", {"name": args.value, "url": args.value2, "token": args.token})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "list":
        out = req("GET", "/api/mcp/clients")
        print(json.dumps(out, indent=2))


def cmd_swarm(args):
    body = {"goal": args.goal, "n_workers": args.n_workers}
    if args.max_steps:
        body["max_steps"] = args.max_steps   # omitted -> config/subagents.yaml
    out = req("POST", "/api/swarm/run", body)
    print("Goal id: %s" % out.get("goal_id"))
    print("Subgoal ids: %s" % out.get("subgoal_ids"))
    print("Synthesis id: %s" % out.get("synthesis_id"))
    print("Worker count: %d" % out.get("worker_count", 0))
    for s in out.get("summaries", []):
        print(" - %s" % s[:160])


def cmd_mcp(args):
    """MCP: tools/list over JSON-RPC AND client management (mirrors the WebUI)."""
    action = getattr(args, "action", None) or "tools"
    if action == "tools":
        init = req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {"protocolVersion": "2025-06-18"}})
        print("server:", json.dumps(init.get("result", {}).get("serverInfo", {})))
        tl = req("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        for t in tl.get("result", {}).get("tools", []):
            print(" -", t["name"], "::", t["description"][:70])
        return
    if action == "ls":
        print(json.dumps(req("GET", "/api/mcp/clients"), indent=2, ensure_ascii=False))
        return
    if action == "add":
        # value = a preset name; value2 = a raw JSON spec (command/args or url)
        if getattr(args, "json", None):
            try:
                body = json.loads(args.json)
            except json.JSONDecodeError as e:
                print("bad json:", e, file=sys.stderr); sys.exit(2)
            print(json.dumps(req("POST", "/api/mcp/clients", body), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(req("POST", "/api/mcp/clients", {"preset": args.value}),
                             indent=2, ensure_ascii=False))
        return
    if action == "remove":
        print(json.dumps(req("POST", "/api/mcp/clients/remove", {"name": args.value}),
                         indent=2, ensure_ascii=False))
        return
    if action == "reload":
        print(json.dumps(req("POST", "/api/mcp/reload", {}), indent=2, ensure_ascii=False))
        return
    if action == "local-file":
        print(json.dumps(req("POST", "/api/mcp/local-file", {"path": args.value}),
                         indent=2, ensure_ascii=False))
        return
    print("unknown mcp action", file=sys.stderr); sys.exit(2)


def cmd_market(args):
    """Marketplace: the catalogue, the sync job, live search and one-row import.

    A thin mirror of the Marketplace page: the catalogue is data, an import writes
    a catalogue file (nothing installs by itself), and a full registry pass is ONE
    background job — `market sync --wait` is how a terminal follows it.
    """
    action = getattr(args, "action", None) or "ls"

    def _age(src):
        sec = src.get("age_seconds")
        if sec is None:
            return "never synced"
        text = "synced %ds ago" % int(sec) if sec < 3600 else "synced %dh ago" % (sec // 3600)
        return text + (" (stale)" if src.get("stale") else "")

    if action == "ls":
        qs = ["limit=%d" % int(args.limit or 20), "offset=%d" % int(args.offset or 0)]
        if args.kind:
            qs.append("kind=" + _q(args.kind))
        if args.category:
            qs.append("category=" + _q(args.category))
        if args.source:
            qs.append("source=" + _q(args.source))
        if args.value:
            qs.append("q=" + _q(args.value))
        out = req("GET", "/api/market/catalog?" + "&".join(qs))
        items = out.get("items") or []
        for it in items:
            print("%-40s %-9s %-18s %-14s %s"
                  % (str(it.get("id"))[:40], it.get("kind"),
                     str(it.get("category") or "")[:18],
                     str(it.get("origin_label") or "")[:14],
                     str(it.get("title") or "")[:44]))
        stats = out.get("stats") or {}
        print('matched %s \u00b7 showing %d \u00b7 by kind %s'
              % (stats.get("matched"), len(items), json.dumps(stats.get("by_kind") or {})))
        for err in (out.get("errors") or [])[:5]:
            print("  !", err)
        return
    if action == "sources":
        out = req("GET", "/api/market/sources")
        for s in out.get("sources") or []:
            print("%-14s %6s items  %-26s %s"
                  % (s.get("id"), s.get("items"), _age(s), s.get("cost") or ""))
        print("allow_hosts:", ", ".join(out.get("allow_hosts") or []))
        print("job:", json.dumps(out.get("job") or {}))
        return
    if action == "status":
        print(json.dumps(req("GET", "/api/market/sync/status").get("job") or {}, indent=2))
        return
    if action == "installed":
        out = req("GET", "/api/market/installed")
        for r in out.get("installed") or []:
            print("%-40s %-9s %-14s %-10s %s"
                  % (str(r.get("id"))[:40], r.get("kind"),
                     str(r.get("origin_label") or "")[:14],
                     str(r.get("installed") or "")[:10], r.get("target") or ""))
        print("installed:", out.get("count"))
        return
    if action == "sync":
        source = args.source or "mcp-registry"
        body = {"source": source}
        if args.limit:
            body["limit"] = int(args.limit)
        res = req("POST", "/api/market/sync", body)
        if not res.get("ok"):
            print(json.dumps(res, indent=2))
            return
        print("started:", json.dumps(res.get("job") or {}))
        if not args.wait:
            print("poll with: python3 forge.py market status")
            return
        job = res.get("job") or {}
        while job.get("running"):
            time.sleep(3)
            job = req("GET", "/api/market/sync/status").get("job") or {}
            print("pages=%s rows=%s items=%s skipped=%s"
                  % (job.get("pages"), job.get("rows_seen"), job.get("items"),
                     job.get("skipped")), flush=True)
        print("done:", json.dumps({k: job.get(k) for k in
                                   ("items", "skipped", "capped", "error", "path")}))
        return
    if action == "remote":
        if not args.value:
            print("usage: forge.py market remote <query> [--source clawhub]", file=sys.stderr)
            sys.exit(2)
        out = req("GET", "/api/market/remote?source=" + _q(args.source or "clawhub")
                  + "&q=" + _q(args.value) + "&limit=%d" % int(args.limit or 20))
        if not out.get("ok"):
            print(json.dumps(out, indent=2))
            return
        for it in out.get("items") or []:
            print("%-28s %-18s %s" % (str(it.get("name"))[:28],
                                      str(it.get("category") or "")[:18],
                                      str(it.get("title") or "")[:48]))
        print("online %d \u00b7 import with: python3 forge.py market import %s <slug>"
              % (len(out.get("items") or []), out.get("source")))
        return
    if action == "import":
        if not (args.value and args.value2):
            print("usage: forge.py market import <source> <slug>", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(req("POST", "/api/market/import-remote",
                             {"source": args.value, "slug": args.value2}),
                         indent=2, ensure_ascii=False))
        return
    if action == "install":
        if not args.value:
            print("usage: forge.py market install <id> [--overwrite]", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(req("POST", "/api/market/install",
                             {"id": args.value, "overwrite": bool(args.overwrite)}),
                         indent=2, ensure_ascii=False))
        return
    if action == "plugin-scan":
        out = req("GET", "/api/market/plugin-scan")
        for p in out.get("packages") or []:
            ok = "ok  " if not p.get("error") else "no  "
            members = ",".join("%s:%s" % (m.get("kind"), m.get("name"))
                               for m in (p.get("members") or []))
            print("%s %-9s %-22s %-40s %s" % (ok, p.get("format"), str(p.get("name") or "-")[:22],
                                              members[:40] or str(p.get("error") or "")[:40],
                                              p.get("path")))
        print("found %s \u00b7 convertible %s \u00b7 roots %s"
              % ((out.get("counts") or {}).get("found"),
                 (out.get("counts") or {}).get("convertible"),
                 ", ".join(out.get("roots") or [])))
        return
    if action == "plugin-add":
        if not args.value:
            print("usage: forge.py market plugin-add <path|https-url>", file=sys.stderr)
            sys.exit(2)
        key = "url" if str(args.value).startswith("https://") else "path"
        print(json.dumps(req("POST", "/api/market/plugin-import",
                             {key: args.value, "overwrite": bool(args.overwrite)}),
                         indent=2, ensure_ascii=False))
        return
    if action == "rm":
        if not args.value:
            print("usage: forge.py market rm <id> [--files]", file=sys.stderr)
            sys.exit(2)
        path = "/api/market/installed/" + _q(args.value)
        if args.files:
            path += "?files=1"
        print(json.dumps(req("DELETE", path), indent=2, ensure_ascii=False))
        return
    print("unknown market action", file=sys.stderr)
    sys.exit(2)


def cmd_models(args):
    if getattr(args, "action", None) == "ensure":
        print(json.dumps(req("POST", "/api/model/ensure", {"model": args.value}),
                         indent=2, ensure_ascii=False))
        return
    out = req("GET", "/api/models")
    # JAG-241: `/api/models` returns {providers:[...], router_models:[...]} — there
    # is NO top-level "models" key, so the old `out.get("models")` printed NOTHING
    # even with the router full. List the local router roster + the providers.
    rm = out.get("router_models") or []
    if rm:
        print("local router models:")
        for m in rm:
            ctx = ("%sk ctx" % (int(m.get("n_ctx")) // 1024)) if m.get("n_ctx") else ""
            print("  %-52s %-9s %s" % (m.get("alias") or m.get("id"),
                                       "LOADED" if m.get("loaded") else (m.get("status") or ""),
                                       ctx))
    provs = out.get("providers") or []
    if provs:
        print("providers:")
        for p in provs:
            print("  [%s] %s avail=%s" % (p.get("id"), p.get("name"), p.get("available")))
            for mm in p.get("models") or []:
                cl = mm.get("context_length")
                tag = "loaded" if mm.get("loaded") else (("%sk" % (int(cl) // 1024)) if cl else "")
                print("     %-56s %s" % (mm.get("ref"), tag))
    if not rm and not provs:
        print(json.dumps(out, indent=2, ensure_ascii=False)[:2000])


def cmd_index(args):
    """Codebase index (JAG-400): status / build / search — the workspace's code/docs."""
    action = getattr(args, "action", "status") or "status"
    if action == "build":
        print(json.dumps(req("POST", "/api/codebase/build",
                             {"force": bool(getattr(args, "force", False))}),
                         indent=2, ensure_ascii=False))
        return
    if action == "search":
        out = req("GET", "/api/codebase/search?k=%d&q=%s" % (args.limit, _q(args.value or "")))
        for r in out.get("results", []):
            print("%s:%s  [%s]  %s" % (r.get("path"), r.get("start"), out.get("mode"),
                                       (r.get("snippet") or "").replace("\n", " ")[:160]))
        if not out.get("results"):
            print("(no matches)")
        return
    print(json.dumps(req("GET", "/api/codebase/status"), indent=2, ensure_ascii=False))


def cmd_knowledge(args):
    """Knowledge base (JAG-401): GLOBAL notebooks — status/notebooks/add/search/discover/import."""
    action = getattr(args, "action", "status") or "status"
    nb = getattr(args, "notebook", None)
    if action == "notebooks":
        out = req("GET", "/api/knowledge/notebooks")
        for n in out.get("notebooks", []):
            print("%-14s %-24s (%s sources)" % (n.get("id"), n.get("name"), n.get("sources")))
        return
    if action == "create":
        print(json.dumps(req("POST", "/api/knowledge/notebooks",
                             {"action": "create", "name": args.value or ""}),
                         indent=2, ensure_ascii=False))
        return
    if action == "add":
        body = {"notebook": nb, "refs": args.value or ""}
        print(json.dumps(req("POST", "/api/knowledge/sources", body), indent=2, ensure_ascii=False))
        return
    if action == "search":
        qs = "/api/knowledge/search?k=%d&q=%s" % (args.limit, _q(args.value or ""))
        if nb:
            qs += "&notebook=" + _q(nb)
        out = req("GET", qs)
        for r in out.get("results", []):
            print("%s:%s  [%s]  %s" % (r.get("ref") or r.get("path"), r.get("start"),
                                       out.get("mode"), (r.get("snippet") or "").replace("\n", " ")[:160]))
        if not out.get("results"):
            print("(no matches)")
        return
    if action == "discover":
        out = req("POST", "/api/knowledge/discover", {"q": args.value or "", "n": args.limit})
        for c in out.get("candidates", []):
            print("%s\n  %s" % (c.get("title"), c.get("url")))
        if not out.get("candidates"):
            print("(no results)")
        return
    if action == "import":
        urls = [u.strip() for u in (args.value or "").replace(",", "\n").splitlines() if u.strip()]
        print(json.dumps(req("POST", "/api/knowledge/import", {"notebook": nb, "urls": urls}),
                         indent=2, ensure_ascii=False))
        return
    if action == "research":
        body = {"q": args.value or "", "notebook": nb or "default",
                "depth": args.depth or "shallow", "n": args.limit,
                "max_rounds": args.max_rounds}
        print(json.dumps(req("POST", "/api/knowledge/research", body),
                         indent=2, ensure_ascii=False))
        return
    print(json.dumps(req("GET", "/api/knowledge/status"), indent=2, ensure_ascii=False))


def cmd_research(args):
    """Research model selection (JAG-403b). `set` / `ls` / `active`."""
    action = getattr(args, "action", "active") or "active"
    if action == "ls":
        out = req("GET", "/api/research/model")
        for m in out.get("models", []):
            print("  %-50s %-12s %s" % (m.get("id"), m.get("provider", ""), m.get("label", "")))
        print("\nactive: %s" % (out.get("active") or "(none)"))
        return
    if action == "set":
        print(json.dumps(req("POST", "/api/research/model", {"model": args.value or ""}),
                         indent=2, ensure_ascii=False))
        return
    print(json.dumps(req("GET", "/api/research/model"), indent=2, ensure_ascii=False))


def cmd_embedding(args):
    """Embedding models + cost log (JAG-403): models/active/costs/cost-test."""
    action = getattr(args, "action", "active") or "active"
    if action == "models":
        out = req("GET", "/api/embedding/models")
        for m in out.get("models", []):
            local = " (local, free)" if (m.get("price_per_mtok") or 0) == 0 else (
                " $%s/1Mt" % m.get("price_per_mtok"))
            print("%-48s %-6d dim  %-12s%s  %s" % (
                m.get("id"), m.get("dim", 0), m.get("provider", ""), local,
                m.get("label", "")))
        print("\nactive: %s" % (out.get("active") or "(none — lexical only)"))
        return
    if action == "active":
        out = req("GET", "/api/embedding/active")
        print("active: %s" % (out.get("active") or "(none — lexical only)"))
        return
    if action == "set":
        print(json.dumps(req("POST", "/api/embedding/active",
                             {"model": args.value or ""}),
                         indent=2, ensure_ascii=False))
        return
    if action == "add":
        try:
            spec = json.loads(args.value) if args.value else {}
        except json.JSONDecodeError as e:
            print("bad json model spec:", e, file=sys.stderr)
            sys.exit(2)
        print(json.dumps(req("POST", "/api/embedding/models", {"add": spec}),
                         indent=2, ensure_ascii=False))
        return
    if action == "remove":
        print(json.dumps(req("POST", "/api/embedding/models", {"remove": args.value or ""}),
                         indent=2, ensure_ascii=False))
        return
    if action == "costs":
        out = req("GET", "/api/embedding/costs")
        print("total cost so far: $%.6f   total tokens: %d" % (
            out.get("total_cost_usd", 0.0), out.get("total_tokens", 0)))
        print("by model:")
        for m in out.get("by_model", []):
            real = "  (real: $%.6f from OR)" % m["real_cost_usd"] if m.get("real_n") else ""
            print("  %-44s  $%0.6f   %d tokens%s" % (
                m["model"], m["total_cost_usd"], m["tokens"], real))
        if out.get("by_day"):
            print("last 30 days:")
            for d in out["by_day"]:
                print("  %s  $%0.6f  %d tokens" % (d["day"], d["cost_usd"], d["tokens"]))
        return
    if action == "cost-test":
        from longrun.model import embed as _embed
        print(json.dumps(_embed.probe(args.value or None), indent=2,
                         ensure_ascii=False))
        return
    print("(unknown action; use: models|active|set|costs|cost-test)")


def cmd_feed(_):
    try:
        for ev, payload in sse("/api/feed"):
            try:
                d = json.loads(payload) if payload and not payload.startswith("[") else {}
            except json.JSONDecodeError:
                continue
            if ev == "backlog":
                for e in d if isinstance(d, list) else []:
                    print("%3s %-18s %s" % (e.get("id"), e.get("kind"), json.dumps(
                        {k: v for k, v in e.items() if k not in ("id", "ts", "kind")})[:140]))
            elif ev != "chat.delta":
                print("%-18s %s" % (ev, json.dumps(d, ensure_ascii=False)[:160]))
    except KeyboardInterrupt:
        pass


def _print_history_full(out):
    """`sessions history --full`: the transcript and the tool cards, untruncated.

    2026-11-18 (operator: "tutto il flusso di informazioni"): the compact view cuts
    every message at 200 chars and reduces a tool card to one line, which is enough
    to find a turn and not enough to reconstruct it. This prints what the WebUI
    renders: each message in order (harness injects flagged), then every card with
    its arguments, exit code, error, result and the thought that chose it.
    """
    msgs = out.get("messages") or []
    for i, m in enumerate(msgs):
        print("\n[%03d %s%s]" % (i, m.get("role") or "?", " · internal" if m.get("internal") else ""))
        print(m.get("content") or "")
    cards = out.get("tool_cards") or []
    if cards:
        print("\n--- tool cards (%d, in the order they ran) ---" % len(cards))
        for c in cards:
            print("\n→ %s  ok=%s%s backend=%s%s" % (
                c.get("tool") or "?", c.get("ok"),
                ("  exit=%s" % c.get("exit_code")) if c.get("exit_code") not in (None, "") else "",
                c.get("backend") or "-",
                ("  node=%s" % c.get("node")) if c.get("node") else ""))
            if c.get("args"):
                print("  args:   %s" % c.get("args"))
            if c.get("error"):
                print("  error:  %s" % c.get("error"))
            if c.get("result"):
                print("  result: %s" % c.get("result"))
            if c.get("think"):
                print("  think:  %s" % c.get("think"))


def cmd_sessions(args):
    if args.action == "ls":
        out = req("GET", "/api/sessions")
        cur = _current_session()
        for s in out.get("sessions", []):
            mark = "*" if cur and s.get("id") == cur else " "
            print("%s%-24s %4s msg  %s" % (mark, s.get("id"), s.get("messages"),
                                           s.get("title") or ""))
    elif args.action == "current":
        cur = _current_session()
        print(cur or "none — run `sessions new` or `sessions use ID`")
    elif args.action == "use":
        want = str(args.value or "").strip()
        if not want:
            print("usage: sessions use ID", file=sys.stderr)
            sys.exit(2)
        hist = req("GET", "/api/history?session=" + _q(want))
        if hist.get("error"):
            print("error:", hist["error"], file=sys.stderr)
            sys.exit(1)
        _set_current_session(want)
        print("current session: %s" % want)
    elif args.action == "new":
        ws = getattr(args, "workspace", None)
        if ws:
            # The SAME route the WebUI uses when the operator names a folder
            # (`GET /api/sessions/new`); POST /api/sessions has no workspace field.
            out = req("GET", "/api/sessions/new?title=" + _q(args.value or "session")
                      + "&workspace=" + _q(ws))
        else:
            out = req("POST", "/api/sessions", {"title": args.value})
        print(json.dumps({k: out.get(k) for k in ("id", "title", "messages")},
                         indent=2, ensure_ascii=False))
        if out.get("id"):
            # A new session becomes the current one: a following bare `chat` lands
            # HERE instead of in an anonymous row (the "empty session" defect).
            _set_current_session(out["id"])
            print("current session: %s" % out["id"])
    elif args.action == "fork":
        if not str(args.value or "").strip():
            print("usage: sessions fork ID [--at N] [--title TITLE] [--model MODEL] "
                  "[--workspace DIR]", file=sys.stderr)
            sys.exit(2)
        body = {}
        if getattr(args, "at", None) is not None:
            try:
                body["at"] = int(args.at)
            except (TypeError, ValueError):
                print("--at must be an integer", file=sys.stderr)
                sys.exit(2)
        for k in ("title", "model", "workspace"):
            v = getattr(args, k, None)
            if v:
                body[k] = v
        out = req("POST", "/api/sessions/%s/fork" % args.value, body)
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        s = out.get("session") or {}
        print(json.dumps({"id": s.get("id"), "source": out.get("source"),
                          "fork_at": out.get("fork_at"),
                          "messages": out.get("messages"), "model": s.get("model"),
                          "replay": s.get("replay")},
                         indent=2, ensure_ascii=False))
        if s.get("id"):
            _set_current_session(s["id"])
            print("current session: %s" % s["id"])
    elif args.action == "rm":
        print(json.dumps(req("DELETE", "/api/sessions/" + args.value), indent=2))
        _clear_current_session(args.value)
    elif args.action == "card":
        # round 10: the compacted manifest prints `#<handle>`; this dereferences
        # one tool card of the CURRENT session (the CLI twin of sessions action=card).
        ref = _current_session()
        if not ref:
            _no_current_session()
        h = str(args.value or "").strip()
        if not h:
            print("usage: sessions card HANDLE   (the #id in the compacted manifest)",
                  file=sys.stderr)
            sys.exit(2)
        out = req("GET", "/api/history?session=%s&card=%s" % (_q(ref), _q(h)))
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        print(json.dumps(out.get("card") or {}, indent=2, ensure_ascii=False))
    elif args.action == "counterfactual":
        # HD-1: change ONE argument of a recorded read-only call, re-execute it
        # and report whether the observation moved (CausalFlow, 2605.25338).
        ref = _current_session()
        if not ref:
            _no_current_session()
        h = str(args.value or "").strip()
        if not h:
            print("usage: sessions counterfactual HANDLE --arg key=value [--arg k=v]",
                  file=sys.stderr)
            sys.exit(2)
        change = {}
        for item in (getattr(args, "arg", None) or []):
            if "=" not in item:
                print("--arg must be key=value: %r" % item, file=sys.stderr)
                sys.exit(2)
            k, v = item.split("=", 1)
            try:
                change[k] = json.loads(v)
            except ValueError:
                change[k] = v
        if not change:
            print("at least one --arg is required: the ONE fact to change",
                  file=sys.stderr)
            sys.exit(2)
        out = req("POST", "/api/sessions/%s/counterfactual" % ref,
                  {"handle": h, "change": change})
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        cmp_ = out.get("compare") or {}
        print("%s  changed=%s  fidelity=%s  (%s)"
              % (cmp_.get("verdict"), ",".join(cmp_.get("changed") or []) or "-",
                 out.get("fidelity"), out.get("caveat") or ""))
        print(json.dumps(cmp_, indent=2, ensure_ascii=False))
    elif args.action == "model-counterfactual":
        # HD-1 model branch (2026-11-18): replace the CONTENT of ONE stored message
        # and re-ask the model, so the operator obtains the verdict from the shell.
        # Nothing executes; it costs one model call on the session's own model.
        ref = _current_session()
        if not ref:
            _no_current_session()
        idx = str(args.value or "").strip()
        content = getattr(args, "content", None)
        if idx == "" or not str(content or "").strip():
            print('usage: sessions model-counterfactual INDEX --content "new text"'
                  "   (INDEX = the #N from sessions history; -1 = last message)",
                  file=sys.stderr)
            sys.exit(2)
        try:
            idx = int(idx)
        except ValueError:
            print("INDEX must be an integer (the #N of the message): %r" % idx,
                  file=sys.stderr)
            sys.exit(2)
        out = req("POST", "/api/sessions/%s/counterfactual/model" % ref,
                  {"index": idx, "change": {"content": content}})
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        cmp_ = out.get("compare") or {}
        print("%s  moved=%s  model=%s  fidelity=%s  (%s)"
              % (cmp_.get("verdict"), ",".join(cmp_.get("moved") or []) or "-",
                 out.get("model"), out.get("fidelity"), out.get("caveat") or ""))
        print(json.dumps({"original": out.get("original"),
                          "replacement": out.get("replacement"),
                          "recorded_action": out.get("recorded_action"),
                          "replayed_action": out.get("replayed_action")},
                         indent=2, ensure_ascii=False))
    elif args.action == "stopping":
        # Round 109 (arXiv:2611.22901): done-but-working, measured from the cards.
        ref = _chat_ref(args.value)
        out = req("GET", "/api/sessions/%s/stopping" % ref)
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        print("verdict: %s" % out.get("verdict"))
        print("first pass: %s  last pass: %s  post-pass steps: %s  writes after: %s"
              % (out.get("first_pass"), out.get("last_pass"),
                 out.get("post_pass_steps"), out.get("writes_after_pass")))
        if out.get("saving_steps"):
            print("stoppable now: %s step(s)" % out["saving_steps"])
        print("rule: %s" % out.get("rule"))
    elif args.action == "transport":
        # Round 108 (arXiv:2611.18471): what compaction kept of the evidence.
        ref = _chat_ref(args.value)
        out = req("GET", "/api/sessions/%s/transport?budget=%d"
                  % (ref, int(getattr(args, "budget", 4000) or 4000)))
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        print("fidelity: %s%% of %s decisive item(s) survived compaction"
              % (round(100.0 * float(out.get("fidelity") or 0), 1), out.get("total")))
        for item in out.get("missing") or []:
            print("  lost %s: %s" % (item.get("kind"), item.get("value")))
        if out.get("restore"):
            print(out["restore"])
    elif args.action == "backtrace":
        # Round 107 (arXiv:2611.19448): the failing card is usually the reporter,
        # not the cause. Walk backward over the stored cards.
        ref = _chat_ref(args.value)
        q = "/api/sessions/%s/backtrace" % ref
        card = getattr(args, "card", None)
        if card:
            q += "?card=" + _q(card)
        out = req("GET", q)
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        a = out.get("anchor") or {}
        print("verdict: %s" % out.get("verdict"))
        if a:
            print("anchor:  #%s %s exit=%s %s" % (a.get("seq"), a.get("tool"),
                                                 a.get("exit_code"), a.get("error_class") or ""))
        for c in out.get("causes") or []:
            print("  <- #%s %s %s%s" % (c.get("seq"), c.get("tool"), c.get("reason"),
                                        (" shared=" + ",".join(c.get("shared") or []))
                                        if c.get("shared") else ""))
    elif args.action == "export":
        # Round 106 (arXiv:2611.20389): the evidence bundle for someone who is
        # not you. `share` is the default because an accidental paste of `audit`
        # is the failure this feature exists to prevent.
        ref = _chat_ref(args.value)
        profile = getattr(args, "profile", None) or "share"
        out = req("GET", "/api/sessions/%s/export?profile=%s" % (ref, _q(profile)))
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        blob = json.dumps(out, indent=2, ensure_ascii=False)
        dest = getattr(args, "out", None)
        if dest:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(blob + "\n")
            d = out.get("diagnosability") or {}
            print("wrote %s (profile=%s, %d bytes) failures=%s redactions=%s"
                  % (dest, out.get("profile"), len(blob),
                     d.get("failure_signals"), d.get("redactions")))
        else:
            print(blob)
    elif args.action in ("history", "graph", "tree"):
        ref = _chat_ref(args.value)
        if args.action == "history":
            out = req("GET", "/api/history?session=" + _q(ref))
            if out.get("error"):
                print("error:", out["error"], file=sys.stderr)
                sys.exit(1)
            if getattr(args, "full", False):
                _print_history_full(out)
                return
            for m in out.get("messages", []):
                print("[%-9s] %s" % (m.get("role"), (m.get("content") or "").replace("\n", " ")[:200]))
            for c in out.get("tool_cards", []) or []:
                print("[tool     ] %s ok=%s backend=%s" % (c.get("tool"), c.get("ok"), c.get("backend")))
        elif args.action == "graph":
            print(json.dumps(req("GET", "/api/sessions/%s/graph" % ref),
                             indent=2, ensure_ascii=False))
        else:
            # HD-2: the stage→step tree plus the first failure. The one-line verdict
            # leads because that is the answer to "why did this turn go wrong"; the
            # JSON is there when the operator (or an agent) needs the detail.
            out = req("GET", "/api/sessions/%s/trace-tree" % ref)
            if out.get("error"):
                print("error:", out["error"], file=sys.stderr)
                sys.exit(1)
            if out.get("verdict"):
                print(out["verdict"])
            else:
                print("no failed step in %d step(s)" % (out.get("counts") or {}).get("steps", 0))
            # Round 64: a step marked DONE with no tool call is a CLAIM; it is a
            # different fact from a step that was never started, and the two used
            # to share one line ("planned but never executed").
            if out.get("claim_note"):
                print(out["claim_note"])
            for st in out.get("stages") or []:
                print("\n%s  [%s]  %d step(s)" % (st.get("id"), st.get("status"), st.get("n") or 0))
                print("  %s" % st.get("label"))
                for s in st.get("steps") or []:
                    print("    %2d %-4s %s%s" % (s.get("i"), "FAIL" if s.get("failed") else "ok",
                                                 s.get("tool"),
                                                 ("  " + s.get("reason", "")[:90])
                                                 if s.get("failed") else ""))
            if out.get("open"):
                print("\nplanned but never started (no tool call): %d"
                      % len(out["open"]))
                for st in out["open"]:
                    print("  %s  [%s]  %s" % (st.get("id"), st.get("status"), st.get("label")))
            if out.get("claimed"):
                print("\nmarked done with no tool call (nothing on disk proves them): %d"
                      % len(out["claimed"]))
                for st in out["claimed"]:
                    print("  %s  [%s]  %s" % (st.get("id"), st.get("status"), st.get("label")))
    elif args.action == "reset":
        print(json.dumps(req("POST", "/api/sessions/%s/graph/reset" % args.value, {}),
                         indent=2, ensure_ascii=False))
    elif args.action == "clear":
        print(json.dumps(req("POST", "/api/sessions/%s/clear" % args.value, {}),
                         indent=2, ensure_ascii=False))
    elif args.action == "model":
        v = (args.value or "").split(None, 1)
        sid = v[0] if v else ""
        model = v[1] if len(v) > 1 else ""
        print(json.dumps(req("POST", "/api/sessions/%s/model" % sid, {"model": model}),
                         indent=2, ensure_ascii=False))


def cmd_docs(args):
    """`/plan` and `/spec` from the terminal — the WebUI's twin, same endpoints.

    `status` reads the bar; `plan`/`spec` write the document and lock the session;
    `approve`/`reject`/`unlock` decide. One request per invocation; a failure is a
    non-zero exit with the server's reason, never a silent 0.
    """
    sid = args.session or _current_session()
    if not sid:
        _no_current_session()
    act = args.action
    if act == "status":
        out = req("GET", "/api/docs?session=" + _q(sid))
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        a = out.get("active") or {}
        print("plan_mode=%s status=%s implement=%s"
              % (bool(out.get("plan_mode")), a.get("status") or "-", bool(a.get("implement"))))
        if a:
            print("kind=%s%s" % (a.get("kind") or "?", "  FILE MISSING" if a.get("stale") else ""))
            for p in [a.get("path")] + [d for d in (a.get("documents") or []) if d != a.get("path")]:
                if p:
                    print("  " + str(p))
        return
    # Exact route literals, not a concatenation: `v588` proves every CLI path
    # exists on the server, and the server gates these five as exact tuples.
    route = {"plan": "/api/docs/plan", "spec": "/api/docs/spec",
             "approve": "/api/docs/approve", "implement": "/api/docs/implement",
             "reject": "/api/docs/reject",
             "unlock": "/api/docs/unlock"}[act]
    if act in ("plan", "spec"):
        ask = (args.value or "").strip()
        if not ask:
            print('error: a request is required: docs %s "<request>" --session %s' % (act, sid),
                  file=sys.stderr)
            sys.exit(2)
        out = req("POST", route, {"session": sid, "prompt": ask, "model": args.model,
                                  "origin": "cli"}, timeout=_LONG_TIMEOUT)
    else:
        body = {"session": sid}
        if act == "approve" and getattr(args, "implement", False):
            body["implement"] = True   # approve AND authorise (the bar's ▶)
        out = req("POST", route, body)
    if out.get("error"):
        print("error:", out["error"], file=sys.stderr)
        sys.exit(1)
    if act in ("plan", "spec"):
        print("%s written: %s" % (out.get("kind") or act,
                                  out.get("rel_path") or out.get("path") or "?"))
        for d in out.get("documents") or []:
            print("  " + str(d.get("rel_path") or d.get("path") or "?"))
        print("status=%s plan_mode=%s implement=%s model=%s lines=%s"
              % (out.get("status"), bool(out.get("plan_mode")),
                 bool(out.get("implement")), out.get("model") or "?", out.get("lines") or "?"))
    else:
        a = out.get("active") or {}
        print("ok: %s · plan_mode=%s%s"
              % (act, bool(out.get("plan_mode")),
                 (" · active=%s implement=%s" % (a.get("status"), bool(a.get("implement"))))
                 if a else " · no document"))


def cmd_context(args):
    # Round 116: `context cost FILE.json` prices a run or compares two policies.
    if args.action == "cost":
        return _context_cost(args)
    # Same contract as `chat`/`docs`: no `--session` = the CLI's current session.
    # Without it `context show` answered `{"session": null, "available": false}`,
    # which reads as "the meter is broken" instead of "you did not name a session".
    sid = _chat_ref(args.session, required=False)
    if args.action == "show":
        url = "/api/context" + ("?session=" + _q(sid) if sid else "")
        print(json.dumps(req("GET", url), indent=2, ensure_ascii=False))
    elif args.action == "compact":
        print(json.dumps(req("POST", "/api/context/compact", {"session": sid}),
                         indent=2, ensure_ascii=False))
    elif args.action == "preview":
        out = req("POST", "/api/context/preview", {"session": sid, "message": args.value})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.action == "items":
        url = "/api/context/items" + ("?session=" + _q(sid) if sid else "")
        print(json.dumps(req("GET", url), indent=2, ensure_ascii=False))


def cmd_hooks(_):
    print(json.dumps(req("GET", "/api/hooks"), indent=2, ensure_ascii=False))


def cmd_routing(args):
    if args.action == "show":
        print(json.dumps(req("GET", "/api/routing"), indent=2, ensure_ascii=False))
    else:
        try:
            body = json.loads(args.value) if args.value else {}
        except json.JSONDecodeError as e:
            print("bad json:", e, file=sys.stderr)
            sys.exit(2)
        print(json.dumps(req("POST", "/api/routing", body), indent=2, ensure_ascii=False))


def cmd_setup(args):
    """Semantic setup blocks (round 106, arXiv:2611.18443). Runs LOCALLY: the
    workspace being set up is the caller's, not necessarily the server's."""
    from longrun.harness import setup_blocks
    from longrun.util import paths
    if args.action == "run":
        if not args.plan:
            print("usage: setup run PLAN.json [--workspace DIR] [--reuse]",
                  file=sys.stderr)
            sys.exit(2)
        try:
            blocks = setup_blocks.load_plan(args.plan)
        except (OSError, ValueError) as e:
            print("bad plan:", e, file=sys.stderr)
            sys.exit(2)
        workdir = args.workspace or os.getcwd()
        state = args.state or os.path.join(paths.DATA_DIR, "setup")
        out = setup_blocks.run(blocks, workdir, state, reuse=bool(args.reuse))
        for b in out.get("blocks") or []:
            print("%-8s %s%s" % (b.get("status"), b.get("name"),
                                 (" -> rollback " + b["rollback"]
                                  if b.get("rollback") else "")))
        c = out.get("cost") or {}
        print("ok=%s commands_run=%s commands_skipped=%s"
              % (out.get("ok"), c.get("commands_run"), c.get("commands_skipped")))
        sys.exit(0 if out.get("ok") else 1)
    print(json.dumps({"state": args.state or os.path.join(paths.DATA_DIR, "setup")},
                     indent=2))


def cmd_skills(args):
    """Round 109: skill staleness, paired value, explicit repair (arXiv:2611.22525, -22017)."""
    from longrun.harness import skills_maintenance, skill_value
    if args.action in ("compile", "optimize", "conflict"):
        # Round 118: verified-trace compilation (2611.01386), SkIR repair (2611.20856),
        # cross-skill conflict (2610.35082).
        from longrun.harness import skill_compiler, skill_repair, skill_conflict
        path = getattr(args, "value", None)
        if not path:
            print("usage: skills %s FILE.json" % args.action, file=sys.stderr)
            sys.exit(2)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad file:", e, file=sys.stderr)
            sys.exit(2)
        if args.action == "compile":
            out = skill_compiler.compile_skill(doc.get("trace") or doc,
                                               doc.get("min_strength") or "independent")
            print(json.dumps(out, indent=2, ensure_ascii=False))
            sys.exit(0 if out["admitted"] else 1)
        if args.action == "optimize":
            out = skill_repair.repair(doc)
            print(json.dumps(out, indent=2, ensure_ascii=False))
            sys.exit(0 if out["accepted"] else 1)
        out = skill_conflict.conflicts(doc.get("pool") or doc)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if out["verdict"] == "clean" else 1)
    if args.action == "prune":
        # Round 112 (arXiv:2611.19823): compact a skill without touching contract lines.
        from longrun.harness import skill_prune
        path = getattr(args, "value", None)
        if not path:
            print("usage: skills prune FILE.json [--budget N] [--write]", file=sys.stderr)
            sys.exit(2)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad file:", e, file=sys.stderr)
            sys.exit(2)
        text = doc.get("text") if isinstance(doc, dict) else doc
        out = skill_prune.prune(text or "", budget_tokens=getattr(args, "budget", None))
        if getattr(args, "write", False):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out["text"])
        print(json.dumps({k: v for k, v in out.items() if k != "text"},
                         indent=2, ensure_ascii=False))
        return
    if args.action == "stale":
        import longrun.tools.registry as _reg
        out = skills_maintenance.maintain(os.path.join(_reg.REPO, "skills"),
                                          repo=_reg.REPO)
        for row in out.get("stale") or []:
            print("%s  %s" % (row.get("skill"), row.get("path")))
            for f in row.get("findings") or []:
                print("   L%-4s %-6s %s — %s" % (f.get("line"), f.get("kind"),
                                                  f.get("value"), f.get("reason")))
        c = out.get("counts") or {}
        print("skills=%s stale=%s" % (c.get("skills"), c.get("stale")))
        sys.exit(0 if not c.get("stale") else 1)
    path = getattr(args, "value", None)
    if not path:
        print("usage: skills %s FILE" % args.action, file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "value":
        recs = doc.get("records") if isinstance(doc, dict) else doc
        print(json.dumps(skill_value.paired(recs), indent=2, ensure_ascii=False))
        return
    mapping = {}
    for pair in getattr(args, "map", None) or []:
        old, _, new = str(pair).partition("=")
        if old:
            mapping[old] = new
    if not mapping:
        print("repair needs --map old=new (exact, caller-supplied)", file=sys.stderr)
        sys.exit(2)
    text = doc.get("text") if isinstance(doc, dict) else doc
    res = skills_maintenance.repair(text, mapping)
    if getattr(args, "write", False):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(res["text"])
    print(json.dumps({"changes": res["changes"], "written": bool(getattr(args, "write", False))},
                     indent=2, ensure_ascii=False))


def cmd_autonomy(args):
    """Round 112 (arXiv:2611.10058): bounded/observable/reversible autonomy scorecard."""
    from longrun.harness import autonomy
    path = getattr(args, "file", None)
    if not path:
        print("usage: autonomy check FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    rows = doc.get("actions") if isinstance(doc, dict) else doc
    out = autonomy.scoreboard(rows or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_reuse(args):
    """Round 110 (arXiv:2611.09254): repeated deterministic reads in a card file."""
    from longrun.harness import reuse
    path = getattr(args, "file", None)
    if not path:
        print("usage: reuse audit FILE.json [--allow a,b]", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    cards = doc.get("cards") if isinstance(doc, dict) else doc
    allow = None
    if getattr(args, "allow", None):
        allow = [t.strip() for t in str(args.allow).split(",") if t.strip()]
    out = reuse.audit(cards or [], allow=allow)
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_principals(args):
    """Round 110 (arXiv:2611.08768): principal-context authorization + laundering."""
    from longrun.harness import principals
    path = getattr(args, "file", None)
    if not path:
        print("usage: principals check FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = principals.check(doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("allow") else 1)


def cmd_residency(args):
    """Round 110 (arXiv:2611.13412): the park/admit band over a session file."""
    from longrun.util import residency
    path = getattr(args, "file", None)
    if not path:
        print("usage: residency plan FILE.json --capacity N [--current SID]",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    sessions = doc.get("sessions") if isinstance(doc, dict) else doc
    out = residency.plan(sessions or [], getattr(args, "capacity", 0),
                         current=getattr(args, "current", None))
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_procedure(args):
    """Round 111 (arXiv:2611.10884): replay a procedure FSM over plain events."""
    from longrun.plan import procedure
    path = getattr(args, "file", None)
    if not path:
        print("usage: procedure run FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = procedure.replay(doc.get("procedure") or doc, doc.get("events") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_intent(args):
    """Round 111 (arXiv:2611.06563): declarations against observed effects."""
    from longrun.harness import intent_journal
    path = getattr(args, "file", None)
    if not path:
        print("usage: intent %s FILE.json" % args.action, file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if args.action == "check":
        out = intent_journal.check(doc.get("declaration") or {},
                                   doc.get("effects") or {},
                                   doc.get("declared_targets"))
    else:
        rows = doc.get("entries") if isinstance(doc, dict) else doc
        out = intent_journal.audit(rows)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("verdict") in ("clean",) else 1)


def cmd_handoff(args):
    """Round 111 (arXiv:2611.06545): policy sentences vs the permission ledger."""
    from longrun.harness import handoff_audit
    path = getattr(args, "file", None)
    if not path:
        print("usage: handoff audit FILE.json", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    out = handoff_audit.audit(doc.get("text") or "", doc.get("ledger") or [])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out.get("verdict") == "clean" else 1)


def cmd_invariants(_):
    """Round 107 (arXiv:2611.19960): the corner cases written down as checks."""
    from longrun.harness import invariants
    out = invariants.check()
    for r in out.get("rows") or []:
        print("%-6s %-9s %-8s %s" % (r.get("id"), r.get("status"), r.get("tag"),
                                     r.get("statement")))
        if r.get("status") == "violated" and r.get("detail"):
            print("        %s" % r["detail"])
    c = out.get("counts") or {}
    print("holds=%s violated=%s open=%s of %s"
          % (c.get("holds"), c.get("violated"), c.get("open"), c.get("total")))
    sys.exit(0 if not c.get("violated") else 1)


def cmd_manifest(_):
    """Round 107 (arXiv:2611.22299): what this harness currently decides."""
    from longrun.harness import manifest
    print(json.dumps(manifest.build(), indent=2, ensure_ascii=False))


def cmd_checkpoints(args):
    if args.action == "ls":
        out = req("GET", "/api/checkpoints")
        for c in out.get("checkpoints", []):
            print(" %-14s %-20s %s" % (c.get("id"), c.get("label") or "", c.get("ts") or ""))
    elif args.action == "create":
        print(json.dumps(req("POST", "/api/checkpoints",
                             {"label": args.value, "session": args.session}),
                         indent=2, ensure_ascii=False))
    elif args.action == "show":
        print(json.dumps(req("GET", "/api/checkpoints/" + args.value), indent=2, ensure_ascii=False))
    elif args.action == "rollback":
        print(json.dumps(req("POST", "/api/checkpoints/%s/rollback" % args.value, {}),
                         indent=2, ensure_ascii=False))
    elif args.action == "rm":
        print(json.dumps(req("DELETE", "/api/checkpoints/" + args.value),
                         indent=2, ensure_ascii=False))
    elif args.action == "prune":
        print(json.dumps(req("DELETE", "/api/checkpoints"),
                         indent=2, ensure_ascii=False))


def cmd_self(_):
    print(json.dumps(req("GET", "/api/self"), indent=2, ensure_ascii=False))


def cmd_selfcheck(_):
    print(json.dumps(req("GET", "/api/selfcheck"), indent=2, ensure_ascii=False))


def cmd_providers(args):
    action = getattr(args, "action", None) or "ls"
    if action == "ls":
        print(json.dumps(req("GET", "/api/providers"), indent=2, ensure_ascii=False))
    elif action == "add":
        try:
            body = json.loads(args.value) if args.value else {}
        except json.JSONDecodeError as e:
            print("bad json:", e, file=sys.stderr); sys.exit(2)
        print(json.dumps(req("POST", "/api/providers", body), indent=2, ensure_ascii=False))
    elif action == "rm":
        print(json.dumps(req("DELETE", "/api/providers?id=" + _q(args.value)),
                         indent=2, ensure_ascii=False))
    elif action == "default":
        print(json.dumps(req("POST", "/api/providers/default", {"ref": args.value}),
                         indent=2, ensure_ascii=False))
    elif action == "rm-model":
        print(json.dumps(req("DELETE", "/api/providers/models?provider=" + _q(args.value)),
                         indent=2, ensure_ascii=False))
    else:
        print("unknown providers action", file=sys.stderr); sys.exit(2)


def cmd_eval(args):
    if args.action == "select":
        # Round 108 (arXiv:2611.21515): leaderboard rank is not a selection.
        # The file is `[{"name","cost","passes","n"}]` (or {"candidates": [...]}).
        from longrun.util import selection
        path = getattr(args, "value", None)
        if not path:
            print("usage: eval select FILE.json [--budget N] [--cost-cap N]",
                  file=sys.stderr)
            sys.exit(2)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as e:
            print("bad candidates file:", e, file=sys.stderr)
            sys.exit(2)
        cands = doc.get("candidates") if isinstance(doc, dict) else doc
        out = selection.select(cands, eval_budget=args.budget,
                               cost_cap=args.cost_cap)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    if args.action == "tasks":
        out = req("GET", "/api/eval/tasks")
        rows = out.get("tasks", []) if isinstance(out, dict) else (out if isinstance(out, list) else [])
        for t in rows:
            if isinstance(t, dict):
                print(" %-22s %s" % (t.get("id"), (t.get("goal") or t.get("prompt")
                                                     or t.get("description") or "")[:70]))
            else:
                print(" ", t)
    else:
        out = req("POST", "/api/eval/run", {"model": args.model, "max_steps": args.max_steps,
                                            "task_id": args.task, "save": not args.no_save})
        print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_voice(args):
    if args.action == "status":
        print(json.dumps(req("GET", "/api/voice/status"), indent=2, ensure_ascii=False))
    elif args.action == "stt":
        print(json.dumps(req("POST", "/api/voice/stt", {"text": args.value}),
                         indent=2, ensure_ascii=False))
    elif args.action == "tts":
        print(json.dumps(req("POST", "/api/voice/tts", {"text": args.value}),
                         indent=2, ensure_ascii=False))


def cmd_events(args):
    qs = "since=%d&limit=%d" % (args.since, args.limit)
    if getattr(args, "session", None):
        qs += "&session=" + _q(args.session)
    if getattr(args, "kind", None):
        qs += "&kind=" + _q(args.kind)
    out = req("GET", "/api/events?" + qs)
    for e in reversed(out.get("events", [])):
        print("%5s %-18s %s" % (e.get("id"), e.get("kind"), json.dumps(
            {k: v for k, v in e.items() if k not in ("id", "kind")},
            ensure_ascii=False)[:140]))


def _agent_row(tree, aid):
    return next((x for x in (tree or {}).get("agents", []) if x.get("id") == aid), None)


def _resolve_session(ref):
    """Accept a session id OR an agent id (AX) and return the session id (JAG-294)."""
    if ref and re.match(r"^A\d+$", str(ref)):
        a = _agent_row(req("GET", "/api/agents/tree"), ref)
        return a.get("session") if a else ref
    return ref


def cmd_roles(args):
    """Per-session ROLE.md: a small role + behaviour patch merged into the prompt."""
    sid = _resolve_session(args.session)
    if args.action == "show":
        out = req("GET", "/api/roles?session=" + _q(sid))
        if out.get("error"):
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        print("# %s" % out.get("path", ""))
        print(out.get("text") or "(no role for this session)")
    elif args.action == "set":
        text = sys.stdin.read() if args.text in (None, "-") else args.text
        print(json.dumps(req("POST", "/api/roles", {"session": sid, "text": text}),
                         indent=2, ensure_ascii=False))
    elif args.action == "clear":
        print(json.dumps(req("POST", "/api/roles", {"session": sid, "text": ""}),
                         indent=2, ensure_ascii=False))
    elif args.action == "reset":
        print(json.dumps(req("DELETE", "/api/roles?session=" + _q(sid)), indent=2))


def cmd_agents(args):
    if args.action == "ls":
        out = req("GET", "/api/agents/tree")
        for a in out.get("agents", []):
            # 2026-11-18 (operator: "parlare con i miei agenti"): an agent IS a
            # session, and that session is what `chat --session` takes — printing it
            # is what makes the round trip possible without a lookup.
            print(" %-4s %-22s %-18s %-12s %-26s %s" % (
                a.get("id"), a.get("name") or "", a.get("role") or "",
                a.get("session") or "-", a.get("model") or "default",
                ("-> " + a["reports_to"]) if a.get("reports_to") else ""))
    elif args.action == "new":
        name = (args.value or "").strip()
        if not name:
            print("error: a name is required", file=sys.stderr)
            sys.exit(1)
        tree = req("GET", "/api/agents/tree")
        if any((x.get("name") or "").strip().lower() == name.lower()
               for x in tree.get("agents", [])):
            print("error: name already in use:", name, file=sys.stderr)
            sys.exit(1)
        s = req("POST", "/api/orbit/sessions", {"title": name})
        if not s.get("ok"):
            print("error:", s.get("error") or "could not create session", file=sys.stderr)
            sys.exit(1)
        body = {"session": s["session"], "name": name}
        for k in ("role", "model", "reports_to"):
            if getattr(args, k):
                body[k] = getattr(args, k)
        out = req("POST", "/api/agents", body)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        if not out.get("ok"):
            sys.exit(1)
    elif args.action == "set":
        a = _agent_row(req("GET", "/api/agents/tree"), args.value)
        if not a:
            print("error: unknown agent", args.value, file=sys.stderr)
            sys.exit(1)
        body = {"session": a["session"]}
        for k in ("name", "role", "model", "reports_to"):
            if getattr(args, k):
                body[k] = getattr(args, k)
        print(json.dumps(req("POST", "/api/agents", body), indent=2, ensure_ascii=False))
    elif args.action == "rm":
        a = _agent_row(req("GET", "/api/agents/tree"), args.value)
        if not a:
            print("error: unknown agent", args.value, file=sys.stderr)
            sys.exit(1)
        print(json.dumps(req("DELETE", "/api/agents/" + _q(a["session"])),
                         indent=2, ensure_ascii=False))


def cmd_routines(args):
    if args.action == "ls":
        print(json.dumps(req("GET", "/api/routines"), indent=2, ensure_ascii=False))
    elif args.action == "new":
        print(json.dumps(req("POST", "/api/routines", {"agent": args.agent, "goal": args.value, "every_seconds": args.every}), indent=2, ensure_ascii=False))
    elif args.action == "rm":
        print(json.dumps(req("DELETE", "/api/routines/" + args.value), indent=2, ensure_ascii=False))
    elif args.action in ("enable", "disable"):
        print(json.dumps(req("POST", "/api/routines/%s/%s" % (args.value, args.action), {}), indent=2, ensure_ascii=False))


def cmd_jobs(args):
    if args.action == "ls":
        out = req("GET", "/api/jobs")
        for j in out.get("jobs", []):
            print(" %-4s %-8s %-6s %s" % (j.get("id"), j.get("status"),
                                          j.get("coordinator") or "",
                                          (j.get("goal") or "")[:64]))
    elif args.action == "new":
        body = {"goal": args.value}
        if args.to:
            body["assignee"] = args.to
        if getattr(args, "blocked_by", None):
            body["blocked_by"] = [x.strip() for x in args.blocked_by.split(",") if x.strip()]
        if getattr(args, "agents", None):
            body["agents"] = [x.strip() for x in args.agents.split(",") if x.strip()]
        if getattr(args, "coordinator", None):
            body["coordinator"] = args.coordinator
        if getattr(args, "mode", None):
            body["mode"] = args.mode
        print(json.dumps(req("POST", "/api/jobs", body), indent=2, ensure_ascii=False))
    elif args.action == "run":
        print(json.dumps(req("POST", "/api/jobs/%s/dispatch" % _q(args.value), {}),
                         indent=2, ensure_ascii=False))
    elif args.action == "wake":
        print(json.dumps(req("POST", "/api/jobs/wake", {}), indent=2, ensure_ascii=False))
    elif args.action == "get":
        print(json.dumps(req("GET", "/api/jobs/" + _q(args.value)), indent=2, ensure_ascii=False))


def cmd_paperclip_bot(args):
    """Run ONE Paperclip-issued task (JAG-467): envelope on stdin, NDJSON on stdout.

    The protocol lives in ``longrun.integrations.paperclip_bot``; this command
    only registers it with the CLI and propagates its exit code, which
    Paperclip reads to classify the run (0 completed / 1 otherwise / 130
    cancelled).
    """
    from longrun.integrations.paperclip_bot import main as paperclip_main
    sys.exit(paperclip_main())


def main():
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("chat"); p.add_argument("message"); p.add_argument("--session"); \
        p.add_argument("--model"); p.add_argument("--stream", action="store_true"); \
        p.add_argument("--new", action="store_true", help="force a fresh session (ignore the current one)"); \
        p.set_defaults(fn=cmd_chat)
    p = sub.add_parser("agent"); p.add_argument("goal"); p.add_argument("--max-steps", type=int, default=6); \
        p.add_argument("--model"); p.set_defaults(fn=cmd_agent)
    p = sub.add_parser("plan"); p.add_argument("action", choices=["show", "generate", "toggle", "set"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--steps"); p.add_argument("--session"); \
        p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("tasks"); p.add_argument("action", choices=["ls", "add", "done", "set"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--status"); p.set_defaults(fn=cmd_tasks)
    p = sub.add_parser("tools"); \
        p.add_argument("action", choices=["ls", "call", "running", "cancel"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.set_defaults(fn=cmd_tools)
    p = sub.add_parser("approvals"); \
        p.add_argument("action", choices=["ls", "show", "approve", "deny", "rm", "clear", "audit"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--status"); \
        p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_approvals)
    p = sub.add_parser("runs"); \
        p.add_argument("action", choices=["ls", "show", "trace", "summary", "node"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); p.set_defaults(fn=cmd_runs)
    p = sub.add_parser("control"); p.add_argument("action", choices=["pause", "resume", "abort"]); \
        p.add_argument("run"); p.set_defaults(fn=cmd_control)
    sub.add_parser("sandbox").set_defaults(fn=cmd_sandbox)
    p = sub.add_parser("mcp"); p.add_argument("action", nargs="?", default="tools", choices=["tools", "ls", "add", "remove", "reload", "local-file"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--json"); p.set_defaults(fn=cmd_mcp)
    p = sub.add_parser("market"); p.add_argument("action", nargs="?", default="ls",
        choices=["ls", "sources", "status", "sync", "remote", "import", "install", "installed",
                 "rm", "plugin-scan", "plugin-add"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.add_argument("--kind"); p.add_argument("--category"); p.add_argument("--source"); \
        p.add_argument("--limit", type=int, default=20); p.add_argument("--offset", type=int, default=0); \
        p.add_argument("--wait", action="store_true"); p.add_argument("--overwrite", action="store_true"); \
        p.add_argument("--files", action="store_true"); p.set_defaults(fn=cmd_market)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("models"); p.add_argument("action", nargs="?", default="ls", choices=["ls", "ensure"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_models)
    p = sub.add_parser("index"); p.add_argument("action", nargs="?", default="status", choices=["status", "build", "search"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--limit", type=int, default=8); \
        p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("knowledge"); p.add_argument("action", nargs="?", default="status", choices=["status", "notebooks", "create", "add", "search", "discover", "import", "research"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--notebook"); p.add_argument("--limit", type=int, default=8); \
        p.add_argument("--depth", choices=["shallow", "medium", "deep"]); p.add_argument("--max-rounds", type=int, default=4); \
        p.set_defaults(fn=cmd_knowledge)
    p = sub.add_parser("research"); p.add_argument("action", nargs="?", default="active", choices=["ls", "set", "active"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_research)
    p = sub.add_parser("embedding"); p.add_argument("action", nargs="?", default="active", choices=["models", "active", "set", "add", "remove", "costs", "cost-test"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_embedding)
    sub.add_parser("feed").set_defaults(fn=cmd_feed)
    p = sub.add_parser("memory"); p.add_argument("action", choices=["store", "search", "forget", "purge", "surface", "boundary", "conflicts", "ledger"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.add_argument("--kind"); p.add_argument("--semantic", action="store_true"); \
        p.add_argument("--budget", type=int, default=None,
                       help="surface: token budget (rules are never dropped)"); \
        p.add_argument("--limit", type=int, default=10); p.set_defaults(fn=cmd_memory)
    p = sub.add_parser("episodes"); p.add_argument("action", choices=["audit"]); \
        p.add_argument("file", nargs="?", help="JSON: origin, symptom, propagation, detection, response, consequence"); \
        p.set_defaults(fn=cmd_episodes)
    p = sub.add_parser("contract"); p.add_argument("action", choices=["check"]); \
        p.add_argument("file", nargs="?", help="JSON: {contract, sequence}"); \
        p.set_defaults(fn=cmd_contract)
    p = sub.add_parser("recovery"); p.add_argument("action", choices=["adjudicate", "trace"]); \
        p.add_argument("file", nargs="?", help="JSON: capabilities, obligations, evidence (+ proposed, residual)"); \
        p.set_defaults(fn=cmd_recovery)
    p = sub.add_parser("effects"); p.add_argument("action", choices=["coverage", "verify"]); \
        p.add_argument("file", nargs="?", help="JSON: {catalog, trace}"); \
        p.add_argument("--live", action="store_true", help="coverage: read the live tool catalog"); \
        p.set_defaults(fn=cmd_effects)
    p = sub.add_parser("commit"); p.add_argument("action", choices=["decide", "diagnose"]); \
        p.add_argument("file", nargs="?", help="JSON: actions, edges, broken, costs/values, threshold, patch debt"); \
        p.set_defaults(fn=cmd_commit)
    p = sub.add_parser("expectations"); p.add_argument("action", choices=["verify", "savings"]); \
        p.add_argument("file", nargs="?", help="JSON: {steps:[{expect,observation}], keys, tokens_per_step}"); \
        p.set_defaults(fn=cmd_expectations)
    p = sub.add_parser("governance"); p.add_argument("action", choices=["decide", "check"]); \
        p.add_argument("file", nargs="?", help="JSON: {ontology, state, call}"); \
        p.set_defaults(fn=cmd_governance)
    p = sub.add_parser("capsule"); p.add_argument("action", choices=["compile", "replay", "savings"]); \
        p.add_argument("file", nargs="?", help="JSON: {invocation|skill} or {capsule, state}"); \
        p.set_defaults(fn=cmd_capsule)
    p = sub.add_parser("flow"); p.add_argument("action", choices=["judge", "calibrate", "evaluate"]); \
        p.add_argument("file", nargs="?", help="JSON: {relay} or {scores, labels, threshold}"); \
        p.set_defaults(fn=cmd_flow)
    p = sub.add_parser("selfdirected"); p.add_argument("action", choices=["audit", "transfer"]); \
        p.add_argument("file", nargs="?", help="JSON: a self-improvement run record"); \
        p.set_defaults(fn=cmd_selfdirected)
    p = sub.add_parser("harnessevo"); p.add_argument("action", choices=["diagnose", "admit", "bloat"]); \
        p.add_argument("file", nargs="?", help="JSON: rollouts, or one candidate edit, or rules"); \
        p.set_defaults(fn=cmd_harnessevo)
    p = sub.add_parser("contextpipeline"); \
        p.add_argument("action", choices=["boundaries", "deliver", "profile"]); \
        p.add_argument("file", nargs="?", help="JSON: {payload, budget, mode} or {runs}"); \
        p.set_defaults(fn=cmd_contextpipeline)
    p = sub.add_parser("stepzero"); p.add_argument("action", choices=["peek", "extract", "bind"]); \
        p.add_argument("file", nargs="?", help="JSON: {members, budget, protect} or {declared_name, body_sha, declared_sha}"); \
        p.set_defaults(fn=cmd_stepzero)
    p = sub.add_parser("harnessrecord"); \
        p.add_argument("action", choices=["audit", "degradation", "drift"]); \
        p.add_argument("file", nargs="?", help="JSON: a harness record, or {changes, declared}, or {declared, observed}"); \
        p.set_defaults(fn=cmd_harnessrecord)
    p = sub.add_parser("conduct"); p.add_argument("action", choices=["score", "stated", "matrix"]); \
        p.add_argument("file", nargs="?", help="JSON: {episode} or {rows}"); \
        p.set_defaults(fn=cmd_conduct)
    p = sub.add_parser("completion"); p.add_argument("action", choices=["check", "ladder"]); \
        p.add_argument("file", nargs="?", help="JSON: {run} or {rows}"); \
        p.set_defaults(fn=cmd_completion)
    p = sub.add_parser("skillret"); p.add_argument("action", choices=["calibrate", "rank", "apply"]); \
        p.add_argument("file", nargs="?", help="JSON: {pairs}, {candidates, learned}, or {learned, skill}"); \
        p.set_defaults(fn=cmd_skillret)
    p = sub.add_parser("ruleret"); p.add_argument("action", choices=["closure", "audit"]); \
        p.add_argument("file", nargs="?", help="JSON: {rules, seeds, budget} (+ selection)"); \
        p.set_defaults(fn=cmd_ruleret)
    p = sub.add_parser("skillquality"); p.add_argument("action", choices=["profile", "predict"]); \
        p.add_argument("file", nargs="?", help="JSON: {skill} or {skill, references, k}"); \
        p.set_defaults(fn=cmd_skillquality)
    p = sub.add_parser("opspolicy"); \
        p.add_argument("action", choices=["realize", "ground", "affinity", "route"]); \
        p.add_argument("file", nargs="?", help="JSON: {output, tools, guidance}, {claim, observations}, {rows}, or {models, learned}"); \
        p.set_defaults(fn=cmd_opspolicy)
    p = sub.add_parser("execpolicy"); \
        p.add_argument("action", choices=["reversal", "confirm", "efficiency", "amortize"]); \
        p.add_argument("file", nargs="?", help="JSON: {declared, measured}, {panel, candidate}, {rows}, or {acquisition_s, gain_per_task_s, tasks}"); \
        p.set_defaults(fn=cmd_execpolicy)
    p = sub.add_parser("skilladapter"); \
        p.add_argument("action", choices=["bind", "recheck", "expire", "maintain"]); \
        p.add_argument("file", nargs="?", help="JSON: {skill, adapters, context}, {preloaded, inputs}, {adapters, today}, or {entries, events}"); \
        p.set_defaults(fn=cmd_skilladapter)
    p = sub.add_parser("intake"); \
        p.add_argument("action", choices=["admit", "mandate", "subscribe", "preset", "shadow"]); \
        p.add_argument("file", nargs="?", help="JSON: {trigger, policy}, {ticket}, {events, owned}, {base, strip}, or {actions, confirmed}"); \
        p.set_defaults(fn=cmd_intake)
    p = sub.add_parser("memcredit"); \
        p.add_argument("action", choices=["credit", "arbitrate", "sparsity"]); \
        p.add_argument("file", nargs="?", help="JSON: {candidate, reference}, {candidates, budget}, or {rows}"); \
        p.set_defaults(fn=cmd_memcredit)
    p = sub.add_parser("lessongate"); \
        p.add_argument("action", choices=["hypothesis", "trial", "probe"]); \
        p.add_argument("file", nargs="?", help="JSON: {lesson} or {lesson, results}"); \
        p.set_defaults(fn=cmd_lessongate)
    p = sub.add_parser("seclattice"); \
        p.add_argument("action", choices=["admit", "attenuate", "write", "read", "effect"]); \
        p.add_argument("file", nargs="?", help="JSON: {label, action}, {parent, child}, {ledger, path, actor}, or {actor, effect}"); \
        p.set_defaults(fn=cmd_seclattice)
    p = sub.add_parser("optmemory"); \
        p.add_argument("action", choices=["record", "continuity", "advantage"]); \
        p.add_argument("file", nargs="?", help="JSON: {memory, edit}, {memory, target}, or {pairs}"); \
        p.set_defaults(fn=cmd_optmemory)
    p = sub.add_parser("detour"); \
        p.add_argument("action", choices=["attainment", "residual", "progress", "classify", "rank"]); \
        p.add_argument("file", nargs="?", help="JSON: {success, charged, optimum}, {success, wrong, remaining}, or {episodes}"); \
        p.set_defaults(fn=cmd_detour)
    p = sub.add_parser("patchprobe"); \
        p.add_argument("action", choices=["verdict", "compare", "provenance", "validate"]); \
        p.add_argument("file", nargs="?", help="JSON: {control_ok, effect_seen, token_ok}, {b0, sibling}, {runs, advisory}, or {runs}"); \
        p.set_defaults(fn=cmd_patchprobe)
    p = sub.add_parser("poison"); p.add_argument("action", choices=["trace", "descendants"]); \
        p.add_argument("file", nargs="?", help="JSON: {run} or {store, poisoned}"); \
        p.set_defaults(fn=cmd_poison)
    p = sub.add_parser("boundary"); p.add_argument("action", choices=["evaluate", "classify"]); \
        p.add_argument("file", nargs="?", help="JSON: {call} or {outcome}"); \
        p.set_defaults(fn=cmd_boundary)
    p = sub.add_parser("gapleak"); \
        p.add_argument("action", choices=["gap", "disclosure", "verify", "compare"]); \
        p.add_argument("file", nargs="?", help="JSON: {requested, authorized, reachable}, {form, policy, third_party}, {form, summary, required}, or {before, after}"); \
        p.set_defaults(fn=cmd_gapleak)
    p = sub.add_parser("binding"); \
        p.add_argument("action", choices=["alignment", "pressure", "bind", "resolve",
                                          "outcomes", "judge", "sweep"]); \
        p.add_argument("file", nargs="?", help="JSON: {advert, reference}, {advert, expected_provider}, {candidates, reference, authorized_provider}, {trials}, or {rows}"); \
        p.set_defaults(fn=cmd_binding)
    p = sub.add_parser("gateway"); \
        p.add_argument("action", choices=["utility", "delta", "holm", "claim", "stub",
                                          "hints", "fallback", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: a cell, {base, candidate}, {pvalues}, {delta, ci, p_adjusted}, {tool}, {hinted, bare}, {unbounded, bounded}, or {profile}"); \
        p.set_defaults(fn=cmd_gateway)
    p = sub.add_parser("scoring"); \
        p.add_argument("action", choices=["depends", "reversal", "select", "paired",
                                          "advise", "binary", "learn"]); \
        p.add_argument("file", nargs="?", help="JSON: {mode}, {pair}, {mode, scores}, {instances}, {task, candidates}, {gold_yes_rate, predicted_yes}, or {mode, relational_share}"); \
        p.set_defaults(fn=cmd_scoring)
    p = sub.add_parser("instructions"); p.add_argument("action", choices=["audit"]); \
        p.add_argument("file", nargs="?", help="JSON: {text, cards}"); \
        p.set_defaults(fn=cmd_instructions)
    p = sub.add_parser("teams"); p.add_argument("action", choices=["audit"]); \
        p.add_argument("file", nargs="?", help="JSON: coordinator, members, safety_lead, safety_doc, jobs"); \
        p.set_defaults(fn=cmd_teams)
    p = sub.add_parser("toolgraph"); p.add_argument("action", choices=["build", "feedback"]); \
        p.add_argument("file", nargs="?", help="JSON: catalog + transitions + probes (+ goal/candidate)"); \
        p.set_defaults(fn=cmd_toolgraph)
    p = sub.add_parser("subagent"); p.add_argument("action", choices=["spawn", "collect", "status"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--max-steps", type=int, default=None); \
        p.set_defaults(fn=cmd_subagent)
    p = sub.add_parser("meta"); p.add_argument("action", choices=["run", "status", "best"]); \
        p.add_argument("--n-candidates", type=int, default=8); p.set_defaults(fn=cmd_meta)
    p = sub.add_parser("blackboard"); \
        p.add_argument("action", choices=["post", "get", "search", "stats", "watch"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.add_argument("--id"); p.add_argument("--topic"); p.add_argument("--tags"); \
        p.add_argument("--limit", type=int, default=20); p.set_defaults(fn=cmd_blackboard)
    p = sub.add_parser("acp"); p.add_argument("action", choices=["server", "connect", "list"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.add_argument("--token"); p.set_defaults(fn=cmd_acp)
    p = sub.add_parser("swarm"); p.add_argument("goal"); p.add_argument("--n-workers", type=int, default=3); \
        p.add_argument("--max-steps", type=int, default=None); p.set_defaults(fn=cmd_swarm)
    sub.add_parser("paperclip-bot").set_defaults(fn=cmd_paperclip_bot)
    p = sub.add_parser("sessions"); p.add_argument("action", choices=["ls", "new", "fork", "rm", "use", "current", "history", "card", "counterfactual", "model-counterfactual", "graph", "tree", "reset", "clear", "model", "export", "backtrace", "transport", "stopping"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--workspace"); \
        p.add_argument("--at"); p.add_argument("--title"); p.add_argument("--model"); \
        p.add_argument("--arg", action="append"); p.add_argument("--content"); \
        p.add_argument("--card", help="backtrace: the tool card handle (default: last failure)"); \
        p.add_argument("--budget", type=float, default=4000,
                       help="transport: the compaction token budget to audit"); \
        p.add_argument("--profile", choices=["audit", "share"], default="share",
                       help="export: share = pseudonyms + bucketed counters; "
                            "audit = the operator's own copy"); \
        p.add_argument("--out", help="export: write the JSON bundle to this file"); \
        p.add_argument("--full", action="store_true",
                       help="history: the transcript and tool cards untruncated"); \
        p.set_defaults(fn=cmd_sessions)
    p = sub.add_parser("docs"); p.add_argument("action", choices=["status", "plan", "spec", "approve", "implement", "reject", "unlock"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--session"); \
        p.add_argument("--implement", action="store_true",
                       help="approve AND authorise the implementation (the bar's ▶)"); \
        p.add_argument("--model"); p.set_defaults(fn=cmd_docs)
    p = sub.add_parser("context"); p.add_argument("action", choices=["show", "compact", "preview", "items", "cost"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--session"); p.set_defaults(fn=cmd_context)
    p = sub.add_parser("hooks"); p.set_defaults(fn=cmd_hooks)
    p = sub.add_parser("routing"); p.add_argument("action", choices=["show", "update"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_routing)
    p = sub.add_parser("checkpoints"); p.add_argument("action", choices=["ls", "create", "show", "rollback", "rm", "prune"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--session"); p.set_defaults(fn=cmd_checkpoints)
    p = sub.add_parser("setup"); p.add_argument("action", choices=["run", "status"]); \
        p.add_argument("plan", nargs="?"); p.add_argument("--workspace"); \
        p.add_argument("--state", help="where block checkpoints live (default: data/setup)"); \
        p.add_argument("--reuse", action="store_true",
                       help="skip a block whose digest and pre-state match its checkpoint"); \
        p.set_defaults(fn=cmd_setup)
    sub.add_parser("self").set_defaults(fn=cmd_self)
    sub.add_parser("invariants").set_defaults(fn=cmd_invariants)
    sub.add_parser("manifest").set_defaults(fn=cmd_manifest)
    p = sub.add_parser("skills"); p.add_argument("action", choices=["stale", "value", "repair", "prune", "compile", "optimize", "conflict"]); \
        p.add_argument("value", nargs="?", help="value/repair/prune: the JSON file"); \
        p.add_argument("--map", action="append",
                       help="repair: exact rename, old=new (repeatable)"); \
        p.add_argument("--budget", type=int, default=None,
                       help="prune: token budget (chars/4 estimate)"); \
        p.add_argument("--write", action="store_true",
                       help="repair/prune: write the result back to the file"); \
        p.set_defaults(fn=cmd_skills)
    p = sub.add_parser("autonomy"); p.add_argument("action", choices=["check"]); \
        p.add_argument("file", nargs="?", help="JSON: {actions:[{action, allowlist, ...}]} or a list"); \
        p.set_defaults(fn=cmd_autonomy)
    p = sub.add_parser("reuse"); p.add_argument("action", choices=["audit"]); \
        p.add_argument("file", nargs="?", help="JSON: a card list or {\"cards\": [...]}"); \
        p.add_argument("--allow", help="comma-separated read-only tool allowlist"); \
        p.set_defaults(fn=cmd_reuse)
    p = sub.add_parser("principals"); p.add_argument("action", choices=["check"]); \
        p.add_argument("file", nargs="?", help="JSON: action, influences, permissions, objects"); \
        p.set_defaults(fn=cmd_principals)
    p = sub.add_parser("residency"); p.add_argument("action", choices=["plan"]); \
        p.add_argument("file", nargs="?", help="JSON: a session list or {\"sessions\": [...]}"); \
        p.add_argument("--capacity", type=int, default=0, help="cache pool size in tokens"); \
        p.add_argument("--current", help="the session that reached a turn boundary"); \
        p.set_defaults(fn=cmd_residency)
    p = sub.add_parser("procedure"); p.add_argument("action", choices=["run"]); \
        p.add_argument("file", nargs="?", help="JSON: {procedure, events} or a procedure spec"); \
        p.set_defaults(fn=cmd_procedure)
    p = sub.add_parser("intent"); p.add_argument("action", choices=["check", "audit"]); \
        p.add_argument("file", nargs="?", help="check: {declaration, effects}; audit: {entries}"); \
        p.set_defaults(fn=cmd_intent)
    p = sub.add_parser("handoff"); p.add_argument("action", choices=["audit"]); \
        p.add_argument("file", nargs="?", help="JSON: {text, ledger}"); \
        p.set_defaults(fn=cmd_handoff)
    sub.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)
    p = sub.add_parser("providers"); p.add_argument("action", nargs="?", default="ls", choices=["ls", "add", "rm", "default", "rm-model"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_providers)
    p = sub.add_parser("eval"); p.add_argument("action", choices=["tasks", "run", "select"]); \
        p.add_argument("--task"); p.add_argument("--model"); p.add_argument("--max-steps", type=int, default=6); \
        p.add_argument("value", nargs="?", help="select: the candidates JSON file"); \
        p.add_argument("--budget", type=float, default=100.0,
                       help="select: evaluation budget (same unit as each candidate's cost)"); \
        p.add_argument("--cost-cap", type=float, default=None,
                       help="select: maximum per-run deployment cost"); \
        p.add_argument("--no-save", action="store_true"); p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("voice"); p.add_argument("action", choices=["status", "stt", "tts"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_voice)
    p = sub.add_parser("events"); p.add_argument("--since", type=int, default=0); \
        p.add_argument("--limit", type=int, default=40); p.add_argument("--session"); \
        p.add_argument("--kind"); p.set_defaults(fn=cmd_events)
    p = sub.add_parser("roles"); p.add_argument("action", choices=["show", "set", "clear", "reset"]); \
        p.add_argument("--session", required=True, help="session id or agent id (AX)"); \
        p.add_argument("--text", help="role text ('-' or omitted reads stdin)"); p.set_defaults(fn=cmd_roles)
    p = sub.add_parser("agents"); p.add_argument("action", choices=["ls", "new", "set", "rm"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--name"); p.add_argument("--role"); \
        p.add_argument("--model"); p.add_argument("--reports-to"); p.set_defaults(fn=cmd_agents)
    p = sub.add_parser("routines"); p.add_argument("action", choices=["ls", "new", "rm", "enable", "disable"]); p.add_argument("value", nargs="?"); p.add_argument("--agent"); p.add_argument("--every", type=int, default=3600); p.set_defaults(fn=cmd_routines)
    p = sub.add_parser("jobs"); p.add_argument("action", choices=["ls", "new", "run", "wake", "get"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--to"); p.add_argument("--blocked-by"); \
        p.add_argument("--agents"); p.add_argument("--coordinator"); p.add_argument("--mode"); \
        p.set_defaults(fn=cmd_jobs)
    args = ap.parse_args()
    if args.cmd == "plan":
        args.goal = args.value if getattr(args, "action", None) in ("generate", "set") else None
        args.id = args.value if getattr(args, "action", None) == "toggle" else None
    if args.cmd == "control":
        args.value, args.value2 = args.action, args.run
    if args.cmd == "tasks":
        args.value = args.value
    args.fn(args)


if __name__ == "__main__":
    main()

