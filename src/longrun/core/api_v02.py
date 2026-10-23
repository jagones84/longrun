#!/usr/bin/env python3
"""Longrun v0.2 — safe execution surface: tool registry, approval gates,
HITL run control and the MCP endpoint.

This module owns the v0.2 HTTP surface (and the tool-enabled agent loop) so
that server.py only needs a tiny delegation hook:

    if api_v02.handle(self, method, path, qs, body):
        return

`server` is imported lazily inside functions (server.py imports this module at
startup, so a top-level import would be circular).

Routes owned here:
  GET  /api/tools                 registry + allowlist + sandbox backend
  POST /api/tools                 enable/disable a tool or change its policy
  POST /api/tools/call            run a tool through the approval gate
  GET  /api/approvals             approval queue (+stats)
  GET  /api/approvals/<id>        one approval
  POST /api/approvals/<id>        decide: {decision: approve|deny, by}
  GET  /api/sandbox               sandbox backend probe (evidence)
  GET  /api/feed/recent           feed backlog as JSON (MCP-friendly)
  GET  /api/agent/run             SSE agent run (tools enabled)  [GET]
  POST /api/agent/run             JSON agent run (goal, max_steps, script?)
  GET  /api/agent/runs            list agent runs + HITL status
  GET  /api/agent/runs/<id>       one run (trace)
  POST /api/agent/control         {runId, action: pause|resume|abort}
  POST /mcp                       MCP JSON-RPC 2.0 (tools/list, tools/call, …)
"""

import copy
import json
import queue
import sys
import threading
import time
import uuid

from longrun.util.dataio import as_int as _int
from longrun.tools import approvals
from longrun.interop import mcp
from longrun.tools import registry
from longrun.tools import sandbox
from longrun.tools import tools as toolmod


def _srv():
    from longrun.core import server
    return server


def _publish(kind, **data):
    try:
        return _srv().publish(kind, **data)
    except Exception:  # feed must never break the run
        return None


# ------------------------------------------------------------- run state ----

class AbortRun(Exception):
    """Raised inside a run when the operator aborts it (HITL)."""


def normalize_tool_args(tool: str, args: dict) -> dict:
    """Canonicalize known model argument wrappers before policy and dispatch."""
    return toolmod.normalize_args(tool, args)


class RunState:
    def __init__(self, rid, goal, model, max_steps, script=None):
        self.id = rid
        self.goal = goal
        self.model = model
        self.max_steps = max_steps
        self.script = script
        self.status = "running"           # running|paused|aborting|aborted|done
        # Machine-readable terminal classification (JAG-467 / Paperclip adapter).
        # `status: "done"` is NOT proof the agent finished: a max-step or
        # no-progress stop also ends "done". `termination` separates them:
        #   completed | max_steps | no_progress | aborted | error
        self.termination = None
        self.trace = []
        self.summary = None
        self.created = round(time.time(), 3)
        self.paused = False
        self.abort = False
        self.pause_notified = False
        self.resume_ev = threading.Event()
        self.resume_ev.set()

    def public(self):
        return {"id": self.id, "goal": self.goal, "model": self.model,
                "max_steps": self.max_steps, "status": self.status,
                "termination": self.termination,
                "created": self.created, "summary": self.summary,
                "steps": len(self.trace), "trace": self.trace,
                "scripted": self.script is not None}


RUNS = {}
RUNS_LOCK = threading.RLock()


def new_run(goal, model=None, max_steps=6, script=None):
    st = RunState("run_" + uuid.uuid4().hex[:8], goal, model, max_steps, script)
    with RUNS_LOCK:
        RUNS[st.id] = st
        if len(RUNS) > 200:  # keep memory bounded
            for rid in sorted(RUNS, key=lambda r: RUNS[r].created)[:len(RUNS) - 200]:
                RUNS.pop(rid, None)
    return st


def run_get(rid):
    # JAG-235: `rid` comes from the wire. A non-string (list/dict) is unhashable,
    # so `RUNS.get(rid)` raised TypeError and dropped the connection with no
    # response (live repro: POST /api/agent/control with {"run_id":[1]}).
    if not isinstance(rid, str):
        return None
    with RUNS_LOCK:
        return RUNS.get(rid)


def run_control(rid, action):
    st = run_get(rid)
    if not st or action not in ("pause", "resume", "abort"):
        return None
    terminal = st.status in ("done", "aborted", "error")
    if action == "pause" and not terminal:
        st.paused = True
        st.resume_ev.clear()
        if st.status == "running":
            st.status = "paused"
    elif action == "resume" and not terminal:
        st.paused = False
        if st.status == "paused":
            st.status = "running"
        st.resume_ev.set()
    elif action == "abort" and not terminal:
        st.abort = True
        st.status = "aborting"
        st.resume_ev.set()
    _publish("agent.control", run=rid, action=action, status=st.status, terminal=terminal)
    return st


def checkpoint(st):
    """Honour pause/abort. Called at every step and while waiting for approvals."""
    if st is None:
        return
    if st.abort:
        if st.status != "aborted":
            st.status = "aborting"
        raise AbortRun()
    if st.paused:
        if not st.pause_notified:
            st.pause_notified = True
            _publish("agent.paused", run=st.id)
        st.resume_ev.wait()
        st.pause_notified = False
        if st.abort:
            raise AbortRun()


# -------------------------------------------------------------- tool gate ---

def tool_action(st, tool, args, on_event, workspace=None):
    """Gate then execute one tool action inside a run.

    Returns (observation_text, meta) where meta carries the evidence:
    approval id/status/decided_by, sandbox backend, exit code, stdout/stderr.
    `workspace` (JAG-127) makes a file op outside the session folder require approval.
    """
    run_id = st.id if st else None
    args = normalize_tool_args(tool, args or {})
    # JAG-163: the session workspace IS the tool's working directory. Without
    # this, `shell` fell back to the per-run scratch dir (data/sandbox/<run>) and
    # the agent explored an empty folder, never the project it was asked about.
    if workspace and "workspace" not in args:
        args["workspace"] = workspace
    spec = registry.tool_spec(tool)
    if spec is None:
        obs = "unknown tool %r — available: %s" % (tool, ", ".join(registry.tool_names()))
        _publish("tool.blocked", run=run_id, tool=tool, reason="unknown tool")
        return obs, {"tool": tool, "blocked": "unknown"}

    decision, reason = registry.classify(tool, args, workspace)
    if decision in ("disabled", "denied"):
        _publish("tool.blocked", run=run_id, tool=tool, args=args, reason=reason)
        on_event("tool.blocked", run=run_id, tool=tool, reason=reason)
        return "tool %r blocked by policy: %s" % (tool, reason), {"tool": tool, "blocked": reason}

    if decision == "auto":
        rec = approvals.create(tool, args, run_id=run_id,
                               decision="auto_approved", reason=reason)
        _publish("approval.auto", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], reason=reason)
        on_event("approval.auto", run=run_id, id=rec["id"], tool=tool,
                 summary=rec["summary"], reason=reason)
    else:
        rec = approvals.create(tool, args, run_id=run_id, decision="pending", reason=reason)
        _publish("approval.request", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], args=args)
        on_event("approval.request", run=run_id, id=rec["id"], tool=tool,
                 summary=rec["summary"], args=args)
        rec = approvals.wait(rec["id"], checkpoint=(lambda: checkpoint(st)) if st else None)
        if rec["status"] != "approved":
            _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                     status=rec["status"], by=rec.get("decided_by"))
            on_event("approval.resolved", run=run_id, id=rec["id"], status=rec["status"],
                     by=rec.get("decided_by"))
            return ("action not executed: approval %s %s (by %s)"
                    % (rec["id"], rec["status"], rec.get("decided_by")),
                    {"tool": tool, "approval_id": rec["id"], "approval_status": rec["status"]})
        _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                 status="approved", by=rec.get("decided_by"))
        on_event("approval.resolved", run=run_id, id=rec["id"], status="approved",
                 by=rec.get("decided_by"))

    _publish("tool.call", run=run_id, tool=tool, args=args, approval=rec["id"])
    on_event("tool.call", run=run_id, tool=tool, args=args, approval=rec["id"])
    res = toolmod.execute(tool, args, run_id=run_id)
    # JAG-347: the operator-facing event must carry the payload too — fs.read puts
    # it in `content`, so without this fallback the tool card / feed showed an
    # empty result for every file read.
    _payload = res.get("stdout") or res.get("content") or ""
    meta = {"tool": tool, "approval_id": rec["id"], "approval_status": rec["status"],
            "approval_by": rec.get("decided_by"), "sandbox_backend": res.get("backend"),
            "sandboxed": res.get("sandboxed"), "exit_code": res.get("exit_code"),
            "stdout": _payload[:4000], "stderr": (res.get("stderr") or "")[:2000],
            "duration_ms": res.get("duration_ms"), "ok": res.get("ok")}
    _publish("tool.result", run=run_id, tool=tool, approval=rec["id"], ok=res.get("ok"),
             exit_code=res.get("exit_code"), backend=res.get("backend"),
             sandboxed=res.get("sandboxed"), duration_ms=res.get("duration_ms"),
             stdout=_payload[:2000], stderr=(res.get("stderr") or "")[:1000])
    on_event("tool.result", run=run_id, tool=tool, ok=res.get("ok"),
             exit_code=res.get("exit_code"), backend=res.get("backend"),
             sandboxed=res.get("sandboxed"), duration_ms=res.get("duration_ms"),
             stdout=_payload[:20000], stderr=(res.get("stderr") or "")[:8000])
    return toolmod.observation(res), meta


def batch_action(st, items, on_event, srv, workspace=None):
    """Run the calls of a `batch` action inside the v2 loop (JAG-533).

    `AGENT_PROMPT_V2`/`tool_context` have always advertised `batch`, and the CHAT
    loop implemented it, but this loop did not: the action fell through to
    ``apply_agent_action`` and came back as "unknown action". A subagent that
    followed the prompt therefore burned a step on a dead end and — because the
    repeat guard hashed two different batches identically — was then killed at
    step 2 with ``no_progress`` (live: SJ1.3, 2026-10-23).

    TOOL items run CONCURRENTLY under `runtime.max_parallel_tools`. Every other
    item (subagent / plan_step / note / …) runs SEQUENTIALLY afterwards, because
    those mutate harness state (plan.json, the task graph) and must not race.
    Returns ``(observation, results)`` in the model's order.
    """
    from concurrent.futures import ThreadPoolExecutor

    from longrun.agent.agent import _parallel_tool_cap

    def _is_tool(it):
        return str(it.get("action") or "") in ("", "tool") and bool(it.get("tool"))

    def _one_tool(it):
        tool = it.get("tool")
        args = dict(it.get("args") or {})
        for k in ("command", "path", "content", "url"):
            if k in it and k not in args:
                args[k] = it[k]
        obs, meta = tool_action(st, tool, args, on_event, workspace=workspace)
        return {"tool": tool, "ok": (meta or {}).get("ok") is not False,
                "observation": obs}

    tool_items = [it for it in items if _is_tool(it)]
    other_items = [it for it in items if not _is_tool(it)]
    results = []
    if tool_items:
        with ThreadPoolExecutor(max_workers=_parallel_tool_cap()) as pool:
            results.extend(list(pool.map(_one_tool, tool_items)))
    for it in other_items:
        if str(it.get("action") or "") == "batch":
            obs = ("nested `batch` is not supported — put its calls in the TOP-LEVEL "
                   "`calls` list")
            ok = False
        else:
            try:
                obs, ok = srv.apply_agent_action(it, run_id=st.id), True
            except Exception as e:  # noqa: BLE001 — one item must not kill the batch
                obs, ok = "batch item failed: %s" % str(e)[:300], False
        results.append({"tool": str(it.get("action") or it.get("tool") or "?"),
                        "ok": ok, "observation": obs})
    lines = ["batch: %d call(s) — %d tool, %d other"
             % (len(items), len(tool_items), len(other_items))]
    for n, r in enumerate(results, 1):
        lines.append("%d. %s -> %s" % (n, r.get("tool"),
                                       str(r.get("observation") or "")[:1500]))
    return "\n".join(lines)[:12000], results


def gated_call(tool, args, run_id=None, wait=True, by="api", timeout=None, workspace=None,
               obs_max=1600):
    """One-shot gated tool call used by POST /api/tools/call and the chat loop.

    `timeout` (JAG-80) caps how long a `required` tool waits for a human decision.
    The chat loop passes a short cap so a turn can never freeze for the full
    approvals.timeout_secs (300s): the request is recorded, the app shows an
    inline Approve/Deny card, and if nobody decides in time the model continues.
    `workspace` (JAG-127) escalates file ops outside the session folder to required.
    """
    spec = registry.tool_spec(tool)
    if spec is None:
        return {"status": "error", "error": "unknown tool %r" % tool}
    if not spec["enabled"]:
        _publish("tool.blocked", run=run_id, tool=tool, reason="not enabled")
        return {"status": "blocked", "reason": "tool %r is disabled (allowlist)" % tool}
    args = normalize_tool_args(tool, dict(args or {}))
    # JAG-163: run the tool INSIDE the session workspace (see tool_action above).
    if workspace and "workspace" not in args:
        args["workspace"] = workspace
    decision, reason = registry.classify(tool, args, workspace)
    if decision in ("disabled", "denied"):
        _publish("tool.blocked", run=run_id, tool=tool, args=args, reason=reason)
        return {"status": "blocked", "reason": reason}
    rec = approvals.create(tool, args, run_id=run_id,
                           decision="auto_approved" if decision == "auto" else "pending",
                           reason=reason)
    if rec["status"] == "pending":
        _publish("approval.request", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], args=args)
        if wait:
            rec = approvals.wait(rec["id"], timeout=timeout)
            if rec["status"] != "approved":
                _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                         status=rec["status"], by=rec.get("decided_by"))
                return {"status": rec["status"], "approval": rec, "reason": reason}
            _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                     status="approved", by=rec.get("decided_by"))
        else:
            return {"status": "pending", "approval": rec, "reason": reason}
    else:
        _publish("approval.auto", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], reason=reason)
    res = toolmod.execute(tool, args, run_id=run_id)
    _publish("tool.result", run=run_id, tool=tool, approval=rec["id"], ok=res.get("ok"),
             exit_code=res.get("exit_code"), backend=res.get("backend"),
             sandboxed=res.get("sandboxed"), stdout=(res.get("stdout") or "")[:2000])
    return {"status": "executed", "approval": rec, "result": res,
            "observation": toolmod.observation(res, max_chars=obs_max)}


# ------------------------------------------------------------- agent loop ---

AGENT_PROMPT_V2 = (
    "You are the agent loop of the Longrun harness. Given the goal and the "
    "current harness state, decide ONE next action. Respond with ONLY one JSON "
    'object, always with a "thought" field. Actions:\n'
    '  {"action":"todo.write","todos":[{"label":"...","deps":[]}]}\n'
    '  {"action":"tool","tool":"<name>","args":{...}}   run a registered tool\n'
    '  {"action":"batch","calls":[{...},{...}]}   run INDEPENDENT calls in '
    "parallel (each item is a full action: a tool call or a subagent)\n"
    '  {"action":"plan_step","title":"...","detail":"..."}\n'
    '  {"action":"complete_plan_step","id":"..."}\n'
    '  {"action":"add_task","title":"..."}\n'
    '  {"action":"complete_task","id":"..."}\n'
    '  {"action":"note","detail":"..."}\n'
    '  {"action":"finish","summary":"..."}\n'
    "Every action that touches the world goes through an approval gate: if the "
    "gate requires a human, the run PAUSES until the decision arrives, then the "
    "observation carries the tool output. Prefer one tool call per iteration."
)


_GATEWAY_PREFIX = "pmcp__gateway."
# The gateway's DISCOVERY + CALL interface. These three stay listed with their
# full schema; every OTHER `pmcp__gateway.*` tool (auth/provision/tasks/config/…)
# is a management helper the model reaches through them.
_GATEWAY_KEEP = ("catalog_search", "describe", "invoke")


def tool_context():
    """Render the tool DISCOVERY contract + a compact name index for the prompt.

    JAG-513: the prompt used to carry the whole registry (every subtool with its
    argument list, its approval policy and a truncated description). That is a
    large, always-stale block: the model read the SYNOPSIS and still guessed the
    arguments, and a truncated description ("fs.read — Read a text file from the
    harness filesystem") hid the line-range contract that matters. The registry is
    now DISCOVERABLE at call time — the same shape skills use — so the prompt only
    carries what the prompt alone can answer:
      * the protocol (args is one JSON object, never positional/`key=value`),
      * HOW to look a tool up (`self {action:"tools"}` / `{...,tool:"<name>"}`),
      * the ENABLED NAMES, grouped by namespace, so nothing has to be invented.

    Only ENABLED tools are listed: a disabled tool is not callable, and naming it
    here used to make the model insist on it.
    """
    groups, singles = {}, []
    gw_collapsed = 0
    disabled = 0
    for t in registry.catalog():
        if not t["enabled"]:
            disabled += 1
            continue
        nm = t["name"]
        if nm.startswith(_GATEWAY_PREFIX):
            short = nm[len(_GATEWAY_PREFIX):]
            if short not in _GATEWAY_KEEP:
                gw_collapsed += 1
                continue
        if "." in nm and "__" not in nm:
            ns, sub = nm.split(".", 1)
            groups.setdefault(ns, []).append(sub)
        else:
            singles.append(nm)
    lines = [
        "## Tool discovery — read before you call",
        "The index below is the ONLY allowlist: a tool that is not here (or not "
        "enabled) cannot be called. Never invent a name and never guess an argument.",
        '- `self {action:"tools", query:"<words>"}` → the tools matching those '
        "words, each with its one-line description.",
        '- `self {action:"tools", tool:"<name>"}` → that tool\'s FULL input '
        "schema: every property, its type, its default and which ones are "
        "REQUIRED. Read it BEFORE the first call of a tool you have not used in "
        "this session — the schema is authoritative, your memory is not.",
        "`args` is ALWAYS one JSON object — never positional, never "
        "`key=value`, never a JSON string:",
        "Put tool fields directly inside that object; never nest another "
        "`args` object.",
        '  {"action":"tool","tool":"fs.read","args":{"path":"src/foo.py",'
        '"start_line":1,"end_line":60}}',
        "One call per turn is the default. When several calls are INDEPENDENT "
        "(none needs another's output), you MAY issue them together and the "
        "harness runs them CONCURRENTLY:",
        '  {"action":"batch","calls":[{"tool":"fs.read","args":{"path":"a.py"}},'
        '{"tool":"fs.read","args":{"path":"b.py"}}]}',
        "Each item of `calls` is a FULL action — a tool call, or "
        '{"action":"subagent","goal":"..."}. At most `runtime.max_parallel_tools` '
        "tools run at once (config/tools.yaml); subagents are capped by "
        "`max_parallel` (config/subagents.yaml). Never batch an approval-gated "
        "mutation with a read that depends on it.",
        "A SUBAGENT item may declare ORDER over other subagent items of the same "
        "batch, and the whole batch becomes one Session Job (SJ) you can inspect "
        "with `self {action:\"sj\"}`:",
        '  {"action":"batch","calls":['
        '{"action":"subagent","label":"data","goal":"collect the numbers"},'
        '{"action":"subagent","label":"report","goal":"write the summary",'
        '"deps":["data"]}]}',
        "`label` names the item; `deps` lists the labels that must FINISH first — "
        "the item starts only then and automatically receives their output under "
        "`## Input from dependencies` (use `input_from:\"<label>\"` to take just "
        "one dependency's output). Never invent `deps` you do not need: items with "
        "no `deps` start together, which is faster.",
        "Enabled tools, grouped by namespace (name{s sub-tools}):",
    ]
    for ns in sorted(groups):
        lines.append("  %s{%s}" % (ns, ",".join(sorted(groups[ns]))))
    for nm in sorted(singles):
        lines.append("  " + nm)
    if gw_collapsed:
        lines.append("  (+ %d more `%s*` tools — reach them via "
                     "`%scatalog_search` -> `describe` -> `invoke`)"
                     % (gw_collapsed, _GATEWAY_PREFIX, _GATEWAY_PREFIX))
    if disabled:
        lines.append("  (%d tool(s) present in the registry are DISABLED by "
                     "policy and omitted above; enable them in Settings -> "
                     "Tools & approvals or config/tools.yaml.)" % disabled)
    return "\n".join(lines)


def _routed_agent_model(goal):
    """The role-routing answer for an agent run (the LAST resort, JAG-478).

    Kept in one function so the run loop and the HTTP route cannot resolve the
    model differently: the route calls it BEFORE the run starts, records the
    answer on the session, and hands it in as an EXPLICIT model.
    """
    srv = _srv()
    try:
        from longrun.model import routing
        from longrun.model import decision as _decision
        _hint = _decision.get().route(_decision.StepCtx(role="agent", goal=goal))
        return getattr(_hint, "model", "") or routing.pick("agent") or srv.default_model()
    except Exception:  # noqa: BLE001 — a routing hint must never break a run
        return srv.default_model()


def agent_model_for(goal, explicit=None, session_obj=None):
    """JAG-478: the ONE place a run's model is decided.

    Precedence is the same as the chat's (`resolve_ctx_model`): an explicit
    choice wins, then the SESSION's own model, then the role-routing hint. Two
    independent resolutions were the bug — a session showed
    `deepseek:deepseek-reasoner` while the run really executed on the local
    role model. A session pinned to X must RUN on X.
    """
    if explicit:
        return explicit
    pinned = str((session_obj or {}).get("model") or "").strip()
    if pinned:
        return pinned
    return _routed_agent_model(goal)


def agent_run_v2(goal, max_steps=6, model=None, on_event=None, script=None, run_id=None,
                 workspace=None, fallbacks=None):
    """Sense-think-act loop with real tools behind the approval gate + HITL."""
    srv = _srv()
    if on_event is None:
        on_event = lambda kind, **d: srv.publish(kind, **d)
    st = run_get(run_id) if run_id else new_run(goal, model, max_steps, script)
    if st is None:
        st = new_run(goal, model, max_steps, script)
    st.goal, st.max_steps, st.script = goal, max_steps, script
    # JAG-455: an EXPLICIT model is authoritative — the decision hint must never swap
    # it. The old code resolved `model or default_model()` FIRST (so the `if not
    # model` branch below was dead) and then ALWAYS overwrote it with the route
    # hint's role model (`pick("agent")` = the LOCAL weights): every /api/agent/run
    # silently ran on the local model even when the caller had pinned a cloud one.
    # JAG-478: the resolver is shared with the HTTP route, so a caller that knows
    # the session resolves it the SAME way and passes it in explicitly.
    model = model or _routed_agent_model(goal)
    st.model = model
    # JAG-448: the subagent (and any caller passing `fallbacks`) gets a real
    # failover chain of literal model refs. `model` stays PRIMARY; on a stream
    # failure the loop walks `candidates` instead of dying at the first error.
    candidates = [model]
    for f in (fallbacks or []):
        f = str(f or "").strip()
        if f and f not in candidates:
            candidates.append(f)
    # v0.3 checkpoint at run start (idempotent per run) so plan/tasks/transcript
    # survive a restart and can be rolled back after a bad run.
    try:
        from longrun.memory import checkpoints
        _CHECKPOINTS_START = checkpoints.create(
            label="agent run %s" % st.id, idempotency_key="agent-run:" + st.id,
            by="agent-loop")
        on_event("checkpoint.created", run=st.id, id=_CHECKPOINTS_START.get("id"))
    except Exception as _exc:
        _CHECKPOINTS_START = None
        on_event("checkpoint.error", run=st.id, error=str(_exc))
    probe = sandbox.probe()
    on_event("agent.start", run=st.id, goal=goal, max_steps=max_steps,
             scripted=script is not None, sandbox=probe["backend"], isolated=probe["isolated"])
    # v0.6: the FIRST action of every (non-scripted) run is a model-generated
    # write_todos call → the per-run task graph, streamed live as nodes land.
    if script is None:
        try:
            srv.start_run_graph(st.id, goal, None, model, on_event=on_event)
        except Exception as e:  # noqa: BLE001 — graph must never break the run
            _publish("graph.error", run=st.id, error=str(e))
    last_sig, repeated = None, 0
    # JAG-61: persistent turn history. The observation produced at step N MUST be
    # visible to the model at step N+1, otherwise the model re-derives everything
    # from scratch each iteration, never learns its own tool output, and loops
    # forever (the exact failure that looked like "the model cannot install the
    # app"). We carry assistant actions + observations across the whole run.
    hist = []
    rb = srv.rules_context(ws=workspace)  # JAG-114/115: standing rules for this run
    mx = srv.matrix_context(ws=workspace)  # JAG-497: …and the Matrix dynamic rules too
    from longrun.model import prompt as prompt_mod  # JAG-128A: prompt-map + capability in the agent loop too
    try:
        for i in range(max_steps):
            checkpoint(st)
            if script is not None:
                act = script[i] if i < len(script) else {"action": "finish",
                                                         "summary": "script complete",
                                                         "thought": "script exhausted"}
                thought = str(act.get("thought", ""))[:400]
                action = act.get("action")
                on_event("agent.thought", run=st.id, i=i + 1, thought=thought,
                         action=action, scripted=True)
            else:
                # JAG-163: the agent loop now preloads the same SKILLS block as
                # the chat loop (name + one-line description). Before this it saw
                # NO skills at all and could not pick the right one proactively.
                try:
                    from longrun.memory import skills as _skills_mod
                    _sk = _skills_mod.skills_context(max_chars=8000)
                except Exception:  # noqa: BLE001
                    _sk = ""
                sysp = (prompt_mod.prompt_map_text() + "\n\n" + prompt_mod.capability_text()
                        + "\n\n" + srv.SYSTEM_PROMPT + "\n\n" + AGENT_PROMPT_V2 + "\n\n"
                        + srv.RULES_POLICY + ("\n" + rb if rb else "") + "\n\n"
                        + srv.SKILLS_POLICY + ("\n" + _sk if _sk else "") + "\n\n"
                        + tool_context() + ("\n\n" + mx if mx else ""))
                if not hist:
                    hist.append({"role": "user", "content":
                                 "Goal: %s\n\nWork step by step: issue ONE action "
                                 "per message, read each Observation, then continue "
                                 "from what you already learned. Do not repeat an "
                                 "action that already succeeded. Keep going until "
                                 "the goal is fully accomplished (max %d steps)."
                                 % (goal, max_steps)})
                # JAG-276: the live task list rides in the user turn (cache-safe) and
                # is refreshed each iteration so the model sees the current list.
                msgs = ([{"role": "system", "content": sysp}] + hist
                        + [{"role": "user", "content": srv.state_block(graph_key=st.id)}])
                on_event("agent.iteration", run=st.id, i=i + 1, of=max_steps)
                # JAG-448: walk the failover chain (primary + config fallbacks) so
                # a broken cloud model does not kill the run at the first error.
                # JAG-477: one 5xx from the local router used to kill the whole run.
                # The DGX router runs with `--models-max 1 --parallel 1`, so a tool
                # that calls the model endpoint itself (a smoke test curling :8080)
                # forces a model swap and the NEXT harness call can get a 500. One
                # short retry turns that into a hiccup instead of a failed task.
                answer, think, last_err = "", "", None
                for _attempt in range(2):
                    for cand in candidates:
                        try:
                            answer, think = srv._router_stream(
                                msgs, cand, lambda ch, t: on_event("agent.think",
                                                                   channel=ch, text=t))
                            if cand != model:
                                on_event("model.fallback", run=st.id, from_model=model,
                                         to_model=cand)
                                # promote the working model so later iterations try it
                                # first instead of re-hitting the broken primary.
                                model = cand
                                st.model = cand
                                candidates.insert(0, candidates.pop(candidates.index(cand)))
                            break
                        except Exception as _e:  # noqa: BLE001
                            last_err = _e
                            on_event("model.failover", run=st.id, failed=cand,
                                     next_model=None)
                    else:
                        if _attempt == 0 and _transient_model_error(last_err):
                            on_event("model.retry", run=st.id,
                                     error=str(last_err)[:200])
                            time.sleep(2.0)
                            continue
                        raise last_err if last_err else RuntimeError("no model available")
                    break
                # JAG-534: use the SAME parser as the chat loop. `extract_json`
                # alone sees no action in the model's native DSML markup, so a
                # subagent whose model emitted it turned every iteration into a
                # no-op "note" and the run died at max_steps / on the repeat guard.
                act = srv._extract_action(answer) or {}
                if not isinstance(act, dict) or not act.get("action"):
                    act = {"thought": answer[:200], "action": "note", "detail": answer[:400]}
                thought = str(act.get("thought", ""))[:400]
                action = act.get("action")
                on_event("agent.thought", run=st.id, i=i + 1, thought=thought, action=action)

            if action == "finish":
                summary = str(act.get("summary", ""))[:600] or "done"
                st.summary, st.status, st.termination = summary, "done", "completed"
                on_event("agent.finish", run=st.id, summary=summary,
                         termination=st.termination)
                st.trace.append({"i": i + 1, "thought": thought, "action": "finish",
                                 "summary": summary})
                return _result(st, goal, model)

            # JAG-58: no-progress guard. A small model can re-emit the identical
            # action forever and never call `finish`, so the run dies at
            # max_steps having "worked" but never concluded. If the same action
            # (tool+args, or step+id+title) repeats, conclude the run instead of
            # re-executing it — deterministic termination for any model.
            # JAG-533: the signature is the WHOLE action. It used to be built from
            # `args` + command/path/url/content only, so a `batch` — whose payload
            # lives in `calls` — hashed identically every time: the SECOND batch
            # of a run, even with completely different calls, counted as a repeat
            # and killed the run at step 2 (live: SJ1.3, 2026-10-23). `thought`
            # fluctuates every turn and volatile timeouts must not defeat the guard.
            try:
                norm_args = dict(act.get("args") or {})
                for k in ("command", "path", "url", "content"):
                    if k in act and k not in norm_args:
                        norm_args[k] = act[k]
                rest = {k: v for k, v in act.items()
                        if k not in ("args", "thought", "timeout_secs", "timeout",
                                     "command", "path", "url", "content")}
                sig = json.dumps({"args": norm_args, "rest": rest},
                                 sort_keys=True, default=str)
            except (TypeError, ValueError):
                sig = str(action)
            if sig == last_sig:
                repeated += 1
            else:
                repeated, last_sig = 1, sig
            if repeated >= 2:
                summary = "no progress: %r repeated; concluding run" % action
                st.summary, st.status, st.termination = summary, "done", "no_progress"
                on_event("agent.finish", run=st.id, summary=summary,
                         termination=st.termination, no_progress=True)
                _publish("agent.no_progress", run=st.id, action=action)
                st.trace.append({"i": i + 1, "thought": thought, "action": "finish",
                                 "summary": summary})
                return _result(st, goal, model)

            items = []
            if action == "batch":
                from longrun.agent.agent import _batch_items
                items = _batch_items(act)
                if len(items) == 1:
                    # A one-item batch is just a normal call: unwrap it so it
                    # keeps the ordinary single-action semantics (and its gate).
                    act = dict(items[0], thought=thought)
                    action = act.get("action") or ("tool" if act.get("tool") else "note")

            if action == "tool":
                tool = act.get("tool")
                args = dict(act.get("args") or {})
                for k in ("command", "path", "content", "url", "args"):
                    if k in act and k not in args:
                        args[k] = act[k]
                checkpoint(st)
                entry = {"i": i + 1, "thought": thought, "action": "tool",
                         "tool": tool, "args": args}
                obs, meta = tool_action(st, tool, args, on_event, workspace=workspace)
                entry["observation"] = obs
                entry["tool_result"] = meta
            elif action == "batch":
                if items:
                    checkpoint(st)
                    obs, _results = batch_action(st, items, on_event, srv,
                                                 workspace=workspace)
                    entry = {"i": i + 1, "thought": thought, "action": "batch",
                             "calls": items, "observation": obs, "results": _results}
                else:
                    obs = ('batch needs a non-empty `calls` list of full actions, e.g. '
                           '{"action":"batch","calls":[{"tool":"fs.read",'
                           '"args":{"path":"a.py"}},{"tool":"glob.list",'
                           '"args":{"pattern":"*.py"}}]}')
                    entry = {"i": i + 1, "thought": thought, "action": "batch",
                             "observation": obs}
            else:
                obs = srv.apply_agent_action(act, run_id=st.id)
                entry = {"i": i + 1, "thought": thought, "action": action,
                         "observation": obs}

            st.trace.append(entry)
            on_event("agent.observation", run=st.id, i=i + 1, observation=obs)
            if script is None:
                # JAG-61: feed the action + its observation back so the next
                # iteration continues from evidence instead of restating the goal.
                hist.append({"role": "assistant",
                             "content": json.dumps(act, ensure_ascii=False, default=str)[:4000]})
                hist.append({"role": "user", "content":
                             "Observation (step %d/%d):\n%s"
                             % (i + 1, max_steps, (obs or "")[:4000])})
                if len(hist) > 30:
                    del hist[:-30]
        else:
            summary = "stopped at max_steps=%d; see trace" % max_steps
            st.summary, st.status, st.termination = summary, "done", "max_steps"
            on_event("agent.finish", run=st.id, summary=summary,
                     termination=st.termination)
            st.trace.append({"action": "finish", "summary": summary})
    except AbortRun:
        st.status = "aborted"
        summary = "aborted by operator at step %d" % len(st.trace)
        st.summary = summary
        st.termination = "aborted"
        _publish("agent.aborted", run=st.id, summary=summary)
        on_event("agent.aborted", run=st.id, summary=summary,
                 termination=st.termination)
        st.trace.append({"action": "abort", "summary": summary})
    except Exception as e:  # noqa: BLE001
        st.status = "error"
        st.termination = "error"
        st.summary = "run error: %s" % e
        on_event("agent.error", run=st.id, error=str(e), termination=st.termination)
    return _result(st, goal, model)


def _result(st, goal, model):
    if st.status in ("running", "paused", "aborting"):
        st.status = "done"
    if st.termination is None:
        # A run state that never entered the loop has no better evidence than
        # its status; the field must still be one of the documented values.
        st.termination = {"done": "completed", "aborted": "aborted"}.get(
            st.status, "error")
    # v0.6: run end — close every still-open graph node with evidence.
    try:
        _srv().finish_run_graph(st.id, None, goal)
    except Exception:  # noqa: BLE001
        pass
    try:  # JAG-69: deterministic Stop hooks at the end of the run
        from longrun.tools import hooks
        hooks.run("Stop", run_id=st.id, observation=st.summary)
    except Exception:  # noqa: BLE001
        pass
    # JAG-95: deterministic process-reward / verification report over the trace.
    # Pure function (no model) — never breaks a run on failure.
    prm_report = None
    try:
        from longrun.plan import prm
        from longrun.plan import taskgraph as _tg
        _g = _tg.load(st.id)
        open_n = sum(1 for n in (_g or {}).get("nodes", [])
                     if n.get("status") in ("todo", "doing", "blocked"))
        ev = prm.evaluate(st.trace, open_nodes=open_n)
        prm_report = {"score": ev["score"], "issues": [i["code"] for i in ev["issues"]],
                      "feedback": ev["feedback"]}
        if ev["feedback"]:
            _publish("prm.feedback", run=st.id, score=ev["score"],
                     issues=[i["code"] for i in ev["issues"]], feedback=ev["feedback"])
    except Exception:  # noqa: BLE001
        prm_report = None
    return {"run_id": st.id, "goal": goal, "model": model, "status": st.status,
            "termination": st.termination,
            "summary": st.summary, "trace": st.trace, "prm": prm_report}


def _goal_title(goal, limit=80):
    """A session title taken from the task's first line (never the whole goal)."""
    text = " ".join((goal or "").split())
    if not text:
        return "Paperclip task"
    return (text[:limit - 1] + "\u2026") if len(text) > limit else text


def _transient_model_error(err):
    """A model-endpoint failure worth ONE retry (5xx, timeout, reset).

    A 4xx is a contract error and must fail fast; a 5xx or a dropped connection
    on the single-slot DGX router is transient and usually clears in seconds.
    """
    text = str(err or "").lower()
    if "http error 5" in text or "timeout" in text or "timed out" in text \
            or "connection reset" in text or "connection refused" in text:
        return True
    return isinstance(err, (TimeoutError, ConnectionError))


def agent_stream_gen_v2(goal, max_steps, model, run_id, script=None, workspace=None,
                        session_obj=None):
    srv = _srv()
    q = queue.Queue()
    # JAG-476: a HEADLESS run (Paperclip, jobs) used to be INVISIBLE in the WebUI —
    # it produced a task graph and feed events but never a chat session, so the
    # operator could not watch the task just assigned. When the caller hands us a
    # session, the goal becomes its user turn and the outcome its reply.
    _outcome = {"text": ""}

    def on_event(kind, **d):
        q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
        if not kind.startswith("agent.think"):
            srv.publish(kind, **d)
        if kind == "agent.finish":
            _outcome["text"] = str(d.get("summary") or "").strip()
        elif kind == "agent.error" and not _outcome["text"]:
            _outcome["text"] = "run failed: %s" % (d.get("error") or "unknown error")

    def worker():
        try:
            agent_run_v2(goal, max_steps, model, on_event, script=script, run_id=run_id,
                         workspace=workspace)
        except Exception as e:  # noqa: BLE001
            q.put("event: error\ndata: %s\n\n" % json.dumps({"error": str(e)}))
        finally:
            if session_obj is not None:
                try:
                    srv.append_message(session_obj, "assistant",
                                       _outcome["text"] or "(run produced no summary)")
                except Exception:  # noqa: BLE001 — visibility must never fail a run
                    pass
            # JAG-479: release the running bracket ONLY after the reply is stored, so
            # a browser that reacts to `chat.done` by reloading the transcript already
            # finds the run's answer on disk.
            if _turn_tok is not None:
                srv.turn_end(session_obj["id"], _turn_tok)
            q.put(None)

    if session_obj is not None:
        try:
            srv.append_message(session_obj, "user", goal)
        except Exception:  # noqa: BLE001
            pass
    # JAG-479: a run that OWNS a session (Paperclip task, job) must carry the same
    # server-truth "running" signal a chat turn does. Only `chat_once` and the
    # in-process MCP chat bracketed themselves, so a headless AGENT run left the rail
    # showing the session idle while the loop burned GPU, and its end never rang the
    # "finished" bell. `turn_begin` also publishes `chat.run`; the matching
    # `turn_end` (in the worker's finally, on ANY outcome) publishes `chat.done` —
    # the exact event pair the chat path uses and the feed replays to every browser.
    _turn_tok = srv.turn_begin(session_obj["id"]) if session_obj is not None else None
    yield "event: run\ndata: %s\n\n" % json.dumps({"run_id": run_id,
                                                   "session": (session_obj or {}).get("id")})
    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=15)
        except queue.Empty:
            # Keepalive: a run blocked on an approval gate can stay silent for
            # up to 300s; without this the SSE channel idles and mobile
            # networks/proxies abort it ("Software caused connection abort").
            # Clients ignore SSE comment lines.
            yield ": ping\n\n"
            continue
        if item is None:
            break
        yield item
    yield "event: done\ndata: {}\n\n"


# ------------------------------------------------------------- MCP backend --

class LocalApi:
    """Harness operations for the in-process MCP endpoint (POST /mcp)."""

    def status(self):
        return _srv().status_payload()

    def chat(self, message, session=None, model=None):
        srv = _srv()
        sess = srv.get_or_create_session(session)
        mark = srv.session_mark(sess)  # JAG-51: boundary of this request
        srv.append_message(sess, "user", message)
        srv.publish("chat.user", session=sess["id"], text=message)
        # JAG-325: the in-process MCP chat runs a REAL model turn; bracket it in the
        # active-turn registry so the session shows its running signal like any other
        # turn (no phantom run). turn_end runs in the finally, on any outcome.
        tok = srv.turn_begin(sess["id"])
        # JAG-431q: clear a stale abort at TURN START (never inside chat_once — that ran
        # after the planner, wiping a Stop pressed in between).
        srv.clear_abort(sess["id"])
        try:
            reply, mdl = srv.chat_once(sess, message, model)
        except Exception as e:  # noqa: BLE001
            # JAG-51: same contract as /api/chat — persist the error turn.
            from longrun.core import diagnostics
            issue = diagnostics.report_model_failure(e, sess["id"], model, srv.publish)
            srv.ensure_reply_persisted(sess, mark, error=issue["message"], model=model)
            return {"session": sess["id"], "model": model, "error": issue["message"],
                    "diagnostic": issue, "stored_error": True}
        finally:
            srv.turn_end(sess["id"], tok)
        return {"session": sess["id"], "model": mdl, "reply": reply.get("content"),
                "reasoning": reply.get("reasoning"), "error": bool(reply.get("error"))}

    def plan(self, goal=None):
        srv = _srv()
        if goal:
            plan, answer, think, run_id = srv.generate_plan(goal)
            return {"plan": plan, "raw": answer[:800], "run_id": run_id}
        return srv.load_plan()

    def tasks(self, a):
        srv = _srv()
        a = a or {}
        action = a.get("action", "list")
        if action == "add":
            title = str(a.get("title", ""))
            if not title:
                return {"error": "title required"}
            store = srv.load_tasks()
            t = {"id": uuid.uuid4().hex[:6], "title": title[:140],
                 "status": "todo", "created": round(time.time(), 3)}
            store.setdefault("tasks", []).append(t)
            srv.save_tasks(store)
            return t
        if action == "set":
            store = srv.load_tasks()
            for t in store.get("tasks", []):
                if t["id"] == a.get("id"):
                    if a.get("status") in ("todo", "doing", "done"):
                        t["status"] = a["status"]
                        if a["status"] == "done":
                            t["done_ts"] = round(time.time(), 3)
                    if a.get("title"):
                        t["title"] = str(a["title"])[:140]
                    srv.save_tasks(store)
                    return t
            return {"error": "task not found"}
        tasks = srv.load_tasks()
        # JAG-431r4: .get() — a stored task without `status`/`title` raised KeyError
        # and dropped the connection (same bug fixed in httpapi /api/tasks).
        remaining = ["%s: %s" % (t.get("status", "?"), t.get("title", ""))
                     for t in tasks.get("tasks", []) if t.get("status") != "done"]
        return {**tasks, "remaining": remaining}

    def agent_run(self, goal, max_steps=6, model=None):
        return agent_run_v2(goal, max_steps, model)

    def feed(self, since=0, limit=40):
        # JAG-431r4: pass the limit THROUGH to events_since — loading the whole
        # durable log and slicing the tail is a memory-DoS (see events.py docstring).
        return {"events": _srv().events_since(since, limit=limit)}

    def tools(self):
        return {"tools": registry.catalog(), "sandbox": sandbox.probe(),
                "approvals": approvals.stats()}

    def approvals(self, a):
        a = a or {}
        if a.get("action") == "decide":
            rec = approvals.decide(a.get("id"), a.get("decision"), a.get("by", "mcp"))
            _publish("approval.decided", id=a.get("id"), decision=a.get("decision"),
                     by=a.get("by", "mcp"))
            return rec or {"error": "approval not found"}
        return {"approvals": approvals.list_all(a.get("status"), 100), "stats": approvals.stats()}


# ---------------------------------------------- lazy Sperimentale modules ----
# Sperimentale/v0.3 routes import optional feature modules on first use so a
# broken optional dep can never take down the core harness.

_LAZY_MODS = {"memory": ("_MEMORY", "memory.memory"),
              "mcp_client": ("_MCP_CLIENT", "interop.mcp_client"),
              "subagent": ("_SUBAGENT", "agent.subagent"),
              "meta": ("_META", "util.meta"),
              "swarm": ("_SWARM", "agent.swarm"),
              "acp": ("_ACP", "interop.acp"),
              "checkpoints": ("_CHECKPOINTS", "memory.checkpoints"),
              "context_engine": ("_CONTEXT", "model.context_engine"),
              "routing": ("_ROUTING", "model.routing"),
              "providers": ("_PROVIDERS", "model.providers"),
              "rules": ("_RULES", "memory.rules"),
              "term": ("_TERM", "tools.term")}


def _lazy(name):
    import importlib
    entry = _LAZY_MODS.get(name)
    if entry is None:
        raise ValueError("unknown lazy module %r" % name)
    attr, dotted = entry
    if getattr(sys.modules[__name__], attr, None) is None:
        setattr(sys.modules[__name__], attr, importlib.import_module("longrun." + dotted))


from longrun.memory import checkpoints  # noqa: E402  (v0.3)
from longrun.model import context_engine  # noqa: E402  (v0.3)


# --------------------------------------------------------------- HTTP glue --

def _r(handler, code, obj):
    handler._send(code, obj)
    return True


def handle(handler, method, path, qs, body):
    """Return True if this module produced the response.

    Routes: v0.2 core + Sperimentale (memory, subagent, meta, acp, blackboard, swarm).
    """

    from longrun.orchestrate import orchestration  # JAG-287: Agents & Jobs (/api/agents*, /api/jobs*)
    if orchestration.handle(handler, method, path, qs, body):
        return True

    if method == "GET":
        # v0.2 core GET routes
        # JAG-533: WHERE the user's data lives, and the state of a running move.
        if path == "/api/home":
            from longrun.core import homemove
            from longrun.util import paths as _paths
            return _r(handler, 200, {"home": _paths.home_status(),
                                     "move": homemove.status()})
        if path == "/api/tools":
            # JAG-488: an explicitly requested backend that is unavailable raises
            # from probe() (never silently run on the host) — report it in the
            # payload instead of failing the whole Settings panel with a 500.
            try:
                _probe = sandbox.probe(force=qs.get("probe") == "1")
            except RuntimeError as _e:
                _probe = {"requested": (registry.load_config().get("sandbox") or {}).get("backend"),
                          "backend": "unavailable", "isolated": False,
                          "error": str(_e), "available": {}}
            return _r(handler, 200, {"tools": registry.catalog(),
                                     "sandbox": _probe,
                                     "sandbox_config": registry.load_config().get("sandbox") or {},
                                     "policy": registry.load_config().get("approvals") or {},
                                     "runtime": registry.load_config().get("runtime") or {},
                                     "verifier": registry.load_config().get("verifier") or {},
                                     "bestofn": registry.load_config().get("bestofn") or {},
                                     "difficulty": registry.load_config().get("difficulty") or {},
                                     "selfevolve": registry.load_config().get("selfevolve") or {},
                                     "reasoning": registry.load_config().get("reasoning") or {},
                                     "approvals": approvals.stats()})
        if path == "/api/tools/running":
            return _r(handler, 200, {"running": sandbox.running()})
        if path == "/api/hooks":
            from longrun.tools import hooks
            return _r(handler, 200, {"hooks": hooks.load(reload=qs.get("reload") == "1"),
                                     "events": list(hooks.EVENTS),
                                     "config": hooks.CONFIG})
        # JAG-488: the WHOLE config/ YAML store is editable from the WebUI.
        if path == "/api/config/files":
            from longrun.core import configfiles
            return _r(handler, 200, {"ok": True, "dir": configfiles.CONFIG_DIR,
                                     "files": configfiles.list_files()})
        if path == "/api/config/file":
            from longrun.core import configfiles
            try:
                res = configfiles.read_file(qs.get("name"))
            except ValueError as e:
                return _r(handler, 400, {"ok": False, "error": str(e)})
            return _r(handler, 200 if res.get("ok") else 404, res)
        # JAG-491: structured (object) editors for the config files — every field
        # is a checkbox/number/select/row, never hand-typed YAML.
        if path == "/api/settings":
            from longrun.core import settings as _settings
            try:
                return _r(handler, 200, _settings.view())
            except Exception as e:  # noqa: BLE001 — the panel must still load
                return _r(handler, 500, {"ok": False, "error": str(e)})
        if path == "/api/sandbox":
            return _r(handler, 200, sandbox.probe(force=qs.get("force") == "1"))
        if path == "/api/approvals":
            return _r(handler, 200, {
                "approvals": approvals.list_unified(
                    qs.get("status"), _int(qs.get("limit", 100), 100)),
                "stats": approvals.stats_unified()})
        if path.startswith("/api/approvals/"):
            rec = approvals.get_any(path.rsplit("/", 1)[-1])
            return _r(handler, 200, rec) if rec else _r(handler, 404, {"error": "approval not found"})
        if path == "/api/feed/recent":
            since, limit = _int(qs.get("since", 0), 0), _int(qs.get("limit", 40), 40)
            # JAG-431r4: hand the limit to events_since instead of materializing the
            # entire log then slicing — an unbounded replay is a memory-DoS.
            return _r(handler, 200, {"events": _srv().events_since(since, limit=limit)})
        if path == "/api/agent/runs":
            # JAG-431r4: snapshot RUNS under the lock — new_run mutates/pops it, so
            # iterating RUNS.values() unguarded could raise "dictionary changed size
            # during iteration" and drop the connection with no response.
            with RUNS_LOCK:
                _snap = list(RUNS.values())
            return _r(handler, 200, {"runs": [r.public() for r in
                                              sorted(_snap, key=lambda r: r.created,
                                                     reverse=True)]})
        if path.startswith("/api/agent/runs/"):
            st = run_get(path.rsplit("/", 1)[-1])
            return _r(handler, 200, st.public()) if st else _r(handler, 404, {"error": "run not found"})
        if path == "/api/agent/run":  # SSE, tool-enabled loop
            goal = qs.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            max_steps = _int(qs.get("max_steps", 6), 6)
            st = new_run(goal, qs.get("model"), max_steps)
            ws, _sess = _session_ws(qs.get("session"))  # JAG-115: the session's folder
            return _sse(handler, agent_stream_gen_v2(goal, max_steps, qs.get("model"),
                                                     st.id, workspace=ws))

        # --- Sperimentale GET routes ---
        if path == "/api/memory":
            _lazy('memory')
            query_text = qs.get("query", "")
            kind = qs.get("kind")
            limit = _int(qs.get("limit", 20), 20)
            semantic = qs.get("semantic", "").lower() in ("1", "true", "yes")
            if query_text:
                results = _MEMORY.search(query_text, kind, limit, semantic)
                return _r(handler, 200, {"results": [{"score": s, **r} for s, r in results]})
            return _r(handler, 200, _MEMORY.stats())

        if path == "/api/mcp/clients":
            _lazy('mcp_client')
            return _r(handler, 200, _MCP_CLIENT.status())

        # --- JAG-109: skills (engine in skills.py) ---
        if path == "/api/skills":
            from longrun.memory import skills as skills_mod
            items = skills_mod.list_skills()
            return _r(handler, 200, {"skills": items, "count": len(items),
                                     "local_dir": skills_mod._local_dir()})
        if path.startswith("/api/skills/"):
            from longrun.memory import skills as skills_mod
            nm = path[len("/api/skills/"):]
            sk = skills_mod.get_skill(nm)
            return _r(handler, 200, sk) if sk else \
                _r(handler, 404, {"error": "skill not found: %s" % nm})

        if path == "/api/subagent":
            _lazy('subagent')
            sid = qs.get("id")
            st = _SUBAGENT.status(sid)
            # JAG-233: an unknown id yields None; return 404 rather than a bare
            # `null` (which used to reach _send and crash the socket).
            if sid and st is None:
                return _r(handler, 404, {"error": "subagent not found"})
            return _r(handler, 200, st)

        if path == "/api/meta":
            _lazy('meta')
            action = qs.get("action", "status")
            if action == "best":
                return _r(handler, 200, _META.propose_best())
            return _r(handler, 200, _META.status())

        if path == "/api/blackboard":
            _lazy('swarm')
            eid = qs.get("id")
            topic = qs.get("topic")
            tags = qs.get("tags")
            limit = _int(qs.get("limit", 50), 50)
            tag_list = tags.split(",") if tags else None
            if eid:
                thread = qs.get("thread", "").lower() in ("1", "true", "yes")
                if thread:
                    return _r(handler, 200, {"thread": _SWARM.thread(eid)})
                entry = _SWARM.get(entry_id=eid)
                return _r(handler, 200, entry[0] if entry else {"error": "not found"})
            entries = _SWARM.get(topic=topic, tags=tag_list, limit=limit)
            return _r(handler, 200, {"entries": entries, "stats": _SWARM.stats()})

        if path == "/api/blackboard/watch":
            _lazy('swarm')
            since = _int(qs.get("since", 0), 0)
            # blackboard watcher = loopback tail, kept open on purpose (JAG-48)
            return _sse(handler, _SWARM.watch_gen(since), keepalive=True)

        if path == "/api/checkpoints":
            # JAG-426-fix: this v0.3 route is dispatched BEFORE httpapi's handler
            # (see httpapi.do_GET -> api_v02.handle), so it is the ONLY live
            # GET /api/checkpoints. It used to ignore `session` entirely and return
            # the newest N checkpoints of EVERY session with no turn anchors — the
            # rewind marks a client needs. Now: filter by `session` when given and
            # always include the session's turn anchors (`marks`).
            _lazy('checkpoints')
            limit = _int(qs.get("limit", 500), 500)
            allc = _CHECKPOINTS.list_checkpoints(limit)
            sid = qs.get("session")
            if sid:
                allc = [c for c in allc if c.get("session_id") == sid]
                try:
                    from longrun.memory import rewind as _rew
                    marks = _rew.marks(sid)
                except Exception:  # noqa: BLE001 — marks are additive, never fatal
                    marks = []
                return _r(handler, 200, {"session": sid, "marks": marks,
                                         "checkpoints": allc})
            return _r(handler, 200, {"checkpoints": allc})
        if path.startswith("/api/checkpoints/"):
            _lazy('checkpoints')
            cp_id = path.rsplit("/", 1)[-1]
            manifest = _CHECKPOINTS.get(cp_id)
            return _r(handler, 200, manifest) if manifest else \
                _r(handler, 404, {"error": "checkpoint not found"})

        if path == "/api/routing":
            _lazy('routing')
            return _r(handler, 200, _ROUTING.status())
        if path == "/api/subagents":
            # JAG-451: the Subagents panel — model + fallbacks (routing.yaml), depth
            # (runtime), parallel cap + role briefs (config/subagents.yaml), the live
            # count, and the context model (subagents are ISOLATED).
            try:
                from longrun.agent import subagent as _sub
                from longrun.plan import keepgoing as _kg
                _lazy('routing')
                _cfg = _sub.load_cfg()
                return _r(handler, 200, {
                    "model": _ROUTING.role_model("subagent"),
                    "fallbacks": _ROUTING.model_chain("subagent")[1:],
                    "max_depth": int((_kg.cfg() or {}).get("subagent_max_depth", 2)),
                    "max_parallel": int(_cfg.get("max_parallel") or 0),
                    "roles": _cfg.get("roles") or {},
                    "running": _sub._running_count(),
                    "context": "isolated",
                    "config_path": _sub.CFG_PATH,
                })
            except Exception as e:  # noqa: BLE001
                return _r(handler, 500, {"error": str(e)})
        if path == "/api/diagnostics":
            from longrun.core import diagnostics
            try:
                host = handler.server.server_address[0]
            except Exception:  # noqa: BLE001 — diagnostics still work without listener metadata
                host = "127.0.0.1"
            try:
                report = diagnostics.collect(
                    session_id=qs.get("session"), model=qs.get("model"), host=host)
            except Exception:  # noqa: BLE001 — do not expose internals or fake an empty result
                report = {
                    "ok": False,
                    "generated_at": time.time(),
                    "summary": {"errors": 0, "warnings": 1, "info": 0, "actionable": 1},
                    "issues": [{
                        "code": "diagnostics.unavailable",
                        "severity": "warning",
                        "scope": "global",
                        "title": "Diagnostics could not complete",
                        "message": "Longrun could not complete the settings report. Review Settings → Config files.",
                        "source": "Diagnostics",
                        "action": "config",
                    }],
                }
            return _r(handler, 200, report)
        # JAG-114: global/project rules + workspace selection
        if path == "/api/rules":
            return _r(handler, 200, rules_status(qs))
        if path == "/api/workspace":
            return _r(handler, 200, workspace_get(qs))
        if path == "/api/fs/dirs":  # JAG-121: folder picker for a new session
            return _r(handler, 200, fs_dirs(qs))
        if path == "/api/fs/list":  # JAG-124: workspace file tree
            return _r(handler, 200, fs_list(qs))
        if path == "/api/fs/find":  # JAG-501: keyboard search for folders/files
            return _r(handler, 200, fs_find(qs))
        if path == "/api/fs/read":  # JAG-124: read a text file into the editor
            return _r(handler, 200, fs_read(qs))
        if path == "/api/fs/raw":  # JAG-150: raw bytes for inline image/pdf preview
            return _fs_raw(handler, qs)
        if path == "/api/term/poll":  # JAG-281: real terminal — new output since cursor
            return _r(handler, 200, term_poll(qs))
        if path == "/api/edits":  # JAG-127: change summary for the run/session
            return _r(handler, 200, edits_summary(qs))
        if path == "/api/edits/diff":  # JAG-127: side-by-side rows for one file
            return _r(handler, 200, edits_diff(qs))
        if path == "/api/costs":  # JAG-355: per-session cost ledger + totals
            from longrun.model import costs
            return _r(handler, 200, costs.summary(qs.get("session"),
                                                  _int(qs.get("tail", 60), 60)))
        # JAG-400: CODEBASE index (per workspace) + KNOWLEDGE base (global notebooks)
        if path == "/api/codebase/status":
            return _r(handler, 200, codebase_status(qs))
        if path == "/api/codebase/files":
            return _r(handler, 200, codebase_files(qs))
        if path == "/api/codebase/search":
            return _r(handler, 200, codebase_search(qs))
        if path == "/api/knowledge/status":
            return _r(handler, 200, knowledge_status())
        if path == "/api/knowledge/notebooks":
            return _r(handler, 200, knowledge_notebooks())
        if path == "/api/knowledge/sources":
            return _r(handler, 200, knowledge_sources(qs))
        if path == "/api/knowledge/files":
            return _r(handler, 200, knowledge_files(qs))
        if path == "/api/knowledge/search":
            return _r(handler, 200, knowledge_search(qs))
        # JAG-403b: inspect the active research LLM + catalogue (GET)
        if path == "/api/research/model":
            from longrun.research import researchcfg as _rc
            return _r(handler, 200, {"active": _rc.active_model(),
                                     "models": _rc.all_models(),
                                     "depths": ["shallow", "medium", "deep"]})
        # shared index config + embedding picker (used by BOTH stores)
        if path == "/api/index/config":
            return _r(handler, 200, index_config_get())
        if path == "/api/index/embed-models":
            from longrun.model import embed as _embed
            return _r(handler, 200, {"suggested": _embed.SUGGESTED, "current": _embed.model_ref()})
        if path == "/api/index/embed-test":
            from longrun.model import embed as _embed
            return _r(handler, 200, _embed.probe(qs.get("model")))
        # JAG-403: embedding model catalogue + cost log
        if path == "/api/embedding/models":
            from longrun.memory import embedcfg as _ec
            return _r(handler, 200, {"models": _ec.all_models(),
                                     "active": _ec.active_model()})
        if path == "/api/embedding/active":
            from longrun.memory import embedcfg as _ec
            return _r(handler, 200, {"active": _ec.active_model()})
        if path == "/api/embedding/costs":
            from longrun.memory import costlog as _cl
            return _r(handler, 200, _cl.aggregate(qs.get("scope"), qs.get("scope_id")))
        if path == "/api/embedding/costs.csv":
            from longrun.memory import costlog as _cl
            handler.send_response(200)
            handler.send_header("Content-Type", "text/csv; charset=utf-8")
            handler.send_header("Content-Disposition",
                                "attachment; filename=embedding-costs.csv")
            handler.end_headers()
            handler.wfile.write(_cl.export_csv().encode("utf-8"))
            return True

        return False

    if method == "POST":
        # v0.2 core POST routes
        if path == "/api/fs/write":  # JAG-124: save the editor buffer to disk
            return _r(handler, 200, fs_write(body))
        if path == "/api/edits/undo":  # JAG-127: restore files to their pre-image (REJECT)
            return _r(handler, 200, edits_undo(body))
        if path == "/api/edits/reject":  # JAG-275: explicit reject alias
            return _r(handler, 200, edits_undo(body))
        if path == "/api/edits/approve":  # JAG-275: ACCEPT changes, drop the pending diff
            return _r(handler, 200, edits_approve(body))
        if path == "/api/costs/refresh":  # JAG-355/JAG-527: cloud cache + official provider table
            from longrun.model import costs
            return _r(handler, 200, costs.refresh_prices())
        if path == "/api/costs/reset":  # JAG-355: clear this session's ledger
            from longrun.model import costs
            return _r(handler, 200, costs.reset((body or {}).get("session")))
        # JAG-400: CODEBASE index (per workspace) + KNOWLEDGE base (global notebooks)
        if path == "/api/codebase/build":
            from longrun.memory import codeindex as _ci
            b = body or {}
            sid = b.get("session")
            ws, _ = _session_ws(sid)
            started = time.monotonic()
            _publish("index.progress", phase="start", session=sid, workspace=ws)

            def _index_progress(details: dict[str, object]) -> None:
                _publish("index.progress", session=sid, workspace=ws, **details)

            try:
                res = _ci.build(ws, force=bool(b.get("force")), progress=_index_progress)
            except Exception as exc:  # noqa: BLE001 — report failures to UI and durable feed
                message = str(exc).replace("\n", " ").strip()
                try:
                    import re as _re
                    message = _re.sub(
                        r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/-]+",
                        r"\1[redacted]", message)
                    message = _re.sub(
                        r"(?i)(api[_-]?key|authorization|token|secret)(\s*[:=]\s*)"
                        r"[^,\s;]+", r"\1\2[redacted]", message)
                except Exception:  # noqa: BLE001 — redaction failure must not hide the build error
                    message = type(exc).__name__
                error = "%s: %s" % (type(exc).__name__, message[:400])
                _publish("index.error", session=sid, workspace=ws, error=error)
                return _r(handler, 500, {"ok": False, "error": error})
            _publish("index.done", session=sid, workspace=ws,
                     files=res.get("files"), chunks=res.get("chunks"),
                     embedded=res.get("embedded"), embed_error=res.get("embed_error"),
                     duration_ms=int((time.monotonic() - started) * 1000))
            return _r(handler, 200, res)
        if path == "/api/codebase/search":
            return _r(handler, 200, codebase_search(body or {}))
        if path == "/api/codebase/clear":
            from longrun.memory import codeindex as _ci
            ws, _ = _session_ws((body or {}).get("session"))
            return _r(handler, 200, _ci.clear(ws))
        if path == "/api/knowledge/notebooks":
            return _r(handler, 200, knowledge_notebook_action(body or {}))
        if path == "/api/knowledge/sources":
            return _r(handler, 200, knowledge_source_action(body or {}))
        if path == "/api/knowledge/search":
            return _r(handler, 200, knowledge_search(body or {}))
        if path == "/api/knowledge/discover":
            from longrun.memory import knowledge as _kb
            b = body or {}
            return _r(handler, 200, _kb.discover(b.get("q") or b.get("query"), b.get("n", 5)))
        if path == "/api/knowledge/import":
            from longrun.memory import knowledge as _kb
            b = body or {}
            return _r(handler, 200, _kb.import_candidates(b.get("notebook"), b.get("urls") or b.get("refs")))
        if path == "/api/knowledge/clear":
            from longrun.memory import knowledge as _kb
            return _r(handler, 200, _kb.clear())
        # JAG-403k: back-fill vectors for chunks indexed with no embedding model.
        if path == "/api/knowledge/reembed":
            from longrun.memory import knowledge as _kb
            return _r(handler, 200, _kb.reembed())
        # JAG-403b: research agent — discover + iterative summarisation + import.
        if path == "/api/knowledge/research":
            from longrun.research import executor as _rs
            b = body or {}
            return _r(handler, 200, _rs.run(
                query=b.get("q") or b.get("query") or "",
                notebook=b.get("notebook") or "default",
                depth=b.get("depth") or "shallow",
                n=_int(b.get("n"), 5),
                max_rounds=_int(b.get("max_rounds"), 4),
            ))
        # JAG-431r5: auto-route a ref to the right notebook (or create one).
        # Used by the WebUI's "add to knowledge" flow so the agent doesn't have
        # to pick a notebook by hand. Body: {ref, text?, title?, session?}.
        if path == "/api/knowledge/auto-route":
            from longrun.memory import knowledge as _kb
            b = body or {}
            ref = (b.get("ref") or "").strip()
            text = b.get("text")
            session = b.get("session") or None
            if not ref and not text:
                return _r(handler, 400, {"ok": False, "error": "ref or text required"})
            if text:
                res = _kb.add_source_text("auto", ref or "inline://note", text,
                                          title=b.get("title"), session_id=session)
            else:
                res = _kb.add_source("auto", ref, session_id=session)
            _publish("knowledge.auto_route", ok=bool(res.get("ok")),
                     notebook=res.get("notebook"), notebook_auto=res.get("notebook_auto"),
                     recommend_visual=res.get("recommend_visual"))
            return _r(handler, 200 if res.get("ok") else 400, res)
        # JAG-403b: pick / inspect the active research LLM.
        if path == "/api/research/model":
            from longrun.research import researchcfg as _rc
            b = body or {}
            if b.get("model"):
                return _r(handler, 200, _rc.set_active(str(b.get("model") or "")))
            return _r(handler, 200, {"active": _rc.active_model(),
                                     "models": _rc.all_models()})
        if path == "/api/index/config":
            from longrun.memory import indexcfg as _cfg
            return _r(handler, 200, _cfg.save_config(body or {}))
        # JAG-403: switch the active embedding model
        if path == "/api/embedding/active":
            from longrun.memory import embedcfg as _ec
            b = body or {}
            return _r(handler, 200, _ec.set_active(str(b.get("model") or "")))
        # JAG-403: add/remove a PERSONAL embedding model (persisted in the overlay)
        if path == "/api/embedding/models":
            from longrun.memory import embedcfg as _ec
            b = body or {}
            if b.get("remove"):
                return _r(handler, 200, _ec.remove_model(b.get("remove")))
            if b.get("add"):
                return _r(handler, 200, _ec.add_model(b.get("add")))
            return _r(handler, 400, {"error": "add or remove required"})
        if path == "/api/term/exec":  # JAG-281: real terminal — send a command line
            return _r(handler, 200, term_exec(body))
        if path == "/api/term/reset":  # JAG-281: kill the session's shell
            return _r(handler, 200, term_reset(body))
        if path == "/api/config/file":
            # JAG-488: validate + atomically write any config/*.yaml, then reload.
            from longrun.core import configfiles
            from longrun.tools import matrix_guard
            try:
                with matrix_guard.NUCLEUS_EXEC_LOCK:
                    res = configfiles.write_file(body.get("name"), body.get("text"))
            except ValueError as e:
                return _r(handler, 400, {"ok": False, "error": str(e)})
            _publish("config.saved", name=body.get("name"), ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/settings":
            # JAG-491: apply ONE structured section (validated paths + types).
            from longrun.core import settings as _settings
            from longrun.tools import matrix_guard
            try:
                with matrix_guard.NUCLEUS_EXEC_LOCK:
                    res = _settings.update(body)
            except ValueError as e:
                return _r(handler, 400, {"ok": False, "error": str(e)})
            if res.get("ok"):
                _publish("config.saved", name=body.get("file"), structured=True)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/tools":
            return _r(handler, 200, update_policy(body))
        if path == "/api/tools/call":
            tool = body.get("tool")
            if not tool:
                return _r(handler, 400, {"error": "tool required"})
            # JAG-127: resolve the session workspace so a file op outside it is gated.
            _lazy('rules')
            _sid = body.get("session") or body.get("run_id")
            _ws = _RULES.resolve_workspace(_srv().load_session(_sid) if _sid else None)
            # Journal file edits under the session id (chat does the same), so the
            # UI's diff/undo works for tool calls made from the API too.
            return _r(handler, 200, gated_call(tool, body.get("args") or {},
                                               body.get("run_id") or body.get("session"),
                                               body.get("wait", True),
                                               body.get("by", "api"), workspace=_ws))
        if path == "/api/tools/cancel":
            job = body.get("job") or body.get("run_id")
            if not job:
                return _r(handler, 400, {"error": "job or run_id required"})
            res = sandbox.cancel(job)
            _publish("tool.cancel", job=job, cancelled=res.get("cancelled"))
            return _r(handler, 200, res)
        if path.startswith("/api/approvals/"):
            aid = path.rsplit("/", 1)[-1]
            res = approvals.decide_any(aid, body.get("decision"),
                                       body.get("by", "webui"))
            if not res.get("ok"):
                code = 404 if "not found" in str(res.get("error") or "") else 400
                return _r(handler, code, res)
            rec = res["approval"]
            _publish("approval.decided", id=rec["id"], decision=body.get("decision"),
                     by=rec.get("decided_by"), status=rec["status"])
            return _r(handler, 200, rec)
        if path == "/api/agent/control":
            rid, action = body.get("runId") or body.get("run_id"), body.get("action")
            st = run_control(rid, action)
            if not st:
                return _r(handler, 404, {"error": "run not found or bad action"})
            return _r(handler, 200, st.public())
        if path in ("/mcp", "/api/mcp"):
            return _r(handler, 200, _mcp_message(body))

        # --- JAG-108: user-managed external MCP clients (engine lives in mcp_client) ---
        if path == "/api/mcp/clients":
            _lazy('mcp_client')
            res = _MCP_CLIENT.upsert_client(body.get("name"), body)
            _publish("mcp.clients", action="upsert", name=body.get("name"),
                     ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/mcp/clients/remove":
            _lazy('mcp_client')
            res = _MCP_CLIENT.remove_client(body.get("name"))
            _publish("mcp.clients", action="remove", name=body.get("name"),
                     ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/mcp/clients/test":
            _lazy('mcp_client')
            return _r(handler, 200, _MCP_CLIENT.test_client(body))
        if path == "/api/mcp/reload":
            _lazy('mcp_client')
            return _r(handler, 200, _MCP_CLIENT.reload())
        if path == "/api/mcp/local-file":
            # JAG-158: ensure the hand-editable local mcp.json exists, return its path.
            _lazy('mcp_client')
            return _r(handler, 200, {"ok": True, "path": _MCP_CLIENT.ensure_local_file()})
        if path == "/api/agent/run":
            goal = body.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            script = body.get("script")
            if script is not None and not isinstance(script, list):
                return _r(handler, 400, {"error": "script must be a list of actions"})
            result = agent_run_v2(goal, _int(body.get("max_steps", 6), 6), body.get("model"),
                                  script=script)
            return _r(handler, 200, result)

        if path == "/api/agent/run/stream":
            # JAG-467 (Paperclip adapter): the SAME run, but the goal arrives in
            # the request BODY and the answer is SSE. `GET /api/agent/run` puts
            # the goal in the query string, which a task goal cannot use (URL
            # length, escaping). Event vocabulary and framing are unchanged.
            goal = body.get("goal")
            if not isinstance(goal, str) or not goal.strip():
                return _r(handler, 400, {"error": "goal required"})
            if "max_steps" in body:
                ms = body.get("max_steps")
                if isinstance(ms, bool) or not isinstance(ms, int) or ms < 1:
                    return _r(handler, 400,
                              {"error": "max_steps must be a positive integer"})
            else:
                ms = 6
            model = body.get("model")
            if model is not None and not isinstance(model, str):
                return _r(handler, 400, {"error": "model must be a string"})
            session = body.get("session")
            if session is not None and not isinstance(session, str):
                return _r(handler, 400, {"error": "session must be a string"})
            st = new_run(goal, model, ms)
            ws, sess = _session_ws(session)
            # JAG-476: one Paperclip task = one VISIBLE session. Only when the
            # caller supplied no session do we create one (and transcript it), so a
            # configured session keeps its "workspace context only" meaning.
            visible = sess if session is not None else None
            if session is None:
                visible = _srv().get_or_create_session(None, _goal_title(goal), ws)
                _srv().publish("session.created", session=visible["id"],
                               title=visible.get("title"))
            # JAG-478: resolve the model ONCE, here, then hand it to the run as an
            # EXPLICIT ref and RECORD it on the session. Before this, the route
            # forwarded the raw body model (None for Paperclip) and `agent_run_v2`
            # resolved the ROLE hint (local weights) while the composer showed the
            # session's own model — a session could display `deepseek-reasoner`
            # while `qwen…` really ran. A run and its session now share ONE model.
            resolved = agent_model_for(goal, model, visible)
            if visible is not None and resolved:
                _srv()._set_session_model(visible["id"], resolved)
                visible = _srv().load_session(visible["id"]) or visible
            return _sse(handler, agent_stream_gen_v2(goal, ms, resolved, st.id,
                                                     workspace=ws, session_obj=visible))

        # --- Sperimentale POST routes ---
        if path == "/api/memory":
            _lazy('memory')
            action = str(body.get("action") or "store").strip().lower()
            if action == "forget":
                # JAG-317: TRUE delete (physical compaction), unlike `invalidate`.
                res = _MEMORY.forget(body.get("target") or body.get("id"))
                _publish("memory.forget", ok=bool(res.get("ok")),
                         removed=res.get("removed"))
                return _r(handler, 200 if res.get("ok") else 400, res)
            if action == "purge":
                res = _MEMORY.purge_invalidated()
                _publish("memory.purge", removed=res.get("removed"))
                return _r(handler, 200, res)
            if action == "invalidate":
                _tgt = (body.get("target") or body.get("id") or "").strip()
                # JAG-431r4b: an invalidate with no target used to silently
                # succeed with {"ok": True} — every tool write was a no-op
                # and the operator got no signal. Require a target.
                if not _tgt:
                    return _r(handler, 400, {"ok": False,
                                             "error": "target (or id) required"})
                _MEMORY.invalidate(_tgt,
                                   reason=str(body.get("reason") or ""))
                return _r(handler, 200, {"ok": True, "target": _tgt})
            kind = body.get("kind", "memory.store")
            content = body.get("content", "")
            meta = {k: v for k, v in body.items()
                    if k not in ("kind", "content", "action")}
            # JAG-447: a memory posted straight to the API (WebUI form or a human
            # curl) is USER-authored unless told otherwise — never mislabelled as
            # agent-generated. Provenance is what the segregation report counts.
            meta.setdefault("origin", "user")
            meta.setdefault("source", "user")
            rec = _MEMORY.store(kind, content, **meta)
            return _r(handler, 200, rec)

        if path == "/api/subagent/spawn":
            _lazy('subagent')
            goal = body.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            max_steps = _int(body.get("max_steps", 4), 4)
            result = _SUBAGENT.spawn(goal, parent_run_id=body.get("run_id"),
                                     max_steps=max_steps, model=body.get("model"))
            return _r(handler, 200, result)

        if path == "/api/subagent/collect":
            _lazy('subagent')
            sid = body.get("id") or body.get("subagent_id")
            if not sid:
                return _r(handler, 400, {"error": "subagent_id required"})
            timeout = body.get("timeout", 120)
            result = _SUBAGENT.collect(sid, timeout=timeout)
            return _r(handler, 200, result)

        if path == "/api/meta":
            _lazy('meta')
            action = body.get("action", "run")
            if action == "run":
                n_candidates = _int(body.get("n_candidates", 8), 8)
                candidates = _META.sample_candidates(n=n_candidates)
                report = _META.meta_run(candidates, eval_task_id=body.get("eval_task_id"))
                return _r(handler, 200, report)
            return _r(handler, 200, _META.status())

        if path == "/api/acp":
            _lazy('acp')
            resp = _ACP.handle_http(body)
            return _r(handler, 200, resp if resp else {})

        if path == "/api/acp/connect":
            _lazy('acp')
            name = body.get("name", "")
            url = body.get("url", "")
            if not name or not url:
                return _r(handler, 400, {"error": "name and url required"})
            ok = _ACP.get_manager().connect(name, url, body.get("token"))
            return _r(handler, 200, {"connected": ok, "name": name, "url": url})

        if path == "/api/blackboard":
            _lazy('swarm')
            topic = body.get("topic", "general")
            content = body.get("content", "")
            if not content:
                return _r(handler, 400, {"error": "content required"})
            entry = _SWARM.post(topic, content,
                               tags=body.get("tags"),
                               parent=body.get("parent"),
                               author=body.get("author", "api"),
                               run_id=body.get("run_id"))
            return _r(handler, 200, entry)

        if path == "/api/swarm/run":
            _lazy('swarm')
            goal = body.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            n_workers = _int(body.get("n_workers", 3), 3)
            max_steps = _int(body.get("max_steps", 4), 4)
            coord = _SWARM.Coordinator()
            report = coord.run_swarm(goal, n_workers, max_steps, body.get("model"))
            return _r(handler, 200, report)

        # --- v0.3 POST routes: checkpoints / context / routing ---
        if path == "/api/checkpoints":
            _lazy('checkpoints')
            manifest = _CHECKPOINTS.create(
                label=body.get("label"), session_id=body.get("session"),
                idempotency_key=body.get("idempotency_key"),
                by=body.get("by", "api"))
            return _r(handler, 200 if "error" not in manifest else 400, manifest)
        if path.startswith("/api/checkpoints/") and path.endswith("/rollback"):
            _lazy('checkpoints')
            cp_id = path[len("/api/checkpoints/"):-len("/rollback")]
            res = _CHECKPOINTS.rollback(cp_id, by=body.get("by", "api"))
            return _r(handler, 200 if res.get("ok") else 404, res)
        if path == "/api/context/preview":
            _lazy('context_engine')
            res = _CONTEXT.preview(body.get("session"), body.get("message"),
                                   _int(body.get("budget_tokens",
                                                 _CONTEXT.DEFAULT_BUDGET),
                                        _CONTEXT.DEFAULT_BUDGET))
            return _r(handler, 200 if "error" not in res else 404, res)
        # --- JAG-112: user-editable providers / models -------------------------
        if path == "/api/providers":
            res = provider_upsert(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/models":
            res = provider_add_model(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/default":
            res = provider_set_default(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/reload":
            return _r(handler, 200, provider_reload())
        if path == "/api/keys":
            # JAG-161: set/clear an env var and persist it to the gitignored .env.
            res = _srv().set_key(body.get("name"), body.get("value"))
            if res.get("ok") and str(body.get("name") or "").strip() == "LONGRUN_TOKEN":
                # Keep the live HTTP gate aligned with the persisted key. The
                # browser can rotate its server token without a restart.
                from longrun.core import httpapi as _httpapi
                _httpapi.sync_runtime_token(body.get("value"))
            if res.get("ok"):
                _publish("settings.changed", area="keys")
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/keys/reveal":
            # JAG-163: on-demand single-value reveal for the eye / copy buttons.
            res = _srv().reveal_key(body.get("name"))
            return _r(handler, 200 if not res.get("error") else 400, res)
        if path == "/api/routing":
            _lazy('routing')
            return _r(handler, 200, _ROUTING.update(body))
        if path == "/api/subagents":
            # JAG-451: update the parallel cap + role briefs (config/subagents.yaml)
            # and, when given, the subagent MODEL / fallbacks (routing.yaml — ONE
            # source of truth, so the Models picker and this panel cannot drift).
            try:
                from longrun.agent import subagent as _sub
                cfg = dict(_sub.load_cfg())
                if "max_parallel" in body:
                    try:
                        cfg["max_parallel"] = max(0, int(body["max_parallel"]))
                    except (TypeError, ValueError):
                        return _r(handler, 400, {"error": "max_parallel must be an integer"})
                if isinstance(body.get("roles"), dict):
                    cfg["roles"] = {str(k): str(v) for k, v in body["roles"].items()}
                if "model" in body or "fallbacks" in body:
                    upd = {}
                    if "model" in body:
                        upd["model"] = str(body.get("model") or "")
                    if "fallbacks" in body:
                        upd["fallbacks"] = [str(x) for x in (body.get("fallbacks") or [])]
                    _lazy('routing')
                    _ROUTING.update({"roles": {"subagent": upd}})
                _sub.save_cfg(cfg)
                return _r(handler, 200, {"ok": True})
            except Exception as e:  # noqa: BLE001
                return _r(handler, 500, {"error": str(e)})
        # --- JAG-114: global/project rules + workspace selection --------------
        if path == "/api/rules":
            res = rules_save(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        # JAG-533: change the data home; the move runs in the BACKGROUND (its
        # progress is polled at GET /api/home and pushed as `home.move`).
        if path == "/api/home/move":
            from longrun.core import homemove
            res = homemove.start(body.get("path") or body.get("home"),
                                 remove_source=body.get("remove_source", True),
                                 move_matrix=body.get("move_matrix", True))
            return _r(handler, 202 if res.get("ok") else 400, res)
        if path == "/api/home/restart":
            from longrun.core import homemove
            res = homemove.restart_supervised()
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/workspace":
            res = workspace_set(body)
            return _r(handler, 200 if res.get("ok") else 400, res)

        return False

    if method == "DELETE":
        # JAG-108: delete a user-managed external MCP client by name.
        if path == "/api/mcp/clients":
            _lazy('mcp_client')
            res = _MCP_CLIENT.remove_client(qs.get("name"))
            _publish("mcp.clients", action="remove", name=qs.get("name"),
                     ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)

        # JAG-109: remove a user-installed (local) skill.
        if path.startswith("/api/skills/"):
            from longrun.memory import skills as skills_mod
            nm = path[len("/api/skills/"):]
            res = skills_mod.remove(nm)
            _publish("skills.remove", name=nm, ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)

        # JAG-112: remove a provider / a model.
        if path == "/api/providers":
            res = provider_remove(qs.get("id"))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/models":
            res = provider_remove_model(qs.get("provider"), qs.get("model"))
            return _r(handler, 200 if res.get("ok") else 400, res)

        # JAG-317: a TRUE delete for a stored memory (?target=<mid>), not a tombstone.
        if path == "/api/memory":
            _lazy('memory')
            res = _MEMORY.forget(qs.get("target") or qs.get("id"))
            _publish("memory.forget", ok=bool(res.get("ok")), removed=res.get("removed"))
            return _r(handler, 200 if res.get("ok") else 400, res)

        # JAG-318: true deletes for checkpoints and the approval queue.
        if path.startswith("/api/checkpoints/") and path.strip("/") != "api/checkpoints":
            _lazy('checkpoints')
            cp_id = path[len("/api/checkpoints/"):].strip("/")
            res = _CHECKPOINTS.delete(cp_id)
            return _r(handler, 200 if res.get("ok") else 404, res)
        if path == "/api/checkpoints":
            _lazy('checkpoints')
            return _r(handler, 200, _CHECKPOINTS.prune(_int(qs.get("keep", 100), 100)))
        if path.startswith("/api/approvals/"):
            aid = path[len("/api/approvals/"):].strip("/")
            res = approvals.delete(aid)
            return _r(handler, 200 if res.get("ok") else 404, res)
        if path == "/api/approvals":
            keep_pending = str(qs.get("keep_pending", "1")).lower() not in ("0", "false", "no")
            return _r(handler, 200, approvals.clear(qs.get("status"),
                                                    keep_pending=keep_pending))
        return False
    return False


def _sse(handler, gen, keepalive=False):
    return _srv().sse_response(handler, gen, keepalive=keepalive) or True


def _mcp_message(body):
    """Handle one (or a batch of) MCP JSON-RPC message(s)."""
    if isinstance(body, list):
        out = [mcp.handle(m, LocalApi()) for m in body]
        return [r for r in out if r is not None]
    resp = mcp.handle(body, LocalApi())
    return resp if resp is not None else {"jsonrpc": "2.0", "id": None, "result": {}}


def _reload_policy(cfg=None):
    import os
    if cfg is None:
        registry.load_config(reload=True)
    return registry.catalog()


def update_policy(body):
    """POST /api/tools — flip enabled / approval / auto_approve for a tool."""
    # JAG-251: a non-numeric runtime/verifier/bestofn/difficulty/selfevolve value
    # (e.g. {"runtime":{"keepgoing_max":"abc"}}) used to raise out of the handler
    # and DROP the connection. Answer cleanly instead.
    try:
        return _update_policy(body)
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": "invalid settings value: %s" % e}


def _apply_tool_fields(entry, body):
    """The per-tool policy fields, applied to ONE config entry.

    Shared by the single-tool path and the GROUP path (JAG-498) so the two can
    never drift. Returns an error string, or None on success.
    """
    if "enabled" in body:
        entry["enabled"] = bool(body["enabled"])
    if "approval" in body:
        ap = str(body["approval"] or "").strip().lower()
        if ap not in ("auto", "required", "denied"):
            return "approval must be auto|required|denied"
        entry["approval"] = ap
    # JAG-491: the per-tool ADVANCED fields (the same lists the shipped YAML
    # documents) are editable as objects too. Each is a list of strings.
    for key in ("auto_approve", "roots", "deny", "allow_hosts"):
        if key in body:
            vals = body[key]
            if not isinstance(vals, list):
                return "%s must be a list" % key
            entry[key] = [str(x)[:500] for x in vals if str(x).strip()]
    return None


def _update_policy(body):
    # Work on a candidate: validation may fail after earlier fields were changed,
    # and load_config() returns the shared live cache.
    cfg = copy.deepcopy(registry.load_config())
    # JAG-127c: the GLOBAL approval policy (Config panel) — no `tool` needed.
    #   approvals.mode: normal | full ("never ask, only hard-deny blocks")
    #   approvals.outside_workspace: required | auto
    if isinstance(body.get("approvals"), dict):
        ap = cfg.setdefault("approvals", {})
        for k in ("mode", "outside_workspace", "timeout_secs"):
            if k in body["approvals"]:
                ap[k] = body["approvals"][k]
        if "allow_matrix_promote" in body["approvals"]:
            ap["allow_matrix_promote"] = bool(body["approvals"]["allow_matrix_promote"])
        # JAG-510: the DANGEROUS Nucleus unlock. Read live by matrix_guard.
        if "allow_nucleus_write" in body["approvals"]:
            ap["allow_nucleus_write"] = bool(body["approvals"]["allow_nucleus_write"])
        if "matrix_enabled" in body["approvals"]:
            ap["matrix_enabled"] = bool(body["approvals"]["matrix_enabled"])
            try:
                from longrun.core import matrix as _mtx_ap
                _mtx_ap._ENABLED_OVERRIDE = ap["matrix_enabled"]
            except Exception:  # noqa: BLE001
                pass
        # JAG-451: approval policy BY CATEGORY — what the harness may emit on its
        # own. auto = apply without asking · required = raise an approval · denied =
        # never emit. Only known values are accepted (never trust the client).
        kinds = body["approvals"].get("kinds")
        if isinstance(kinds, dict):
            cur = ap.setdefault("kinds", {})
            for name, val in kinds.items():
                v = str(val or "").strip().lower()
                if v in ("auto", "required", "denied"):
                    cur[str(name)] = v
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", policy=dict(ap))
        return {"ok": True, "tools": registry.catalog(), "policy": dict(ap)}
    if isinstance(body.get("runtime"), dict):
        cfg.setdefault("runtime", {})
        for k in ("keepgoing_max", "no_progress_rounds", "max_wall_secs",
                  "subagent_max_depth", "max_parallel_tools"):
            if k in body["runtime"] and body["runtime"][k] is not None:
                cfg["runtime"][k] = int(body["runtime"][k])
        # JAG-431r4: `autocontinue` is a BOOL consumed by plan/keepgoing.py but was
        # never persisted — so the Settings toggle was a no-op both ways (write dropped,
        # read absent -> always rendered checked).
        if "autocontinue" in body["runtime"] and body["runtime"]["autocontinue"] is not None:
            cfg["runtime"]["autocontinue"] = bool(body["runtime"]["autocontinue"])
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", runtime=dict(cfg["runtime"]))
        return {"ok": True, "tools": registry.catalog(), "runtime": dict(cfg["runtime"])}
    # JAG-131: verifier "apply-only-if-green" (modulo: enabled/command/timeout/paths)
    if isinstance(body.get("verifier"), dict):
        v = cfg.setdefault("verifier", {})
        src = body["verifier"]
        if "enabled" in src:
            v["enabled"] = bool(src["enabled"])
        if "command" in src:
            v["command"] = str(src["command"] or "")
        if src.get("timeout_secs") is not None:
            v["timeout_secs"] = int(src["timeout_secs"])
        if isinstance(src.get("paths"), list):
            v["paths"] = [str(p) for p in src["paths"] if str(p).strip()]
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", verifier=dict(v))
        return {"ok": True, "tools": registry.catalog(), "verifier": dict(v)}
    # JAG-132: best-of-N + rank (enabled / n / min_score)
    if isinstance(body.get("bestofn"), dict):
        b = cfg.setdefault("bestofn", {})
        src = body["bestofn"]
        if "enabled" in src:
            b["enabled"] = bool(src["enabled"])
        if src.get("n") is not None:
            b["n"] = max(1, min(int(src["n"]), 16))
        if src.get("min_score") is not None:
            b["min_score"] = float(src["min_score"])
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", bestofn=dict(b))
        return {"ok": True, "tools": registry.catalog(), "bestofn": dict(b)}
    # JAG-134: difficulty / budget adattivo (enabled / easy_n / medium_n / hard_n / soglie)
    if isinstance(body.get("difficulty"), dict):
        d = cfg.setdefault("difficulty", {})
        src = body["difficulty"]
        if "enabled" in src:
            d["enabled"] = bool(src["enabled"])
        for k in ("easy_n", "medium_n", "hard_n"):
            if src.get(k) is not None:
                d[k] = max(1, min(int(src[k]), 16))
        for k in ("medium_at", "hard_at"):
            if src.get(k) is not None:
                d[k] = max(0.0, min(float(src[k]), 1.0))
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", difficulty=dict(d))
        return {"ok": True, "tools": registry.catalog(), "difficulty": dict(d)}
    # JAG-133/135: self-evolving (miner di sequenze + stadio 2)
    if isinstance(body.get("selfevolve"), dict):
        s = cfg.setdefault("selfevolve", {})
        src = body["selfevolve"]
        for k in ("min_len", "min_count", "max_len", "verify_timeout"):
            if src.get(k) is not None:
                s[k] = max(1, int(src[k]))
        if "category" in src:
            s["category"] = str(src["category"] or "auto").strip() or "auto"
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", selfevolve=dict(s))
        return {"ok": True, "tools": registry.catalog(), "selfevolve": dict(s)}
    # JAG-281: thinking effort — OpenAI-compatible `reasoning_effort` (OPT-IN: the
    # field is sent only when enabled AND a valid value is set, so plain/local
    # models that reject it are unaffected by default).
    if isinstance(body.get("reasoning"), dict):
        r = cfg.setdefault("reasoning", {})
        src = body["reasoning"]
        if "enabled" in src:
            r["enabled"] = bool(src["enabled"])
        if "effort" in src:
            eff = str(src["effort"] or "").strip().lower()
            r["effort"] = eff if eff in ("none", "minimal", "low", "medium", "high", "xhigh") else ""
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", reasoning=dict(r))
        return {"ok": True, "tools": registry.catalog(), "reasoning": dict(r)}
    # JAG-488: the `sandbox` block was the ONLY part of config/tools.yaml with no
    # writer — the topbar pill showed the state and nothing could change it.
    if isinstance(body.get("sandbox"), dict):
        sb = cfg.setdefault("sandbox", {})
        src = body["sandbox"]
        if "backend" in src:
            v = str(src["backend"] or "").strip().lower()
            if v not in ("auto", "docker", "bwrap", "nsjail", "none"):
                return {"ok": False, "error":
                        "sandbox.backend must be auto|docker|bwrap|nsjail|none"}
            sb["backend"] = v
        if "image" in src:
            img = str(src["image"] or "").strip()
            if not img or len(img) > 200 or any(c.isspace() for c in img):
                return {"ok": False, "error": "sandbox.image must be an image reference"}
            sb["image"] = img
        if "network" in src:
            sb["network"] = bool(src["network"])
        for k, lo, hi in (("timeout_secs", 1, 86400), ("memory_mb", 16, 65536),
                          ("pids_limit", 8, 65536)):
            if src.get(k) is not None:
                try:
                    n = int(src[k])
                except (TypeError, ValueError):
                    return {"ok": False, "error": "sandbox.%s must be an integer" % k}
                if n < lo or n > hi:
                    return {"ok": False, "error":
                            "sandbox.%s must be between %d and %d" % (k, lo, hi)}
                sb[k] = n
        if src.get("cpus") is not None:
            try:
                c = float(src["cpus"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "sandbox.cpus must be a number"}
            if not (0 < c <= 64):
                return {"ok": False, "error": "sandbox.cpus must be > 0 and <= 64"}
            sb["cpus"] = str(c)
        if "workspace" in src:
            raw_ws = str(src["workspace"] or "").strip()
            ws = raw_ws.rstrip("/")
            # Check the ORIGINAL value: stripping the slash would turn an
            # absolute "/etc" into the relative "etc" and let it through.
            if (not ws or raw_ws.startswith(("/", "\\"))
                    or ".." in ws.split("/")
                    or (len(ws) > 1 and ws[1] == ":")):
                return {"ok": False, "error":
                        "sandbox.workspace must be a relative path inside the repo"}
            sb["workspace"] = ws
        registry.save_config(cfg)
        registry.load_config(reload=True)
        sandbox.invalidate_probe()
        _publish("tools.update", sandbox=dict(sb))
        # An EXPLICIT unavailable backend raises by design (never silently run on
        # the host); report it instead of failing the save.
        try:
            probed = sandbox.probe(force=True)
        except RuntimeError as e:
            probed = {"error": str(e)}
        return {"ok": True, "tools": registry.catalog(), "sandbox": dict(sb),
                "probe": probed}
    # JAG-463: BULK policy — one request for the whole list (the Settings panel's
    # "enable all" / "disable all"). Applies to every tool the registry knows
    # (native + external MCP), so the operator does not have to click 48 rows.
    if body.get("enable_all") or body.get("disable_all"):
        want = bool(body.get("enable_all"))
        names = [t.get("name") for t in registry.catalog() if t.get("name")]
        for _nm in names:
            cfg.setdefault("tools", {}).setdefault(_nm, {})["enabled"] = want
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", bulk=("enable" if want else "disable"),
                 count=len(names))
        return {"ok": True, "updated": len(names), "tools": registry.catalog()}
    # JAG-498: GROUP policy — ONE request for every tool of a namespace, so the
    # Settings panel can "approve all" / enable / disable a whole MCP server
    # (e.g. the 26 `pmcp__gateway.*` tools) or the `fs.*` group without looping
    # one request per row. Applied with the SAME field logic as the single-tool
    # path below (`_apply_tool_fields`) so the two can never drift.
    group = body.get("tools")
    if isinstance(group, list) and group:
        group = [str(n) for n in group if str(n).strip()]
        if not group:
            return {"ok": False, "error": "tools list is empty"}
        for _nm in group:
            entry = cfg.setdefault("tools", {}).setdefault(_nm, {})
            err = _apply_tool_fields(entry, body)
            if err:
                return {"ok": False, "error": "%s: %s" % (_nm, err)}
        registry.save_config(cfg)
        registry.load_config(reload=True)
        _publish("tools.update", group=len(group), enabled=body.get("enabled"),
                 approval=body.get("approval"))
        return {"ok": True, "updated": len(group), "tools": registry.catalog()}
    name = body.get("tool") or body.get("name")
    if not name:
        return {"error": "tool required", "tools": registry.catalog()}
    entry = cfg.setdefault("tools", {}).setdefault(name, {})
    err = _apply_tool_fields(entry, body)
    if err:
        return {"ok": False, "error": err}
    registry.save_config(cfg)
    registry.load_config(reload=True)
    _publish("tools.update", tool=name, enabled=entry.get("enabled"),
             approval=entry.get("approval"))
    return {"ok": True, "tools": registry.catalog()}


def provider_upsert(body):
    """POST /api/providers — add/update a provider (engine: providers.upsert_provider)."""
    _lazy('providers')
    res = _PROVIDERS.upsert_provider(body or {})
    _publish("providers.update", action="upsert", id=(body or {}).get("id"),
             ok=bool(res.get("ok")))
    return res


def provider_remove(pid):
    """DELETE /api/providers?id= — remove or disable a provider."""
    _lazy('providers')
    res = _PROVIDERS.remove_provider(pid)
    _publish("providers.update", action="remove", id=pid, ok=bool(res.get("ok")))
    return res


def provider_add_model(body):
    """POST /api/providers/models — add a model to a provider."""
    _lazy('providers')
    body = body or {}
    res = _PROVIDERS.add_model(body.get("provider"), body.get("model"),
                               body.get("context_length"))
    _publish("providers.update", action="add_model", id=body.get("provider"),
             model=body.get("model"), ok=bool(res.get("ok")))
    return res


def provider_remove_model(pid, mid):
    """DELETE /api/providers/models?provider=&model= — remove a model."""
    _lazy('providers')
    res = _PROVIDERS.remove_model(pid, mid)
    _publish("providers.update", action="remove_model", id=pid, model=mid,
             ok=bool(res.get("ok")))
    return res


def provider_set_default(body):
    """POST /api/providers/default — set the default model reference."""
    _lazy('providers')
    body = body or {}
    res = _PROVIDERS.set_default(body.get("ref") or body.get("default"))
    _publish("providers.update", action="default", ok=bool(res.get("ok")))
    return res


def provider_reload():
    """POST /api/providers/reload — re-read providers + .env (hot reload)."""
    _lazy('providers')
    _PROVIDERS.reload()
    return {"ok": True}


def _browse_roots():
    """Allowed roots, separated with the current platform's path-list separator."""
    import os as _os
    env = _os.environ.get("LONGRUN_BROWSE_ROOTS")
    if env:
        roots = [r.strip() for r in env.split(_os.pathsep) if r.strip()]
    else:
        # JAG-2.8: the home directory PLUS the dynamic workspaces root, so the
        # default workspace of a fresh clone is browsable instead of a dead end.
        roots = [_os.path.expanduser("~")]
        try:
            from longrun.memory import rules as _rm
            base = _rm.workspaces_root()
            if base and base not in roots:
                roots.append(base)
        except Exception:  # noqa: BLE001 — browsing must work without rules
            pass
    return [_os.path.realpath(_os.path.expanduser(r)) for r in roots]


def _path_is_within(path: str, root: str) -> bool:
    """Check path containment without breaking filesystem or drive roots."""
    import os as _os
    try:
        common = _os.path.commonpath([path, root])
        return _os.path.normcase(common) == _os.path.normcase(root)
    except (OSError, ValueError):
        return False


def fs_dirs(qs=None):
    """GET /api/fs/dirs — list sub-directories for the workspace folder picker.

    JAG-2.8: the allowed set is `_fs_allowed_roots`, i.e. the browse roots PLUS the
    session's own workspace — the SAME rule the file-tree endpoints use. The picker
    used to be limited to the browse roots alone, so opening it from a session whose
    workspace lives elsewhere dead-ended with "path outside browse roots" and an
    empty list: the operator could not browse at all from that session.
    """
    import os as _os
    roots = _fs_allowed_roots(qs)
    p = _os.path.realpath(_os.path.expanduser((qs or {}).get("path") or roots[0]))
    if not any(_path_is_within(p, r) for r in roots):
        return {"error": "path outside browse roots", "roots": roots, "path": p}
    if not _os.path.isdir(p):
        return {"error": "not a directory: %s" % p, "roots": roots, "path": p}
    dirs = []
    try:
        with _os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                        dirs.append({"name": e.name, "path": e.path})
                except OSError:
                    continue
    except OSError as e:
        return {"error": str(e), "roots": roots, "path": p}
    dirs.sort(key=lambda d: d["name"].lower())
    parent = _os.path.dirname(p)
    if not any(_path_is_within(parent, r) for r in roots):
        parent = None
    return {"path": p, "parent": parent, "roots": roots, "dirs": dirs[:500], "count": len(dirs)}


# ---------------------------------------------------------------------------
# JAG-124: workspace file tree + editor (GET /api/fs/list, /api/fs/read,
# POST /api/fs/write). All paths are sandboxed to the browse roots; the tree is
# rooted at the SESSION's workspace so it follows the folder the user opened.
# ---------------------------------------------------------------------------
FS_TEXT_MAX = 1024 * 1024  # 1 MiB: files above this are shown read-only (truncated)


def _ws_root(qs=None) -> str:
    """Root to browse: explicit ?root=, else the session workspace, else browse[0]."""
    import os as _os
    q = qs or {}
    explicit = q.get("root")
    if explicit:
        return _os.path.realpath(_os.path.expanduser(explicit))
    sid = q.get("session")
    if sid:
        ws, _sess = _session_ws(sid)
        if ws:
            return _os.path.realpath(_os.path.expanduser(ws))
    return _browse_roots()[0]


def _fs_allowed_roots(qs=None) -> list[str]:
    """Return browse roots plus a trusted session workspace, never client root input."""
    import os as _os
    q = qs or {}
    roots = _browse_roots()
    if not q.get("root"):
        workspace = _ws_root(q)
        if workspace and not any(_path_is_within(workspace, root) for root in roots):
            roots.append(workspace)
    return roots


def _resolve_fs_arg(path, qs=None) -> str:
    """Resolve a caller-supplied path for the fs endpoints (JAG-354, JAG-364).

    An absolute path is used as-is. A RELATIVE path — agents emit links like
    `viz/trend.png` or `insights.md` — is resolved against the SESSION workspace,
    then each ANCESTOR of that workspace that is still inside a browse root, then
    the process CWD and the browse roots, so a link in the chat opens the file the
    agent actually wrote. The ancestor walk matters because agents work across
    SIBLING projects: a link like `sparkpulse-server/x.py` is correct when the
    workspace is `Repositories/TESTS/Jago` (the file lives in `Repositories/`).
    Returns "" for an empty path; the sandbox check still runs afterwards.
    """
    import os as _os
    raw = str(path or "").strip()
    if not raw:
        return ""
    p = _os.path.expanduser(raw)
    if _os.path.isabs(p):
        return p
    candidates = []
    try:
        root = _ws_root(qs)
    except Exception:  # noqa: BLE001 — a lookup hint must never be fatal
        root = ""
    try:
        roots = _browse_roots()
    except Exception:  # noqa: BLE001
        roots = []
    if root:
        # JAG-364: the workspace, then its ancestors while they stay inside a
        # browse root (bounded to 12 levels, so it can never walk up to `/`).
        d = _os.path.abspath(_os.path.expanduser(root))
        for _ in range(12):
            candidates.append(_os.path.join(d, p))
            parent = _os.path.dirname(d)
            if parent == d:
                break
            if roots and not any(_path_is_within(parent, r) for r in roots):
                break
            d = parent
    candidates.append(_os.path.join(_os.getcwd(), p))
    for r in roots:
        candidates.append(_os.path.join(r, p))
    for c in candidates:
        try:
            if _os.path.exists(c):
                return c
        except OSError:
            continue
    return candidates[0] if candidates else p


def _safe_fs_path(path, roots=None):
    """Resolve `path` and return it only if inside an allowed root, else None."""
    import os as _os
    roots = roots or _browse_roots()
    p = _os.path.realpath(_os.path.expanduser(path or ""))
    if not any(_path_is_within(p, r) for r in roots):
        return None
    return p


FS_TREE_SKIP = {"node_modules", "__pycache__", ".git", ".hg", ".svn", ".venv",
                "venv", "dist", "build", "target", ".mypy_cache", ".pytest_cache",
                ".ruff_cache", ".ipynb_checkpoints"}

FS_TREE_DIR_MAX = 1000
FS_TREE_FILE_MAX = 2000


def fs_list(qs=None) -> dict:
    """GET /api/fs/list — list one directory (dirs first, then files).

    `?session=` roots the browse at that session's workspace; `?path=` selects
    the directory. JAG-509: the operator works INSIDE dot-directories and
    gitignored folders (`.Matrix`, `.agent`, `data/`), and the editor tree used to
    drop every dot-entry — those files were invisible and unopenable. Only VCS
    internals and dependency/build caches stay out (they are thousands of files
    nobody hand-edits). Reading was never restricted by that filter —
    `/api/fs/read` already served any path inside the browse roots — so this
    makes the tree match the filesystem. Read-only, never mutates.
    """
    import os as _os
    q = qs or {}
    root = _ws_root(q)
    p = _safe_fs_path(_resolve_fs_arg(q.get("path"), q) or root,
                      _fs_allowed_roots(q))
    if not p:
        return {"error": "path outside allowed roots", "root": root}
    if not _os.path.isdir(p):
        return {"error": "not a directory: %s" % p, "root": root, "path": p}
    dirs, files = [], []
    try:
        with _os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name in FS_TREE_SKIP:
                            continue
                        dirs.append({"name": e.name, "path": e.path, "type": "dir"})
                    elif e.is_file(follow_symlinks=False):
                        files.append({"name": e.name, "path": e.path, "type": "file",
                                      "size": e.stat().st_size})
                except OSError:
                    continue
    except OSError as e:
        return {"error": str(e), "root": root, "path": p}
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda d: d["name"].lower())
    return {"root": root, "path": p, "dirs": dirs[:FS_TREE_DIR_MAX],
            "files": files[:FS_TREE_FILE_MAX],
            "count": len(dirs) + len(files)}


FS_FIND_MAX = 20000  # entries scanned per query: bounded, never a full-disk walk


def fs_find(qs=None) -> dict:
    """GET /api/fs/find — search folders/files by name under the browse root.

    Keyboard-first navigation for the workspace pickers (JAG-501): the operator
    types a fragment, the server walks the tree breadth-first and returns the
    closest matches (exact > prefix > substring, dirs before files), so a deep
    folder is one Enter away instead of a dozen clicks. Read-only, sandboxed to
    the same roots as /api/fs/list, and bounded by FS_FIND_MAX entries.
    """
    import os as _os
    q = qs or {}
    term = str(q.get("q") or "").strip().lower()
    kind = str(q.get("kind") or "any")
    if kind not in ("dir", "file", "any"):
        kind = "any"
    try:
        limit = max(1, min(200, int(q.get("limit") or 60)))
    except (TypeError, ValueError):
        limit = 60
    if not term:
        return {"error": "q required", "results": [], "count": 0}
    root = _ws_root(q)
    start = _safe_fs_path(_resolve_fs_arg(q.get("path"), q) or root,
                          _fs_allowed_roots(q))
    if not start:
        return {"error": "path outside allowed roots", "root": root, "results": []}
    if not _os.path.isdir(start):
        return {"error": "not a directory: %s" % start, "root": root, "results": []}
    skip = FS_TREE_SKIP
    hits, scanned, queue = [], 0, [start]
    while queue and scanned < FS_FIND_MAX:
        cur = queue.pop(0)
        try:
            entries = list(_os.scandir(cur))
        except OSError:
            continue
        for e in entries:
            scanned += 1
            if scanned >= FS_FIND_MAX:
                break
            name = e.name
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                # JAG-509: same visibility rule as the editor tree — hidden and
                # gitignored folders are searchable; only VCS/cache noise is not.
                if name.lower() in skip:
                    continue
                queue.append(e.path)
            low = name.lower()
            if kind == "dir" and not is_dir:
                continue
            if kind == "file" and is_dir:
                continue
            if term not in low:
                continue
            score = 0 if low == term else (1 if low.startswith(term) else 2)
            try:
                rel = _os.path.relpath(e.path, start)
            except ValueError:
                rel = name
            hits.append({"name": name, "path": e.path, "rel": rel,
                         "dir": is_dir, "score": score})
        if len(hits) >= limit * 4:
            break
    hits.sort(key=lambda h: (h["score"], not h["dir"], len(h["rel"]), h["rel"].lower()))
    return {"root": root, "path": start, "q": term, "kind": kind,
            "results": hits[:limit], "count": len(hits), "scanned": scanned}


def fs_read(qs=None) -> dict:
    """GET /api/fs/read — return a text file's content for the editor.

    Binary files report `binary: True` with empty text; files over FS_TEXT_MAX
    are truncated and flagged so the UI can lock the editor.
    """
    import os as _os
    q = qs or {}
    p = _safe_fs_path(_resolve_fs_arg(q.get("path"), q), _fs_allowed_roots(q))
    if not p:
        return {"error": "path outside allowed roots"}
    if not _os.path.isfile(p):
        return {"error": "not a file: %s" % p}
    size = _os.path.getsize(p)
    if size > FS_TEXT_MAX:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(FS_TEXT_MAX)
        return {"path": p, "text": text, "size": size, "truncated": True, "binary": False}
    try:
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
    except (UnicodeDecodeError, ValueError):
        return {"path": p, "text": "", "size": size, "truncated": False, "binary": True}
    return {"path": p, "text": text, "size": size, "truncated": False, "binary": False}


def _fs_raw(handler, qs=None):
    """GET /api/fs/raw — raw bytes for an inline preview (images / PDF only).

    Deliberately restricted to safe MIME types: it must never serve text/html or
    javascript from the workspace inline, or it would become an XSS vector.
    """
    import os as _os
    import mimetypes
    q = qs or {}
    p = _safe_fs_path(_resolve_fs_arg(q.get("path"), q), _fs_allowed_roots(q))
    if not p or not _os.path.isfile(p):
        return _r(handler, 404, {"error": "not found"})
    if _os.path.getsize(p) > 32 * 1024 * 1024:
        return _r(handler, 413, {"error": "file too large to preview"})
    ctype = (mimetypes.guess_type(p)[0] or "application/octet-stream").lower()
    # JAG-232: an ALLOW-LIST of inert types only. `image/svg+xml` (and any other
    # `+xml`) is a script container: served inline at THIS origin the browser runs
    # its embedded JS (verified — an `<svg onload>` set a global). The workspace is
    # agent-writable, so a planted .svg was a stored-XSS -> token theft. Never do
    # `startswith("image/")`: SVG passes it.
    _SAFE_PREVIEW = {"image/png", "image/jpeg", "image/jpg", "image/gif",
                     "image/webp", "image/bmp", "image/x-icon",
                     "image/vnd.microsoft.icon", "image/avif", "image/tiff",
                     "application/pdf"}
    if ctype not in _SAFE_PREVIEW:
        return _r(handler, 415, {"error": "unsupported preview type: %s" % ctype})
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError as e:
        return _r(handler, 500, {"error": str(e)})
    handler._send(200, data, ctype=ctype)
    return True


def fs_write(body) -> dict:
    """POST /api/fs/write — overwrite an EXISTING text file with `content`.

    Overwrite-only (never creates new files) and length-capped, so the editor
    cannot be used to plant files or blow up the disk. Publishes `fs.write` so
    the app/UI can react to on-disk changes.
    """
    import os as _os
    b = body or {}
    p = _safe_fs_path(_resolve_fs_arg(b.get("path"), b), _fs_allowed_roots(b))
    if not p:
        return {"error": "path outside allowed roots"}
    if not _os.path.isfile(p):
        return {"error": "not a file (create is not allowed): %s" % p}
    content = b.get("content")
    if not isinstance(content, str):
        return {"error": "content (string) required"}
    raw = content.encode("utf-8")
    if len(raw) > FS_TEXT_MAX:
        return {"error": "content too large (%d bytes > %d)" % (len(raw), FS_TEXT_MAX)}
    try:
        from longrun.tools import matrix_guard
        with matrix_guard.NUCLEUS_EXEC_LOCK:
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
    except OSError as e:
        return {"error": str(e)}
    _publish("fs.write", path=p, bytes=len(raw))
    return {"ok": True, "path": p, "bytes": len(raw)}


# ---------------------------------------------------------------------------
# JAG-279: attachment upload (POST /api/attach, raw bytes). The composer's
# native file picker posts the file body because a browser cannot reveal a
# client-side path; storing the bytes server-side is the only cross-platform
# way to attach a REAL file (Windows client + Linux server, or vice-versa).
# The stored ABSOLUTE path is what the model receives, so it can fs.read it.
# ---------------------------------------------------------------------------
def attach_save(data, name=None, session=None) -> dict:
    """POST /api/attach — persist an uploaded attachment and return its path.

    The filename is sanitized and a timestamp suffix deduplicates instead of
    overwriting. Success includes whether the file is knowledge-indexable.
    """
    import os as _os
    import re as _re
    import time as _time
    from longrun.memory import chunk as _chunk
    cap = int(_os.environ.get("LONGRUN_ATTACH_MAX", str(32 * 1024 * 1024)))
    if not data:
        return {"ok": False, "error": "empty upload"}
    if len(data) > cap:
        return {"ok": False, "error": "attachment too large (%d > %d bytes)" % (len(data), cap)}
    base = _os.path.basename(str(name or "upload.bin")).strip() or "upload.bin"
    base = _re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120] or "upload.bin"
    sid = _re.sub(r"[^A-Za-z0-9._-]", "_", str(session or "default"))[:64] or "default"
    folder = _os.path.join(_srv().DATA_DIR, "attachments", sid)
    try:
        _os.makedirs(folder, exist_ok=True)
        path = _os.path.join(folder, base)
        if _os.path.exists(path):
            stem, ext = _os.path.splitext(base)
            path = _os.path.join(folder, "%s-%d%s" % (stem, int(_time.time()), ext))
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    indexable = bool(_chunk.lang_for(base)[0])
    return {"ok": True, "path": path, "name": _os.path.basename(path),
            "size": len(data), "indexable": indexable}


# ---------------------------------------------------------------------------
# JAG-281: real terminal — a persistent per-session shell (term.py). This is the
# HUMAN terminal; the agent's `shell` tool keeps its own approval gate. Reachable
# only behind the harness token (the whole HTTP surface is auth-gated).
# ---------------------------------------------------------------------------
def _term():
    _lazy("term")
    return getattr(sys.modules[__name__], "_TERM")


def term_exec(body):
    """POST /api/term/exec {session, cmd} — run a line in the persistent shell."""
    b = body or {}
    sid = b.get("session") or "default"
    if b.get("cmd") is None:
        return {"error": "cmd required"}
    ws, _sess = _session_ws(sid if sid != "default" else None)
    sh = _term().get(sid, ws)
    res = sh.run(b.get("cmd"))
    res["cwd"] = sh.cwd
    return res


def term_poll(qs):
    """GET /api/term/poll?session=&cursor= — shell output newer than `cursor`."""
    q = qs or {}
    sid = q.get("session") or "default"
    try:
        cur = int(q.get("cursor") or 0)
    except (TypeError, ValueError):
        cur = 0
    sh = _term().peek(sid)
    if not sh:
        return {"events": [], "cursor": cur, "busy": False, "reset": False, "alive": False}
    out = sh.poll(cur)
    out["alive"] = True
    return out


def term_reset(body):
    """POST /api/term/reset {session} — kill the persistent shell (fresh next use)."""
    b = body or {}
    return {"ok": bool(_term().reset(b.get("session") or "default"))}


# ---------------------------------------------------------------------------
# JAG-127: file-edit journal — IDE-style change summary, diff and undo.
# Keyed by the run/session id (chat passes the session id). Backed by edits.py.
# ---------------------------------------------------------------------------
def edits_summary(qs=None) -> dict:
    """GET /api/edits?session= — per-file +N/-M summary of the changes made."""
    from longrun.tools import edits as edits_mod
    q = qs or {}
    return edits_mod.summary(q.get("session") or q.get("key") or "default")


def edits_diff(qs=None) -> dict:
    """GET /api/edits/diff?session=&path= — aligned before/after rows for one file."""
    from longrun.tools import edits as edits_mod
    q = qs or {}
    path = q.get("path")
    if not path:
        return {"error": "path required"}
    return edits_mod.diff(q.get("session") or q.get("key") or "default", path)


def edits_undo(body) -> dict:
    """POST /api/edits/undo {session, path?} — REJECT: restore files to their pre-image."""
    from longrun.tools import edits as edits_mod
    b = body or {}
    return edits_mod.undo(b.get("session") or b.get("key") or "default", b.get("path"))


def edits_approve(body) -> dict:
    """POST /api/edits/approve {session, path?} — APPROVE: keep files, drop the pending diff."""
    from longrun.tools import edits as edits_mod
    b = body or {}
    return edits_mod.approve(b.get("session") or b.get("key") or "default", b.get("path"))


def _session_ws(session_id):
    """Resolve the workspace for a session id (or the global default when none)."""
    _lazy('rules')
    sess = _srv().load_session(session_id) if session_id else None
    return _RULES.resolve_workspace(sess), sess


def codebase_status(qs=None):
    """GET /api/codebase/status — the CODEBASE index for the session's workspace."""
    from longrun.memory import codeindex as _ci
    ws, _ = _session_ws((qs or {}).get("session"))
    return _ci.status(ws)


def codebase_files(qs=None):
    """GET /api/codebase/files — every file indexed for the session's workspace."""
    from longrun.memory import codeindex as _ci
    ws, _ = _session_ws((qs or {}).get("session"))
    return _ci.list_files(ws)


def codebase_search(src):
    """GET/POST /api/codebase/search — search THIS workspace's codebase index."""
    from longrun.memory import codeindex as _ci
    ws, _ = _session_ws(src.get("session"))
    return _ci.search(ws, src.get("q") or src.get("query"), _int(src.get("k", 8), 8), src.get("kind"))


def knowledge_status():
    """GET /api/knowledge/status — the GLOBAL knowledge base counts."""
    from longrun.memory import knowledge as _kb
    return _kb.status()


def knowledge_notebooks():
    """GET /api/knowledge/notebooks — GLOBAL notebooks + SESSION notebooks.

    JAG-431r6b: session-scoped KBs are returned separately under `sessions`
    (adds `is_session=True`), so the WebUI renders them in a dedicated,
    request-expanded "Session" tab instead of mixing them into the global list.
    """
    from longrun.memory import knowledge as _kb
    return {"notebooks": _kb.list_notebooks(), "sessions": _kb.list_sessions()}


def knowledge_sources(qs=None):
    """GET /api/knowledge/sources — sources, optionally for one notebook."""
    from longrun.memory import knowledge as _kb
    return {"sources": _kb.list_sources((qs or {}).get("notebook"))}


def knowledge_files(qs=None):
    """GET /api/knowledge/files — indexed files, optionally for one notebook."""
    from longrun.memory import knowledge as _kb
    return _kb.list_files((qs or {}).get("notebook"))


def knowledge_search(src):
    """GET/POST /api/knowledge/search — search the knowledge base.

    Optional `session` scopes the search to that session's notebooks only
    (JAG-431r6b); a global search (no session/notebook) excludes session KBs.
    """
    from longrun.memory import knowledge as _kb
    return _kb.search(src.get("q") or src.get("query"), src.get("notebook"),
                      _int(src.get("k", 8), 8), src.get("kind"),
                      session=src.get("session") or None)


def knowledge_notebook_action(body):
    """POST /api/knowledge/notebooks — create / rename / delete a notebook."""
    from longrun.memory import knowledge as _kb
    action = (body.get("action") or "create").lower()
    if action == "rename":
        return _kb.rename_notebook(body.get("id"), body.get("name"))
    if action == "delete":
        return _kb.delete_notebook(body.get("id"))
    return _kb.create_notebook(body.get("name"))


def knowledge_source_action(body):
    """POST /api/knowledge/sources — add / add-text / remove a source."""
    from longrun.memory import knowledge as _kb
    if body.get("remove") or body.get("source"):
        return _kb.remove_source(body.get("remove") or body.get("source"))
    if body.get("text"):
        return _kb.add_text(body.get("notebook"), body.get("title"), body.get("text"))
    res = _kb.add_sources(body.get("notebook"),
                          body.get("refs") or body.get("ref") or body.get("url") or body.get("path") or "")
    _publish("knowledge.docs", ok=bool(res.get("ok")), added=res.get("added"))
    return res


def index_config_get():
    """GET /api/index/config — the SHARED index config + embedding suggestions."""
    from longrun.memory import indexcfg as _cfg
    from longrun.model import embed as _embed
    return {"config": _cfg.load_config(), "embed_model": _embed.model_ref(),
            "suggested": _embed.SUGGESTED}


def rules_status(qs=None):
    """GET /api/rules — workspace + global/project rules state for a session."""
    sid = (qs or {}).get("session")
    ws, sess = _session_ws(sid)
    st = _RULES.status(ws=ws)
    st["session"] = sid
    st["source"] = "session" if (sess and sess.get("workspace")) else "default"
    return st


def rules_save(body):
    """POST /api/rules — save rules for 'global' or 'project' (session-aware)."""
    body = body or {}
    sid = body.get("session")
    ws, _sess = _session_ws(sid)
    res = _RULES.save(body.get("scope"), body.get("content"), ws=ws)
    _publish("rules.update", scope=body.get("scope"), ok=bool(res.get("ok")))
    return res


def workspace_get(qs=None):
    """GET /api/workspace — the resolved workspace + the global default + status."""
    sid = (qs or {}).get("session")
    ws, sess = _session_ws(sid)
    return {"workspace": ws, "default": _RULES.get_workspace(), "session": sid,
            "source": "session" if (sess and sess.get("workspace")) else "default",
            "status": rules_status(qs)}


def workspace_set(body):
    """POST /api/workspace — link a folder to a session, or set the global default."""
    _lazy('rules')
    body = body or {}
    asked = body.get("path") or body.get("workspace")
    real = _RULES.check_dir(asked)
    if not real:
        return {"ok": False, "error": "no such folder: %s" % (asked or "(empty)")}
    sid = body.get("session")
    if sid:
        with _srv()._turn_lock(sid):
            sess = _srv().load_session(sid)
            if not sess:
                return {"ok": False, "error": "no such session: %s" % sid}
            sess["workspace"] = real
            _srv().save_session(sess)
        try:
            _RULES.remember_workspace(real)  # JAG-126: next new session defaults here
        except Exception:  # noqa: BLE001 — convenience only
            pass
        _publish("workspace.update", session=sid, workspace=real, ok=True)
        return {"ok": True, "scope": "session", "session": sid, "workspace": real}
    res = _RULES.set_workspace(real)
    # JAG-2.9: a new DEFAULT workspace must get the automatic background index too.
    try:
        from longrun.memory import autoidx as _autoidx
        _autoidx.start(real)
    except Exception:  # noqa: BLE001 — indexing is best-effort
        pass
    _publish("workspace.update", workspace=real, ok=bool(res.get("ok")))
    return dict(res, scope="default")


def install_skill_raw(data, name=None, overwrite=False):
    """POST /api/skills/install — body zip grezzo. Engine: skills.install_zip."""
    from longrun.memory import skills as skills_mod
    res = skills_mod.install_zip(data, name=name, overwrite=overwrite)
    _publish("skills.install", name=res.get("name"), ok=bool(res.get("ok")))
    return res
