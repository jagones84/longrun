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
  python3 forge.py harness [GROUP]      # every per-paper group: actions + where its JSON goes
  python3 forge.py skills stale | skills value FILE.json | skills repair FILE.json --map old=new
  python3 forge.py approvals audit [FILE.json]   # no FILE: the live approval store
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
        # completeness. With no FILE this audits the RUNNING harness: the tool
        # gate records decision -> call -> dispatch -> effect on every approval,
        # and `approvals.audit_records()` is the one adapter to the auditor's
        # shape. A FILE is still accepted for a hand-written ledger.
        from longrun.harness.checks import approval_audit
        from longrun.tools import approvals as _ap
        if args.value:
            try:
                with open(args.value, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError) as e:
                print("bad file:", e, file=sys.stderr)
                sys.exit(2)
            rows = doc.get("records") if isinstance(doc, dict) else doc
            source = "file"
        else:
            rows = _ap.audit_records()
            source = "live-store"
        out = approval_audit.audit(rows or [])
        out["source"] = source
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


# ------------------------------------------------------- harness commands ---
# Every per-paper group below is the same three steps: read one JSON record,
# call one pure checker, print its verdict and turn the verdict into an exit
# code. These two helpers are the ONE implementation of the first and third
# step — the old copies drifted (some took `doc["x"]`, some `doc["x"] or doc`,
# and the module's FORMAT was never checked at all).

def _load_doc(args, usage, allow_list=False):
    """Read a harness group's JSON input, or exit 2 with that group's usage.

    `file` or `value` is the path (both spellings exist in the parser). A
    top-level array is accepted only where the checker takes a bare sequence;
    otherwise a list is refused, so a document with the wrong shape can never
    reach a checker as an empty default.
    """
    path = getattr(args, "file", None) or getattr(args, "value", None)
    if not path:
        print("usage: " + usage, file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("bad file:", e, file=sys.stderr)
        sys.exit(2)
    if isinstance(doc, dict) or (allow_list and isinstance(doc, list)):
        return doc
    print("bad file: expected a JSON object%s in %s"
          % (" or array" if allow_list else "", path), file=sys.stderr)
    sys.exit(2)


def _emit(mod, out, ok=None, codes=None):
    """Print one harness verdict and exit with an explicit code.

    Every module declares `FORMAT` and stamps it on every result; a result that
    does not carry the module's own format is a wiring bug (a renamed key, a
    half-built record), so it exits 2 instead of letting a wrong key quietly
    flip the exit code. `ok(out)` maps a verdict to 0/1; `codes(out)` overrides
    that for tri-state groups (effect_types uses 0 safe / 1 unsafe / 3
    undecidable). With neither, any verdict exits 0 (report-only groups).
    """
    expected = getattr(mod, "FORMAT", None)
    got = out.get("format") if isinstance(out, dict) else None
    if expected and got != expected:
        print("harness error: %s returned format %r, expected %r"
              % (getattr(mod, "__name__", mod), got, expected), file=sys.stderr)
        sys.exit(2)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if codes is not None:
        sys.exit(codes(out))
    sys.exit(0 if (ok is None or ok(out)) else 1)


def cmd_episodes(args):
    """Round 115 (arXiv:2611.13254): validate a fault episode record and name controls."""
    from longrun.harness.checks import fault_episode
    doc = _load_doc(args, "episodes audit FILE.json")
    out = fault_episode.audit(doc)
    out["controls"] = fault_episode.controls(doc)["controls"]
    _emit(fault_episode, out, lambda o: o["verdict"] == "complete")


def cmd_contract(args):
    """Round 115 (arXiv:2611.15207): a declared call-order contract vs a sequence."""
    from longrun.harness.checks import api_contract
    doc = _load_doc(args, "contract check FILE.json")
    out = api_contract.check(doc.get("contract") or {}, doc.get("sequence") or [])
    _emit(api_contract, out, lambda o: o["verdict"] == "pass")


def cmd_recovery(args):
    """Round 116 (arXiv:2610.41453): what a timeout lets you re-issue safely."""
    from longrun.harness import effect_recovery
    doc = _load_doc(args, "recovery adjudicate|trace FILE.json")
    if args.action == "trace":
        out = effect_recovery.trace_safety(doc.get("trace") or [], doc.get("capabilities") or {})
        _emit(effect_recovery, out, lambda o: o["verdict"] == "clean")
    out = effect_recovery.adjudicate(doc)
    _emit(effect_recovery, out,
          lambda o: o["certificate"] in ("goal-satisfied", "safe-stop"))


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
        _emit(effect_types, out, lambda o: o["verdict"] in ("typed", "partial"))
    doc = _load_doc(args, "effects coverage|verify FILE.json")
    if args.action == "coverage":
        out = effect_types.coverage(doc.get("catalog") or {})
        _emit(effect_types, out, lambda o: o["verdict"] == "typed")
    out = effect_types.verify_trace(doc.get("trace") or [], doc.get("catalog") or {})
    # 0 safe, 1 proven unsafe, 3 not decidable (an untyped call left it unjudged).
    _emit(effect_types, out,
          codes=lambda o: {"safe": 0, "unsafe": 1}.get(o["verdict"], 3))


def _context_cost(args):
    """Round 116 (arXiv:2611.22238): price a run, or compare two policies, in money."""
    from longrun.harness.checks import context_cost
    doc = _load_doc(args, "context cost FILE.json")
    prices = doc.get("prices")
    if "runs" in doc:
        out = context_cost.screen(doc.get("runs") or {}, prices, doc.get("baseline") or "baseline")
    elif "treatment" in doc:
        out = context_cost.compare(doc.get("baseline") or {}, doc["treatment"], prices,
                                   doc.get("label") or "treatment")
    else:
        out = context_cost.run_cost(doc.get("run") or doc, prices)
    _emit(context_cost, out,
          lambda o: o.get("verdict") not in ("more-expensive", "no-baseline"))


def cmd_commit(args):
    """Round 117 (arXiv:2611.19663): repair, replan or abandon, by damage depth."""
    from longrun.plan import commitment
    doc = _load_doc(args, "commit decide|diagnose FILE.json")
    out = commitment.worth_diagnosis(doc) if args.action == "diagnose" else commitment.decide(doc)
    if args.action == "diagnose":
        _emit(commitment, out, lambda o: o["worth"])
    _emit(commitment, out,
          lambda o: o["decision"] in ("repair", "replan", "abandon"))


def cmd_expectations(args):
    """Round 117 (arXiv:2611.02438): does the batch still match its expectations?"""
    from longrun.harness.checks import expectations
    doc = _load_doc(args, "expectations verify|savings FILE.json")
    steps = doc.get("steps") or []
    if args.action == "savings":
        out = expectations.savings(steps, doc.get("tokens_per_step"))
    else:
        out = expectations.verify(steps, doc.get("keys"))
    _emit(expectations, out, lambda o: o.get("action", "continue") == "continue")


def cmd_governance(args):
    """Round 117 (arXiv:2611.06682): ready, waiting or forbidden from an ontology."""
    from longrun.harness.checks import governance
    doc = _load_doc(args, "governance decide|check FILE.json")
    if args.action == "check":
        out = governance.check_ontology(doc.get("ontology") or {})
        _emit(governance, out, lambda o: o["verdict"] == "consistent")
    out = governance.decide(doc.get("call") or {}, doc.get("ontology") or {}, doc.get("state") or {})
    _emit(governance, out, lambda o: o["decision"] == "ready")


def cmd_capsule(args):
    """Round 120 (arXiv:2611.10022): compile one invocation into a replayable capsule."""
    from longrun.harness.checks import skill_cache
    doc = _load_doc(args, "capsule compile|replay|savings FILE.json")
    if args.action == "compile":
        out = skill_cache.compile_capsule(doc.get("invocation") or doc, doc.get("skill"))
        _emit(skill_cache, out, lambda o: o["ok"])
    cap = doc.get("capsule") or {}
    if args.action == "savings":
        out = skill_cache.savings(cap, doc.get("tokens_per_step"), doc.get("model_tokens"))
    else:
        out = skill_cache.replay(cap, doc.get("state") or doc)
    _emit(skill_cache, out, lambda o: o.get("decision") in ("reuse", None))


def cmd_flow(args):
    """Round 120 (arXiv:2611.21520): judge a relay by behaviour and policy."""
    from longrun.harness.checks import flow_guard
    doc = _load_doc(args, "flow judge|calibrate|evaluate FILE.json")
    if args.action == "judge":
        out = flow_guard.judge(doc.get("relay") or doc)
    elif args.action == "calibrate":
        out = flow_guard.calibrate(doc.get("scores") or [], doc.get("labels") or [],
                                   doc.get("target_fpr", 0.05))
    else:
        out = flow_guard.evaluate(doc.get("scores") or [], doc.get("labels") or [],
                                  doc.get("threshold"))
    _emit(flow_guard, out, lambda o: o.get("decision") in ("allow", None))


def cmd_selfdirected(args):
    """Round 120 (arXiv:2611.23219): was the improvement loop the agent's own?"""
    from longrun.harness.checks import self_directed
    doc = _load_doc(args, "selfdirected audit|transfer FILE.json")
    out = (self_directed.transfer(doc) if args.action == "transfer"
           else self_directed.audit(doc))
    _emit(self_directed, out,
          lambda o: o.get("verdict") in ("self-directed", "improved", None))


def cmd_harnessevo(args):
    """Round 121 (arXiv:2611.22299): attribute a failure and gate a harness edit."""
    from longrun.harness.checks import harness_evolution
    doc = _load_doc(args, "harnessevo diagnose|admit|bloat FILE.json")
    if args.action == "diagnose":
        out = harness_evolution.diagnose(doc)
    elif args.action == "bloat":
        out = harness_evolution.bloat(doc.get("rules") or doc)
    else:
        out = harness_evolution.admit(doc)
    _emit(harness_evolution, out,
          lambda o: o.get("attribution") in ("harness", None)
          and o.get("decision") in ("merge", "route", "keep", None))


def cmd_contextpipeline(args):
    """Round 121 (arXiv:2610.36114): measure what a tool result loses before delivery."""
    from longrun.harness.checks import context_pipeline
    if args.action == "boundaries":
        _emit(context_pipeline, context_pipeline.boundaries())
    doc = _load_doc(args, "contextpipeline boundaries | deliver|profile FILE.json")
    if args.action == "deliver":
        out = context_pipeline.deliver(doc.get("payload") or doc,
                                       doc.get("budget", 0), doc.get("mode", "prefix"))
    else:
        out = context_pipeline.profile(doc.get("runs") or doc)
    _emit(context_pipeline, out, lambda o: o.get("ok", True))


def cmd_stepzero(args):
    """Round 121 (arXiv:2611.01953): gate the first processing of an opaque carrier."""
    from longrun.harness.checks import step_zero
    doc = _load_doc(args, "stepzero peek|extract|bind FILE.json")
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
    _emit(step_zero, out,
          lambda o: o.get("decision") in ("safe", "commit", "write", None))


def cmd_harnessrecord(args):
    """Round 122 (arXiv:2610.40917): is the harness that ran described, and did it stay in envelope?"""
    from longrun.harness.checks import harness_record
    doc = _load_doc(args, "harnessrecord audit|degradation|drift FILE.json")
    if args.action == "audit":
        out = harness_record.audit(doc)
    elif args.action == "degradation":
        out = harness_record.degradation(doc.get("changes") or doc,
                                         doc.get("declared") or {})
    else:
        out = harness_record.drift(doc.get("declared") or {},
                                  doc.get("observed") or {})
    _emit(harness_record, out,
          lambda o: o.get("ok") is not False and o.get("decision") != "block")


def cmd_conduct(args):
    """Round 122 (arXiv:2611.06116): score the action log, then compare it with the message."""
    from longrun.harness.checks import conduct_audit
    doc = _load_doc(args, "conduct score|stated|matrix FILE.json")
    if args.action == "score":
        out = conduct_audit.score(doc.get("episode") or doc)
    elif args.action == "stated":
        out = conduct_audit.stated(doc.get("episode") or doc)
    else:
        out = conduct_audit.matrix(doc.get("rows") or doc)
    _emit(conduct_audit, out,
          lambda o: o.get("outcome") in ("correct", None)
          and o.get("agrees") is not False)


def cmd_completion(args):
    """Round 122 (arXiv:2611.21407): an exit status is not a deliverable."""
    from longrun.harness.checks import completion_gate
    doc = _load_doc(args, "completion check|ladder FILE.json")
    out = (completion_gate.ladder(doc.get("rows") or doc) if args.action == "ladder"
           else completion_gate.check(doc.get("run") or doc))
    _emit(completion_gate, out, lambda o: o.get("complete") is not False)


def cmd_skillret(args):
    """Round 123 (arXiv:2611.01115): retrieval calibrated by matched execution comparisons."""
    from longrun.harness.checks import skill_retrieval
    doc = _load_doc(args, "skillret calibrate|rank|apply FILE.json")
    if args.action == "calibrate":
        out = skill_retrieval.calibrate(doc.get("pairs") or doc)
    elif args.action == "rank":
        out = skill_retrieval.rank(doc.get("candidates") or doc,
                                   doc.get("learned") or {})
    else:
        out = skill_retrieval.apply(doc.get("learned") or {}, doc.get("skill"))
    _emit(skill_retrieval, out, lambda o: o.get("write") is not False)


def cmd_ruleret(args):
    """Round 123 (arXiv:2611.01042): closure-based rule retrieval under a context budget."""
    from longrun.harness.checks import rule_retrieval
    doc = _load_doc(args, "ruleret closure|audit FILE.json")
    if args.action == "closure":
        out = rule_retrieval.closure(doc.get("rules") or [], doc.get("seeds") or [],
                                     doc.get("budget"))
    else:
        out = rule_retrieval.audit(doc.get("selection") or [], doc.get("rules") or [],
                                   doc.get("seeds") or [], doc.get("budget"))
    _emit(rule_retrieval, out,
          lambda o: o.get("ok") is not False and o.get("decision") != "refuse")


def cmd_skillquality(args):
    """Round 123 (arXiv:2610.38147): nine-dimension skill profile, execution-free estimate."""
    from longrun.harness.checks import skill_quality
    doc = _load_doc(args, "skillquality profile|predict FILE.json")
    if args.action == "profile":
        out = skill_quality.profile(doc.get("skill") or doc)
    else:
        out = skill_quality.predict(doc.get("skill") or {}, doc.get("references") or [],
                                    doc.get("k", 3))
    _emit(skill_quality, out,
          lambda o: o.get("verdict") in ("complete", "partial", None))


def cmd_opspolicy(args):
    """Round 124 (arXiv:2611.15006): harness as an operational policy, per-model affinity."""
    from longrun.harness.checks import operational_policy
    doc = _load_doc(args, "opspolicy realize|ground|affinity|route FILE.json")
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
    _emit(operational_policy, out,
          lambda o: not (o.get("decision") == "diagnose" or o.get("supported") is False))


def cmd_execpolicy(args):
    """Round 124 (arXiv:2611.21688): reversal, frozen-panel replacement, amortization."""
    from longrun.harness.checks import execution_policy
    doc = _load_doc(args, "execpolicy reversal|confirm|efficiency|amortize FILE.json")
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
    _emit(execution_policy, out,
          codes=lambda o: 1 if o.get("decision") == "retain" else 0)


def cmd_skilladapter(args):
    """Round 124 (arXiv:2611.17007): adapter binding, preload re-check, evidence expiry."""
    from longrun.harness.checks import skill_adapter
    doc = _load_doc(args, "skilladapter bind|recheck|expire|maintain FILE.json")
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
    _emit(skill_adapter, out,
          codes=lambda o: 1 if args.action == "bind" and not o.get("changes") else 0)


def cmd_intake(args):
    """Round 124 (transcript OrcsMi2-IcM): deterministic gate, mandate, shadow-first work."""
    from longrun.harness.checks import intake_gate
    doc = _load_doc(args, "intake admit|mandate|subscribe|preset|shadow FILE.json")
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
    _emit(intake_gate, out,
          codes=lambda o: 1 if o.get("decision") == "ignore" or o.get("valid") is False else 0)


def cmd_memcredit(args):
    """Round 125 (arXiv:2611.15600): memory arbitrated by decision utility, not relevance."""
    from longrun.harness.checks import memory_credit
    doc = _load_doc(args, "memcredit credit|arbitrate|sparsity FILE.json")
    if args.action == "credit":
        out = memory_credit.credit(doc.get("candidate") or {}, doc.get("reference") or [])
    elif args.action == "arbitrate":
        out = memory_credit.arbitrate(doc.get("candidates") or [], doc.get("budget"),
                                      doc.get("min_credit", 0.0))
    else:
        out = memory_credit.sparsity(doc.get("rows") or doc)
    _emit(memory_credit, out,
          codes=lambda o: 1 if o.get("findings") and args.action == "arbitrate"
          and not o.get("selected") else 0)


def cmd_lessongate(args):
    """Round 125 (arXiv:2611.14326): a lesson is committed only after its probes pass."""
    from longrun.harness.checks import lesson_gate
    doc = _load_doc(args, "lessongate hypothesis|trial|probe FILE.json")
    if args.action == "hypothesis":
        out = lesson_gate.hypothesis(doc.get("lesson") or doc)
    elif args.action == "trial":
        out = lesson_gate.trial(doc.get("lesson") or {}, doc.get("state"),
                                doc.get("persist", False))
    else:
        out = lesson_gate.probe(doc.get("lesson") or {}, doc.get("results") or {})
    _emit(lesson_gate, out,
          lambda o: o.get("decision") in ("commit", None) and o.get("applied") is not False
          and o.get("valid") is not False)


def cmd_seclattice(args):
    """Round 125 (arXiv:2611.13960): product taint lattice, attenuation, provenance ledger."""
    from longrun.harness.checks import security_lattice
    doc = _load_doc(args, "seclattice admit|attenuate|write|read|effect FILE.json")
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
    _emit(security_lattice, out,
          codes=lambda o: 1 if o.get("allowed") is False or o.get("valid") is False
          or o.get("found") is False else 0)


def cmd_optmemory(args):
    """Round 126 (arXiv:2611.18856): the optimizer's memory of why a harness was edited."""
    from longrun.harness.checks import optimizer_memory
    doc = _load_doc(args, "optmemory record|continuity|advantage FILE.json")
    if args.action == "record":
        out = optimizer_memory.record(doc.get("memory") or {}, doc.get("edit") or {})
    elif args.action == "continuity":
        out = optimizer_memory.continuity(doc.get("memory") or {},
                                          doc.get("target") or {})
    else:
        out = optimizer_memory.advantage(doc.get("pairs") or doc)
    _emit(optimizer_memory, out,
          codes=lambda o: 1 if any(f["kind"] in ("no-root-cause", "not-significant", "no-pairs")
                                   for f in (o.get("findings") or [])) else 0)


def cmd_detour(args):
    """Round 126 (arXiv:2611.20844): success, attainment, residual work, detour."""
    from longrun.harness.checks import detour
    doc = _load_doc(args, "detour attainment|residual|progress|classify|rank FILE.json")
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
    _emit(detour, out,
          codes=lambda o: 1 if any(f["kind"] in ("below-optimum", "no-optimum")
                                   for f in (o.get("findings") or [])) else 0)


def cmd_patchprobe(args):
    """Round 126 (arXiv:2611.20514): control-gated verdicts, sibling paths, provenance."""
    from longrun.harness.checks import patch_probe
    doc = _load_doc(args, "patchprobe verdict|compare|provenance|validate FILE.json")
    if args.action == "verdict":
        out = patch_probe.verdict(doc.get("control_ok"), doc.get("effect_seen"),
                                  doc.get("token_ok", True))
    elif args.action == "compare":
        out = patch_probe.compare(doc.get("b0") or {}, doc.get("sibling") or {})
    elif args.action == "provenance":
        out = patch_probe.provenance(doc.get("runs") or [], doc.get("advisory") or {})
    else:
        out = patch_probe.validate(doc.get("runs") or [])
    _emit(patch_probe, out,
          lambda o: o.get("valid") is not False and o.get("verdict") != "INCONCLUSIVE")


def cmd_poison(args):
    """Round 127 (arXiv:2611.09721): a payload's lifecycle through agent memory."""
    from longrun.harness.checks import memory_poison
    doc = _load_doc(args, "poison trace|descendants FILE.json")
    if args.action == "trace":
        out = memory_poison.trace(doc.get("run") or doc)
    else:
        out = memory_poison.descendants(doc.get("store") or {}, doc.get("poisoned") or [])
    _emit(memory_poison, out,
          codes=lambda o: 1 if o.get("isr") == 0 or o.get("br") == 0 else 0)


def cmd_boundary(args):
    """Round 127 (arXiv:2611.21259): identity, authorization and propagation at a seam."""
    from longrun.harness.checks import trust_boundary
    doc = _load_doc(args, "boundary evaluate|classify FILE.json")
    if args.action == "evaluate":
        out = trust_boundary.evaluate(doc.get("call") or doc)
        failed = out.get("decision") != "allow"
    else:
        out = trust_boundary.classify(doc.get("outcome") or doc)
        failed = False
    _emit(trust_boundary, out, lambda o: not failed)


def cmd_gapleak(args):
    """Round 127 (arXiv:2611.22223): information gap, disclosure, submission-time filter."""
    from longrun.harness.checks import gap_leak
    doc = _load_doc(args, "gapleak gap|disclosure|verify|compare FILE.json")
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
    _emit(gap_leak, out,
          codes=lambda o: 1 if o.get("preserved_required") is False else 0)


def cmd_binding(args):
    """Round 128 (arXiv:2611.21577): a tool advertisement is not a provider identity."""
    from longrun.harness.checks import provider_binding
    doc = _load_doc(args, "binding alignment|pressure|bind|resolve|outcomes|judge|sweep FILE.json")
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
    _emit(provider_binding, out,
          codes=lambda o: 1 if (args.action == "bind" and not o.get("provider_bound"))
          or (args.action == "resolve" and o.get("decision") != "bound") else 0)


def cmd_gateway(args):
    """Round 128 (arXiv:2611.19123): code mode, stubs, router and fallback accounting."""
    from longrun.harness.checks import gateway_shape
    doc = _load_doc(args, "gateway utility|delta|holm|claim|stub|hints|fallback|advise FILE.json")
    if args.action == "utility":
        # A scalar helper: the group's own FORMAT is what makes it a group result.
        out = {"format": gateway_shape.FORMAT,
               "utility": gateway_shape.utility(doc.get("cell") or doc)}
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
    _emit(gateway_shape, out)


def cmd_scoring(args):
    """Round 128 (arXiv:2611.20335): pointwise, setwise or candidate attention."""
    from longrun.harness.checks import scoring_mode
    doc = _load_doc(args, "scoring depends|reversal|select|paired|advise|binary|learn FILE.json")
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
    _emit(scoring_mode, out)


def cmd_reversibility(args):
    """Round 129 (arXiv:2611.22075): reversibility classes and recovery claims."""
    from longrun.harness.checks import reversibility
    doc = _load_doc(args, "reversibility classify|restoration|capture|classes|recovery|replay FILE.json")
    if args.action == "classify":
        out = reversibility.classify(doc.get("call") or doc, doc.get("record"))
    elif args.action == "restoration":
        out = reversibility.restoration_requirements(doc.get("state") or doc)
    elif args.action == "capture":
        out = reversibility.capture_override(doc.get("base_class"), doc.get("override") or doc)
    elif args.action == "classes":
        out = reversibility.policy_for(doc.get("class"))
    elif args.action == "recovery":
        out = reversibility.recovery(doc.get("observations") or [])
    else:
        out = reversibility.replay(doc.get("rows") or [], doc.get("baseline_policy"))
    _emit(reversibility, out)


def cmd_gain(args):
    """Round 129 (arXiv:2611.20736): gain-based stopping under a quality allowance."""
    from longrun.harness.checks import gain_control
    doc = _load_doc(args, "gain vector|interpolate|reference|decide|calibrate|frontier|matched|verdict|advise FILE.json")
    if args.action == "vector":
        out = gain_control.gain_vector(doc.get("score"))
    elif args.action == "interpolate":
        out = gain_control.interpolate(doc.get("gains") or [], doc.get("reference"))
    elif args.action == "reference":
        out = gain_control.reference(doc.get("mode"), doc.get("current"),
                                     doc.get("best_previous"))
    elif args.action == "decide":
        out = gain_control.decide(doc.get("gains") or [], doc.get("mode"),
                                  doc.get("current"), doc.get("best_previous"),
                                  doc.get("threshold"))
    elif args.action == "calibrate":
        out = gain_control.calibrate(doc.get("candidates") or [], doc.get("full") or {},
                                     doc.get("allowance"))
    elif args.action == "frontier":
        out = gain_control.frontier(doc.get("points") or [])
    elif args.action == "matched":
        out = gain_control.matched_quality(doc.get("points") or [], doc.get("target"))
    elif args.action == "verdict":
        out = gain_control.verdict(doc.get("estimate"), doc.get("bounds") or [],
                                   doc.get("level") or 0.975)
    else:
        out = gain_control.advise(doc.get("profile") or doc)
    _emit(gain_control, out)


def cmd_history(args):
    """Round 129 (arXiv:2611.14654): a record edited against a live world."""
    from longrun.harness.checks import history_truth
    doc = _load_doc(args, "history agree|disclose|effect|interaction|recheck|advise FILE.json")
    if args.action == "agree":
        out = history_truth.agreement(doc.get("record") or {}, doc.get("world") or {})
    elif args.action == "disclose":
        out = history_truth.disclosure_vs_assertion(doc.get("record") or doc)
    elif args.action == "effect":
        out = history_truth.effect(doc.get("arms") or doc)
    elif args.action == "interaction":
        out = history_truth.interaction(doc.get("cells") or doc)
    elif args.action == "recheck":
        out = history_truth.recheck(doc.get("runs") or [])
    else:
        out = history_truth.advise(doc.get("policy") or doc)
    _emit(history_truth, out)


def cmd_composed(args):
    """Round 130 (arXiv:2611.22971): a safe screen is not a safe task."""
    from longrun.harness.checks import composed_harm
    doc = _load_doc(args, "composed compose|screens|recognition|channel|gate|advise FILE.json")
    if args.action == "compose":
        out = composed_harm.compose(doc.get("facts") or [],
                                    doc.get("binding") or {})
    elif args.action == "screens":
        out = composed_harm.screen_check(doc.get("screens") or [])
    elif args.action == "recognition":
        out = composed_harm.recognition_vs_action(doc.get("rows") or [])
    elif args.action == "channel":
        out = composed_harm.channel_effect(doc.get("rows") or [])
    elif args.action == "gate":
        out = composed_harm.commit_gate(doc.get("state") or doc)
    else:
        out = composed_harm.advise(doc.get("profile") or doc)
    _emit(composed_harm, out)


def cmd_measure(args):
    """Round 130 (arXiv:2611.21784): measurement choices decide the verdict."""
    from longrun.harness.checks import measurement_spec
    if args.action == "checklist":
        _emit(measurement_spec, measurement_spec.checklist())
    doc = _load_doc(
        args, "measure specify|specs|decides|power|classifiers|checklist FILE.json")
    if args.action == "specify":
        out = measurement_spec.specify(doc.get("choice"), doc.get("level"),
                                       **(doc.get("params") or {}))
    elif args.action == "specs":
        out = measurement_spec.specifications(doc.get("rows") or [])
    elif args.action == "decides":
        out = measurement_spec.decides(doc.get("rows") or [])
    elif args.action == "power":
        out = measurement_spec.power(doc.get("clusters"),
                                     doc.get("detectable_below", 0.32),
                                     doc.get("detectable_above", 3.13))
    else:
        out = measurement_spec.classifier_family(doc.get("rows") or [])
    _emit(measurement_spec, out)


def cmd_trap(args):
    """Round 130 (arXiv:2611.19295): traps on the path, alerts that can be trusted."""
    from longrun.harness.checks import trap_path
    doc = _load_doc(args, "trap position|ablation|alert|scope|falsepositive FILE.json")
    if args.action == "position":
        out = trap_path.path_position(doc.get("bait") or {},
                                      doc.get("weakness") or {})
    elif args.action == "ablation":
        out = trap_path.ablation(doc.get("baseline") or {},
                                 doc.get("hardened") or {},
                                 doc.get("defended") or {})
    elif args.action == "alert":
        out = trap_path.alert_gate(doc.get("event") or {},
                                   doc.get("rules") or {})
    elif args.action == "scope":
        out = trap_path.scope(doc.get("revocation") or {},
                              doc.get("clients") or [])
    else:
        out = trap_path.false_positive(doc.get("bait_use") or {},
                                       doc.get("legitimate") or [])
    _emit(trap_path, out)


def cmd_evidence(args):
    """Round 131 (arXiv:2611.22169): admission is decided outside the reasoner."""
    from longrun.harness.checks import evidence_gate
    doc = _load_doc(args, "evidence admit|gates|firstorder|advise FILE.json")
    if args.action == "admit":
        out = evidence_gate.admit(doc.get("cards") or [], doc.get("context") or {})
    elif args.action == "gates":
        out = evidence_gate.gates(doc.get("rows") or [])
    elif args.action == "firstorder":
        out = evidence_gate.first_order(doc.get("rows") or [])
    else:
        out = evidence_gate.advise(doc.get("profile") or doc)
    _emit(evidence_gate, out)


def cmd_stress(args):
    """Round 131 (arXiv:2611.22583): utility constrains parenthood, stressors evolve."""
    from longrun.harness.checks import stress_evolution
    doc = _load_doc(args, "stress qualify|promote|pareto|parent|compare|transfer|advise FILE.json")
    if args.action == "qualify":
        out = stress_evolution.qualify(doc.get("candidate") or doc)
    elif args.action == "promote":
        out = stress_evolution.promote(doc.get("result") or doc)
    elif args.action == "pareto":
        out = stress_evolution.pareto(doc.get("candidates") or [])
    elif args.action == "parent":
        out = stress_evolution.sample_parent(doc.get("front") or [],
                                             doc.get("seed") or 0)
    elif args.action == "compare":
        out = stress_evolution.compare_search(doc.get("configs") or [])
    elif args.action == "transfer":
        out = stress_evolution.transfer(doc.get("stressors") or [],
                                        doc.get("recipients") or None)
    else:
        out = stress_evolution.advise(doc.get("profile") or doc)
    _emit(stress_evolution, out)


def cmd_trial(args):
    """Round 131 (arXiv:2611.19359): one run is not enough."""
    from longrun.harness.checks import paired_trial
    doc = _load_doc(args, "trial paired|noise|claim|mechanism|funnel|budget|advise FILE.json")
    if args.action == "paired":
        out = paired_trial.paired(doc.get("rows") or [])
    elif args.action == "noise":
        out = paired_trial.noise_floor(doc.get("run1") or [], doc.get("run2") or [])
    elif args.action == "claim":
        floor = paired_trial.noise_floor(doc.get("run1") or [], doc.get("run2") or []) \
            if doc.get("run1") else doc.get("floor")
        out = paired_trial.claim(doc.get("rows") or [], doc.get("strata"), floor)
    elif args.action == "mechanism":
        out = paired_trial.mechanism(doc.get("stats") or doc)
    elif args.action == "funnel":
        out = paired_trial.funnel(doc.get("stages") or [])
    elif args.action == "budget":
        out = paired_trial.budget(doc.get("points") or [])
    else:
        out = paired_trial.advise(doc.get("profile") or doc)
    _emit(paired_trial, out)


def cmd_scope(args):
    """Round 132 (arXiv:2611.22835): a passing check is not the requested operation."""
    from longrun.harness.checks import evidence_scope
    doc = _load_doc(args, "scope item|claim|witness|obligation|reach|classify|explain|advise FILE.json")
    if args.action == "item":
        out = evidence_scope.item(doc.get("source"), doc.get("check"), doc.get("phase"),
                                  doc.get("operation"), doc.get("witness"))
    elif args.action == "claim":
        out = evidence_scope.scope(doc.get("claim") or doc)
    elif args.action == "witness":
        out = evidence_scope.witness(doc.get("evidence") or {}, doc.get("expected_operation"))
    elif args.action == "obligation":
        out = evidence_scope.obligation(doc.get("evidence") or {}, doc.get("obligation"))
    elif args.action == "reach":
        out = evidence_scope.reachability(doc.get("run") or doc)
    elif args.action == "classify":
        out = evidence_scope.classify(doc.get("outcome") or doc)
    elif args.action == "explain":
        out = evidence_scope.explanation(doc.get("repair") or doc)
    else:
        out = evidence_scope.advise(doc.get("profile") or doc)
    _emit(evidence_scope, out)


def cmd_round(args):
    """Round 132 (arXiv:2611.22661): the between-round decision is an object."""
    from longrun.harness.checks import round_controller
    doc = _load_doc(args, "round champion|decision|lesson|guardrails|ladder|progress|frontier|advise FILE.json")
    if args.action == "champion":
        out = round_controller.champion(doc.get("rounds") or [])
    elif args.action == "decision":
        out = round_controller.decision(doc.get("decision") or doc)
    elif args.action == "lesson":
        out = round_controller.lesson(doc.get("entry") or doc)
    elif args.action == "guardrails":
        out = round_controller.guardrails(doc.get("decision") or {}, doc.get("state") or {})
    elif args.action == "ladder":
        out = round_controller.context_ladder(doc.get("rows") or [])
    elif args.action == "progress":
        out = round_controller.progress(doc.get("rounds") or [])
    elif args.action == "frontier":
        out = round_controller.frontier(doc.get("decision") or doc)
    else:
        out = round_controller.advise(doc.get("profile") or doc)
    _emit(round_controller, out)


def cmd_attest(args):
    """Round 132 (arXiv:2611.23202): trust in the build and in the record."""
    from longrun.harness.checks import attestation_trust
    doc = _load_doc(args, "attest identity|certificate|build|calls|accountability|measure|advise FILE.json")
    if args.action == "identity":
        out = attestation_trust.identity(doc.get("request") or doc)
    elif args.action == "certificate":
        out = attestation_trust.certificate(doc.get("cert") or {}, doc.get("federation") or ())
    elif args.action == "build":
        out = attestation_trust.attestation(doc.get("build") or {}, doc.get("approved") or {})
    elif args.action == "calls":
        out = attestation_trust.policy(doc.get("call") or doc)
    elif args.action == "accountability":
        out = attestation_trust.accountability(doc.get("entries") or [])
    elif args.action == "measure":
        out = attestation_trust.measure(doc.get("rows") or [])
    else:
        out = attestation_trust.advise(doc.get("profile") or doc)
    _emit(attestation_trust, out)


def cmd_criteria(args):
    """Round 133 (arXiv:2611.23074): per-criterion ternary verdicts at runtime."""
    from longrun.harness.checks import criterion_verification
    doc = _load_doc(args, "criteria criterion|verdict|coverage|escalate|measure|decompose|advise FILE.json")
    if args.action == "criterion":
        out = criterion_verification.criterion(
            doc.get("text"), doc.get("source") or "developer",
            doc.get("polarity") or "positive", doc.get("precondition"),
            doc.get("trace_decidable", True), doc.get("compounds") or 0)
    elif args.action == "verdict":
        out = criterion_verification.verdict(doc.get("record") or doc)
    elif args.action == "coverage":
        out = criterion_verification.coverage(doc.get("criteria") or [],
                                              doc.get("trace") or {})
    elif args.action == "escalate":
        out = criterion_verification.escalate(doc.get("rows") or [])
    elif args.action == "measure":
        out = criterion_verification.measure(doc.get("rows") or [])
    elif args.action == "decompose":
        out = criterion_verification.decomposition(
            doc.get("text") or "", doc.get("expected_per_words") or 20, doc.get("actual"))
    else:
        out = criterion_verification.advise(doc.get("profile") or doc)
    _emit(criterion_verification, out)


def cmd_rubric(args):
    """Round 133 (arXiv:2611.22841): the verifier is the object."""
    from longrun.harness.checks import rubric_verification
    doc = _load_doc(args, "rubric capability|verifier|errors|batch|ablation|agreement|advise FILE.json")
    if args.action == "capability":
        out = rubric_verification.capability(doc.get("name"), doc.get("description") or "")
    elif args.action == "verifier":
        out = rubric_verification.verifier(doc.get("config") or doc)
    elif args.action == "errors":
        out = rubric_verification.errors(doc.get("rows") or [])
    elif args.action == "batch":
        out = rubric_verification.batch(doc.get("rows") or [])
    elif args.action == "ablation":
        out = rubric_verification.ablation(doc.get("rows") or [])
    elif args.action == "agreement":
        out = rubric_verification.agreement(doc.get("rows") or [])
    else:
        out = rubric_verification.advise(doc.get("profile") or doc)
    _emit(rubric_verification, out)


def cmd_docmaint(args):
    """Round 133 (arXiv:2611.23142): a human correction is a gap signal."""
    from longrun.harness.checks import doc_maintenance
    doc = _load_doc(args, "docmaint signal|gap|tracker|pipeline|measure|advise FILE.json")
    if args.action == "signal":
        out = doc_maintenance.signal(doc.get("ticket") or doc)
    elif args.action == "gap":
        out = doc_maintenance.gap(doc.get("gap") or doc)
    elif args.action == "tracker":
        out = doc_maintenance.tracker(doc.get("entries") or [])
    elif args.action == "pipeline":
        out = doc_maintenance.pipeline(doc.get("draft") or doc)
    elif args.action == "measure":
        out = doc_maintenance.measure(doc.get("rows") or [])
    else:
        out = doc_maintenance.advise(doc.get("profile") or doc)
    _emit(doc_maintenance, out)


def cmd_priority(args):
    """Round 134 (arXiv:2611.22989): a priority says what to attend to, not how to judge."""
    from longrun.harness.checks import priority_criteria
    doc = _load_doc(args, "priority statement|report|trace|compare|evidence|revise|advise FILE.json")
    if args.action == "statement":
        out = priority_criteria.priority(doc.get("text") or "")
    elif args.action == "report":
        out = priority_criteria.report(doc.get("report") or doc)
    elif args.action == "trace":
        out = priority_criteria.trace(doc.get("row") or doc)
    elif args.action == "compare":
        out = priority_criteria.compare(doc.get("runs") or [])
    elif args.action == "evidence":
        out = priority_criteria.evidence(doc.get("path") or doc)
    elif args.action == "revise":
        out = priority_criteria.revise(doc.get("interface") or doc)
    else:
        out = priority_criteria.advise(doc.get("profile") or doc)
    _emit(priority_criteria, out)


def cmd_values(args):
    """Round 134 (arXiv:2611.23067): a value statement shapes what the agent builds."""
    from longrun.harness.checks import value_disposition
    doc = _load_doc(args, "values statement|compare|solutions|oversight|progress|advise FILE.json")
    if args.action == "statement":
        out = value_disposition.statement(doc.get("text") or "",
                                          doc.get("value") or "openness",
                                          doc.get("fixed", True), doc.get("paired", True),
                                          doc.get("words"))
    elif args.action == "compare":
        out = value_disposition.compare(doc.get("rows") or [])
    elif args.action == "solutions":
        out = value_disposition.solutions(doc.get("rows") or [])
    elif args.action == "oversight":
        out = value_disposition.oversight(doc.get("profile") or doc)
    elif args.action == "progress":
        out = value_disposition.progress(doc.get("rows") or [])
    else:
        out = value_disposition.advise(doc.get("profile") or doc)
    _emit(value_disposition, out)


def cmd_crossenv(args):
    """Round 134 (arXiv:2611.22777): a workflow that spans services needs joint verification."""
    from longrun.harness.checks import cross_env_tasks
    doc = _load_doc(args, "crossenv task|align|rules|validate|curriculum|measure|advise FILE.json")
    if args.action == "task":
        out = cross_env_tasks.task(doc.get("spec") or doc)
    elif args.action == "align":
        out = cross_env_tasks.align(doc.get("records") or [])
    elif args.action == "rules":
        out = cross_env_tasks.rules(doc.get("task") or doc)
    elif args.action == "validate":
        out = cross_env_tasks.validate(doc.get("row") or doc)
    elif args.action == "curriculum":
        out = cross_env_tasks.curriculum(doc.get("levels") or [])
    elif args.action == "measure":
        out = cross_env_tasks.measure(doc.get("rows") or [])
    else:
        out = cross_env_tasks.advise(doc.get("profile") or doc)
    _emit(cross_env_tasks, out)


def cmd_resolution(args):
    """Round 135 (arXiv:2611.23068): evolution stalls because improvements go unidentified."""
    from longrun.harness.checks import resolution_budget
    doc = _load_doc(
        args, "resolution runs|decompose|verdict|select|quality|advantage|advise FILE.json")
    if args.action == "runs":
        out = {"format": resolution_budget.FORMAT,
               "runs_required": resolution_budget.runs_required(
                   doc.get("margin"), doc.get("sd"),
                   doc.get("alpha", 0.05), doc.get("power", 0.8))}
    elif args.action == "decompose":
        out = resolution_budget.decompose(doc.get("rows") or doc.get("measurements") or [],
                                         doc.get("margin"))
    elif args.action == "verdict":
        out = resolution_budget.resolution(doc.get("rows") or doc.get("measurements") or [],
                                          doc.get("margin"), doc.get("budget", 8))
    elif args.action == "select":
        out = resolution_budget.selection(doc.get("pairs") or doc.get("rows") or [])
    elif args.action == "quality":
        out = resolution_budget.quality_at_k(doc.get("rows") or doc.get("pool") or [],
                                             doc.get("k", 1))
    elif args.action == "advantage":
        out = resolution_budget.advantage(doc.get("rows") or doc.get("pool") or [],
                                          doc.get("k", 1))
    else:
        out = resolution_budget.advise(doc.get("profile") or doc)
    _emit(resolution_budget, out)


def cmd_replay(args):
    """Round 135 (arXiv:2611.23151): a faster environment is admissible only if it replays."""
    from longrun.harness.checks import replay_parity
    doc = _load_doc(args, "replay trace|replay|variation|parity|render|timing|audit|advise FILE.json")
    if args.action == "trace":
        out = replay_parity.trace(doc.get("states") or doc.get("rollout") or [])
    elif args.action == "replay":
        out = replay_parity.replay(doc.get("record") or doc)
    elif args.action == "variation":
        out = replay_parity.variation(doc.get("record") or doc)
    elif args.action == "parity":
        out = replay_parity.parity(doc.get("source") or [], doc.get("port") or [],
                                   doc.get("tol", 1e-6))
    elif args.action == "render":
        out = replay_parity.render_parity(doc.get("mse_mean"), doc.get("mse_max"),
                                          doc.get("tol_mean", 1e-3), doc.get("tol_max", 1e-2))
    elif args.action == "timing":
        out = replay_parity.timing(doc.get("rows") or doc.get("windows") or [])
    elif args.action == "audit":
        out = replay_parity.audit(doc.get("record") or doc)
    else:
        out = replay_parity.advise(doc.get("profile") or doc)
    _emit(replay_parity, out)


def cmd_dialogue(args):
    """Round 135 (arXiv:2611.23119): what a teammate says is evidence about hidden state."""
    from longrun.harness.checks import dialogue_allocation
    doc = _load_doc(args, "dialogue posterior|entropy|speak|evidence|propositions|schedule|compare|audit|advise FILE.json")
    if args.action == "posterior":
        out = dialogue_allocation.posterior(doc.get("prior") or {}, doc.get("action"),
                                            doc.get("utterance"))
    elif args.action == "entropy":
        out = dialogue_allocation.entropy(doc.get("belief") or {})
    elif args.action == "speak":
        out = dialogue_allocation.speak(doc.get("belief") or {}, doc.get("epsilon", 0.7))
    elif args.action == "evidence":
        out = dialogue_allocation.evidence(doc.get("before") or [], doc.get("after") or [])
    elif args.action == "propositions":
        out = dialogue_allocation.propositions(
            doc.get("prior") or {}, doc.get("kind") or "none", doc.get("affected") or [],
            doc.get("evidence_likelihood"), doc.get("implied"))
    elif args.action == "schedule":
        out = dialogue_allocation.schedule(doc.get("n", 3), doc.get("rate", 0.025),
                                           doc.get("horizon", 300), doc.get("seed", 7))
    elif args.action == "compare":
        out = dialogue_allocation.compare(doc.get("comm") or [], doc.get("base") or [])
    elif args.action == "audit":
        out = dialogue_allocation.audit(doc.get("spec") or doc)
    else:
        out = dialogue_allocation.advise(doc.get("profile") or doc)
    _emit(dialogue_allocation, out)


def cmd_selective(args):
    """Round 136 (arXiv:2611.23174): an agent that picks the analysis pays for picking it."""
    from longrun.harness.checks import selective_replay
    doc = _load_doc(
        args, "selective correct|multiplier|gate|allocate|resample|audit|selfcorrect|detect|advise FILE.json")
    if args.action == "multiplier":
        value = selective_replay.multiplier(doc.get("p"), doc.get("tail_rate"),
                                            doc.get("body_rate"))
        out = {"format": selective_replay.FORMAT,
               "multiplier": None if value is None else round(value, 4)}
    elif args.action == "correct":
        out = selective_replay.corrected(
            doc.get("p"), doc.get("tail_matches"), doc.get("tail_replays"),
            doc.get("body_matches"), doc.get("body_replays"))
    elif args.action == "gate":
        out = selective_replay.gate(doc.get("corrected"), doc.get("alpha", 0.05))
    elif args.action == "allocate":
        out = selective_replay.allocation(doc.get("total"), doc.get("tail_rate"),
                                          doc.get("body_rate"), doc.get("floor", 1))
    elif args.action == "resample":
        out = selective_replay.resampling(doc.get("m"), doc.get("n"),
                                          doc.get("replacement", False),
                                          doc.get("max_fraction", 0.2))
    elif args.action == "audit":
        out = selective_replay.audit(doc.get("run") or doc)
    elif args.action == "selfcorrect":
        out = selective_replay.self_correction(doc.get("row") or doc)
    elif args.action == "detect":
        out = selective_replay.detect(doc.get("rows") or [])
    else:
        out = selective_replay.advise(doc.get("profile") or doc)
    _emit(selective_replay, out)


def cmd_continuation(args):
    """Round 136 (arXiv:2611.22888): a stop is not the limit; a burst is the signal."""
    from longrun.harness.checks import continuation_policy
    doc = _load_doc(args, "continuation rate|burst|gains|judgment|relabel|summary|rules|compare|methods|advise FILE.json")
    if args.action == "rate":
        out = continuation_policy.stop_rate(doc.get("turns") or [], doc.get("window"))
    elif args.action == "burst":
        out = continuation_policy.burst(doc.get("turns") or [], doc.get("window", 20),
                                        doc.get("rho", 0.2))
    elif args.action == "gains":
        out = continuation_policy.gains(doc.get("bins") or [])
    elif args.action == "judgment":
        out = continuation_policy.judgment(doc.get("text") or "")
    elif args.action == "relabel":
        out = continuation_policy.relabel(doc.get("text") or "")
    elif args.action == "summary":
        out = continuation_policy.summary(doc.get("record") or doc)
    elif args.action == "rules":
        out = continuation_policy.policy(doc.get("spec") or doc)
    elif args.action == "compare":
        out = continuation_policy.compare(doc.get("rows") or [])
    elif args.action == "methods":
        out = continuation_policy.methods(doc.get("rows") or [])
    else:
        out = continuation_policy.advise(doc.get("profile") or doc)
    _emit(continuation_policy, out)


def cmd_bench(args):
    """Round 136 (arXiv:2611.23045): the evidence is an experimental variable."""
    from longrun.harness.checks import evidence_replay
    doc = _load_doc(args, "bench state|freeze|leak|score|trajectory|paired|sources|memory|advise FILE.json")
    if args.action == "state":
        out = evidence_replay.state(doc.get("record") or doc)
    elif args.action == "freeze":
        out = evidence_replay.freeze(doc.get("spec") or doc)
    elif args.action == "leak":
        out = evidence_replay.leak(doc.get("rows") or [])
    elif args.action == "score":
        out = evidence_replay.score(doc.get("rows") or [])
    elif args.action == "trajectory":
        out = evidence_replay.trajectory(doc.get("states") or [])
    elif args.action == "paired":
        out = evidence_replay.paired(doc.get("rows") or [])
    elif args.action == "sources":
        out = evidence_replay.sources(doc.get("rows") or [], doc.get("model_spread"))
    elif args.action == "memory":
        out = evidence_replay.memory(doc.get("rows") or [])
    else:
        out = evidence_replay.advise(doc.get("profile") or doc)
    _emit(evidence_replay, out)


def cmd_deliberation(args):
    """Round 137 (arXiv:2611.22905): a generic summary can hide a missing design judgement."""
    from longrun.harness.checks import deliberation_audit
    doc = _load_doc(args, "deliberation type|match|tags|metadata|summary|ablation|audit|advise FILE.json")
    if args.action == "type":
        out = deliberation_audit.artifact(doc.get("artifact") or doc)
    elif args.action == "match":
        out = deliberation_audit.match(doc.get("gold") or [], doc.get("model") or [])
    elif args.action == "tags":
        out = deliberation_audit.tags(doc.get("gold") or [], doc.get("model") or [])
    elif args.action == "metadata":
        out = deliberation_audit.metadata(doc.get("gold") or [], doc.get("model") or [],
                                          doc.get("threshold", 0.82))
    elif args.action == "summary":
        out = deliberation_audit.summary(doc.get("score"), doc.get("coverage"))
    elif args.action == "ablation":
        out = deliberation_audit.ablation(doc.get("rows") or [])
    elif args.action == "audit":
        out = deliberation_audit.audit(doc.get("record") or doc)
    else:
        out = deliberation_audit.advise(doc.get("profile") or doc)
    _emit(deliberation_audit, out)


def cmd_frontier(args):
    """Round 137 (arXiv:2611.23080): a bracket says what is known and where the gap is."""
    from longrun.harness.checks import complexity_frontier
    doc = _load_doc(args, "frontier bracket|open|coascent|evidence|memory|round|advise FILE.json")
    if args.action == "bracket":
        out = complexity_frontier.bracket(doc.get("regimes") or [])
    elif args.action == "open":
        out = complexity_frontier.frontier(doc.get("rows") or [])
    elif args.action == "coascent":
        out = complexity_frontier.coascent(doc.get("record") or doc)
    elif args.action == "evidence":
        out = complexity_frontier.evidence(doc.get("record") or doc)
    elif args.action == "memory":
        out = complexity_frontier.memory(doc.get("rows") or [])
    elif args.action == "round":
        out = complexity_frontier.round(doc.get("rows") or [])
    else:
        out = complexity_frontier.advise(doc.get("profile") or doc)
    _emit(complexity_frontier, out)


def cmd_transfer(args):
    """Round 137 (arXiv:2611.23216): a benchmark gain is not yet work done."""
    from longrun.harness.checks import work_transfer
    doc = _load_doc(args, "transfer check|pool|ceiling|design|reversal|pooled|power|advise FILE.json")
    if args.action == "check":
        out = work_transfer.transfer(doc.get("rows") or doc.get("upgrades") or [])
    elif args.action == "pool":
        out = work_transfer.pool(doc.get("rows") or [])
    elif args.action == "ceiling":
        out = work_transfer.ceiling(doc.get("baseline"), doc.get("open_outcome"),
                                    doc.get("threshold", 0.9))
    elif args.action == "design":
        out = work_transfer.design(doc.get("spec") or doc)
    elif args.action == "reversal":
        out = work_transfer.reversal(doc.get("phases") or doc)
    elif args.action == "pooled":
        out = work_transfer.pooled_comparison(doc.get("rows") or [])
    elif args.action == "power":
        out = work_transfer.power(doc.get("sd"), doc.get("effect"), doc.get("available"))
    else:
        out = work_transfer.advise(doc.get("profile") or doc)
    _emit(work_transfer, out)


def cmd_repair(args):
    """Round 138 (arXiv:2611.22991): accuracy hides repairs cancelled by regressions."""
    from longrun.harness.checks import repair_audit
    doc = _load_doc(args, "repair churn|reach|failure|capability|flags|provenance|veto|advise FILE.json")
    if args.action == "churn":
        out = repair_audit.churn(doc.get("rows") or doc.get("executions") or [])
    elif args.action == "reach":
        out = repair_audit.reachability(doc.get("row") or doc)
    elif args.action == "failure":
        out = repair_audit.failure(doc.get("row") or doc)
    elif args.action == "capability":
        out = repair_audit.capability(doc.get("row") or doc)
    elif args.action == "flags":
        out = repair_audit.flags(doc.get("rows") or [])
    elif args.action == "provenance":
        out = repair_audit.provenance(doc.get("record") or doc)
    elif args.action == "veto":
        out = repair_audit.veto(doc.get("rows") or [])
    else:
        out = repair_audit.advise(doc.get("profile") or doc)
    _emit(repair_audit, out)


def cmd_validation(args):
    """Round 138 (arXiv:2611.22973): risk decides the evidence, and oversight must be real."""
    from longrun.harness.checks import validation_ladder
    doc = _load_doc(args, "validation risk|autonomy|controls|domains|evidence|calibrate|advise FILE.json")
    if args.action == "risk":
        out = validation_ladder.risk(doc.get("row") or doc)
    elif args.action == "autonomy":
        out = validation_ladder.autonomy(doc.get("row") or doc)
    elif args.action == "controls":
        out = validation_ladder.controls(doc.get("row") or doc)
    elif args.action == "domains":
        out = validation_ladder.domains(doc.get("row") or doc)
    elif args.action == "evidence":
        out = validation_ladder.evidence(doc.get("row") or doc)
    elif args.action == "calibrate":
        out = validation_ladder.calibrate(doc.get("rows") or [])
    else:
        out = validation_ladder.advise(doc.get("profile") or doc)
    _emit(validation_ladder, out)


def cmd_grounding(args):
    """Round 138 (arXiv:2611.23203): knowledge widens the search, a verifier keeps it honest."""
    from longrun.harness.checks import skill_grounding
    doc = _load_doc(args, "grounding skill|equivalence|verdict|session|layers|advise FILE.json")
    if args.action == "skill":
        out = skill_grounding.skill(doc.get("spec") or doc)
    elif args.action == "equivalence":
        out = skill_grounding.equivalence(doc.get("record") or doc)
    elif args.action == "verdict":
        out = skill_grounding.verdict(doc.get("record") or doc)
    elif args.action == "session":
        out = skill_grounding.session(doc.get("rows") or [])
    elif args.action == "layers":
        out = skill_grounding.layers(doc.get("rows") or [])
    else:
        out = skill_grounding.advise(doc.get("profile") or doc)
    _emit(skill_grounding, out)


def cmd_folding(args):
    """Round 139 (arXiv:2611.16627): the reduced view is a selection, not a rewrite."""
    from longrun.harness.checks import context_folding
    doc = _load_doc(args, "folding levels|contract|fold|trigger|cost|recover|advise FILE.json")
    if args.action == "levels":
        out = context_folding.levels(doc.get("record") or doc)
    elif args.action == "contract":
        out = context_folding.contract(doc.get("record") or doc)
    elif args.action == "fold":
        out = context_folding.fold(doc.get("turns") or [], doc.get("budget"))
    elif args.action == "trigger":
        out = context_folding.trigger(
            doc.get("requests") or [], doc.get("stable_prefix", 0.0),
            doc.get("layout_budget", 0.0), doc.get("dossier", 0.0),
            doc.get("rewrite_ratio", 30.0), doc.get("lam", 1.0))
    elif args.action == "cost":
        out = context_folding.cost(doc.get("usage") or {}, doc.get("ratios"))
    elif args.action == "recover":
        out = context_folding.recover(doc.get("rows") or [])
    else:
        out = context_folding.advise(doc.get("profile") or doc)
    _emit(context_folding, out)


def cmd_invocation(args):
    """Round 139 (arXiv:2608.26189): a wrong call poisons every step that follows."""
    from longrun.harness.checks import invocation_reliability
    doc = _load_doc(args, "invocation rates|wiring|severity|recovery|scoring|terminal|discrimination|advise FILE.json")
    if args.action == "rates":
        out = invocation_reliability.rates(doc.get("rows") or [], doc.get("depth"))
    elif args.action == "wiring":
        out = invocation_reliability.wiring(doc.get("rows") or [])
    elif args.action == "severity":
        out = invocation_reliability.severity(doc.get("rows") or [])
    elif args.action == "recovery":
        out = invocation_reliability.recovery(doc.get("rows") or [])
    elif args.action == "scoring":
        out = invocation_reliability.scoring(doc.get("rows") or [])
    elif args.action == "terminal":
        out = invocation_reliability.terminal(doc.get("rows") or [])
    elif args.action == "discrimination":
        out = invocation_reliability.discrimination(doc.get("rows") or [])
    else:
        out = invocation_reliability.advise(doc.get("profile") or doc)
    _emit(invocation_reliability, out)


def cmd_capabilities(args):
    """Round 139 (arXiv:2605.30621): updating a harness and benefiting from it differ."""
    from longrun.harness.checks import evolution_capabilities
    doc = _load_doc(args, "capabilities updating|benefit|activation|adherence|budget|pairing|insitu|advise FILE.json")
    if args.action == "updating":
        out = evolution_capabilities.updating(doc.get("rows") or [])
    elif args.action == "benefit":
        out = evolution_capabilities.benefit(doc.get("rows") or [])
    elif args.action == "activation":
        out = evolution_capabilities.activation(doc.get("rows") or [])
    elif args.action == "adherence":
        out = evolution_capabilities.adherence(doc.get("rows") or [])
    elif args.action == "budget":
        out = evolution_capabilities.budget(doc.get("rows") or [])
    elif args.action == "pairing":
        out = evolution_capabilities.pairing(doc.get("row") or doc)
    elif args.action == "insitu":
        out = evolution_capabilities.insitu(doc.get("row") or doc)
    else:
        out = evolution_capabilities.advise(doc.get("profile") or doc)
    _emit(evolution_capabilities, out)


def cmd_govern(args):
    """Round 140 (arXiv:2609.34017): a deterministic gate, and the halt it earns."""
    from longrun.harness.checks import handoff_governance
    doc = _load_doc(args, "govern anchor|validate|attribute|compare|coverage|posture|advise FILE.json")
    if args.action == "anchor":
        out = handoff_governance.anchor(doc.get("rules") or [], doc.get("version", 1))
    elif args.action == "validate":
        out = handoff_governance.validate(
            doc.get("handoff") or doc, doc.get("anchor") or {},
            doc.get("mode", "warn"), doc.get("state"))
    elif args.action == "attribute":
        out = handoff_governance.attribute(doc.get("halts") or [])
    elif args.action == "compare":
        out = handoff_governance.compare(doc.get("pairs") or [],
                                         doc.get("flat_band", 0.02))
    elif args.action == "coverage":
        out = handoff_governance.coverage(doc.get("checks") or [])
    elif args.action == "posture":
        out = handoff_governance.posture(doc.get("profile") or doc)
    else:
        out = handoff_governance.advise(doc.get("profile") or doc)
    _emit(handoff_governance, out)


def cmd_typed(args):
    """Round 140 (arXiv:2610.37461): withhold the tool, do not ask the model."""
    from longrun.harness.checks import session_protocol
    doc = _load_doc(
        args, "typed build|allowed|tick|refines|split|charge|compliance|pressure|advise FILE.json")
    if args.action == "build":
        out = session_protocol.protocol(
            doc.get("states") or [], doc.get("actions") or [], doc.get("start"),
            doc.get("finals") or [], doc.get("delta") or {})
    elif args.action == "allowed":
        out = {"format": session_protocol.FORMAT,
               "allowed": session_protocol.allowed(doc.get("protocol") or doc,
                                                   doc.get("state"))}
    elif args.action == "tick":
        # `tick`/`refines` are operational helpers that return bare results, so
        # the CLI stamps the group's FORMAT on them (all fields stay top-level).
        out = session_protocol.tick(doc.get("protocol") or {}, doc.get("state"),
                                    doc.get("action"), doc.get("target"))
        out["format"] = session_protocol.FORMAT
    elif args.action == "refines":
        out = session_protocol.refines(
            doc.get("parent") or {}, doc.get("child") or {},
            doc.get("human_parent") or [], doc.get("human_child") or [])
        out["format"] = session_protocol.FORMAT
    elif args.action == "split":
        out = session_protocol.split(doc.get("budget") or {}, doc.get("share", 0.5))
    elif args.action == "charge":
        out = session_protocol.charge(doc.get("budget") or {}, doc.get("usage") or {})
    elif args.action == "compliance":
        out = session_protocol.compliance(doc.get("runs") or [])
    elif args.action == "pressure":
        out = session_protocol.pressure(doc.get("rows") or [])
    else:
        out = session_protocol.advise(doc.get("profile") or doc)
    _emit(session_protocol, out)


def cmd_pipeline(args):
    """Round 140 (arXiv:2510.07614): blame is a computation over stages."""
    from longrun.harness.checks import pipeline_traceability
    doc = _load_doc(
        args, "pipeline final|blame|handoff|rates|origins|pareto|casting|gain|advise FILE.json")
    if args.action == "final":
        out = {"format": pipeline_traceability.FORMAT,
               "final": pipeline_traceability.final(doc.get("stages") or doc)}
    elif args.action == "blame":
        out = pipeline_traceability.blame(doc.get("stages") or doc,
                                          doc.get("gold"))
    elif args.action == "handoff":
        out = pipeline_traceability.handoff(doc.get("record") or doc)
    elif args.action == "rates":
        out = pipeline_traceability.rates(doc.get("rows") or [])
    elif args.action == "origins":
        out = pipeline_traceability.origins(doc.get("rows") or [])
    elif args.action == "pareto":
        out = pipeline_traceability.pareto(doc.get("rows") or [])
    elif args.action == "casting":
        out = pipeline_traceability.casting(doc.get("table") or doc)
    elif args.action == "gain":
        out = pipeline_traceability.gain(doc.get("pairs") or [],
                                         doc.get("flat_band", 0.5))
    else:
        out = pipeline_traceability.advise(doc.get("profile") or doc)
    _emit(pipeline_traceability, out)


def cmd_envelope(args):
    """Round 141 (arXiv:2611.23844): an envelope label is a weight, not a switch."""
    from longrun.harness.checks import defense_envelope
    doc = _load_doc(args, "envelope outcomes|weight|arbitration|content|dose|roles|stack|audit|advise FILE.json")
    if args.action == "outcomes":
        out = defense_envelope.outcomes(doc.get("rows") or [])
    elif args.action == "weight":
        out = defense_envelope.weight(doc.get("arms") or doc)
    elif args.action == "arbitration":
        out = defense_envelope.arbitration(doc.get("backends") or doc)
    elif args.action == "content":
        out = defense_envelope.content(doc.get("arms") or doc)
    elif args.action == "dose":
        out = defense_envelope.dose(doc.get("levels") or [])
    elif args.action == "roles":
        out = defense_envelope.roles(doc.get("rows") or doc)
    elif args.action == "stack":
        out = defense_envelope.stack(doc)
    elif args.action == "audit":
        out = defense_envelope.audit(doc.get("record") or doc)
    else:
        out = defense_envelope.advise(doc.get("profile") or doc)
    _emit(defense_envelope, out)


def cmd_tracefp(args):
    """Round 141 (arXiv:2610.32092): the repair trajectory is the fingerprint."""
    from longrun.harness.checks import execution_fingerprint
    doc = _load_doc(args, "tracefp trace|profile|attribute|separation|budget|robustness|probes|audit|advise FILE.json")
    if args.action == "trace":
        out = execution_fingerprint.trace(doc.get("steps") or [])
    elif args.action == "profile":
        out = execution_fingerprint.profile(doc.get("traces") or [])
    elif args.action == "attribute":
        out = execution_fingerprint.attribute(doc.get("traces") or [],
                                              doc.get("profiles") or {})
    elif args.action == "separation":
        out = execution_fingerprint.separation(doc.get("rows") or [])
    elif args.action == "budget":
        out = execution_fingerprint.budget(doc.get("rows") or [])
    elif args.action == "robustness":
        out = execution_fingerprint.robustness(doc.get("rows") or [])
    elif args.action == "probes":
        out = execution_fingerprint.probes(doc.get("row") or doc)
    elif args.action == "audit":
        out = execution_fingerprint.audit(doc.get("record") or doc)
    else:
        out = execution_fingerprint.advise(doc.get("profile") or doc)
    _emit(execution_fingerprint, out)


def cmd_modelhandoff(args):
    """Round 141 (arXiv:2610.07816): route the step, not the query."""
    from longrun.harness.checks import model_handoff
    doc = _load_doc(args, "modelhandoff gate|signals|calibration|budget|pareto|handoff|recovery|saturate|audit|advise FILE.json")
    if args.action == "gate":
        out = model_handoff.gate(doc.get("features") or doc)
    elif args.action == "signals":
        out = model_handoff.signals(doc.get("row") or doc)
    elif args.action == "calibration":
        out = model_handoff.calibration(doc.get("rows") or [])
    elif args.action == "budget":
        out = model_handoff.budget(doc.get("rows") or [])
    elif args.action == "pareto":
        out = model_handoff.pareto(doc.get("rows") or [])
    elif args.action == "handoff":
        out = model_handoff.handoff(doc.get("packet") or doc)
    elif args.action == "recovery":
        out = model_handoff.recovery(doc.get("rows") or [])
    elif args.action == "saturate":
        out = model_handoff.saturate(doc.get("rows") or [])
    elif args.action == "audit":
        out = model_handoff.audit(doc.get("record") or doc)
    else:
        out = model_handoff.advise(doc.get("profile") or doc)
    _emit(model_handoff, out)


def cmd_admission(args):
    """Round 143 (arXiv:2604.17111): the API is a shared resource, so schedule it."""
    from longrun.harness.checks import admission_schedule
    doc = _load_doc(args, "admission provider|slot|aimd|circuit|backoff|budget|order|ablate|pressure|advise FILE.json")
    if args.action == "provider":
        out = admission_schedule.provider(doc.get("profile") or doc)
    elif args.action == "slot":
        out = admission_schedule.slot(doc.get("active"), doc.get("cmax"),
                                      doc.get("waiting", 0))
    elif args.action == "aimd":
        out = admission_schedule.aimd(doc.get("state") or doc)
    elif args.action == "circuit":
        out = admission_schedule.circuit(doc.get("state") or doc)
    elif args.action == "backoff":
        out = admission_schedule.backoff(
            doc.get("attempt", 0), doc.get("retry_after"), doc.get("base", 1.0),
            doc.get("cap", 30.0), doc.get("jitter", 0.0))
    elif args.action == "budget":
        out = admission_schedule.budget(doc.get("ceiling"), doc.get("used"),
                                        doc.get("warn_at", 0.85))
    elif args.action == "order":
        out = admission_schedule.order(doc.get("tasks") or [],
                                       doc.get("completed") or [])
    elif args.action == "ablate":
        out = admission_schedule.ablate(doc.get("rows") or [])
    elif args.action == "pressure":
        out = admission_schedule.pressure(doc.get("rows") or [])
    else:
        out = admission_schedule.advise(doc.get("profile") or doc)
    _emit(admission_schedule, out)


def cmd_statesched(args):
    """Round 143 (arXiv:2512.14142): optimize the request lifecycle, not the segment."""
    from longrun.harness.checks import stateful_scheduling
    doc = _load_doc(
        args, "statesched hrrn|queue|aging|batch|kv|predict|jct|compare|stability|advise FILE.json")
    if args.action == "hrrn":
        out = {"format": stateful_scheduling.FORMAT,
               "score": stateful_scheduling.hrrn(doc.get("wait"),
                                                 doc.get("proc"))}
    elif args.action == "queue":
        out = stateful_scheduling.queue_event(doc.get("row") or doc)
    elif args.action == "aging":
        out = stateful_scheduling.aging(doc.get("row") or doc)
    elif args.action == "batch":
        out = stateful_scheduling.batch(doc.get("segments") or [],
                                        doc.get("capacity"))
    elif args.action == "kv":
        out = stateful_scheduling.kv_policy(doc.get("row") or doc)
    elif args.action == "predict":
        out = stateful_scheduling.predict(doc.get("row") or doc)
    elif args.action == "jct":
        out = stateful_scheduling.jct(doc.get("segments") or [])
    elif args.action == "compare":
        out = stateful_scheduling.compare(doc.get("rows") or [])
    elif args.action == "stability":
        out = stateful_scheduling.stability(doc.get("rows") or [])
    else:
        out = stateful_scheduling.advise(doc.get("profile") or doc)
    _emit(stateful_scheduling, out)


def cmd_capacity(args):
    """Round 143 (arXiv:2603.00356): admission at the gateway, priced in inference units."""
    from longrun.harness.checks import capacity_pools
    doc = _load_doc(
        args, "capacity classes|classify|priority|debt|burst|resources|admission|reclaim|protect|fairshare|advise FILE.json")
    if args.action == "classes":
        out = {"format": capacity_pools.FORMAT, "classes": capacity_pools.classes()}
    elif args.action == "classify":
        out = capacity_pools.classify(doc.get("name"))
    elif args.action == "priority":
        out = capacity_pools.priority(doc.get("row") or doc)
    elif args.action == "debt":
        out = capacity_pools.debt(doc.get("row") or doc)
    elif args.action == "burst":
        out = capacity_pools.burst(doc.get("row") or doc)
    elif args.action == "resources":
        out = capacity_pools.resources(doc.get("row") or doc)
    elif args.action == "admission":
        out = capacity_pools.admission(doc.get("row") or doc)
    elif args.action == "reclaim":
        out = capacity_pools.reclaim(doc.get("items") or [])
    elif args.action == "protect":
        out = capacity_pools.protect(doc.get("rows") or [])
    elif args.action == "fairshare":
        out = capacity_pools.fairshare(doc.get("row") or doc)
    else:
        out = capacity_pools.advise(doc.get("profile") or doc)
    _emit(capacity_pools, out)


def cmd_slots(args):
    """Round 144 (arXiv:2607.17147): hide the value, keep the structure."""
    from longrun.harness.checks import transcript_privacy
    doc = _load_doc(args, "slots suffix|slot|bind|rebind|graph|leak|compatibility|overhead|audit|advise FILE.json")
    if args.action == "suffix":
        out = transcript_privacy.suffix(doc.get("path"), doc.get("roots") or [])
    elif args.action == "slot":
        out = transcript_privacy.slot(doc.get("value"), doc.get("kind"),
                                      doc.get("index", 1))
    elif args.action == "bind":
        out = transcript_privacy.bind(doc.get("value"), doc.get("kind"),
                                      doc.get("session_key"))
    elif args.action == "rebind":
        out = transcript_privacy.rebind(doc.get("handle"), doc.get("table") or {},
                                        doc.get("scope"))
    elif args.action == "graph":
        out = transcript_privacy.graph(doc.get("pairs") or [])
    elif args.action == "leak":
        out = transcript_privacy.leak(doc.get("rows") or [])
    elif args.action == "compatibility":
        out = transcript_privacy.compatibility(doc.get("rows") or [])
    elif args.action == "overhead":
        out = transcript_privacy.overhead(doc.get("rows") or [])
    elif args.action == "audit":
        out = transcript_privacy.audit(doc.get("record") or doc)
    else:
        out = transcript_privacy.advise(doc.get("profile") or doc)
    _emit(transcript_privacy, out)


def cmd_privmem(args):
    """Round 144 (arXiv:2605.09530): a typed placeholder, not an asterisk."""
    from longrun.harness.checks import privacy_memory
    doc = _load_doc(
        args, "privmem levels|classify|sanitize|restore|extraction|utility|leakage|threshold|audit|advise FILE.json")
    if args.action == "levels":
        out = {"format": privacy_memory.FORMAT, "levels": privacy_memory.levels()}
    elif args.action == "classify":
        out = privacy_memory.classify(doc.get("level"))
    elif args.action == "sanitize":
        out = privacy_memory.sanitize(doc.get("spans") or [],
                                      doc.get("threshold", "PL2"))
    elif args.action == "restore":
        out = privacy_memory.restore(doc.get("text"), doc.get("mapping") or {})
    elif args.action == "extraction":
        out = privacy_memory.extraction(doc.get("rows") or [])
    elif args.action == "utility":
        out = privacy_memory.utility(doc.get("rows") or [])
    elif args.action == "leakage":
        out = privacy_memory.leakage(doc.get("rows") or [])
    elif args.action == "threshold":
        out = privacy_memory.threshold(doc.get("rows") or [],
                                       doc.get("tolerance", 0.016))
    elif args.action == "audit":
        out = privacy_memory.audit(doc.get("record") or doc)
    else:
        out = privacy_memory.advise(doc.get("profile") or doc)
    _emit(privacy_memory, out)


def cmd_privaudit(args):
    """Round 144 (arXiv:2610.06454): gate the outbound write."""
    from longrun.harness.checks import privacy_audit
    doc = _load_doc(args, "privaudit flow|disposition|inventory|compare|criteria|auditor|audit|advise FILE.json")
    if args.action == "flow":
        out = privacy_audit.flow(doc.get("row") or doc)
    elif args.action == "disposition":
        out = privacy_audit.disposition(doc.get("row") or doc)
    elif args.action == "inventory":
        out = privacy_audit.inventory(doc.get("reads") or [])
    elif args.action == "compare":
        out = privacy_audit.compare(doc.get("rows") or [])
    elif args.action == "criteria":
        out = privacy_audit.criteria(doc.get("rows") or [])
    elif args.action == "auditor":
        out = privacy_audit.auditor(doc.get("row") or doc)
    elif args.action == "audit":
        out = privacy_audit.audit(doc.get("record") or doc)
    else:
        out = privacy_audit.advise(doc.get("profile") or doc)
    _emit(privacy_audit, out)


def cmd_updategate(args):
    """Round 145 (arXiv:2611.23651): admit a self-improvement, or keep the parent."""
    from longrun.harness.checks import harness_update_gate
    doc = _load_doc(args, "updategate blocks|differential|confirm|localize|verify|risk|utility|admit|transfer|audit|advise FILE.json")
    if args.action == "blocks":
        out = harness_update_gate.blocks(doc.get("items") or [])
    elif args.action == "differential":
        out = harness_update_gate.differential(doc.get("rows") or [])
    elif args.action == "confirm":
        out = harness_update_gate.confirm(doc.get("outcomes") or [],
                                          require_all=doc.get("require_all") is True)
    elif args.action == "localize":
        out = harness_update_gate.localize(doc.get("rollbacks") or [])
    elif args.action == "verify":
        out = harness_update_gate.verify(doc.get("row") or doc)
    elif args.action == "risk":
        out = harness_update_gate.risk(doc.get("records") or [])
    elif args.action == "utility":
        out = harness_update_gate.utility(doc.get("rows") or [])
    elif args.action == "admit":
        out = harness_update_gate.admit(doc.get("row") or doc)
    elif args.action == "transfer":
        out = harness_update_gate.transfer(doc.get("row") or doc)
    elif args.action == "audit":
        out = harness_update_gate.audit(doc.get("record") or doc)
    else:
        out = harness_update_gate.advise(doc.get("profile") or doc)
    _emit(harness_update_gate, out)


def cmd_expledger(args):
    """Round 145 (arXiv:2611.23678): judge the process, not only the best score."""
    from longrun.harness.checks import experiment_ledger
    doc = _load_doc(args, "expledger scope|noop|precondition|decide|ledger|metrics|repeated|counterfactual|relabel|taxonomy|audit|advise FILE.json")
    if args.action == "scope":
        out = experiment_ledger.scope(doc.get("row") or doc)
    elif args.action == "noop":
        out = experiment_ledger.noop(doc.get("row") or doc)
    elif args.action == "precondition":
        out = experiment_ledger.precondition(doc.get("row") or doc)
    elif args.action == "decide":
        out = experiment_ledger.decide(doc.get("row") or doc)
    elif args.action == "ledger":
        out = experiment_ledger.ledger(doc.get("records") or [])
    elif args.action == "metrics":
        out = experiment_ledger.metrics(doc.get("records") or [])
    elif args.action == "repeated":
        out = experiment_ledger.repeated(doc.get("proposals") or [],
                                         float(doc.get("theta") or 0.6))
    elif args.action == "counterfactual":
        out = experiment_ledger.counterfactual(doc.get("pairs") or [])
    elif args.action == "relabel":
        out = experiment_ledger.relabel(doc.get("rows") or [])
    elif args.action == "taxonomy":
        out = experiment_ledger.taxonomy()
    elif args.action == "audit":
        out = experiment_ledger.audit(doc.get("record") or doc)
    else:
        out = experiment_ledger.advise(doc.get("profile") or doc)
    _emit(experiment_ledger, out)


def cmd_prefetch(args):
    """Round 145 (arXiv:2611.23857): predict the next recall before the demand."""
    from longrun.harness.checks import context_prefetch
    doc = _load_doc(args, "prefetch window|encode|decode|contract|prefetch|benefit|degrade|warmup|audit|advise FILE.json")
    if args.action == "window":
        out = context_prefetch.window(doc.get("events") or [],
                                      int(doc.get("size") or context_prefetch.DEFAULTS["window"]))
    elif args.action == "encode":
        out = context_prefetch.encode(doc.get("addresses") or [],
                                      int(doc.get("cap") or context_prefetch.DEFAULTS["vocab_cap"]))
    elif args.action == "decode":
        out = context_prefetch.decode(doc.get("ranks") or [], doc.get("last"),
                                      doc.get("rank_to_delta") or {})
    elif args.action == "contract":
        out = context_prefetch.contract(doc.get("packet") or doc)
    elif args.action == "prefetch":
        out = context_prefetch.prefetch(doc.get("row") or doc)
    elif args.action == "benefit":
        out = context_prefetch.benefit(doc.get("rows") or [])
    elif args.action == "degrade":
        out = context_prefetch.degrade(doc.get("row") or doc)
    elif args.action == "warmup":
        out = context_prefetch.warmup(doc.get("rows") or [])
    elif args.action == "audit":
        out = context_prefetch.audit(doc.get("record") or doc)
    else:
        out = context_prefetch.advise(doc.get("profile") or doc)
    _emit(context_prefetch, out)


def cmd_coverage(args):
    """Round 146 (arXiv:2611.24313): count the ways in, not only how often."""
    from longrun.harness.checks import redteam_coverage
    doc = _load_doc(args, "coverage taxonomy|coverage|concentration|jaccard|asr|equal-sample|equal-cost|labels|audit|advise FILE.json")
    if args.action == "taxonomy":
        out = redteam_coverage.taxonomy(doc.get("units") or [])
    elif args.action == "coverage":
        out = redteam_coverage.coverage(doc.get("successes") or [],
                                        doc.get("totals") or {})
    elif args.action == "concentration":
        out = redteam_coverage.concentration(doc.get("successes") or [],
                                             str(doc.get("level") or "technique"))
    elif args.action == "jaccard":
        out = redteam_coverage.jaccard(doc.get("successes") or [],
                                       str(doc.get("level") or "technique"))
    elif args.action == "asr":
        out = redteam_coverage.asr_at_k(doc.get("attempts") or [],
                                        int(doc.get("k") or 1))
    elif args.action == "equal-sample":
        out = redteam_coverage.equal_sample(doc.get("successes") or [],
                                            int(doc.get("k") or 1),
                                            str(doc.get("level") or "technique"))
    elif args.action == "equal-cost":
        out = redteam_coverage.equal_cost(doc.get("rows") or [])
    elif args.action == "labels":
        out = redteam_coverage.label_check(doc.get("rows") or [])
    elif args.action == "audit":
        out = redteam_coverage.audit(doc.get("record") or doc)
    else:
        out = redteam_coverage.advise(doc.get("profile") or doc)
    _emit(redteam_coverage, out)


def cmd_purpleloop(args):
    """Round 146 (arXiv:2611.24362): discoveries into robustness, not volume."""
    from longrun.harness.checks import purple_loop
    doc = _load_doc(args, "purpleloop primitives|explainability|reward|collapse|rewards|requirements|compare|ablate|audit|advise FILE.json")
    if args.action == "primitives":
        out = purple_loop.primitives(doc.get("records") or [],
                                     int(doc.get("k") or 3))
    elif args.action == "explainability":
        out = purple_loop.explainability(doc.get("row") or doc)
    elif args.action == "reward":
        out = purple_loop.coverage_reward(doc.get("row") or doc)
    elif args.action == "collapse":
        out = purple_loop.collapse(doc.get("series") or [])
    elif args.action == "rewards":
        out = purple_loop.rewards(doc.get("row") or doc)
    elif args.action == "requirements":
        out = purple_loop.requirements(doc.get("row") or doc)
    elif args.action == "compare":
        out = purple_loop.compare(doc.get("rows") or [])
    elif args.action == "ablate":
        out = purple_loop.ablate(doc.get("rows") or [])
    elif args.action == "audit":
        out = purple_loop.audit(doc.get("record") or doc)
    else:
        out = purple_loop.advise(doc.get("profile") or doc)
    _emit(purple_loop, out)


def cmd_renderdef(args):
    """Round 146 (arXiv:2611.24231): protection that depends on the operation."""
    from longrun.harness.checks import render_defense
    doc = _load_doc(args, "renderdef operations|modality|aggregate|utility|presentation|candidates|dissociation|authorization|audit|advise FILE.json")
    if args.action == "operations":
        out = render_defense.operations()
    elif args.action == "modality":
        out = render_defense.modality(doc.get("rows") or [])
    elif args.action == "aggregate":
        out = render_defense.aggregate(doc.get("rows") or [])
    elif args.action == "utility":
        out = render_defense.utility(doc.get("rows") or [])
    elif args.action == "presentation":
        out = render_defense.presentation(doc.get("rows") or [])
    elif args.action == "candidates":
        out = render_defense.candidates(doc.get("rows") or [])
    elif args.action == "dissociation":
        out = render_defense.dissociation(doc.get("rows") or [])
    elif args.action == "authorization":
        out = render_defense.authorization(doc.get("row") or doc)
    elif args.action == "audit":
        out = render_defense.audit(doc.get("record") or doc)
    else:
        out = render_defense.advise(doc.get("profile") or doc)
    _emit(render_defense, out)


def cmd_stateev(args):
    """Round 147 (arXiv:2611.24357): carry the interpretation, keep the proof."""
    from longrun.harness.checks import state_evidence
    doc = _load_doc(args, "stateev state|delta|ack|recover|locality|budget|paired|benefit|audit|advise FILE.json")
    if args.action == "state":
        out = state_evidence.state(doc.get("entries") or [])
    elif args.action == "delta":
        out = state_evidence.apply_delta(doc.get("row") or doc)
    elif args.action == "ack":
        out = state_evidence.acknowledge(doc.get("row") or doc)
    elif args.action == "recover":
        out = state_evidence.recover(doc.get("row") or doc)
    elif args.action == "locality":
        out = state_evidence.locality(doc.get("rows") or [])
    elif args.action == "budget":
        out = state_evidence.budget(doc.get("row") or doc)
    elif args.action == "paired":
        out = state_evidence.paired(doc.get("row") or doc)
    elif args.action == "benefit":
        out = state_evidence.benefit(doc.get("rows") or [])
    elif args.action == "audit":
        out = state_evidence.audit(doc.get("record") or doc)
    else:
        out = state_evidence.advise(doc.get("profile") or doc)
    _emit(state_evidence, out)


def cmd_evidenceview(args):
    """Round 147 (arXiv:2611.24353): mentioning a figure is not checking it."""
    from longrun.harness.checks import evidence_review
    doc = _load_doc(args, "evidenceview outcomes|rates|aided|shortlist|evidence-type|assertion|instrument|near-miss|noise|audit|advise FILE.json")
    if args.action == "outcomes":
        out = evidence_review.outcomes()
    elif args.action == "rates":
        out = evidence_review.rates(doc.get("rows") or [])
    elif args.action == "aided":
        out = evidence_review.aided(doc.get("rows") or [])
    elif args.action == "shortlist":
        out = evidence_review.shortlist(doc.get("row") or doc)
    elif args.action == "evidence-type":
        out = evidence_review.evidence_type(doc.get("rows") or [])
    elif args.action == "assertion":
        out = evidence_review.assertion(doc.get("rows") or [])
    elif args.action == "instrument":
        out = evidence_review.instrument(doc.get("row") or doc)
    elif args.action == "near-miss":
        out = evidence_review.near_miss(doc.get("rows") or [])
    elif args.action == "noise":
        out = evidence_review.noise(doc.get("row") or doc)
    elif args.action == "audit":
        out = evidence_review.audit(doc.get("record") or doc)
    else:
        out = evidence_review.advise(doc.get("profile") or doc)
    _emit(evidence_review, out)


def cmd_uncert(args):
    """Round 147 (arXiv:2611.24351): say how sure the evidence is."""
    from longrun.harness.checks import uncertainty_context
    doc = _load_doc(args, "uncert paired|alignment|subset|flips|correctness|entropy|sensitivity|audit|advise FILE.json")
    if args.action == "paired":
        out = uncertainty_context.paired(doc.get("row") or doc)
    elif args.action == "alignment":
        out = uncertainty_context.alignment(doc.get("rows") or [])
    elif args.action == "subset":
        out = uncertainty_context.subset(doc.get("rows") or [])
    elif args.action == "flips":
        out = uncertainty_context.flips(doc.get("row") or doc)
    elif args.action == "correctness":
        out = uncertainty_context.correctness(doc.get("rows") or [])
    elif args.action == "entropy":
        out = uncertainty_context.entropy(doc.get("rows") or [])
    elif args.action == "sensitivity":
        out = uncertainty_context.sensitivity(doc.get("rows") or [])
    elif args.action == "audit":
        out = uncertainty_context.audit(doc.get("record") or doc)
    else:
        out = uncertainty_context.advise(doc.get("profile") or doc)
    _emit(uncertainty_context, out)


def cmd_skillcfi(args):
    """Round 148 (arXiv:2611.24185): hold a skill to its control skeleton."""
    from longrun.harness.checks import skill_cfi
    doc = _load_doc(args, "skillcfi skeleton|enforceable|dispositions|admit|result|violation|refusal|recovery|audit|advise FILE.json")
    if args.action == "skeleton":
        out = skill_cfi.skeleton(doc.get("row") or doc)
    elif args.action == "enforceable":
        out = skill_cfi.enforceable(doc.get("row") or doc)
    elif args.action == "dispositions":
        out = skill_cfi.dispositions(doc.get("rows") or [])
    elif args.action == "admit":
        out = skill_cfi.admit(doc.get("row") or doc)
    elif args.action == "result":
        out = skill_cfi.result(doc.get("row") or doc)
    elif args.action == "violation":
        out = skill_cfi.violation(doc.get("row") or doc)
    elif args.action == "refusal":
        out = skill_cfi.refusal(doc.get("row") or doc)
    elif args.action == "recovery":
        out = skill_cfi.recovery(doc.get("rows") or [])
    elif args.action == "audit":
        out = skill_cfi.audit(doc.get("record") or doc)
    else:
        out = skill_cfi.advise(doc.get("profile") or doc)
    _emit(skill_cfi, out)


def cmd_memcomm(args):
    """Round 148 (arXiv:2611.24165): memory as a shared, operable object."""
    from longrun.harness.checks import memory_commune
    doc = _load_doc(args, "memcomm entry|scope|proposals|transfer|selection|citation|audit|alignment|gap|activity|audit-record|advise FILE.json")
    if args.action == "entry":
        out = memory_commune.entry(doc.get("row") or doc)
    elif args.action == "scope":
        out = memory_commune.scope_ok(doc.get("row") or doc)
    elif args.action == "proposals":
        out = memory_commune.proposals(doc.get("row") or doc)
    elif args.action == "transfer":
        out = memory_commune.transfer(doc.get("row") or doc)
    elif args.action == "selection":
        out = memory_commune.selection(doc.get("row") or doc)
    elif args.action == "citation":
        out = memory_commune.citation(doc.get("row") or doc)
    elif args.action == "audit":
        out = memory_commune.audit(doc.get("row") or doc)
    elif args.action == "alignment":
        out = memory_commune.alignment(doc.get("rows") or [])
    elif args.action == "gap":
        out = memory_commune.gap(doc.get("rows") or [])
    elif args.action == "activity":
        out = memory_commune.activity(doc.get("rows") or [])
    elif args.action == "audit-record":
        out = memory_commune.audit_record(doc.get("record") or doc)
    else:
        out = memory_commune.advise(doc.get("profile") or doc)
    _emit(memory_commune, out)


def cmd_sparseval(args):
    """Round 148 (arXiv:2611.24159): a weak prior and an exact update."""
    from longrun.harness.checks import sparse_eval
    doc = _load_doc(args, "sparseval prior|posterior|sensitivity|value|brier|alc|calibration|audit|advise FILE.json")
    if args.action == "prior":
        out = sparse_eval.prior(doc.get("rows") or [])
    elif args.action == "posterior":
        out = sparse_eval.posterior(doc.get("row") or doc)
    elif args.action == "sensitivity":
        out = sparse_eval.sensitivity(doc.get("row") or doc)
    elif args.action == "value":
        out = sparse_eval.value(doc.get("row") or doc)
    elif args.action == "brier":
        out = sparse_eval.brier(doc.get("rows") or [])
    elif args.action == "alc":
        out = sparse_eval.alc(doc.get("rows") or [])
    elif args.action == "calibration":
        out = sparse_eval.calibration(doc.get("rows") or [])
    elif args.action == "audit":
        out = sparse_eval.audit_record(doc.get("record") or doc)
    else:
        out = sparse_eval.advise(doc.get("profile") or doc)
    _emit(sparse_eval, out)


def cmd_budgetaudit(args):
    """Round 149 (arXiv:2611.24867): what the looks cost, per step."""
    from longrun.harness.checks import budget_audit
    doc = _load_doc(
        args, "budgetaudit belief|value|observe|qvalue|solve|decompose|anchors|"
              "staged|routing|bound|audit|advise FILE.json")
    if args.action == "belief":
        out = budget_audit.belief(doc.get("state") or doc)
    elif args.action == "value":
        out = budget_audit.value(doc.get("state") or doc)
    elif args.action == "observe":
        out = {"format": budget_audit.FORMAT, "outcomes": [
            {"p": prob, "state": child}
            for prob, child in budget_audit.observe(
                doc.get("state") or {}, doc.get("reads") or 0)]}
    elif args.action == "qvalue":
        out = budget_audit.q_value(doc.get("state") or {},
                                   doc.get("action") or {},
                                   doc.get("budget") or 0)
    elif args.action == "solve":
        out = budget_audit.solve(doc.get("state") or {}, doc.get("budget") or 0,
                                 doc.get("actions"))
    elif args.action == "decompose":
        out = budget_audit.decompose(doc)
    elif args.action == "anchors":
        out = budget_audit.anchors(doc.get("rows") or [])
    elif args.action == "staged":
        out = budget_audit.staged(doc.get("stages") or doc.get("rows") or [])
    elif args.action == "routing":
        out = budget_audit.routing_gain(doc.get("rho"), doc.get("r"))
    elif args.action == "bound":
        out = budget_audit.bound(doc.get("eps"), doc.get("budget"))
    elif args.action == "audit":
        out = budget_audit.audit(doc.get("record") or doc)
    else:
        out = budget_audit.advise(doc.get("profile") or doc)
    _emit(budget_audit, out)


def cmd_simaudit(args):
    """Round 149 (arXiv:2611.24892): does the metric notice the injected failure?"""
    from longrun.harness.checks import simulator_audit
    doc = _load_doc(args, "simaudit paired|population|coverage|auroc|retention|levels|simulators|evidence|audit|advise FILE.json")
    if args.action == "paired":
        out = simulator_audit.paired(doc.get("rows") or [])
    elif args.action == "population":
        out = simulator_audit.population(doc.get("draws") or doc.get("rows") or [])
    elif args.action == "coverage":
        out = simulator_audit.coverage(doc.get("results") or doc.get("rows") or [])
    elif args.action == "auroc":
        out = simulator_audit.auroc(doc.get("rows") or [])
    elif args.action == "retention":
        out = simulator_audit.retention(doc.get("rows") or [],
                                        doc.get("admitted") or 0.05)
    elif args.action == "levels":
        out = simulator_audit.levels(doc.get("scores") or doc)
    elif args.action == "simulators":
        out = simulator_audit.simulators(doc.get("rows") or [])
    elif args.action == "evidence":
        out = simulator_audit.evidence(doc.get("entry") or doc)
    elif args.action == "audit":
        out = simulator_audit.audit(doc.get("record") or doc)
    else:
        out = simulator_audit.advise(doc.get("profile") or doc)
    _emit(simulator_audit, out)


def cmd_progjudge(args):
    """Round 149 (arXiv:2611.24849): one program per topic instead of a call per document."""
    from longrun.harness.checks import program_judge
    doc = _load_doc(args, "progjudge answers|consensus|single|rubric|errors|kendall|labelgain|breakeven|sandbox|audit|advise FILE.json")
    if args.action == "answers":
        out = program_judge.answers(doc.get("answers") or doc)
    elif args.action == "consensus":
        out = program_judge.consensus(doc.get("grades") or [])
    elif args.action == "single":
        out = program_judge.single(doc.get("grades") or [])
    elif args.action == "rubric":
        out = program_judge.rubric(doc.get("criteria") or doc.get("rows") or [])
    elif args.action == "errors":
        out = program_judge.errors(doc.get("rows") or [])
    elif args.action == "kendall":
        out = program_judge.kendall(doc.get("rows") or [])
    elif args.action == "labelgain":
        out = program_judge.label_gain(doc.get("rows") or doc.get("curve") or [])
    elif args.action == "breakeven":
        out = program_judge.break_even(doc.get("write_cost"), doc.get("per_doc_cost"))
    elif args.action == "sandbox":
        out = program_judge.policy(doc.get("source") or doc.get("text") or "")
    elif args.action == "audit":
        out = program_judge.audit(doc.get("record") or doc)
    else:
        out = program_judge.advise(doc.get("profile") or doc)
    _emit(program_judge, out)


def cmd_reql(args):
    """Round 150 (arXiv:2611.24924): a change lands because a requirement says so."""
    from longrun.harness.checks import requirement_loop
    doc = _load_doc(args, "reql issue|triage|consolidate|admission|review|rounds|delivery|generalisation|audit|advise FILE.json")
    if args.action == "issue":
        out = requirement_loop.issue(doc.get("report") or doc)
    elif args.action == "triage":
        out = requirement_loop.triage(doc.get("report") or doc)
    elif args.action == "consolidate":
        out = requirement_loop.consolidate(doc.get("rows") or [])
    elif args.action == "admission":
        out = requirement_loop.admission(doc.get("rows") or [])
    elif args.action == "review":
        out = requirement_loop.review(doc.get("record") or doc)
    elif args.action == "rounds":
        out = requirement_loop.rounds(doc.get("rows") or [])
    elif args.action == "delivery":
        out = requirement_loop.delivery(doc.get("record") or doc)
    elif args.action == "generalisation":
        out = requirement_loop.generalisation(doc.get("rows") or [])
    elif args.action == "audit":
        out = requirement_loop.audit(doc.get("record") or doc)
    else:
        out = requirement_loop.advise(doc.get("profile") or doc)
    _emit(requirement_loop, out)


def cmd_replan(args):
    """Round 150 (arXiv:2611.24839): templates in, validated repairs out."""
    from longrun.harness.checks import secure_replan
    doc = _load_doc(args, "replan apply|validate|templates|repair|closeout|exposure|validation|audit|advise FILE.json")
    if args.action == "apply":
        out = secure_replan.apply(doc.get("plan") or {},
                                  doc.get("operators") or [])
    elif args.action == "validate":
        out = secure_replan.validate(doc.get("plan") or {}, doc)
    elif args.action == "templates":
        out = secure_replan.templates()
    elif args.action == "repair":
        out = secure_replan.repair(doc)
    elif args.action == "closeout":
        out = secure_replan.close_out(doc.get("record") or doc)
    elif args.action == "exposure":
        out = secure_replan.exposure(doc.get("record") or doc)
    elif args.action == "validation":
        out = secure_replan.validation_effect(doc.get("record") or doc)
    elif args.action == "audit":
        out = secure_replan.audit(doc.get("record") or doc)
    else:
        out = secure_replan.advise(doc.get("profile") or doc)
    _emit(secure_replan, out)


def cmd_localcost(args):
    """Round 150 (arXiv:2611.24880): what a solved task costs on your own device."""
    from longrun.harness.checks import local_cost
    doc = _load_doc(args, "localcost expected|energy|capacity|rate|required|computed|notice|compare|audit|advise FILE.json")
    if args.action == "expected":
        out = local_cost.expected(doc.get("record") or doc)
    elif args.action == "energy":
        out = local_cost.energy(doc.get("record") or doc)
    elif args.action == "capacity":
        out = local_cost.capacity(doc.get("record") or doc)
    elif args.action == "rate":
        out = local_cost.decode_rate(doc.get("record") or doc)
    elif args.action == "required":
        out = local_cost.required_rate(doc.get("record") or doc)
    elif args.action == "computed":
        out = local_cost.computed(doc.get("record") or doc)
    elif args.action == "notice":
        out = local_cost.budget_notice(doc.get("record") or doc)
    elif args.action == "compare":
        out = local_cost.compare(doc.get("record") or doc)
    elif args.action == "audit":
        out = local_cost.audit(doc.get("record") or doc)
    else:
        out = local_cost.advise(doc.get("profile") or doc)
    _emit(local_cost, out)


def cmd_intentc(args):
    """Round 151 (arXiv:2611.24025): a contract the trusted side can check and execute."""
    from longrun.harness.checks import intent_contract
    doc = _load_doc(args, "intentc validate|coverage|mcnemar|outcomes|bundling|targets|properties|audit|advise FILE.json")
    if args.action == "validate":
        out = intent_contract.validate(doc.get("record") or doc)
    elif args.action == "coverage":
        out = intent_contract.coverage(doc.get("rows") or [])
    elif args.action == "mcnemar":
        out = intent_contract.mcnemar(doc.get("b"), doc.get("c"))
    elif args.action == "outcomes":
        out = intent_contract.outcomes(doc.get("record") or doc)
    elif args.action == "bundling":
        out = intent_contract.bundling(doc.get("rows") or [])
    elif args.action == "targets":
        out = intent_contract.targets(doc.get("rows") or [])
    elif args.action == "properties":
        out = intent_contract.fixed_properties()
    elif args.action == "audit":
        out = intent_contract.audit(doc.get("record") or doc)
    else:
        out = intent_contract.advise(doc.get("profile") or doc)
    _emit(intent_contract, out)


def cmd_warrant(args):
    """Round 151 (arXiv:2611.23990): which old evidence is admissible in the new context."""
    from longrun.harness.checks import evidence_warrant
    doc = _load_doc(args, "warrant wrc|admissibility|transport|authorize|provenance|composition|selective|audit|advise FILE.json")
    if args.action == "wrc":
        out = evidence_warrant.wrc(doc.get("record") or doc)
    elif args.action == "admissibility":
        out = evidence_warrant.admissibility(doc.get("items") or doc.get("rows") or [])
    elif args.action == "transport":
        out = evidence_warrant.transport(doc.get("items") or doc.get("rows") or [])
    elif args.action == "authorize":
        out = evidence_warrant.authorize(doc.get("record") or doc)
    elif args.action == "provenance":
        out = evidence_warrant.provenance(doc.get("record") or doc)
    elif args.action == "composition":
        out = evidence_warrant.composition(doc.get("record") or doc)
    elif args.action == "selective":
        out = evidence_warrant.selective(doc.get("record") or doc)
    elif args.action == "audit":
        out = evidence_warrant.audit(doc.get("record") or doc)
    else:
        out = evidence_warrant.advise(doc.get("profile") or doc)
    _emit(evidence_warrant, out)


def cmd_platformeval(args):
    """Round 151 (arXiv:2611.24039): gates before scores, with the halo reported."""
    from longrun.harness.checks import platform_eval
    doc = _load_doc(args, "platformeval score|alpha|tiers|gates|reliability|cost|value|audit|advise FILE.json")
    if args.action == "score":
        out = platform_eval.score(doc.get("matrix") or doc.get("rows") or [])
    elif args.action == "alpha":
        out = platform_eval.alpha(doc.get("matrix") or doc.get("rows") or [])
    elif args.action == "tiers":
        scores = platform_eval.score(doc.get("matrix") or doc.get("rows") or [])
        out = platform_eval.tiers(doc.get("totals") or scores.get("totals") or {})
    elif args.action == "gates":
        out = platform_eval.gates(doc.get("record") or doc)
    elif args.action == "reliability":
        out = platform_eval.reliability(doc.get("record") or doc)
    elif args.action == "cost":
        out = platform_eval.cost_of_pass(doc.get("record") or doc)
    elif args.action == "value":
        out = platform_eval.business_value(doc.get("record") or doc)
    elif args.action == "audit":
        out = platform_eval.audit(doc.get("record") or doc)
    else:
        out = platform_eval.advise(doc.get("profile") or doc)
    _emit(platform_eval, out)


def cmd_contaudit(args):
    """Round 152 (arXiv:2611.24491): continue a real session, judge only what follows."""
    from longrun.harness.checks import continuation_audit
    doc = _load_doc(args, "contaudit cuts|realism|awareness|score|narrow|mandate|cover|ablation|audit|advise FILE.json")
    if args.action == "cuts":
        out = continuation_audit.cuts(doc.get("rows") or [])
    elif args.action == "realism":
        out = continuation_audit.realism(doc.get("rows") or [])
    elif args.action == "awareness":
        out = continuation_audit.awareness(doc.get("rows") or [])
    elif args.action == "score":
        out = continuation_audit.score(doc.get("record") or doc)
    elif args.action == "narrow":
        out = continuation_audit.narrow(doc.get("record") or doc)
    elif args.action == "mandate":
        out = continuation_audit.mandate(doc.get("turns") or doc.get("rows") or [])
    elif args.action == "cover":
        out = continuation_audit.cover(doc.get("record") or doc)
    elif args.action == "ablation":
        out = continuation_audit.policy(doc.get("rows") or [])
    elif args.action == "audit":
        out = continuation_audit.audit(doc.get("record") or doc)
    else:
        out = continuation_audit.advise(doc.get("profile") or doc)
    _emit(continuation_audit, out)


def cmd_toolext(args):
    """Round 152 (arXiv:2611.23810): a new tool reuses when-to-call, not which-tool."""
    from longrun.harness.checks import tool_extension
    doc = _load_doc(args, "toolext verified|retention|gain|drift|decisions|cost|admit|audit|advise FILE.json")
    if args.action == "verified":
        out = tool_extension.verified(doc.get("rows") or [])
    elif args.action == "retention":
        out = tool_extension.retention(doc.get("record") or doc)
    elif args.action == "gain":
        out = tool_extension.gain(doc.get("record") or doc)
    elif args.action == "drift":
        out = tool_extension.drift(doc.get("record") or doc)
    elif args.action == "decisions":
        out = tool_extension.decisions()
    elif args.action == "cost":
        out = tool_extension.cost(doc.get("record") or doc)
    elif args.action == "admit":
        out = tool_extension.admit(doc.get("record") or doc)
    elif args.action == "audit":
        out = tool_extension.audit(doc.get("record") or doc)
    else:
        out = tool_extension.advise(doc.get("profile") or doc)
    _emit(tool_extension, out)


def cmd_fastpath(args):
    """Round 152 (arXiv:2611.23751): bounded choices in one pass, the rest to System-2."""
    from longrun.harness.checks import fast_path
    doc = _load_doc(args, "fastpath classify|program|calibrate|gate|cost|smoothed|aurc|collapsed|audit|advise FILE.json")
    if args.action == "classify":
        out = fast_path.classify(doc.get("record") or doc)
    elif args.action == "program":
        out = fast_path.program(doc.get("rows") or [])
    elif args.action == "calibrate":
        out = fast_path.calibrate(doc.get("record") or doc)
    elif args.action == "gate":
        out = fast_path.gate(doc.get("record") or doc)
    elif args.action == "cost":
        out = fast_path.cost(doc.get("record") or doc)
    elif args.action == "smoothed":
        out = fast_path.smoothed(doc.get("probs") or [], doc.get("epsilon"))
    elif args.action == "aurc":
        out = fast_path.aurc(doc.get("rows") or [])
    elif args.action == "collapsed":
        out = fast_path.collapsed(doc.get("record") or doc)
    elif args.action == "audit":
        out = fast_path.audit(doc.get("record") or doc)
    else:
        out = fast_path.advise(doc.get("profile") or doc)
    _emit(fast_path, out)


def cmd_tariff(args):
    """Round 153 (arXiv:2611.24071): what a retained token is charged, and which bound holds."""
    from longrun.harness.checks import context_tariff
    doc = _load_doc(args, "tariff charge|lifetime|coverage|bounds|quality|fairness|audit|advise FILE.json")
    if args.action == "charge":
        out = context_tariff.charge(doc.get("record") or doc)
    elif args.action == "lifetime":
        out = context_tariff.lifetime(doc.get("record") or doc)
    elif args.action == "coverage":
        out = context_tariff.coverage(doc.get("record") or doc)
    elif args.action == "bounds":
        out = context_tariff.bounds(doc.get("record") or doc)
    elif args.action == "quality":
        out = context_tariff.quality(doc.get("rows") or [])
    elif args.action == "fairness":
        out = context_tariff.fairness(doc.get("record") or doc)
    elif args.action == "audit":
        out = context_tariff.audit(doc.get("record") or doc)
    else:
        out = context_tariff.advise(doc.get("profile") or doc)
    _emit(context_tariff, out)


def cmd_hyperke(args):
    """Round 153 (arXiv:2611.24294): a typed store kept sound under edits."""
    from longrun.harness.checks import hypergraph_ke
    doc = _load_doc(args, "hyperke ingest|join|edit|route|evidence|oke|audit|advise FILE.json")
    if args.action == "ingest":
        out = hypergraph_ke.ingest(doc.get("rows") or [])
    elif args.action == "join":
        out = hypergraph_ke.join(doc.get("rows") or [])
    elif args.action == "edit":
        out = hypergraph_ke.edit(doc.get("record") or doc)
    elif args.action == "route":
        out = hypergraph_ke.route(doc.get("record") or doc)
    elif args.action == "evidence":
        out = hypergraph_ke.evidence(doc.get("record") or doc)
    elif args.action == "oke":
        out = hypergraph_ke.oke(doc.get("rows") or [])
    elif args.action == "audit":
        out = hypergraph_ke.audit(doc.get("record") or doc)
    else:
        out = hypergraph_ke.advise(doc.get("profile") or doc)
    _emit(hypergraph_ke, out)


def cmd_beliefprobe(args):
    """Round 153 (arXiv:2611.23938): did the fact go in, and does the metric still mean anything?"""
    from longrun.harness.checks import belief_probe
    doc = _load_doc(args, "beliefprobe belief|categories|scaling|depth|judge|independence|reality|audit|advise FILE.json")
    if args.action == "belief":
        out = belief_probe.belief_rate(doc.get("rows") or [])
    elif args.action == "categories":
        out = belief_probe.categories(doc.get("rows") or [])
    elif args.action == "scaling":
        out = belief_probe.scaling(doc.get("rows") or [])
    elif args.action == "depth":
        out = belief_probe.depth(doc.get("rows") or [])
    elif args.action == "judge":
        out = belief_probe.judge(doc.get("record") or doc)
    elif args.action == "independence":
        out = belief_probe.independence(doc.get("record") or doc)
    elif args.action == "reality":
        out = belief_probe.reality(doc.get("record") or doc)
    elif args.action == "audit":
        out = belief_probe.audit(doc.get("record") or doc)
    else:
        out = belief_probe.advise(doc.get("profile") or doc)
    _emit(belief_probe, out)


def cmd_awareness(args):
    """Round 154 (arXiv:2611.05391): verified host state as a bounded decision input."""
    from longrun.harness.checks import awareness
    doc = _load_doc(args, "awareness reduce|cost|best|regret|snapshot|choose|ablate|wilson|authority|audit|advise FILE.json")
    if args.action == "reduce":
        out = awareness.reduce(doc.get("observations") or [], doc.get("window"))
    elif args.action == "cost":
        out = awareness.cost(doc.get("row") or doc)
    elif args.action == "best":
        out = awareness.best(doc.get("rows") or [])
    elif args.action == "regret":
        out = awareness.regret(doc.get("rows") or [], doc.get("choice"))
    elif args.action == "snapshot":
        out = awareness.snapshot(doc.get("rows") or [], doc.get("now"),
                                 doc.get("max_age_ms", awareness.DEFAULT_MAX_AGE_MS),
                                 doc.get("max_rows"), doc.get("verified", True))
    elif args.action == "choose":
        out = awareness.choose(doc.get("snapshot") or {}, doc.get("action"),
                               doc.get("current"))
    elif args.action == "ablate":
        out = awareness.ablate(doc.get("arms") or [])
    elif args.action == "wilson":
        # A helper interval, not a verdict: stamp the group's FORMAT so the
        # output contract is the same as every other action of this group.
        out = {"format": awareness.FORMAT,
               "wilson": awareness.wilson(doc.get("k"), doc.get("n"))}
    elif args.action == "authority":
        out = awareness.authority(doc.get("record") or doc)
    elif args.action == "audit":
        out = awareness.audit(doc.get("record") or doc)
    else:
        out = awareness.advise(doc.get("profile") or doc)
    _emit(awareness, out)


def cmd_diagnostics(args):
    """Round 154 (arXiv:2611.04507): findings, Signals, severity and remediation."""
    from longrun.harness.checks import diagnostics
    doc = _load_doc(args, "diagnostics taxonomy|finding|scope|severity|group|update|match|coverage|audit|advise FILE.json")
    if args.action == "taxonomy":
        out = diagnostics.taxonomy()
    elif args.action == "finding":
        out = diagnostics.finding(doc.get("record") or doc)
    elif args.action == "scope":
        out = diagnostics.scope(doc.get("affected"), doc.get("analyzed"))
    elif args.action == "severity":
        out = diagnostics.severity(doc.get("record") or doc)
    elif args.action == "group":
        out = diagnostics.group(doc.get("findings") or [])
    elif args.action == "update":
        out = diagnostics.update(doc.get("signal") or {}, doc.get("run") or {})
    elif args.action == "match":
        out = diagnostics.match(doc.get("predicted") or [], doc.get("reference") or [])
    elif args.action == "coverage":
        out = diagnostics.coverage(doc.get("predicted") or [],
                                   doc.get("reference") or [])
    elif args.action == "audit":
        out = diagnostics.audit(doc.get("record") or doc)
    else:
        out = diagnostics.advise(doc.get("profile") or doc)
    _emit(diagnostics, out)


def cmd_orchcredit(args):
    """Round 154 (arXiv:2611.07495): interaction-aware credit and certified updates."""
    from longrun.harness.checks import orchestration_credit
    doc = _load_doc(args, "orchcredit orders|bound|z2|certify|select|detect|leaps|complementarity|controlled|audit|advise FILE.json")
    if args.action == "orders":
        out = orchestration_credit.orders(doc.get("record") or doc)
    elif args.action == "bound":
        out = orchestration_credit.bound(doc.get("K"), doc.get("eta"), doc.get("gbar"))
    elif args.action == "z2":
        out = orchestration_credit.z2(doc.get("record") or doc)
    elif args.action == "certify":
        out = orchestration_credit.certify(doc.get("record") or doc)
    elif args.action == "select":
        out = orchestration_credit.select(doc.get("candidates") or [])
    elif args.action == "detect":
        out = orchestration_credit.detect(doc.get("record") or doc)
    elif args.action == "leaps":
        out = orchestration_credit.leaps(doc.get("record") or doc)
    elif args.action == "complementarity":
        out = orchestration_credit.complementarity(doc.get("record") or doc)
    elif args.action == "controlled":
        out = orchestration_credit.controlled(doc.get("record") or doc)
    elif args.action == "audit":
        out = orchestration_credit.audit(doc.get("record") or doc)
    else:
        out = orchestration_credit.advise(doc.get("profile") or doc)
    _emit(orchestration_credit, out)


def _schema_record(doc):
    """A checker record whose `name` may be supplied as a live tool name.

    `registry.tool_record` is the ONE schema normalizer, so a CLI fixture may be
    `{"tool": "fs.write"}` instead of a hand-assembled `args` list.
    """
    rec = doc.get("record") or doc
    if isinstance(rec, dict) and not rec.get("name"):
        tool = rec.get("tool")
        if isinstance(tool, str) and tool:
            try:
                from longrun.tools import registry
                return registry.tool_record(tool) or rec
            except Exception:  # noqa: BLE001 — a missing catalog keeps the input
                return rec
    return rec


def _live_call(doc):
    """A call record whose string `tool` is resolved through the normalizer."""
    call = dict(doc.get("call") or {})
    tool = call.get("tool")
    if isinstance(tool, str) and tool:
        try:
            from longrun.tools import registry
            rec = registry.tool_record(tool)
        except Exception:  # noqa: BLE001 — a missing catalog keeps the input
            rec = None
        if rec:
            call["tool"] = rec
    return call


def cmd_intentgraph(args):
    """Round 155 (arXiv:2611.11305): least-privilege auditing against an intent DAG."""
    from longrun.harness import intent_audit
    doc = _load_doc(args, "intentgraph graph|scope|classify|audit|metrics|coupling|audit_record|advise FILE.json")
    if args.action == "graph":
        out = intent_audit.graph(doc.get("record") or doc)
    elif args.action == "scope":
        out = intent_audit.scope(doc.get("expr"), doc.get("params") or {},
                                 doc.get("policy") or "fail-closed")
    elif args.action == "classify":
        out = intent_audit.policy(_schema_record(doc))
    elif args.action == "audit":
        out = intent_audit.audit(_live_call(doc), doc.get("graph") or {},
                                 doc.get("state"), doc.get("bypass") is True,
                                 doc.get("severity"), doc.get("threshold", 0.99),
                                 doc.get("scope_policy") or "fail-closed")
    elif args.action == "metrics":
        out = intent_audit.metrics(doc.get("rows") or [])
    elif args.action == "coupling":
        out = intent_audit.coupling(doc.get("record") or doc)
    elif args.action == "audit_record":
        out = intent_audit.audit_record(doc.get("record") or doc)
    else:
        out = intent_audit.advise(doc.get("profile") or doc)
    _emit(intent_audit, out)


def cmd_writeguard(args):
    """Round 155 (arXiv:2611.17115): schema-derived policy and exact grounding."""
    from longrun.harness.checks import write_integrity
    doc = _load_doc(args, "writeguard classify|grounding|commit|mediate|integrity|ablate|audit|advise FILE.json")
    if args.action == "classify":
        out = write_integrity.policy(_schema_record(doc))
    elif args.action == "grounding":
        out = write_integrity.grounding(doc.get("request") or doc.get("text"))
    elif args.action == "commit":
        out = write_integrity.commit(doc.get("plan") or doc)
    elif args.action == "mediate":
        out = write_integrity.mediate(_live_call(doc),
                                      doc.get("ground") or {},
                                      doc.get("plan"), doc.get("schema"))
    elif args.action == "integrity":
        out = write_integrity.integrity(doc.get("trace") or doc)
    elif args.action == "ablate":
        out = write_integrity.ablate(doc.get("record") or doc)
    elif args.action == "audit":
        out = write_integrity.audit_record(doc.get("record") or doc)
    else:
        out = write_integrity.advise(doc.get("profile") or doc)
    _emit(write_integrity, out)


def cmd_ctxregime(args):
    """Round 155 (arXiv:2611.05306): short working context and disciplined state."""
    from longrun.harness.checks import context_regime
    doc = _load_doc(args, "ctxregime length|charge|savings|compaction|regimes|selective|sac|history|audit|advise FILE.json")
    if args.action == "length":
        out = context_regime.length(doc.get("record") or doc)
    elif args.action == "charge":
        out = context_regime.charge(doc.get("record") or doc)
    elif args.action == "savings":
        out = context_regime.savings(doc.get("record") or doc)
    elif args.action == "compaction":
        out = context_regime.compaction(doc.get("record") or doc)
    elif args.action == "regimes":
        out = context_regime.regimes(doc.get("record") or doc)
    elif args.action == "selective":
        out = context_regime.selective(doc.get("record") or doc)
    elif args.action == "sac":
        out = context_regime.sac(doc.get("record") or doc)
    elif args.action == "history":
        out = context_regime.history(doc.get("record") or doc)
    elif args.action == "audit":
        out = context_regime.audit_record(doc.get("record") or doc)
    else:
        out = context_regime.advise(doc.get("profile") or doc)
    _emit(context_regime, out)


def cmd_skillgate(args):
    """Round 156 (arXiv:2608.05810): admission before the pool."""
    from longrun.harness.checks import skill_gate
    usage = ("skillgate tiers|critic|gain|taxonomy|curve|select|"
             "irreversibility|rollback|audit|advise [FILE.json]")
    if not getattr(args, "file", None) and args.action != "tiers":
        print("usage: " + usage, file=sys.stderr)
        sys.exit(2)
    doc = _load_doc(args, usage) if getattr(args, "file", None) else {}
    if args.action == "tiers":
        out = skill_gate.tiers()
    elif args.action == "critic":
        out = skill_gate.critic(doc.get("record") or doc)
    elif args.action == "gain":
        out = skill_gate.gain(doc.get("record") or doc)
    elif args.action == "taxonomy":
        out = skill_gate.taxonomy(doc.get("record") or doc)
    elif args.action == "curve":
        out = skill_gate.curve(doc.get("rows") or [])
    elif args.action == "select":
        out = skill_gate.select(doc.get("candidates") or [])
    elif args.action == "irreversibility":
        out = skill_gate.irreversibility(doc.get("record") or doc)
    elif args.action == "rollback":
        out = skill_gate.rollback(doc.get("record") or doc)
    elif args.action == "audit":
        out = skill_gate.audit_record(doc.get("record") or doc)
    else:
        out = skill_gate.advise(doc.get("profile") or doc)
    _emit(skill_gate, out)


def cmd_skillflow(args):
    """Round 156 (arXiv:2611.20584): the plugin population as a gas."""
    from longrun.harness.checks import skill_flow
    doc = _load_doc(args, "skillflow ledger|project|regime|sound|shock|instruments|diagnose|audit|advise FILE.json")
    if args.action == "ledger":
        out = skill_flow.ledger(doc.get("events") or [])
    elif args.action == "project":
        out = skill_flow.project(doc.get("edits") or [], doc.get("reserve"))
    elif args.action == "regime":
        out = skill_flow.regime(doc.get("series") or [])
    elif args.action == "sound":
        out = skill_flow.sound(doc.get("record") or doc)
    elif args.action == "shock":
        out = skill_flow.shock(doc.get("record") or doc)
    elif args.action == "instruments":
        out = skill_flow.instruments(doc.get("record") or doc)
    elif args.action == "diagnose":
        out = skill_flow.diagnose(doc.get("record") or doc)
    elif args.action == "audit":
        out = skill_flow.audit_record(doc.get("record") or doc)
    else:
        out = skill_flow.advise(doc.get("profile") or doc)
    _emit(skill_flow, out)


def cmd_skilleve(args):
    """Round 156 (arXiv:2611.03238): evidence-grounded skill evolution."""
    from longrun.harness.checks import skill_evolution
    doc = _load_doc(args, "skilleve entry|evidence|diagnose|candidate|validate|consolidate|budget|audit|advise FILE.json")
    if args.action == "entry":
        out = skill_evolution.entry(doc.get("record") or doc)
    elif args.action == "evidence":
        out = skill_evolution.evidence(doc.get("record") or doc)
    elif args.action == "diagnose":
        out = skill_evolution.diagnose(doc.get("record") or doc)
    elif args.action == "candidate":
        out = skill_evolution.candidate(doc.get("record") or doc)
    elif args.action == "validate":
        out = skill_evolution.validate(doc.get("record") or doc)
    elif args.action == "consolidate":
        out = skill_evolution.consolidate(doc.get("record") or doc)
    elif args.action == "budget":
        out = skill_evolution.budget(doc.get("record") or doc)
    elif args.action == "audit":
        out = skill_evolution.audit_record(doc.get("record") or doc)
    else:
        out = skill_evolution.advise(doc.get("profile") or doc)
    _emit(skill_evolution, out)


def cmd_takeover(args):
    """Round 157 (arXiv:2611.07307): requirements recovered, then delivered."""
    from longrun.harness.checks import takeover_eval
    doc = _load_doc(args, "takeover atom|update|delivery|rq1|rq2|decision|poststate|clarify|audit|advise FILE.json")
    if args.action == "atom":
        out = takeover_eval.atom(doc.get("record") or doc)
    elif args.action == "update":
        out = takeover_eval.update(doc.get("before") or {},
                                   doc.get("change") or {})
    elif args.action == "delivery":
        out = takeover_eval.delivery(doc.get("rows") or [])
    elif args.action == "rq1":
        out = takeover_eval.rq1(doc.get("pred") or {}, doc.get("gold") or {})
    elif args.action == "rq2":
        out = takeover_eval.rq2(doc.get("pred") or {}, doc.get("gold") or {},
                                doc.get("matched") or [])
    elif args.action == "decision":
        out = takeover_eval.decision(doc.get("rows") or [])
    elif args.action == "poststate":
        out = takeover_eval.poststate(doc.get("record") or doc)
    elif args.action == "clarify":
        out = takeover_eval.clarify(doc.get("record") or doc)
    elif args.action == "audit":
        out = takeover_eval.audit_record(doc.get("record") or doc)
    else:
        out = takeover_eval.advise(doc.get("profile") or doc)
    _emit(takeover_eval, out)


def cmd_anytime(args):
    """Round 157 (arXiv:2611.21241): certificates after an adaptive sweep."""
    from longrun.harness.checks import anytime_cert
    doc = _load_doc(args, "anytime certificate|grid|structured|margin|allocate|optimism|audit|advise FILE.json")
    if args.action == "certificate":
        out = anytime_cert.certificate(doc.get("record") or doc)
    elif args.action == "grid":
        out = anytime_cert.grid(doc.get("record") or doc)
    elif args.action == "structured":
        out = anytime_cert.structured(doc.get("record") or doc)
    elif args.action == "margin":
        out = anytime_cert.margin(doc.get("record") or doc)
    elif args.action == "allocate":
        out = anytime_cert.allocate(doc.get("record") or doc)
    elif args.action == "optimism":
        out = anytime_cert.optimism(doc.get("record") or doc)
    elif args.action == "audit":
        out = anytime_cert.audit_record(doc.get("record") or doc)
    else:
        out = anytime_cert.advise(doc.get("profile") or doc)
    _emit(anytime_cert, out)


def cmd_longhorizon(args):
    """Round 157 (arXiv:2611.05620): all-or-nothing delivery over many requests."""
    from longrun.harness.checks import longhorizon_eval
    doc = _load_doc(args, "longhorizon plan|grade|gap|horizon|split|grade_quality|audit|advise FILE.json")
    if args.action == "plan":
        out = longhorizon_eval.plan(doc.get("record") or doc)
    elif args.action == "grade":
        out = longhorizon_eval.grade(doc.get("record") or doc)
    elif args.action == "gap":
        out = longhorizon_eval.gap(doc.get("record") or doc)
    elif args.action == "horizon":
        out = longhorizon_eval.horizon(doc.get("record") or doc)
    elif args.action == "split":
        out = longhorizon_eval.split(doc.get("record") or doc)
    elif args.action == "grade_quality":
        out = longhorizon_eval.grade_quality(doc.get("record") or doc)
    elif args.action == "audit":
        out = longhorizon_eval.audit_record(doc.get("record") or doc)
    else:
        out = longhorizon_eval.advise(doc.get("profile") or doc)
    _emit(longhorizon_eval, out)


def cmd_memchannel(args):
    """Round 158 (arXiv:2606.04329): a memory write is a trigger plus an authority."""
    from longrun.harness import memory_channel
    doc = _load_doc(args, "memchannel channels|vulns|classify|taxonomy|exposure|coverage|cost|audit|advise FILE.json")
    if args.action == "channels":
        out = memory_channel.channels()
    elif args.action == "vulns":
        out = memory_channel.vulnerabilities()
    elif args.action == "classify":
        out = memory_channel.classify(doc.get("record") or doc)
    elif args.action == "taxonomy":
        out = memory_channel.taxonomy(doc.get("record") or doc)
    elif args.action == "exposure":
        out = memory_channel.exposure(doc.get("record") or doc)
    elif args.action == "coverage":
        out = memory_channel.coverage(doc.get("record") or doc)
    elif args.action == "cost":
        out = memory_channel.cost(doc.get("record") or doc)
    elif args.action == "audit":
        out = memory_channel.audit_record(doc.get("record") or doc)
    else:
        out = memory_channel.advise(doc.get("profile") or doc)
    _emit(memory_channel, out)


def cmd_memauthority(args):
    """Round 158 (arXiv:2606.24322): authority is bound to origin, at write time."""
    from longrun.harness import memory_authority
    doc = _load_doc(args, "memauthority item|derive|corroborate|authorize|gate|weakening|separation|model_check|audit|advise FILE.json")
    if args.action == "item":
        out = memory_authority.item(doc.get("record") or doc)
    elif args.action == "derive":
        out = memory_authority.derive(doc.get("record") or doc)
    elif args.action == "corroborate":
        out = memory_authority.corroborate(doc.get("record") or doc)
    elif args.action == "authorize":
        out = memory_authority.authorize(doc.get("record") or doc)
    elif args.action == "gate":
        out = memory_authority.gate(doc.get("record") or doc)
    elif args.action == "weakening":
        out = memory_authority.weakening(doc.get("record") or doc)
    elif args.action == "separation":
        out = memory_authority.separation(doc.get("record") or doc)
    elif args.action == "model_check":
        out = memory_authority.model_check(doc.get("record") or doc)
    elif args.action == "audit":
        out = memory_authority.audit_record(doc.get("record") or doc)
    else:
        out = memory_authority.advise(doc.get("profile") or doc)
    _emit(memory_authority, out)


def cmd_exfild(args):
    """Round 158 (arXiv:2605.01970): every defense breaks one of three steps."""
    from longrun.harness.checks import exfil_defense
    doc = _load_doc(args, "exfild points|defenses|applicability|chain|utility|frontier|persistence|audit|advise FILE.json")
    if args.action == "points":
        out = exfil_defense.points()
    elif args.action == "defenses":
        out = exfil_defense.defenses(doc.get("record") or doc)
    elif args.action == "applicability":
        out = exfil_defense.applicability(doc.get("record") or doc)
    elif args.action == "chain":
        out = exfil_defense.chain(doc.get("record") or doc)
    elif args.action == "utility":
        out = exfil_defense.utility(doc.get("record") or doc)
    elif args.action == "frontier":
        out = exfil_defense.frontier(doc.get("record") or doc)
    elif args.action == "persistence":
        out = exfil_defense.persistence(doc.get("record") or doc)
    elif args.action == "audit":
        out = exfil_defense.audit_record(doc.get("record") or doc)
    else:
        out = exfil_defense.advise(doc.get("profile") or doc)
    _emit(exfil_defense, out)


def cmd_formation(args):
    """Round 159 (arXiv:2610.00583): a team of separate agents against one coordinator."""
    from longrun.harness.checks import multiagent_formation
    doc = _load_doc(args, "formation formations|outcome|participation|fairness|interference|mitigation|failure|audit|advise FILE.json")
    if args.action == "formations":
        out = multiagent_formation.formations()
    elif args.action == "outcome":
        out = multiagent_formation.outcome(doc.get("record") or doc)
    elif args.action == "participation":
        out = multiagent_formation.participation(doc.get("record") or doc)
    elif args.action == "fairness":
        out = multiagent_formation.fairness(doc.get("record") or doc)
    elif args.action == "interference":
        out = multiagent_formation.interference(doc.get("record") or doc)
    elif args.action == "mitigation":
        out = multiagent_formation.mitigation(doc.get("record") or doc)
    elif args.action == "failure":
        out = multiagent_formation.failure(doc.get("record") or doc)
    elif args.action == "audit":
        out = multiagent_formation.audit_record(doc.get("record") or doc)
    else:
        out = multiagent_formation.advise(doc.get("profile") or doc)
    _emit(multiagent_formation, out)


def cmd_teammate(args):
    """Round 159 (arXiv:2611.02633): collaboration as one model's capability."""
    from longrun.harness.checks import teammate_eval
    doc = _load_doc(args, "teammate dimensions|score|gate|drop|conflict|failure_mode|inheritance|audit|advise FILE.json")
    if args.action == "dimensions":
        out = teammate_eval.dimensions()
    elif args.action == "score":
        out = teammate_eval.score(doc.get("record") or doc)
    elif args.action == "gate":
        out = teammate_eval.gate(doc.get("record") or doc)
    elif args.action == "drop":
        out = teammate_eval.drop(doc.get("record") or doc)
    elif args.action == "conflict":
        out = teammate_eval.conflict(doc.get("record") or doc)
    elif args.action == "failure_mode":
        out = teammate_eval.failure_mode(doc.get("record") or doc)
    elif args.action == "inheritance":
        out = teammate_eval.inheritance(doc.get("record") or doc)
    elif args.action == "audit":
        out = teammate_eval.audit_record(doc.get("record") or doc)
    else:
        out = teammate_eval.advise(doc.get("profile") or doc)
    _emit(teammate_eval, out)


def cmd_museprincipals(args):
    """Round 159 (arXiv:2604.08567): one context, many principals, explicit rules."""
    from longrun.harness.checks import principal_policy
    doc = _load_doc(args, "museprincipals principals|precedence|access|selection|privacy_utility|meeting|conflict_effect|audit|advise FILE.json")
    if args.action == "principals":
        out = principal_policy.principals(doc.get("record") or doc)
    elif args.action == "precedence":
        out = principal_policy.precedence(doc.get("record") or doc)
    elif args.action == "access":
        out = principal_policy.access(doc.get("record") or doc)
    elif args.action == "selection":
        out = principal_policy.selection(doc.get("record") or doc)
    elif args.action == "privacy_utility":
        out = principal_policy.privacy_utility(doc.get("record") or doc)
    elif args.action == "meeting":
        out = principal_policy.meeting(doc.get("record") or doc)
    elif args.action == "conflict_effect":
        out = principal_policy.conflict_effect(doc.get("record") or doc)
    elif args.action == "audit":
        out = principal_policy.audit_record(doc.get("record") or doc)
    else:
        out = principal_policy.advise(doc.get("profile") or doc)
    _emit(principal_policy, out)


def cmd_instructions(args):
    """Round 114 (arXiv:2611.13709): explicit context-file directives vs the cards."""
    from longrun.harness.checks import instruction_audit
    doc = _load_doc(args, "instructions audit FILE.json")
    out = instruction_audit.audit(doc.get("text") or "", doc.get("cards") or [])
    _emit(instruction_audit, out, lambda o: o["verdict"] == "clean")


def cmd_teams(args):
    """Round 113 (arXiv:2611.17820): the safety lead + published safety specs audit."""
    from longrun.harness.checks import team_safety
    doc = _load_doc(args, "teams audit FILE.json")
    out = team_safety.audit(doc)
    out["brief"] = team_safety.brief(doc)
    _emit(team_safety, out, lambda o: o["verdict"] == "covered")


def cmd_toolgraph(args):
    """Round 113 (arXiv:2611.20569): compile the tool dependency graph, or ask it."""
    from longrun.harness.checks import tool_graph
    doc = _load_doc(args, "toolgraph %s FILE.json" % args.action)
    graph = tool_graph.build(doc.get("catalog") or [], doc.get("transitions") or [],
                             doc.get("probes") or [])
    if args.action == "build":
        _emit(tool_graph, {k: v for k, v in graph.items() if k != "nodes"})
    _emit(tool_graph, tool_graph.feedback(graph, doc.get("goal") or "",
                                          doc.get("candidate") or "",
                                          doc.get("state_types") or []))


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
        # Args are validated BEFORE the session is resolved: a usage error must
        # read as a usage error even when no session is current.
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
        ref = _current_session()
        if not ref:
            _no_current_session()
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
        # Args are validated BEFORE the session is resolved (same rule as above).
        idx = str(args.value or "").strip()
        content = getattr(args, "content", None)
        if idx == "" or not str(content or "").strip():
            print('usage: sessions model-counterfactual INDEX --content "new text"'
                  "   (INDEX = the #N from sessions history; -1 = the last"
                  " intervenable message)", file=sys.stderr)
            sys.exit(2)
        try:
            idx = int(idx)
        except ValueError:
            print("INDEX must be an integer (the #N of the message): %r" % idx,
                  file=sys.stderr)
            sys.exit(2)
        ref = _current_session()
        if not ref:
            _no_current_session()
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
    from longrun.harness.checks import setup_blocks
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
    from longrun.harness import skills_maintenance
    from longrun.harness.checks import skill_value
    if args.action in ("compile", "optimize", "conflict"):
        # Round 118: verified-trace compilation (2611.01386), SkIR repair (2611.20856),
        # cross-skill conflict (2610.35082).
        from longrun.harness.checks import skill_compiler, skill_repair, skill_conflict
        doc = _load_doc(args, "skills %s FILE.json" % args.action)
        if args.action == "compile":
            out = skill_compiler.compile_skill(doc.get("trace") or doc,
                                               doc.get("min_strength") or "independent")
            _emit(skill_compiler, out, lambda o: o["admitted"])
        if args.action == "optimize":
            out = skill_repair.repair(doc)
            _emit(skill_repair, out, lambda o: o["accepted"])
        out = skill_conflict.conflicts(doc.get("pool") or doc)
        _emit(skill_conflict, out, lambda o: o["verdict"] == "clean")
    if args.action == "prune":
        # Round 112 (arXiv:2611.19823): compact a skill without touching contract lines.
        from longrun.harness.checks import skill_prune
        doc = _load_doc(args, "skills prune FILE.json [--budget N] [--write]",
                        allow_list=False)
        text = doc.get("text") if isinstance(doc, dict) else doc
        out = skill_prune.prune(text or "", budget_tokens=getattr(args, "budget", None))
        if getattr(args, "write", False):
            with open(args.value, "w", encoding="utf-8") as fh:
                fh.write(out["text"])
        _emit(skill_prune, {k: v for k, v in out.items() if k != "text"})
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
    doc = _load_doc(args, "skills %s FILE" % args.action, allow_list=True)
    if args.action == "value":
        recs = doc.get("records") if isinstance(doc, dict) else doc
        _emit(skill_value, skill_value.paired(recs))
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
        with open(args.value, "w", encoding="utf-8") as fh:
            fh.write(res["text"])
    _emit(skills_maintenance,
          {"format": skills_maintenance.FORMAT, "changes": res["changes"],
           "written": bool(getattr(args, "write", False))})


def cmd_autonomy(args):
    """Round 112 (arXiv:2611.10058): bounded/observable/reversible autonomy scorecard."""
    from longrun.harness.checks import autonomy
    doc = _load_doc(args, "autonomy check FILE.json", allow_list=True)
    rows = doc.get("actions") if isinstance(doc, dict) else doc
    out = autonomy.scoreboard(rows or [])
    _emit(autonomy, out)


def cmd_reuse(args):
    """Round 110 (arXiv:2611.09254): repeated deterministic reads in a card file."""
    from longrun.harness import reuse
    doc = _load_doc(args, "reuse audit FILE.json [--allow a,b]", allow_list=True)
    cards = doc.get("cards") if isinstance(doc, dict) else doc
    allow = None
    if getattr(args, "allow", None):
        allow = [t.strip() for t in str(args.allow).split(",") if t.strip()]
    out = reuse.audit(cards or [], allow=allow)
    _emit(reuse, out)


def cmd_principals(args):
    """Round 110 (arXiv:2611.08768): principal-context authorization + laundering."""
    from longrun.harness.checks import principals
    doc = _load_doc(args, "principals check FILE.json")
    out = principals.check(doc)
    _emit(principals, out, lambda o: o.get("allow"))


def cmd_residency(args):
    """Round 110 (arXiv:2611.13412): the park/admit band over a session file."""
    from longrun.util import residency
    doc = _load_doc(args, "residency plan FILE.json --capacity N [--current SID]",
                    allow_list=True)
    sessions = doc.get("sessions") if isinstance(doc, dict) else doc
    out = residency.plan(sessions or [], getattr(args, "capacity", 0),
                         current=getattr(args, "current", None))
    _emit(residency, out)


def cmd_procedure(args):
    """Round 111 (arXiv:2611.10884): replay a procedure FSM over plain events."""
    from longrun.plan import procedure
    doc = _load_doc(args, "procedure run FILE.json")
    out = procedure.replay(doc.get("procedure") or doc, doc.get("events") or [])
    _emit(procedure, out)


def cmd_intent(args):
    """Round 111 (arXiv:2611.06563): declarations against observed effects."""
    from longrun.harness.checks import intent_journal
    doc = _load_doc(args, "intent %s FILE.json" % args.action, allow_list=True)
    if args.action == "check":
        out = intent_journal.check(doc.get("declaration") or {},
                                   doc.get("effects") or {},
                                   doc.get("declared_targets"))
    else:
        rows = doc.get("entries") if isinstance(doc, dict) else doc
        out = intent_journal.audit(rows)
    _emit(intent_journal, out, lambda o: o.get("verdict") in ("clean",))


def cmd_handoff(args):
    """Round 111 (arXiv:2611.06545): policy sentences vs the permission ledger."""
    from longrun.harness.checks import handoff_audit
    doc = _load_doc(args, "handoff audit FILE.json")
    out = handoff_audit.audit(doc.get("text") or "", doc.get("ledger") or [])
    _emit(handoff_audit, out, lambda o: o.get("verdict") == "clean")


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
    _emit(manifest, manifest.build())


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


def cmd_harness(args):
    """List the per-paper groups from the PARSER, not from a hand-written block.

    The old docstring usage block drifted: it named `skills prune FILE.json`
    although `skills` keeps its path in `value`, it showed one action per group
    while the parser registers up to eleven, and it kept a `--json` flag nobody
    defines. This prints what is actually registered: every group whose command
    is a round-derived checker, its action choices, where its JSON input comes
    from, and the actions that read the live app instead. `harness GROUP` adds
    the group's own `-h`.
    """
    ap = _build_parser()
    sub = next(a for a in ap._actions
               if isinstance(a, argparse._SubParsersAction))
    if getattr(args, "group", None):
        target = sub.choices.get(args.group)
        if target is None:
            print("unknown group %r" % args.group, file=sys.stderr)
            sys.exit(2)
        target.print_help()
        return
    # A group is a per-paper checker when its command is one of the round-derived
    # wrappers, or when it is `skills` — a multi-purpose group whose stale/value/
    # repair/prune/compile/optimize/conflict actions are all round 112-156
    # checkers but whose docstring cannot start with "Round" (it also lists,
    # reads and audits the library).
    extra = {"skills"}
    rows = []
    for name, parser in sub.choices.items():
        fn = parser.get_default("fn")
        doc = (getattr(fn, "__doc__", "") or "").strip()
        if name not in extra and not re.match(r"Round \d+", doc):
            continue
        actions = []
        file_arg = None
        for act in parser._actions:
            if isinstance(act, argparse._SubParsersAction):
                continue
            if getattr(act, "choices", None):
                actions = list(act.choices)
            if act.dest in ("file", "value") and act.nargs in ("?", None) \
                    and act.dest not in ("action",):
                if act.dest == "file" or (file_arg is None and act.help
                                          and "JSON" in str(act.help)):
                    file_arg = act.dest
        rows.append((name, actions, file_arg))
    width = max(len(r[0]) for r in rows) if rows else 0
    print("%d per-paper groups (JSON in FILE; `harness GROUP -h` for one group)"
          % len(rows))
    for name, actions, file_arg in sorted(rows):
        where = ("file" if file_arg == "file"
                 else ("value" if file_arg == "value" else "—"))
        print("  %-*s  %-8s  %s" % (width, name, where,
                                    ", ".join(actions) or "-"))


def _build_parser():
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
    p = sub.add_parser("reversibility"); \
        p.add_argument("action", choices=["classify", "restoration", "capture",
                                          "classes", "recovery", "replay"]); \
        p.add_argument("file", nargs="?", help="JSON: {call, record}, {state}, {base_class, override}, {class}, {observations}, or {rows, baseline_policy}"); \
        p.set_defaults(fn=cmd_reversibility)
    p = sub.add_parser("gain"); \
        p.add_argument("action", choices=["vector", "interpolate", "reference",
                                          "decide", "calibrate", "frontier",
                                          "matched", "verdict", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {score}, {gains, reference}, {mode, current, best_previous}, {candidates, full, allowance}, {points, target}, {estimate, bounds}, or {profile}"); \
        p.set_defaults(fn=cmd_gain)
    p = sub.add_parser("history"); \
        p.add_argument("action", choices=["agree", "disclose", "effect",
                                          "interaction", "recheck", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record, world}, {arms}, {cells}, {runs}, or {policy}"); \
        p.set_defaults(fn=cmd_history)
    p = sub.add_parser("composed"); \
        p.add_argument("action", choices=["compose", "screens", "recognition",
                                          "channel", "gate", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {facts, binding}, {screens}, {rows}, {state}, or {profile}"); \
        p.set_defaults(fn=cmd_composed)
    p = sub.add_parser("measure"); \
        p.add_argument("action", choices=["specify", "specs", "decides",
                                          "power", "classifiers", "checklist"]); \
        p.add_argument("file", nargs="?", help="JSON: {choice, level}, {rows}, {clusters, detectable_below, detectable_above}, or {rows}"); \
        p.set_defaults(fn=cmd_measure)
    p = sub.add_parser("trap"); \
        p.add_argument("action", choices=["position", "ablation", "alert",
                                          "scope", "falsepositive"]); \
        p.add_argument("file", nargs="?", help="JSON: {bait, weakness}, {baseline, hardened, defended}, {event, rules}, {revocation, clients}, or {bait_use, legitimate}"); \
        p.set_defaults(fn=cmd_trap)
    p = sub.add_parser("evidence"); \
        p.add_argument("action", choices=["admit", "gates", "firstorder", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {cards, context}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_evidence)
    p = sub.add_parser("stress"); \
        p.add_argument("action", choices=["qualify", "promote", "pareto", "parent",
                                          "compare", "transfer", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {candidate}, {result}, {candidates}, {front, seed}, {configs}, {stressors, recipients}, or {profile}"); \
        p.set_defaults(fn=cmd_stress)
    p = sub.add_parser("trial"); \
        p.add_argument("action", choices=["paired", "noise", "claim", "mechanism",
                                          "funnel", "budget", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {run1, run2}, {rows, strata, run1}, {stats}, {stages}, {points}, or {profile}"); \
        p.set_defaults(fn=cmd_trial)
    p = sub.add_parser("scope"); \
        p.add_argument("action", choices=["item", "claim", "witness", "obligation",
                                          "reach", "classify", "explain", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {source, check, phase, operation, witness}, {claim}, {evidence, expected_operation}, {evidence, obligation}, {run}, {outcome}, {repair}, or {profile}"); \
        p.set_defaults(fn=cmd_scope)
    p = sub.add_parser("round"); \
        p.add_argument("action", choices=["champion", "decision", "lesson", "guardrails",
                                          "ladder", "progress", "frontier", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rounds}, {decision}, {entry}, {decision, state}, {rows}, {rounds}, {decision}, or {profile}"); \
        p.set_defaults(fn=cmd_round)
    p = sub.add_parser("attest"); \
        p.add_argument("action", choices=["identity", "certificate", "build", "calls",
                                          "accountability", "measure", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {request}, {cert, federation}, {build, approved}, {call}, {entries}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_attest)
    p = sub.add_parser("criteria"); \
        p.add_argument("action", choices=["criterion", "verdict", "coverage", "escalate",
                                          "measure", "decompose", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {text, source, polarity, compounds}, {record}, {criteria, trace}, {rows}, {text, actual}, or {profile}"); \
        p.set_defaults(fn=cmd_criteria)
    p = sub.add_parser("rubric"); \
        p.add_argument("action", choices=["capability", "verifier", "errors", "batch",
                                          "ablation", "agreement", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {name, description}, {config}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_rubric)
    p = sub.add_parser("docmaint"); \
        p.add_argument("action", choices=["signal", "gap", "tracker", "pipeline",
                                          "measure", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {ticket}, {gap}, {entries}, {draft}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_docmaint)
    p = sub.add_parser("priority"); \
        p.add_argument("action", choices=["statement", "report", "trace", "compare",
                                          "evidence", "revise", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {text}, {report}, {row}, {runs}, {path}, {interface}, or {profile}"); \
        p.set_defaults(fn=cmd_priority)
    p = sub.add_parser("values"); \
        p.add_argument("action", choices=["statement", "compare", "solutions",
                                          "oversight", "progress", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {text, value}, {rows}, {profile}, or {rows}"); \
        p.set_defaults(fn=cmd_values)
    p = sub.add_parser("crossenv"); \
        p.add_argument("action", choices=["task", "align", "rules", "validate",
                                          "curriculum", "measure", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {spec}, {records}, {task}, {row}, {levels}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_crossenv)
    p = sub.add_parser("resolution"); \
        p.add_argument("action", choices=["runs", "decompose", "verdict", "select",
                                          "quality", "advantage", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {margin, sd}, {rows}, {pairs}, {pool, k}, or {profile}"); \
        p.set_defaults(fn=cmd_resolution)
    p = sub.add_parser("replay"); \
        p.add_argument("action", choices=["trace", "replay", "variation", "parity",
                                          "render", "timing", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {states}, {record}, {source, port}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("dialogue"); \
        p.add_argument("action", choices=["posterior", "entropy", "speak", "evidence",
                                          "propositions", "schedule", "compare", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {prior, action, utterance}, {belief}, {before, after}, {n, rate}, {comm, base}, or {profile}"); \
        p.set_defaults(fn=cmd_dialogue)
    p = sub.add_parser("selective"); \
        p.add_argument("action", choices=["correct", "multiplier", "gate", "allocate",
                                          "resample", "audit", "selfcorrect", "detect", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {p, tail_matches, tail_replays, body_matches, body_replays}, {run}, {row}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_selective)
    p = sub.add_parser("continuation"); \
        p.add_argument("action", choices=["rate", "burst", "gains", "judgment", "relabel",
                                          "summary", "rules", "compare", "methods", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {turns}, {bins}, {text}, {record}, {spec}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_continuation)
    p = sub.add_parser("bench"); \
        p.add_argument("action", choices=["state", "freeze", "leak", "score", "trajectory",
                                          "paired", "sources", "memory", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {spec}, {rows}, {states}, or {profile}"); \
        p.set_defaults(fn=cmd_bench)
    p = sub.add_parser("deliberation"); \
        p.add_argument("action", choices=["type", "match", "tags", "metadata", "summary",
                                          "ablation", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {artifact}, {gold, model}, {score, coverage}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_deliberation)
    p = sub.add_parser("frontier"); \
        p.add_argument("action", choices=["bracket", "open", "coascent", "evidence",
                                          "memory", "round", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {regimes}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_frontier)
    p = sub.add_parser("transfer"); \
        p.add_argument("action", choices=["check", "pool", "ceiling", "design", "reversal",
                                          "pooled", "power", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {baseline}, {spec}, {phases}, {sd, effect}, or {profile}"); \
        p.set_defaults(fn=cmd_transfer)
    p = sub.add_parser("repair"); \
        p.add_argument("action", choices=["churn", "reach", "failure", "capability",
                                          "flags", "provenance", "veto", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {row}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_repair)
    p = sub.add_parser("validation"); \
        p.add_argument("action", choices=["risk", "autonomy", "controls", "domains",
                                          "evidence", "calibrate", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {row}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_validation)
    p = sub.add_parser("grounding"); \
        p.add_argument("action", choices=["skill", "equivalence", "verdict", "session",
                                          "layers", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {spec}, {record}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_grounding)
    p = sub.add_parser("folding"); \
        p.add_argument("action", choices=["levels", "contract", "fold", "trigger",
                                          "cost", "recover", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {turns}, {requests}, {usage}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_folding)
    p = sub.add_parser("invocation"); \
        p.add_argument("action", choices=["rates", "wiring", "severity", "recovery",
                                          "scoring", "terminal", "discrimination", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows, depth} or {profile}"); \
        p.set_defaults(fn=cmd_invocation)
    p = sub.add_parser("capabilities"); \
        p.add_argument("action", choices=["updating", "benefit", "activation", "adherence",
                                          "budget", "pairing", "insitu", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {row}, or {profile}"); \
        p.set_defaults(fn=cmd_capabilities)
    p = sub.add_parser("govern"); \
        p.add_argument("action", choices=["anchor", "validate", "attribute", "compare",
                                          "coverage", "posture", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rules, version}, {handoff, anchor, mode}, {halts}, {pairs}, {checks}, or {profile}"); \
        p.set_defaults(fn=cmd_govern)
    p = sub.add_parser("typed"); \
        p.add_argument("action", choices=["build", "allowed", "tick", "refines", "split",
                                          "charge", "compliance", "pressure", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: protocol spec, {parent, child}, {budget, share}, {runs}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_typed)
    p = sub.add_parser("pipeline"); \
        p.add_argument("action", choices=["final", "blame", "handoff", "rates", "origins",
                                          "pareto", "casting", "gain", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {stages, gold}, {record}, {rows}, {pairs}, or {profile}"); \
        p.set_defaults(fn=cmd_pipeline)
    p = sub.add_parser("envelope"); \
        p.add_argument("action", choices=["outcomes", "weight", "arbitration", "content",
                                          "dose", "roles", "stack", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {arms}, {backends}, {levels}, or {profile}"); \
        p.set_defaults(fn=cmd_envelope)
    p = sub.add_parser("tracefp"); \
        p.add_argument("action", choices=["trace", "profile", "attribute", "separation",
                                          "budget", "robustness", "probes", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {steps}, {traces}, {profiles}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_tracefp)
    p = sub.add_parser("modelhandoff"); \
        p.add_argument("action", choices=["gate", "signals", "calibration", "budget", "pareto",
                                          "handoff", "recovery", "saturate", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {features}, {rows}, {packet}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_modelhandoff)
    p = sub.add_parser("admission"); \
        p.add_argument("action", choices=["provider", "slot", "aimd", "circuit", "backoff",
                                          "budget", "order", "ablate", "pressure", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {profile}, {state}, {tasks}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_admission)
    p = sub.add_parser("statesched"); \
        p.add_argument("action", choices=["hrrn", "queue", "aging", "batch", "kv", "predict",
                                          "jct", "compare", "stability", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {wait, proc}, {row}, {segments}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_statesched)
    p = sub.add_parser("capacity"); \
        p.add_argument("action", choices=["classes", "classify", "priority", "debt", "burst",
                                          "resources", "admission", "reclaim", "protect",
                                          "fairshare", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {name}, {row}, {items}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_capacity)
    p = sub.add_parser("slots"); \
        p.add_argument("action", choices=["suffix", "slot", "bind", "rebind", "graph", "leak",
                                          "compatibility", "overhead", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {path, roots}, {value, kind}, {handle, table}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_slots)
    p = sub.add_parser("privmem"); \
        p.add_argument("action", choices=["levels", "classify", "sanitize", "restore", "extraction",
                                          "utility", "leakage", "threshold", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {level}, {spans, threshold}, {text, mapping}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_privmem)
    p = sub.add_parser("privaudit"); \
        p.add_argument("action", choices=["flow", "disposition", "inventory", "compare", "criteria",
                                          "auditor", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {row}, {reads}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_privaudit)
    p = sub.add_parser("updategate"); \
        p.add_argument("action", choices=["blocks", "differential", "confirm", "localize", "verify",
                                          "risk", "utility", "admit", "transfer", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {items}, {rows}, {outcomes}, {rollbacks}, {row}, {records}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_updategate)
    p = sub.add_parser("expledger"); \
        p.add_argument("action", choices=["scope", "noop", "precondition", "decide", "ledger", "metrics",
                                          "repeated", "counterfactual", "relabel", "taxonomy", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {row}, {records}, {proposals}, {pairs}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_expledger)
    p = sub.add_parser("prefetch"); \
        p.add_argument("action", choices=["window", "encode", "decode", "contract", "prefetch", "benefit",
                                          "degrade", "warmup", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {events, size}, {addresses, cap}, {ranks, last, rank_to_delta}, {packet}, {row}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_prefetch)
    p = sub.add_parser("coverage"); \
        p.add_argument("action", choices=["taxonomy", "coverage", "concentration", "jaccard",
                                          "asr", "equal-sample", "equal-cost", "labels",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {units}, {successes, totals}, {attempts, k}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_coverage)
    p = sub.add_parser("purpleloop"); \
        p.add_argument("action", choices=["primitives", "explainability", "reward", "collapse",
                                          "rewards", "requirements", "compare", "ablate",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {records, k}, {row}, {series}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_purpleloop)
    p = sub.add_parser("renderdef"); \
        p.add_argument("action", choices=["operations", "modality", "aggregate", "utility",
                                          "presentation", "candidates", "dissociation",
                                          "authorization", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {row}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_renderdef)
    p = sub.add_parser("stateev"); \
        p.add_argument("action", choices=["state", "delta", "ack", "recover", "locality",
                                          "budget", "paired", "benefit", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {entries}, {row}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_stateev)
    p = sub.add_parser("evidenceview"); \
        p.add_argument("action", choices=["outcomes", "rates", "aided", "shortlist", "evidence-type",
                                          "assertion", "instrument", "near-miss", "noise",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {row}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_evidenceview)
    p = sub.add_parser("uncert"); \
        p.add_argument("action", choices=["paired", "alignment", "subset", "flips", "correctness",
                                          "entropy", "sensitivity", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {row}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_uncert)
    p = sub.add_parser("skillcfi"); \
        p.add_argument("action", choices=["skeleton", "enforceable", "dispositions", "admit",
                                          "result", "violation", "refusal", "recovery",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {row}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_skillcfi)
    p = sub.add_parser("memcomm"); \
        p.add_argument("action", choices=["entry", "scope", "proposals", "transfer", "selection",
                                          "citation", "audit", "alignment", "gap", "activity",
                                          "audit-record", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {row}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_memcomm)
    p = sub.add_parser("sparseval"); \
        p.add_argument("action", choices=["prior", "posterior", "sensitivity", "value", "brier",
                                          "alc", "calibration", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {row}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_sparseval)
    p = sub.add_parser("budgetaudit"); \
        p.add_argument("action", choices=["belief", "value", "observe", "qvalue", "solve",
                                          "decompose", "anchors", "staged", "routing",
                                          "bound", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {state,budget,policy}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_budgetaudit)
    p = sub.add_parser("simaudit"); \
        p.add_argument("action", choices=["paired", "population", "coverage", "auroc",
                                          "retention", "levels", "simulators", "evidence",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {draws}, {scores}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_simaudit)
    p = sub.add_parser("progjudge"); \
        p.add_argument("action", choices=["answers", "consensus", "single", "rubric", "errors",
                                          "kendall", "labelgain", "breakeven", "sandbox",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {answers}, {grades}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_progjudge)
    p = sub.add_parser("reql"); \
        p.add_argument("action", choices=["issue", "triage", "consolidate", "admission",
                                          "review", "rounds", "delivery",
                                          "generalisation", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {report}, {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_reql)
    p = sub.add_parser("replan"); \
        p.add_argument("action", choices=["apply", "validate", "templates", "repair",
                                          "closeout", "exposure", "validation",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: plan+operators, plan+registry, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_replan)
    p = sub.add_parser("localcost"); \
        p.add_argument("action", choices=["expected", "energy", "capacity", "rate",
                                          "required", "computed", "notice", "compare",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {local,cloud}, or {profile}"); \
        p.set_defaults(fn=cmd_localcost)
    p = sub.add_parser("intentc"); \
        p.add_argument("action", choices=["validate", "coverage", "mcnemar", "outcomes",
                                          "bundling", "targets", "properties",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows}, {b,c}, or {profile}"); \
        p.set_defaults(fn=cmd_intentc)
    p = sub.add_parser("warrant"); \
        p.add_argument("action", choices=["wrc", "admissibility", "transport", "authorize",
                                          "provenance", "composition", "selective",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {items}, or {profile}"); \
        p.set_defaults(fn=cmd_warrant)
    p = sub.add_parser("platformeval"); \
        p.add_argument("action", choices=["score", "alpha", "tiers", "gates",
                                          "reliability", "cost", "value",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {matrix}, {platforms...}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_platformeval)
    p = sub.add_parser("contaudit"); \
        p.add_argument("action", choices=["cuts", "realism", "awareness", "score",
                                          "narrow", "mandate", "cover", "ablation",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {turns}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_contaudit)
    p = sub.add_parser("toolext"); \
        p.add_argument("action", choices=["verified", "retention", "gain", "drift",
                                          "decisions", "cost", "admit", "audit",
                                          "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_toolext)
    p = sub.add_parser("fastpath"); \
        p.add_argument("action", choices=["classify", "program", "calibrate", "gate",
                                          "cost", "smoothed", "aurc", "collapsed",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows}, {probs}, or {profile}"); \
        p.set_defaults(fn=cmd_fastpath)
    p = sub.add_parser("tariff"); \
        p.add_argument("action", choices=["charge", "lifetime", "coverage", "bounds",
                                          "quality", "fairness", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_tariff)
    p = sub.add_parser("hyperke"); \
        p.add_argument("action", choices=["ingest", "join", "edit", "route", "evidence",
                                          "oke", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_hyperke)
    p = sub.add_parser("beliefprobe"); \
        p.add_argument("action", choices=["belief", "categories", "scaling", "depth",
                                          "judge", "independence", "reality", "audit",
                                          "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {rows}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_beliefprobe)
    p = sub.add_parser("awareness"); \
        p.add_argument("action", choices=["reduce", "cost", "best", "regret", "snapshot",
                                          "choose", "ablate", "wilson", "authority",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {observations}, {rows}, {arms}, or {record}"); \
        p.set_defaults(fn=cmd_awareness)
    p = sub.add_parser("diagnostics"); \
        p.add_argument("action", choices=["taxonomy", "finding", "scope", "severity",
                                          "group", "update", "match", "coverage",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {findings}, {signal,run}, or label sets"); \
        p.set_defaults(fn=cmd_diagnostics)
    p = sub.add_parser("orchcredit"); \
        p.add_argument("action", choices=["orders", "bound", "z2", "certify", "select",
                                          "detect", "leaps", "complementarity",
                                          "controlled", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {candidates}, or {profile}"); \
        p.set_defaults(fn=cmd_orchcredit)
    p = sub.add_parser("intentgraph"); \
        p.add_argument("action", choices=["graph", "scope", "classify", "audit",
                                          "metrics", "coupling", "audit_record",
                                          "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {call,graph,state}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_intentgraph)
    p = sub.add_parser("writeguard"); \
        p.add_argument("action", choices=["classify", "grounding", "commit", "mediate",
                                          "integrity", "ablate", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {request}, {plan}, {call,ground}, or {trace}"); \
        p.set_defaults(fn=cmd_writeguard)
    p = sub.add_parser("ctxregime"); \
        p.add_argument("action", choices=["length", "charge", "savings", "compaction",
                                          "regimes", "selective", "sac", "history",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows}, or {profile}"); \
        p.set_defaults(fn=cmd_ctxregime)
    p = sub.add_parser("skillgate"); \
        p.add_argument("action", choices=["tiers", "critic", "gain", "taxonomy",
                                          "curve", "select", "irreversibility",
                                          "rollback", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows}, {candidates}, or {profile}"); \
        p.set_defaults(fn=cmd_skillgate)
    p = sub.add_parser("skillflow"); \
        p.add_argument("action", choices=["ledger", "project", "regime", "sound",
                                          "shock", "instruments", "diagnose",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {events}, {edits}, {series}, {record}, or {profile}"); \
        p.set_defaults(fn=cmd_skillflow)
    p = sub.add_parser("skilleve"); \
        p.add_argument("action", choices=["entry", "evidence", "diagnose", "candidate",
                                          "validate", "consolidate", "budget",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record} or {profile}"); \
        p.set_defaults(fn=cmd_skilleve)
    p = sub.add_parser("takeover"); \
        p.add_argument("action", choices=["atom", "update", "delivery", "rq1", "rq2",
                                          "decision", "poststate", "clarify",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {before,change}, {rows}, or {pred,gold}"); \
        p.set_defaults(fn=cmd_takeover)
    p = sub.add_parser("anytime"); \
        p.add_argument("action", choices=["certificate", "grid", "structured", "margin",
                                          "allocate", "optimism", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record} or {profile}"); \
        p.set_defaults(fn=cmd_anytime)
    p = sub.add_parser("longhorizon"); \
        p.add_argument("action", choices=["plan", "grade", "gap", "horizon", "split",
                                          "grade_quality", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record} or {profile}"); \
        p.set_defaults(fn=cmd_longhorizon)
    p = sub.add_parser("memchannel"); \
        p.add_argument("action", choices=["channels", "vulns", "classify", "taxonomy",
                                          "exposure", "coverage", "cost", "audit",
                                          "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows} or {profile}"); \
        p.set_defaults(fn=cmd_memchannel)
    p = sub.add_parser("memauthority"); \
        p.add_argument("action", choices=["item", "derive", "corroborate", "authorize",
                                          "gate", "weakening", "separation",
                                          "model_check", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {items} or {profile}"); \
        p.set_defaults(fn=cmd_memauthority)
    p = sub.add_parser("exfild"); \
        p.add_argument("action", choices=["points", "defenses", "applicability", "chain",
                                          "utility", "frontier", "persistence", "audit",
                                          "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record}, {rows} or {profile}"); \
        p.set_defaults(fn=cmd_exfild)
    p = sub.add_parser("formation"); \
        p.add_argument("action", choices=["formations", "outcome", "participation",
                                          "fairness", "interference", "mitigation",
                                          "failure", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record} or {profile}"); \
        p.set_defaults(fn=cmd_formation)
    p = sub.add_parser("teammate"); \
        p.add_argument("action", choices=["dimensions", "score", "gate", "drop",
                                          "conflict", "failure_mode", "inheritance",
                                          "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record} or {profile}"); \
        p.set_defaults(fn=cmd_teammate)
    p = sub.add_parser("museprincipals"); \
        p.add_argument("action", choices=["principals", "precedence", "access",
                                          "selection", "privacy_utility", "meeting",
                                          "conflict_effect", "audit", "advise"]); \
        p.add_argument("file", nargs="?", help="JSON: {record} or {profile}"); \
        p.set_defaults(fn=cmd_museprincipals)
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
    p = sub.add_parser("harness",
                       help="list the per-paper groups, their actions and their input")
    p.add_argument("group", nargs="?", help="one group: print its own -h")
    p.set_defaults(fn=cmd_harness)
    return ap


def main():
    ap = _build_parser()
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

