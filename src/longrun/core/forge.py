#!/usr/bin/env python3
"""Longrun CLI — command the harness from the terminal.

Usage:
  python3 forge.py chat "message" [--session ID] [--model ALIAS] [--stream]
  python3 forge.py agent "goal" [--max-steps N]
  python3 forge.py plan show [--session ID] | plan generate "goal" | plan toggle ID [--session ID]
  python3 forge.py tasks ls | tasks add "title" | tasks done ID | tasks set ID STATUS
  python3 forge.py tools ls | tools call <tool> '<json-args>' | tools running | tools cancel JOB
  python3 forge.py approvals ls | approvals show ID | approvals approve ID | approvals deny ID | approvals rm ID | approvals clear
  python3 forge.py runs ls | runs show RUN_ID | control pause|resume|abort RUN_ID
  python3 forge.py sessions ls | sessions new "title" | sessions rm ID | sessions history ID
                          | sessions graph ID | sessions reset ID
  python3 forge.py context show [--session ID] | context compact [--session ID]
                          | context preview "message" [--session ID]
  python3 forge.py checkpoints ls | checkpoints create "label" [--session ID]
                         | checkpoints show CP_ID | checkpoints rollback CP_ID
                         | checkpoints rm CP_ID | checkpoints prune
  python3 forge.py routing show | routing update '{"chat":"qwen"}'
  python3 forge.py eval tasks | eval run [--task ID] [--model ALIAS] [--max-steps N] [--no-save]
  python3 forge.py voice status | voice stt "text" | voice tts "text"
  python3 forge.py status | models | providers | self | selfcheck | sandbox | mcp | hooks
  python3 forge.py feed | events [--since N] [--limit N]
  python3 forge.py memory store <kind> <content> | search <query> [--kind K] [--semantic]
  python3 forge.py subagent spawn <goal> [--max-steps N] | collect <id> | status [id]
  python3 forge.py meta run [--n-candidates N] | status | best
  python3 forge.py blackboard post <topic> <content> [--tags T] | get [--id I] [--topic T] | search <q>
  python3 forge.py acp server <method> '[params]' | connect <name> <url> [--token T]
  python3 forge.py swarm <goal> [--n-workers N] [--max-steps N]
Environment:
  LONGRUN_URL (default http://127.0.0.1:8790)
  LONGRUN_TOKEN (bearer token, optional)
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("LONGRUN_URL", "http://127.0.0.1:8790").rstrip("/")
TOKEN = os.environ.get("LONGRUN_TOKEN")


def _q(value):
    """URL-encode a query value (JAG-246: raw spaces/'&' made urlopen raise)."""
    return urllib.parse.quote("" if value is None else str(value), safe="")


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
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


def stream_chat(path):
    for ev, payload in sse(path):
        try:
            d = json.loads(payload) if payload and payload != "{}" else {}
        except json.JSONDecodeError:
            continue
        if ev == "chat.delta":
            # JAG-243: the ANSI codes were missing the ESC byte, so `--stream`
            # printed the literal "[90m…think[0m". Use \x1b to actually dim it.
            if d.get("channel") == "think":
                sys.stdout.write("\x1b[90m…think\x1b[0m ")
            sys.stdout.write(d.get("text", ""))
            sys.stdout.flush()
        elif ev == "error":
            print("\n[error] %s" % d.get("error"), file=sys.stderr)
        elif ev == "done":
            print()


def cmd_chat(args):
    if args.stream:
        stream_chat("/api/chat/stream?message=%s%s%s" % (
            _q(args.message),
            "&session=" + _q(args.session) if args.session else "",
            "&model=" + _q(args.model) if args.model else ""))
        return
    out = req("POST", "/api/chat", {"message": args.message, "session": args.session,
                                    "model": args.model})
    if "error" in out:
        print("error:", out["error"], file=sys.stderr)
        sys.exit(1)
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
        if "error" in out:
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
    elif args.action == "policy":
        body = {"tool": args.value}
        if getattr(args, "enable", False):
            body["enabled"] = True
        if getattr(args, "disable", False):
            body["enabled"] = False
        if getattr(args, "approval", None):
            body["approval"] = args.approval
        print(json.dumps(req("POST", "/api/tools", body), indent=2, ensure_ascii=False))
    elif args.action in ("runtime", "verifier", "bestofn", "difficulty", "selfevolve",
                         "reasoning", "approvals"):
        # mirror the WebUI: POST /api/tools with the preset object under its key
        try:
            obj = json.loads(args.value) if args.value else {}
        except json.JSONDecodeError as e:
            print("bad json:", e, file=sys.stderr); sys.exit(2)
        print(json.dumps(req("POST", "/api/tools", {args.action: obj}),
                         indent=2, ensure_ascii=False))


def cmd_approvals(args):
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


def cmd_subagent(args):
    if args.action == "spawn":
        out = req("POST", "/api/subagent/spawn", {"goal": args.value, "max_steps": args.max_steps})
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
    out = req("POST", "/api/swarm/run", {"goal": args.goal, "n_workers": args.n_workers,
                                          "max_steps": args.max_steps})
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
    print(json.dumps(req("GET", "/api/knowledge/status"), indent=2, ensure_ascii=False))


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


def cmd_sessions(args):
    if args.action == "ls":
        out = req("GET", "/api/sessions")
        for s in out.get("sessions", []):
            print(" %-24s %4s msg  %s" % (s.get("id"), s.get("messages"), s.get("title") or ""))
    elif args.action == "new":
        out = req("POST", "/api/sessions", {"title": args.value})
        print(json.dumps({k: out.get(k) for k in ("id", "title", "messages")},
                         indent=2, ensure_ascii=False))
    elif args.action == "rm":
        print(json.dumps(req("DELETE", "/api/sessions/" + args.value), indent=2))
    elif args.action == "history":
        out = req("GET", "/api/history?session=" + _q(args.value))
        if "error" in out:
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        for m in out.get("messages", []):
            print("[%-9s] %s" % (m.get("role"), (m.get("content") or "").replace("\n", " ")[:200]))
        for c in out.get("tool_cards", []) or []:
            print("[tool     ] %s ok=%s backend=%s" % (c.get("tool"), c.get("ok"), c.get("backend")))
    elif args.action == "graph":
        print(json.dumps(req("GET", "/api/sessions/%s/graph" % args.value),
                         indent=2, ensure_ascii=False))
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


def cmd_context(args):
    sid = args.session
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
        qs += "&session=" + args.session
    if getattr(args, "kind", None):
        qs += "&kind=" + args.kind
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
            print(" %-4s %-18s %-14s %-26s %s" % (
                a.get("id"), a.get("name") or "", a.get("role") or "",
                a.get("model") or "default",
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


def main():
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("chat"); p.add_argument("message"); p.add_argument("--session"); \
        p.add_argument("--model"); p.add_argument("--stream", action="store_true"); p.set_defaults(fn=cmd_chat)
    p = sub.add_parser("agent"); p.add_argument("goal"); p.add_argument("--max-steps", type=int, default=6); \
        p.add_argument("--model"); p.set_defaults(fn=cmd_agent)
    p = sub.add_parser("plan"); p.add_argument("action", choices=["show", "generate", "toggle", "set"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--steps"); p.add_argument("--session"); \
        p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("tasks"); p.add_argument("action", choices=["ls", "add", "done", "set"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--status"); p.set_defaults(fn=cmd_tasks)
    p = sub.add_parser("tools"); \
        p.add_argument("action", choices=["ls", "call", "running", "cancel", "policy", "runtime", "verifier", "bestofn", "difficulty", "selfevolve", "reasoning", "approvals"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.add_argument("--enable", action="store_true"); p.add_argument("--disable", action="store_true"); \
        p.add_argument("--approval"); p.set_defaults(fn=cmd_tools)
    p = sub.add_parser("approvals"); \
        p.add_argument("action", choices=["ls", "show", "approve", "deny", "rm", "clear"]); \
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
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("models"); p.add_argument("action", nargs="?", default="ls", choices=["ls", "ensure"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_models)
    p = sub.add_parser("index"); p.add_argument("action", nargs="?", default="status", choices=["status", "build", "search"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--limit", type=int, default=8); \
        p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("knowledge"); p.add_argument("action", nargs="?", default="status", choices=["status", "notebooks", "create", "add", "search", "discover", "import"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--notebook"); p.add_argument("--limit", type=int, default=8); \
        p.set_defaults(fn=cmd_knowledge)
    sub.add_parser("feed").set_defaults(fn=cmd_feed)
    p = sub.add_parser("memory"); p.add_argument("action", choices=["store", "search", "forget", "purge"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); \
        p.add_argument("--kind"); p.add_argument("--semantic", action="store_true"); \
        p.add_argument("--limit", type=int, default=10); p.set_defaults(fn=cmd_memory)
    p = sub.add_parser("subagent"); p.add_argument("action", choices=["spawn", "collect", "status"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--max-steps", type=int, default=4); \
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
        p.add_argument("--max-steps", type=int, default=4); p.set_defaults(fn=cmd_swarm)
    p = sub.add_parser("sessions"); p.add_argument("action", choices=["ls", "new", "rm", "history", "graph", "reset", "clear", "model"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_sessions)
    p = sub.add_parser("context"); p.add_argument("action", choices=["show", "compact", "preview", "items"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--session"); p.set_defaults(fn=cmd_context)
    p = sub.add_parser("hooks"); p.set_defaults(fn=cmd_hooks)
    p = sub.add_parser("routing"); p.add_argument("action", choices=["show", "update"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_routing)
    p = sub.add_parser("checkpoints"); p.add_argument("action", choices=["ls", "create", "show", "rollback", "rm", "prune"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--session"); p.set_defaults(fn=cmd_checkpoints)
    sub.add_parser("self").set_defaults(fn=cmd_self)
    sub.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)
    p = sub.add_parser("providers"); p.add_argument("action", nargs="?", default="ls", choices=["ls", "add", "rm", "default", "rm-model"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_providers)
    p = sub.add_parser("eval"); p.add_argument("action", choices=["tasks", "run"]); \
        p.add_argument("--task"); p.add_argument("--model"); p.add_argument("--max-steps", type=int, default=6); \
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

