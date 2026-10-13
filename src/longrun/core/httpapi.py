"""Longrun HTTP / JSON API, SSE routes and the process entrypoint (`main`).

Owns the `ThreadingHTTPServer` request handler, the bearer-token check, every
`/api/*` route (chat + agent SSE streams, sessions, plan/tasks, context meter,
tools, voice, feed, telemetry, static assets, the optional beta Bridge pages) and
`main()` — the CLI/daemon bootstrap. Extracted from ``server.py`` (JAG-379); the
agent loop, stores, events, router and config it drives are re-exported by
``server`` (imported here). This module is imported at the BOTTOM of ``server.py``
so the ``from .server import (...)`` below resolves against a fully-populated
module and no import cycle forms.
"""
import argparse
import json
import os
import queue
import re
import ssl
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from longrun.core import api_v02
from longrun.tools import approvals
from longrun.tools import registry
from longrun.model import routing
from longrun.tools import sandbox
from longrun.plan import taskgraph
from longrun.core import server as _sf_server  # only for the AUTH_TOKEN mirror in main()
from longrun.model import rllm
from longrun.core.server import (ASSET_CTYPES, ASSET_EXTS,
                     CHAT_STREAM_IDLE, CHAT_TOOL_PROMPT, COMPACT_FORCE_RATIO,
                     COMPACT_MANUAL_KEEP_RECENT, DATA_DIR, FEED_REPLAY_MAX,
                     HARNESS_MARK, MAX_BODY_BYTES, REPO, ROUTER_BASE, RunTrace,
                     SESSIONS_DIR, SUMMARIZER_MAX_CHARS, ThinkCoalescer, VERSION,
                     WEBUI_DIR, _ACTIVE_CHAT, _ACTIVE_CHAT_LOCK, _DELETED_SESSIONS,
                     _REAL_CACHED_TOKENS, _REAL_PROMPT_TOKENS, _deleted_lock,
                     _ensure_dirs, _forget_session_runtime, _is_aborted, _local_ref,
                     _orbit_handle, _orbit_page, _persist_tombstones,
                     _purge_session_artifacts, _set_session_model, _sse_lock,
                     _sse_queues,
                     _start_event_pruning, _turn_lock, _valid_sid, agent_run,
                     append_message, backfill_jobs, backfill_session_workspaces,
                     chat_once, clear_abort, clear_session, context_budget, default_model,
                     ensure_job, ensure_model, ensure_reply_persisted, eval_list_tasks,
                     eval_run, events_since, feed_seq, generate_plan,
                     get_or_create_session, get_run_trace, graph_post, keys_status,
                     list_sessions, load_plan, load_session, load_tasks, model_loaded,
                     publish, push_abort, push_steer, query_events,
                     reconcile_agent_models, reconcile_orphan_turns, router_models,
                     runs_summary, save_session, save_tasks, self_knowledge,
                     selfcheck_payload, session_mark, sse_pump, sse_response,
                     start_run_graph, state_block, stream_with_fallback, system_prompt,
                     turn_begin, turn_end, voice_status, voice_stt, voice_tts)
from longrun.orbit.api import WEB as ORBIT_WEB


# ------------------------------------------------------------------ HTTP ----

AUTH_TOKEN = None


def check_auth(headers, qs=None):
    if not AUTH_TOKEN:
        return True
    h = headers.get("Authorization") or ""
    if h == "Bearer " + AUTH_TOKEN:
        return True
    # EventSource cannot set headers: allow ?token= as fallback
    return bool(qs) and qs.get("token") == AUTH_TOKEN


def _as_int(x, default):
    """Coerce any wire value to int, falling back on garbage (JAG-229/231)."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _int_arg(qs, key, default):
    """Parse an integer query parameter with a safe fallback (JAG-229).

    Query strings are attacker-controlled: `?since=abc` used to raise an
    unhandled ValueError that reset the connection instead of returning a
    clean response. Any malformed value falls back to `default`.
    """
    return _as_int(qs.get(key, default), default)


def chat_stream_gen(sess, message, model, mark=None, autonomous=False, jid=None,
                    sender=None, subjob=None, plan_only=False):
    """SSE producer for one chat request on `sess`.

    Contract (JAG-51): the caller has already appended the `user` message and
    passes `mark = session_mark(sess)` (the index captured just before it). Every
    exit path of this generator — reply, router error, warm-up error — leaves the
    session with a matching `assistant` message: a failed stream persists an
    explicit assistant error turn *and* emits the `error` SSE event, so a
    streamed request can never leave an orphan `user` message behind.

    `jid` (JAG-301): the job (JN) this turn belongs to, or None for a manual
    turn. It is written onto the session's task graph for THIS turn only, so a
    previous job's tag can never linger on a later, unrelated todo.

    `sender` / `subjob` (JAG-322): a turn TRIGGERED BY ANOTHER AGENT, not the
    human. When a job's coordinator delegates a subjob, the worker's turn must be
    attributed ("Delegation from A8 (Master) · J6.1") instead of showing up as the
    operator's own message. Both fields ride on the persisted user message and are
    rendered by the WebUI; a manual turn leaves them None ("YOU").

    `plan_only` (JAG-344): a turn that DECOMPOSES rather than works — the job
    coordinator's planning turn. It keeps a tight real-tool budget and NEVER
    enters the keepgoing continuation loop, so the master cannot complete the
    whole job itself instead of delegating it to the team.
    """
    q = queue.Queue()
    done = {"flag": False}
    since = mark if mark is not None else max(0, session_mark(sess) - 1)
    # JAG-181: register this turn as ACTIVE for its session, capturing the feed id
    # at turn start, so a re-attaching client can replay the whole turn.
    # JAG-299: a unique token per turn — the worker must only clear the
    # registration IT created. Two overlapping requests on one session (the second
    # blocks on the turn lock) used to have the first worker's exit pop the
    # SECOND turn's registration, so /api/chat/live reported idle and /api/chat/
    # attach could not resume a turn that was in fact still running.
    _turn_tok = object()
    with _ACTIVE_CHAT_LOCK:
        _ACTIVE_CHAT[sess["id"]] = {"ev0": feed_seq(), "ts": time.time(), "tok": _turn_tok}
    # JAG-431q: drop any stale abort LEFT OVER from a previous turn AT TURN START —
    # before the planner/graph/answer emit their own model calls. It used to be cleared
    # inside `chat_once`, i.e. AFTER the planner had already run: a Stop pressed during
    # that window (the UI shows the turn as running from the very first moment) was
    # silently wiped and the whole turn ran anyway ("Stop does nothing").
    clear_abort(sess["id"])

    def _delta(channel, text):
        q.put("event: chat.delta\ndata: %s\n\n" % json.dumps(
            {"session": sess["id"], "channel": channel, "text": text}, ensure_ascii=False))
        publish("chat.delta", session=sess["id"], channel=channel, text=text)

    _coalesce = ThinkCoalescer(_delta)

    def on_delta(channel, text):
        _coalesce.feed(channel, text)

    def worker():
        nonlocal sess, since
        # JAG-201: serialise turns on this session (see _turn_lock).
        _turn_lock(sess["id"]).acquire()
        target = model

        def _emit(kind, **d):
            # graph/model events go to BOTH this chat stream and the feed, so
            # the WebUI can render the task graph live either way.
            q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
            publish(kind, **d)

        try:
            # JAG-201: the transcript read-modify-write happens INSIDE the lock —
            # reload the session, then append this turn's user message. Doing it in
            # the request thread (as before) let two concurrent streaming turns
            # overwrite each other (lost update).
            _fresh = load_session(sess["id"])
            if _fresh:
                sess = _fresh
            sess = prepare_session_for_turn(sess, model or sess.get("model"))
            since = session_mark(sess)
            # JAG-426: anchor this turn so it can be rewound. It MUST run INSIDE the
            # turn lock and AFTER the authoritative `since` is known (JAG-201): a
            # mark created in the request thread raced a concurrent turn on the same
            # session and reused an idempotency key, so the anchor pointed at the
            # wrong message (or the wrong snapshot). Same rule as the sync path.
            try:
                from longrun.memory import rewind as _rewind
                _rewind.mark(sess["id"], since, label="turn %s" % since)
            except Exception:  # noqa: BLE001 — an anchor must never break the turn
                pass
            append_message(sess, "user", message,
                           meta=({"sender": sender, "subjob": subjob}
                                 if (sender or subjob) else None))
            publish("chat.user", session=sess["id"], text=message,
                    sender=sender, subjob=subjob)
            # v0.5.1 warm-up: resolve the target alias and, if it is cold, emit
            # `model.loading` and load it *before* the first token instead of
            # letting the client stall silently on the router's autoload.
            target = model or routing.pick("chat") or default_model()
            trace = RunTrace("chat", goal=message[:120], model=target)
            trace.span("chat.stream", session=sess["id"])
            q.put("event: chat.run\ndata: %s\n\n" % json.dumps(
                {"run_id": trace.id, "session": sess["id"]}))
            # JAG-323: mirror the turn START onto the GLOBAL feed (chat.done already
            # is). Without it, a turn this browser did not begin — a headless job or
            # routine turn — never flipped the session's "running" marker, so the
            # session looked idle while the model burned GPU ("phantom run").
            publish("chat.run", run_id=trace.id, session=sess["id"])
            try:
                # JAG-71: only a LOCAL model has a warm-up (/models/load); remote
                # providers are called directly with no loading step.
                if target and _local_ref(target):
                    loaded, _m = model_loaded(target)
                    if not loaded:
                        ensure_model(target, on_event=_emit)
                # JAG-63: the graph is keyed by SESSION = the persistent task
                # list for this task. It survives every message, compaction and
                # restart; a NEW task (previous list fully done) starts fresh.
                # JAG-65: the todo list is authored INLINE by the model on its own
                # first response (harness action `write_todos`) — exactly like
                # Claude Code / Deep Agents. There is NO separate planner call:
                # that extra round-trip was dead air before any reply and fed the
                # model only the raw user message, so it parroted it back as steps.
                gkey = sess["id"]
                _existing = taskgraph.load(gkey)
                if _existing and taskgraph.all_done(_existing):
                    # JAG-194: a finished task starts a NEW plan. We bump `plan`
                    # instead of hard-resetting the graph: keeping the old nodes
                    # (with their unique ids) is what lets the transcript's old
                    # cards resolve to the right node on reload instead of a
                    # relabelled/reused id.
                    taskgraph.begin_plan(_existing)
                # JAG-301: the job tag belongs to THIS turn. A job turn passes its
                # `jid`; a manual turn passes None — so a finished job's tag never
                # lingers on the session and mislabels a later, unrelated todo.
                # JAG-324: the SUBJOB tag rides alongside, so each todo an agent
                # creates is embraced by the (jid, subjob) it was produced for.
                if _existing is not None:
                    _existing["jid"] = jid
                    _existing["subjob"] = subjob
                    taskgraph.save(_existing)
                chat_once(sess, message, target, on_delta, trace=trace, on_event=_emit,
                          autonomous=autonomous, plan_only=plan_only)
                # JAG-431n: the JAG-76 "guarantee a plan" fallback is GONE.
                #
                # It ran a planner model call AFTER the turn had already answered,
                # so its steps described work that was already DONE (or never
                # attempted) — and nobody ever executed or closed them (JAG-173
                # forbids auto-closing). They dangled as OPEN todos forever and the
                # next turn's JAG-189 "stale plan" rule (user_pivot) exempted them
                # from the JAG-402 close-todo enforcement, so they were never
                # cleaned up. Proven on kb-agent/55a29fae70cb: the reply landed at
                # t=1791835170.33 and `graph.node.added` fired at t=1791835195..200
                # — 3 orphan todos created ~25 s AFTER the answering turn.
                #
                # The harness contract is "the MODEL authors the list, then executes
                # and closes each step with evidence" (JAG-65/173/402). A
                # retrospective plan is a fake surface, not a task list — and the UI
                # must show what is real (a graph is empty until the model writes
                # todos, or the operator adds one). No separate planner call.

                # JAG-63: do NOT finalize the task list at the end of every
                # message — that forced every open node to 'done' and is exactly
                # why the list could never persist. Nodes close only with real
                # evidence (or explicitly by the user).
                trace.finish("done")
            except Exception as e:
                trace.finish("error")
                raise
        except Exception as e:
            # JAG-51: a failed stream must still leave a trace in the session —
            # persist the explicit assistant error turn, then tell the client.
            ensure_reply_persisted(sess, since, error=e, model=target)
            publish("chat.error", session=sess["id"], error=str(e))
            try:
                from longrun.model import runmetrics
                runmetrics.finish(sess["id"], outcome="error", stop_reason="error",
                                  model=target)
                publish("run.metrics", session=sess["id"],
                        metrics=runmetrics.get(sess["id"]))
            except Exception:  # noqa: BLE001
                pass
            q.put("event: error\ndata: %s\n\n" % json.dumps(
                {"error": str(e), "session": sess["id"], "stored": True},
                ensure_ascii=False))
        finally:
            _coalesce.flush()  # JAG-265: emit any coalesced CoT tail before closing
            done["flag"] = True
            q.put(None)
            # JAG-181: the turn is over — no longer "attachable".
            # JAG-299: only clear OUR registration; a newer turn may have replaced it.
            with _ACTIVE_CHAT_LOCK:
                if (_ACTIVE_CHAT.get(sess["id"]) or {}).get("tok") is _turn_tok:
                    _ACTIVE_CHAT.pop(sess["id"], None)
            _turn_lock(sess["id"]).release()  # JAG-201: allow the next turn

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # v0.6.1 (JAG-48): no keep-alive here — one `done`, then the generator is
    # exhausted and sse_response closes the connection.
    try:
        yield from sse_pump(q, t, idle_timeout=CHAT_STREAM_IDLE or None)
    finally:
        # JAG-51 safety net: if the producer is already gone without a reply
        # (e.g. the pump gave up on silence), still leave an assistant trace.
        # While the worker is alive it owns the persistence — never double-write.
        if not t.is_alive():
            ensure_reply_persisted(sess, since, error="stream ended without a reply")


# JAG-431r8: the re-attach stream must replay the SAME render events the live
# own-turn stream carries — otherwise a turn the browser did not begin (a job, a
# routine, another tab) showed only the answer text and NO tool cards / harness
# injects / todo-node updates until it finished (a reload). The client renders
# them live and rebuilds from the durable transcript on `done` (clear first), so
# nothing is duplicated.
_ATTACH_KINDS = (
    "chat.run", "chat.delta", "chat.done",
    "harness.inject", "tool.call", "tool.result", "approval.request",
    "graph.node.added", "graph.node.updated",
    "plan.incomplete", "plan.continuing", "plan.stopped", "hitl.request",
    "verify.run", "run.metrics", "bestofn.chosen", "improve.proposal", "cost.usage",
    "improve.nudge", "improve.verify", "improve.evolve", "improve.archived",  # JAG-447
)


def _attach_frame(ev, terminal=False):
    kind = "done" if (terminal or ev.get("kind") == "chat.done") else ev.get("kind")
    return "id: %d\nevent: %s\ndata: %s\n\n" % (
        ev["id"], kind, json.dumps(ev, ensure_ascii=False))


def chat_attach_gen(sid, since=0):
    """JAG-181: re-attach a refreshed / reopened WebUI to a chat turn that is still
    RUNNING for `sid`.

    A page refresh or a session switch loses the browser's SSE channel but never
    stops the server-side worker. This generator replays the turn's events
    (streaming text AND the render events: tool cards, todo tree, harness injects)
    from the durable event log and then tails new ones until the turn ends, so a
    re-attached turn shows exactly what a turn begun in this tab would show. On
    `done` the client rebuilds the tree from the durable transcript (clear first),
    so the live-rendered cards are replaced, never duplicated (JAG-431r8).
    """
    with _ACTIVE_CHAT_LOCK:
        info = _ACTIVE_CHAT.get(sid)
    if not info:
        yield "event: done\ndata: {}\n\n"   # turn already finished: nothing to follow
        return
    last = since or info.get("ev0", 0)
    for ev in events_since(last):
        if ev.get("session") != sid or ev.get("kind") not in _ATTACH_KINDS:
            continue
        last = ev["id"]
        if ev.get("kind") == "chat.done":
            yield _attach_frame(ev, terminal=True)
            return
        yield _attach_frame(ev)
    idle = 0
    # JAG-431r4: bound the tail. The loop previously ended ONLY when the turn left
    # _ACTIVE_CHAT; a worker that hung mid-turn would ping forever and pin this
    # ThreadingHTTPServer thread. Mirror the live-stream silence policy
    # (CHAT_STREAM_IDLE) so a genuinely silent-but-alive turn is not cut early.
    last_activity = time.time()
    while True:
        with _ACTIVE_CHAT_LOCK:
            if sid not in _ACTIVE_CHAT:
                break
        if time.time() - last_activity > (CHAT_STREAM_IDLE or 900.0):
            break
        time.sleep(0.4)
        emitted = False
        for ev in events_since(last):
            if ev.get("session") != sid or ev.get("kind") not in _ATTACH_KINDS:
                continue
            last = ev["id"]; emitted = True
            if ev.get("kind") == "chat.done":
                yield _attach_frame(ev, terminal=True)
                return
            yield _attach_frame(ev)
        if emitted:
            last_activity = time.time()
        else:
            idle += 1
            if idle % 15 == 0:
                yield ": ping\n\n"
    yield "event: done\ndata: {}\n\n"


def feed_gen(since=0):
    q = queue.Queue()
    with _sse_lock:
        _sse_queues.add(q)
    try:
        backlog = events_since(since, limit=FEED_REPLAY_MAX)
        if backlog:
            yield "event: backlog\ndata: %s\n\n" % json.dumps(backlog, ensure_ascii=False)
        yield ": feed open\n\n"
        idle = 0
        while idle < 600:  # ~10 min max per connection
            try:
                yield q.get(timeout=1)
                idle = 0
            except queue.Empty:
                idle += 1
                yield ": ping\n\n"
    finally:
        with _sse_lock:
            _sse_queues.discard(q)


def telemetry_summary():
    out = {"gpu": None, "memory": None}
    try:
        import psutil  # optional
        vm = psutil.virtual_memory()
        out["memory"] = {"used_gb": round(vm.used / 1024**3, 1),
                         "total_gb": round(vm.total / 1024**3, 1)}
        try:
            import subprocess
            csv = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"], text=True, timeout=4).strip()
            util, temp, power = [p.strip() for p in csv.split(",")]
            out["gpu"] = {"util": util, "temp": temp, "power_w": power}
        except Exception:
            pass
    except ImportError:
        pass
    return out


def context_status(session=None, model=None):
    """Token usage vs budget for a session (UI indicator + compaction evidence).

    v1.6.3 (JAG-55): `available` tells the UI whether these numbers describe a
    real session. Without one the payload used to look like a valid measurement
    and the indicator was misleading — clients render "n/d" when it is false.

    JAG-70: `tokens_used` is now the EFFECTIVE prompt size (system prompt +
    compacted transcript + pending message) — what is really sent to the model —
    not just the stored transcript, which under-reported by ~18x because the
    system prompt (tool registry, skills, task list) dominates.
    """
    return context_usage(session, model=model)


def resolve_ctx_model(sess, model=None):
    """JAG-258: the model a turn's context is measured against.

    Explicit `model` wins; else the session's own model; else the default. NEVER
    the arbitrary model the router happens to have loaded: using that for the
    meter made a healthy 131k-window session read as 99% full while the
    auto-compaction trigger (which uses the session model) correctly saw 22% and
    never fired — the "no autocompaction" illusion.
    """
    if model:
        return model
    return (sess.get("model") if sess else None) or default_model()


def providers_catalog():
    """Every provider + model the harness can use, with live usability (JAG-71)."""
    try:
        from longrun.model import providers
    except Exception as e:  # noqa: BLE001
        return {"providers": [], "error": str(e)}
    loaded = {m["alias"] for m in router_models() if m.get("loaded")}
    cat = providers.catalog(loaded_aliases=loaded)
    cat["router_models"] = router_models()  # backward compat for the old client
    return cat


def _tool_context():
    """The tool-registry block for the chat system prompt ("" if unavailable)."""
    try:
        return CHAT_TOOL_PROMPT + "\n" + api_v02.tool_context()
    except Exception:  # noqa: BLE001 — the registry must never break chat
        return ""


def _system_prompt(sess, tool_ctx=None):
    """Single source of truth for the chat system prompt (JAG-70).

    JAG-128A: now delegates to the section registry (prompt.render_sections). It remains
    the ONLY source for the sent prompt and for the context indicator.
    """
    try:
        from longrun.memory import rules as rules_mod
        ws = rules_mod.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        ws = None
    try:
        from longrun.model import prompt as prompt_mod
        return prompt_mod.render_sections(sess, ws=ws, tool_ctx=tool_ctx)
    except Exception:  # noqa: BLE001 — the prompt must never break the chat
        return system_prompt()


def context_display(tokens_used=0, budget_tokens=0, messages=0,
                    available=True, reason="no session"):
    """JAG-107: single source of truth for the context indicator presentation.

    Both the WebUI (JS) and the Android app (Kotlin) render these ready-made
    strings and flags verbatim, so the token formatting, the percentage and the
    over/near state are computed ONLY here — never replicated client-side.

    JAG-242: these strings are USER-FACING and must be English (project rule).
    """
    def _short(n):
        n = int(n)
        return ("%.0fk" % (n / 1000.0)) if n >= 10000 else str(n)

    if not available or not budget_tokens:
        return {"available": False, "reason": reason or "no session",
                "state": "na", "short": "ctx n/d", "meter": "ctx: n/d",
                "tokens": "n/d", "budget": "n/d", "messages": "n/d",
                "detail": "context n/d", "pct": 0, "bar_pct": 0,
                "bar_hot": False}
    used = int(tokens_used or 0)
    budget = int(budget_tokens)
    pct_f = (used / budget * 100.0) if budget else 0.0
    pct_int = int(round(pct_f))
    over = used > budget
    near = pct_f >= rllm.AUTOCOMPACT_PCT
    state = "over" if over else ("near" if near else "normal")
    threshold = int(round(rllm.AUTOCOMPACT_PCT))
    detail = "used %s / %s tokens" % (_short(used), _short(budget))
    if pct_int > 0:
        detail += " · %d%%" % pct_int
    if over:
        detail += " · over threshold"
    elif near:
        detail += " · auto-compact at %d%%" % threshold
    short = "ctx %s/%s" % (_short(used), _short(budget))
    if pct_int > 0:
        short += " · %d%%" % pct_int
    return {"available": True, "reason": "", "state": state, "short": short,
            "meter": "ctx: %d/%d" % (used, budget),
            "tokens": "%d tok" % used,
            "budget": "%d tok%s" % (budget, " · OVER" if over else ""),
            "messages": "%d messages" % int(messages or 0),
            "detail": detail, "pct": pct_int,
            "bar_pct": max(0, min(100, pct_int)), "bar_hot": pct_int > 90}


_RX_URL = re.compile(r'https?://[^\s"\'<>)\]},]+')
_RX_TOOL = re.compile(r'"tool"\s*:\s*"([A-Za-z0-9_.]+)"')
_RX_PATH = re.compile(
    r'/(?:[^\s"\'<>|:*?]+/)*[^\s"\'<>|:*?]+\.'
    r'(?:py|md|json|ya?ml|sh|txt|html?|jsx?|tsx?|css|toml|cfg|ini|csv|log|lock|env)')


def context_items(session_id=None):
    """JAG-267/269: the Context-panel breakdown for ONE session (never mixes sessions).

    Derived from the session's RETAINED transcript (`sess['messages']`) — the exact
    text transported to the model — plus the workspace rule files (always in the
    system prompt). Because it is recomputed from what is STILL in context, a
    compaction drops aged-out items automatically: the panel resets by itself.
    Categories: skills / rules / web / files / other, matching the operator's UI.

    JAG-269: also returns a TOKEN attribution — how much of the window each category
    occupies (rules from the system prompt; files/web/skills/other from the tool
    observations in the transcript; harness/conversation for the rest) plus the real
    `budget_tokens` / `used_tokens` / `pct`, so the panel ties to the ctx meter.
    File, rule and skill items carry a real `path` the UI can open in the editor.
    """
    from longrun.model import context_engine
    sess = load_session(session_id) if session_id else None
    empty = {"skills": [], "rules": [], "web": [], "files": [], "other": []}
    zero = {"system": 0, "tools": 0, "rules": 0, "skills": 0, "memory": 0,
            "plan": 0, "web": 0, "files": 0, "other": 0, "harness": 0,
            "conversation": 0, "overhead": 0}
    if not sess:
        return {"session": session_id, "available": False, "categories": empty,
                "counts": {}, "total": 0, "tokens": zero, "tokens_total": 0,
                "breakdown": [], "budget_tokens": 0, "used_tokens": 0, "pct": 0.0}
    msgs = sess.get("messages", [])
    blob = "\n".join(str(m.get("content")) for m in msgs
                     if isinstance(m.get("content"), str))

    def _dedupe(items):
        out, seen = [], set()
        for it in items:
            k = it.get("url") or it.get("path") or it.get("label")
            if k and k not in seen:
                seen.add(k)
                out.append(it)
        return out

    # rules live in the SYSTEM prompt (not the transcript): real paths + their tokens
    rules_items = []
    rules_tokens = 0
    try:
        from longrun.memory import rules as _rules
        col = _rules.collect(_rules.resolve_workspace(sess))
        for scope in ("global", "project"):
            for p in (col.get(scope) or {}).get("files") or []:
                if p:
                    rules_items.append({"label": os.path.basename(p), "path": p})
        rules_tokens = context_engine.count_tokens(_rules.rules_prompt_block())
    except Exception:  # noqa: BLE001 — the panel must never break
        pass

    # skills: resolve each used skill to its real SKILL.md path so it can be opened
    try:
        from longrun.memory import skills as _skills
        _skill_path = {}
        for _s in _skills.list_skills():
            _r = _s.get("path") or ""
            _skill_path[_s.get("name")] = (_r if os.path.isabs(_r)
                                           else os.path.join(REPO, _r))
    except Exception:  # noqa: BLE001
        _skill_path = {}

    def _skill(nm):
        it = {"label": nm}
        if _skill_path.get(nm):
            it["path"] = _skill_path[nm]
        return it

    skills = [_skill(nm) for nm in
              re.findall(r'"tool"\s*:\s*"skills".{0,200}?"name"\s*:\s*"([A-Za-z0-9_.\-]{2,})"',
                         blob, re.S)]
    skills += [_skill(nm) for nm in
               re.findall(r'(?:^|\n)\s{2,}([A-Za-z0-9][A-Za-z0-9_.\-]{2,})\s+::\s+', blob)]

    web = []
    for mm in re.finditer(r'(?:^|\s)\d+\.\s+([^\n]+)\n\s*(https?://\S+)', blob):
        web.append({"label": mm.group(1).strip()[:90], "url": mm.group(2).strip().rstrip('.,)')})
    for u in _RX_URL.findall(blob):
        web.append({"label": u.rstrip('.,)')[:100], "url": u.rstrip('.,)')})

    # strip URLs first so their paths are not mistaken for local files.
    # JAG-272: keep ONLY a path that really exists (relatives resolved against the
    # session workspace / repo). A text mention like "/battery.sh" is not a file and
    # must not become a dead click in the editor (it also wasted panel space).
    try:
        from longrun.memory import rules as _rules_ws
        _ws = _rules_ws.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        _ws = None
    files, _seen_files = [], set()
    for p in _RX_PATH.findall(_RX_URL.sub(" ", blob)):
        cands = [p] if os.path.isabs(p) else [os.path.join(_ws or "", p),
                                              os.path.join(REPO, p)]
        real = next((c for c in cands if c and os.path.isfile(c)), None)
        if real and real not in _seen_files:
            _seen_files.add(real)
            files.append({"label": os.path.basename(real), "path": real})

    tool_counts = {}
    for nm in _RX_TOOL.findall(blob):
        if nm in ("fs.read", "fs.write", "fs.edit", "web", "skills"):
            continue
        tool_counts[nm] = tool_counts.get(nm, 0) + 1
    other = [{"label": k, "count": v} for k, v in
             sorted(tool_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    # JAG-269/272: token attribution that ADDS UP to the measured total — the system
    # prompt (per section) + the transcript (per tool) + an explicit 'overhead'
    # bucket for the gap vs the router's real count. sum(tokens.values()) == used.
    tok = dict(zero)
    try:
        from longrun.model import prompt as _prompt
        _secs = _prompt.section_texts(sess, ws=_ws, tool_ctx=None)
    except Exception:  # noqa: BLE001
        _secs = {}

    def _stok(*ids):
        return sum(context_engine.count_tokens(_secs.get(i, "")) for i in ids)

    tok["system"] = _stok("identity", "prompt-map", "self-summary", "rules-policy",
                          "skills-policy", "memory-policy", "capability", "task-policy")
    tok["tools"] = _stok("tools")
    tok["rules"] = _stok("rules") or rules_tokens
    tok["skills"] = _stok("skills")
    tok["memory"] = _stok("memory")
    tok["plan"] = context_engine.count_tokens(state_block(session_id=session_id))

    _obs = re.compile(r"^(?:\[harness\]\s+)?Observation for tool\s+([A-Za-z0-9_.\-]+)\s*:")
    for m in msgs:
        c = m.get("content")
        c = c if isinstance(c, str) else ("" if c is None else str(c))
        n = context_engine.count_tokens(c)
        if not n:
            continue
        mo = _obs.match(c)
        if mo:
            tool = mo.group(1)
            if tool == "skills":
                tok["skills"] += n
            elif tool == "web":
                tok["web"] += n
            elif tool in ("fs.read", "fs.write", "fs.edit"):
                tok["files"] += n
            else:
                tok["other"] += n
        elif c.startswith(HARNESS_MARK):
            tok["harness"] += n
        else:
            tok["conversation"] += n

    budget = used = 0
    pct = 0.0
    cached = 0
    cache_hit_pct = 0.0
    try:
        _u = context_usage(session_id)
        budget = context_budget(resolve_ctx_model(sess))
        used = int(_u.get("tokens_used") or 0)
        cached = int(_u.get("cached_tokens") or 0)
        cache_hit_pct = float(_u.get("cache_hit_pct") or 0.0)
        pct = round(used / budget * 100, 1) if budget else 0.0
    except Exception:  # noqa: BLE001
        pass
    _sum = sum(tok.values())
    if used > _sum:
        tok["overhead"] = used - _sum        # our estimate vs the router's real count

    # JAG-272: the ordered breakdown the UI renders (sums to the context total).
    _order = [("system", "System instructions"), ("tools", "Tool schemas"),
              ("rules", "Rules"), ("skills", "Skills"), ("memory", "Memory"),
              ("plan", "Plan / task list"), ("web", "Web / search"),
              ("files", "Files (reads)"), ("other", "Other tool output"),
              ("harness", "Harness messages"), ("conversation", "Conversation"),
              ("overhead", "Measured overhead")]
    breakdown = [{"key": k, "label": lab, "tokens": tok.get(k, 0)}
                 for k, lab in _order if tok.get(k, 0)]

    cats = {"skills": _dedupe(skills)[:40], "rules": _dedupe(rules_items)[:40],
            "web": _dedupe(web)[:40], "files": _dedupe(files)[:60], "other": other[:40]}
    return {"session": session_id, "available": True, "categories": cats,
            "counts": {k: len(v) for k, v in cats.items()},
            "total": sum(len(v) for v in cats.values()),
            "tokens": tok, "tokens_total": sum(tok.values()),
            "breakdown": breakdown,
            "budget_tokens": budget, "used_tokens": used, "pct": pct,
            "cached_tokens": cached, "cache_hit_pct": cache_hit_pct}


def context_usage(session_id=None, message=None, model=None):
    """Effective prompt tokens vs budget for the next turn (JAG-70).

    Counts what is REALLY sent: the system prompt (tool registry + skills +
    persistent task list), the compacted transcript and the pending user
    message. Returns the raw parts too, so the UI can explain the number.
    """
    from longrun.model import context_engine
    budget = context_budget(model)
    base = {"budget_tokens": budget, "session": session_id, "model": model,
            "auto_compact_pct": rllm.AUTOCOMPACT_PCT,
            "auto_compact_target_pct": rllm.AUTOCOMPACT_TARGET_PCT,
            "keep_recent": rllm.KEEP_RECENT,
            "summarizer_input_chars": rllm.SUMMARIZER_INPUT_CHARS,
            "summarizer_output_chars": rllm.SUMMARIZER_OUTPUT_CHARS}
    sess = load_session(session_id) if session_id else None
    if not sess:
        return {**base, "available": False, "messages": 0, "tokens_used": 0,
                "pct": 0.0, "over_threshold": False, "over_budget": False,
                "display": context_display(available=False,
                                           reason="session not found")}
    sysp = _system_prompt(sess)
    # JAG-276: the live task list is injected into the user turn (see assemble_turn).
    # Mirror that here so the meter counts what is REALLY sent.
    aug_message = (message or "") + "\n\n" + state_block(session_id=session_id)
    # JAG-72: mirror `chat_once` EXACTLY — same model-aware budget and the same
    # memory-retrieval block — so `compacted_tokens` is the size that WILL be sent.
    msgs, stats = context_engine.build(
        sysp, sess.get("messages", []), aug_message,
        budget_tokens=budget, retrieve_memory=True)
    compacted = int(stats.get("final_tokens") or 0)
    sysp_tokens = context_engine.count_tokens(sysp)
    transcript = sum(context_engine.count_tokens(m.get("content", ""))
                     for m in sess.get("messages", []))
    # JAG-214: the meter must show what you are CARRYING (system prompt + the full
    # stored transcript + the pending message), NOT the post-compaction build size.
    # That size can never exceed the threshold, so the auto-compact trigger could
    # never fire; and two different sessions both collapsed to the system prompt,
    # so the ctx bar looked identical when switching sessions. Prefer the router's
    # REAL prompt_tokens (JAG-86) when it is larger, so we never under-report.
    raw = sysp_tokens + transcript + context_engine.count_tokens(aug_message)
    real = _REAL_PROMPT_TOKENS.get(session_id) if session_id else None
    used = max(raw, int(real)) if real else raw
    pct = round(used / budget * 100, 1) if budget else 0.0
    # JAG-273: how much of the last prompt the provider served from its prefix
    # (KV) cache — the evidence that the static-first ordering actually pays off.
    cached = int(_REAL_CACHED_TOKENS.get(session_id) or 0) if session_id else 0
    cache_hit_pct = (round(cached / int(real) * 100, 1)
                     if (real and int(real) > 0) else 0.0)
    out = {**base, "available": True,
           "messages": len(sess.get("messages", [])),
           "tokens_used": used, "pct": pct,
           "estimate_tokens_used": raw,
           "compacted_tokens": compacted,
           "system_tokens": sysp_tokens,
           "transcript_tokens": transcript,
           "final_messages": stats.get("final_messages"),
           "over_threshold": pct >= rllm.AUTOCOMPACT_PCT,
           "over_budget": used > budget,
           "cached_tokens": cached,
           "cache_hit_pct": cache_hit_pct,
           "source": "model" if real else "estimate"}
    out["display"] = context_display(used, budget, len(sess.get("messages", [])))
    if real:
        out["real_tokens_used"] = int(real)
    return out


def prepare_session_for_turn(sess, model=None):
    """Auto-compact the stored transcript BEFORE a turn when it is over threshold.

    JAG-70: runs at the start of the request (before the JAG-51 `since` boundary
    is captured), so message indices stay valid. Extractive + local: no model
    call, so it can never stall a turn. Returns the (possibly reloaded) session.

    JAG-72: the threshold is evaluated against the SAME model-aware budget the
    turn will use, so a small-window remote model is compacted correctly.
    """
    try:
        usage = context_usage(sess["id"], model=model)
        if not usage.get("available") or not usage.get("over_threshold"):
            return sess
        # JAG-99: shrink to TARGET% (not the full budget) so the prompt lands back
        # under the trigger with headroom; the system prompt is accounted for.
        target = int(usage["budget_tokens"] * rllm.AUTOCOMPACT_TARGET_PCT / 100.0)
        stats = compact_session(sess["id"], target, origin="auto")
        publish("context.auto_compact", session=sess["id"],
                pct=usage.get("pct"), threshold=rllm.AUTOCOMPACT_PCT,
                target_pct=rllm.AUTOCOMPACT_TARGET_PCT,
                before=stats.get("input_tokens"), after=stats.get("output_tokens"),
                compacted=stats.get("compacted"), dropped=stats.get("dropped"))
        return load_session(sess["id"]) or sess
    except Exception:  # noqa: BLE001 — compaction must never break a turn
        return sess


def _summarize_with_llm(messages, model=None, meta=None):
    """JAG-103: let the MODEL do the compaction.

    Summarize the OLDER turns into one faithful, compact block (decisions, facts,
    file paths/commands, user preferences, open tasks) in the transcript's own
    language. Reuses `stream_with_fallback` (role "summarizer") — no bespoke router
    code. Returns the summary text, or None on ANY failure so the caller falls back
    to the local extractive merge (compaction must never stall a turn).

    JAG-110: when `meta` (a dict) is passed, records `meta["model"] = <alias that
    actually answered>`, so the UI can show WHICH model did the compaction.

    JAG-431r: the summarizer instruction + max_chars live in
    `config/compaction.yaml` (see `rllm.SUMMARIZER_INSTRUCTION` /
    `rllm.SUMMARIZER_MAX_CHARS`). The instruction is the AGGRESSIVE one that
    asks the model to TARGET ~10x compression and drop narration / repetition /
    partial reasoning — what the user sees as "the harness ordered the LLM to
    compact the chat's context".
    """
    lines = []
    for m in messages:
        content = m.get("content") or ""
        # JAG-238: a stored message may carry a non-string content.
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if content:
            lines.append("%s: %s" % (m.get("role", "?"), content))
    transcript = "\n".join(lines)
    if not transcript.strip():
        return None
    # JAG-431r2: separate input cap from output cap. The summarizer must SEE enough
    # of the old transcript to produce a faithful ~10x-compressed summary. The
    # previous single `max_chars` capped both at 800 chars — the model saw less
    # than one full turn and emitted a 200-token stub. Now:
    #   input_max_chars  -> how much of the OLD transcript the summarizer reads
    #   output_max_chars -> how long the resulting summary may be
    input_chars = rllm.SUMMARIZER_INPUT_CHARS
    output_chars = rllm.SUMMARIZER_OUTPUT_CHARS
    if len(transcript) > input_chars:
        head = int(input_chars * 0.7)
        tail = input_chars - head
        transcript = transcript[:head] + "\n…[middle omitted]…\n" + transcript[-tail:]
    prompt = (
        rllm.SUMMARIZER_INSTRUCTION.rstrip() + "\n\nTRANSCRIPT:\n" + transcript)
    # JAG-160: honour an explicitly pinned summarizer model (Settings -> Models)
    # before falling back to pattern-based routing for the "summarizer" role.
    if not model:
        try:
            from longrun.model import routing as _routing
            model = _routing.role_model("summarizer")
        except Exception:  # noqa: BLE001
            model = None
    try:
        # JAG-431r2: the answer cap is now `output_max_chars` (chars) tokens
        # (~output_chars/4 tokens). With ~10x compression on a 40k-char input
        # we expect ~4k chars of summary; the cap is the safety net if the model
        # writes a verbose preamble anyway.
        answer, _think, used = stream_with_fallback(
            [{"role": "user", "content": prompt}], model, "summarizer",
            lambda ch, t: None, timeout=180,
            max_tokens=max(120, output_chars // 4))
        answer = (answer or "").strip()
        if len(answer) > output_chars:
            answer = answer[:output_chars].rstrip() + "…"
        if answer and meta is not None:
            meta["model"] = used
        return answer or None
    except Exception:  # noqa: BLE001 — never let summarization break compaction
        return None


def compact_session(session, budget_tokens=None, keep_recent=None, origin=None):
    """Compact a session transcript in place under the token budget (v0.5).

    Uses the v0.3 extractive compaction; the newest messages stay verbatim,
    older ones are merged into a synthetic summary message. Returns stats.

    JAG-102: called WITHOUT `budget_tokens` this is the MANUAL "compact now"
    action. It must actually SHRINK the transcript, so it targets a fraction of
    what the transcript currently uses (`COMPACT_FORCE_RATIO`). Previously it used
    the full model budget, which made it a no-op for any session under 100% — the
    button appeared to do nothing. The single source of this policy lives here, so
    the WebUI and the app need no duplicated logic.

    JAG-110: the manual action also FORCES compaction and keeps only
    `COMPACT_MANUAL_KEEP_RECENT` recent turns, so a short session actually shrinks
    and the LLM summarizer runs (previously `keep_recent=8` left <=8-message
    sessions untouched: no model call, no GPU). The automatic path is unchanged
    (engine default 8, never forced).
    """
    from longrun.model import context_engine
    sess = load_session(session) if session else None
    if not sess:
        return {"error": "session not found: %s" % session}
    messages = sess.get("messages", [])
    current = sum(context_engine.count_tokens(m.get("content", "")) for m in messages)
    if budget_tokens:
        budget = int(budget_tokens)
        # JAG-99: the system prompt is sent uncompacted and consumes the budget,
        # so the transcript is compacted against what is really LEFT for it.
        room = max(1024, budget - context_engine.count_tokens(_system_prompt(sess)))
    else:
        # JAG-102: manual action — target a fraction of the CURRENT transcript.
        # JAG-104: the floor is small (256) so the ratio also applies to short
        # sessions; a 1024 floor made the button a near no-op under ~1k tokens.
        budget = current
        room = max(256, int(current * COMPACT_FORCE_RATIO))
    manual = not budget_tokens
    if manual and keep_recent is None:
        keep_recent = COMPACT_MANUAL_KEEP_RECENT
    # JAG-431r: the AUTO path used the engine's DEFAULT_KEEP_RECENT (8) which
    # let the OLD half of the transcript survive a compact — so a 22-msg
    # session only shrunk to 11 and the meter barely moved. The policy file
    # now drives `keep_recent` (default 4), and we honour it when the caller
    # did not pin one explicitly.
    if keep_recent is None:
        keep_recent = rllm.KEEP_RECENT
    meta = {}
    # JAG-431r2: mark the session as "running" for the duration of the summarizer
    # call so the session list shows a spinner while the (possibly different)
    # compaction model is working. The turn_begin/turn_end bracket is the same
    # mechanism the chat turn uses; we guard with try/finally so a crashed
    # summarizer never leaves the session stuck as "running".
    # If a turn is ALREADY running (user clicked compact mid-turn), do NOT
    # overwrite its token — the session already shows as busy.
    from longrun.core import events as _ev
    already_active = session in _ev._ACTIVE_CHAT
    tok = None if already_active else _ev.turn_begin(session)
    try:
        kwargs = {"summarizer": lambda old: _summarize_with_llm(old, meta=meta),
                  "force": manual}
        if keep_recent is not None:
            kwargs["keep_recent"] = keep_recent
        msgs, stats = context_engine.compact(messages, room, **kwargs)
    finally:
        if tok is not None:
            _ev.turn_end(session, tok)
    sess["messages"] = msgs
    save_session(sess)
    # JAG-104: the cached "real" prompt size belongs to the turn BEFORE the
    # compaction; keeping it made /api/context report the OLD number, so the ctx
    # meter did not move and the button looked like a no-op even though the
    # transcript had shrunk. Drop it so the meter falls back to the fresh estimate.
    _REAL_PROMPT_TOKENS.pop(session, None)
    stats.update({"session": session, "budget_tokens": budget,
                  "transcript_room": room,
                  "summarizer": meta.get("model"),
                  "messages_after": len(msgs),
                  "tokens_after": sum(context_engine.count_tokens(m.get("content", ""))
                                      for m in msgs)})
    origin = origin or ("manual" if not budget_tokens else "auto")
    stats["origin"] = origin
    # JAG-431r: an AUTO compaction MUST leave a visible mark in the transcript
    # itself — a single `system` inject at the head of the kept window so the
    # user (and the LLM on the next turn) can both see the harness shrunk the
    # chat. Without this the auto-compact felt like a silent guess; with it the
    # user sees "the harness ordered the LLM to compact the chat's context".
    # We do this only for `origin == "auto"` so the MANUAL button stays clean.
    if origin == "auto" and msgs:
        from longrun.memory import stores as _stores
        from longrun.memory import threads as _th
        from longrun.plan import taskgraph as _tg
        before_n = len(messages)
        after_n = len(msgs)
        freed = max(0, int(stats.get("input_tokens", 0)) - int(stats.get("output_tokens", 0)))
        # JAG-431r: list the compacted-away free groups and open todos so the
        # "long memory" stays visible in the chat after compaction. The ledger
        # and plan files still hold the full data; this marker is the user-facing
        # signpost that says "these groups still exist, use `chapters list` to
        # recall them". Without this the free.x labels vanished from the chat
        # view and the user thought compaction DELETED them.
        free_groups = [g for g in (_th.outline(session) or []) if g.get("kind") == "free"]
        plan = _tg.load(session) or {}
        # JAG-431r4: an OPEN task is one of the OPEN_STATUSES. The old `!= "done"`
        # test counted `cancelled`/`superseded` (both CLOSED) as still pending, so the
        # marker told the user/model that finished steps were still open.
        open_tasks = [n for n in plan.get("nodes", [])
                      if n.get("status") in _tg.OPEN_STATUSES]
        lines = []
        lines.append(
            "[harness] \U0001f5dc Auto-compacted the chat context: "
            "%d \u2192 %d messages, freed ~%d tokens (target %d%% of budget). "
            "The oldest turns were merged into the leading summary block so the "
            "next reply has room to land under the %d%% trigger."
            % (before_n, after_n, freed,
               int(round(rllm.AUTOCOMPACT_TARGET_PCT)),
               int(round(rllm.AUTOCOMPACT_PCT))))
        if free_groups:
            titled = [(g.get("id"), g.get("title") or "(untitled)") for g in free_groups]
            lines.append("Free threads preserved in the ledger (%d): %s"
                         % (len(titled),
                            ", ".join("%s=%s" % (gid, (t or "")[:30]) for gid, t in titled[:12])
                            + (" …" if len(titled) > 12 else "")))
        if open_tasks:
            lines.append("Open tasks still pending (%d): %s"
                         % (len(open_tasks),
                            ", ".join(str(n.get("id")) for n in open_tasks[:12])
                            + (" …" if len(open_tasks) > 12 else "")))
        lines.append("Use the `chapters` tool to recall any compacted thread.")
        sys_marker = "\n".join(lines)
        # JAG-431r4: the marker goes at the very head of the kept window. The engine
        # puts the synthetic summary as message 0 when it merged turns, so insert(0)
        # yields "system marker -> system summary -> kept turns"; when there is no
        # summary the marker simply leads. (Both old branches were byte-identical.)
        msgs.insert(0, {"role": "system", "content": sys_marker})
        sess["messages"] = msgs
        _stores.save_session(sess)
    publish("context.compact", **stats)
    return stats


def _runs_status():
    """JAG-431r4: active/total run counts, snapshotted under RUNS_LOCK."""
    try:
        with api_v02.RUNS_LOCK:
            vals = list(api_v02.RUNS.values())
    except Exception:  # noqa: BLE001
        vals = []
    return {"active": len([r for r in vals
                           if r.status in ("running", "paused", "aborting")]),
            "total": len(vals)}


def status_payload():
    plan, tasks = load_plan(), load_tasks()
    probe = sandbox.probe()
    return {
        "service": "longrun", "version": VERSION, "ts": round(time.time()),
        "router": ROUTER_BASE, "models": router_models(),
        "default_model": default_model(),
        "telemetry": telemetry_summary(),
        "plan": {"goal": plan.get("goal", ""), "steps": len(plan.get("steps", []))},
        "tasks": {"total": len(tasks.get("tasks", [])),
                  # JAG-431r4: .get() — a task without `status` used to raise KeyError.
                  "open": len([t for t in tasks.get("tasks", []) if t.get("status") != "done"])},
        "sandbox": {"backend": probe["backend"], "isolated": probe["isolated"],
                    "requested": probe["requested"]},
        "tools": {"registered": len(registry.catalog()),
                  "enabled": len([t for t in registry.catalog() if t["enabled"]])},
        "approvals": approvals.stats(),
        # JAG-431r4: snapshot RUNS under its lock (new_run mutates/pops it) so this
        # unguarded iteration cannot raise "dictionary changed size during iteration".
        "runs": _runs_status(),
    }


class Handler(BaseHTTPRequestHandler):
    """HTTP surface of the harness.

    Chat session contract (v0.6.2, JAG-51) — `POST /api/chat` and
    `GET|POST /api/chat/stream`:

      `session` (optional, str): id of the transcript to talk to.
        * omitted/empty  -> a NEW session is created (`uuid4().hex[:12]`) and its
                            id is returned in the JSON body (`{"session": id}`)
                            or in the SSE payloads (`chat.user`/`chat.delta`/`done`);
        * unknown id     -> a new session is created with THAT exact id (an id
                            supplied by the client is never silently replaced);
        * existing id    -> the request is appended to that session's `messages`.

      Every request persists exactly two messages on that session: one `user`
      turn and one `assistant` turn — the reply, or an explicit error turn
      (`error:true` + `error_detail`) when the router call failed or returned
      nothing. After N requests the session holds exactly 2N messages and never
      ends on an orphan `user` turn. See `ensure_reply_persisted` and README
      § "session parameter contract".
    """

    server_version = "Longrun/" + VERSION

    def _send(self, code, obj, ctype="application/json"):
        if isinstance(obj, bytes):
            body = obj
        elif isinstance(obj, str):
            body = obj.encode("utf-8")
        else:
            # JAG-233: every JSON-serializable payload (dict / list / None / int /
            # bool / float) must serialize. `None` used to fall through to the old
            # `else` branch and call `None.encode()`, an unhandled AttributeError
            # that closed the socket with NO response (live repro:
            # GET /api/subagent?id=<unknown> when the store returns None).
            body = json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
        # JAG-208 (v208): a client that disconnects mid-response must never raise
        # an unhandled BrokenPipeError/ConnectionResetError (it floods the log and
        # is indistinguishable from a real crash under abuse). Swallow it.
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # JAG-232: never let a browser re-sniff a declared type into HTML/JS.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_asset(self, rel):
        """Serve a read-only static asset under webui/assets (vendored editor
        libs, css, images). The path is resolved inside the assets root and the
        extension is whitelisted, so it can never escape the folder."""
        import posixpath
        rel = posixpath.normpath("/" + (rel or "")).lstrip("/")
        if not rel or rel.startswith(".."):
            return self._send(404, {"error": "not found"})
        root = os.path.normpath(os.path.join(WEBUI_DIR, "assets"))
        full = os.path.normpath(os.path.join(root, rel))
        if full != root and not full.startswith(root + os.sep):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(full)[1].lower()
        if ext not in ASSET_EXTS:
            return self._send(404, {"error": "not found"})
        try:
            with open(full, "rb") as f:
                data = f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return self._send(404, {"error": "not found"})
        return self._send(200, data, ctype=ASSET_CTYPES.get(ext, "application/octet-stream"))

    def _content_length(self):
        """Content-Length as int, 0 on a malformed/missing header (JAG-229)."""
        try:
            return int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return 0

    def _body(self):
        n = self._content_length()
        if not n:
            return {}
        # JAG-208 (v208): an unbounded Content-Length is a memory-DoS. Buffer at
        # most MAX_BODY_BYTES and DRAIN the rest in chunks (so the socket stays
        # framed) instead of allocating the whole payload.
        keep = min(n, MAX_BODY_BYTES)
        raw = self.rfile.read(keep)
        remaining = n - keep
        while remaining > 0:
            got = self.rfile.read(min(65536, remaining))
            if not got:
                break
            remaining -= len(got)
        if n > MAX_BODY_BYTES:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        # JAG-231: a JSON body is only useful as an OBJECT. A top-level array,
        # string, number, bool or null is valid JSON but not a dict, and every
        # caller does `body.get(...)` — that raised AttributeError, which dropped
        # the connection with no response (live repro: POST /api/chat "[1,2]").
        return parsed if isinstance(parsed, dict) else {}

    def _query(self):
        from urllib.parse import parse_qs, urlparse
        q = urlparse(self.path)
        return q.path, {k: v[0] for k, v in parse_qs(q.query).items()}

    # ---- GET ----
    def do_GET(self):
        path, qs = self._query()
        if path.startswith("/assets/"):
            return self._send_asset(path[len("/assets/"):])
        if _orbit_page(self, path):   # JAG-285: optional beta shell (public)
            return
        if path in ("/console", "/console.html", "/deck"):
            # JAG-209: the Command Deck SHELL is public (it holds no secrets); the
            # data it fetches underneath stays auth-gated. This avoids putting the
            # token in the URL just to load the page.
            try:
                with open(os.path.join(WEBUI_DIR, "console.html"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "console missing"})
        # JAG-390: PWA plumbing. Both routes are PUBLIC (non-secret): the browser
        # fetches them during install WITHOUT the API token, and the SW must live
        # at the root so its scope covers the whole app. The manifest injects the
        # caller's token into `start_url` (when given) so the installed icon opens
        # an AUTHENTICATED shell — the HTML route stays token-gated (no change).
        if path == "/manifest.webmanifest":
            import json as _json
            from urllib.parse import quote
            try:
                with open(os.path.join(WEBUI_DIR, "manifest.webmanifest"), "r", encoding="utf-8") as f:
                    man = _json.load(f)
            except (FileNotFoundError, ValueError):
                return self._send(404, {"error": "manifest missing"})
            tok = qs.get("token")
            if tok:
                man["start_url"] = "/?token=" + quote(tok)
            return self._send(200, _json.dumps(man), ctype="application/manifest+json")
        if path == "/sw.js":
            try:
                with open(os.path.join(WEBUI_DIR, "sw.js"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/javascript; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "sw missing"})
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        if api_v02.handle(self, "GET", path, qs, None):
            return
        if _orbit_handle(self, "GET", path, qs, None):   # JAG-285: optional beta API
            return

        if path == "/api/build":
            # JAG-362: a cheap fingerprint of the served UIs so a long-lived tab
            # can notice that the app was updated and reload itself — the reason
            # a freshly-fixed UI could keep looking stale in an open tab. It MUST
            # cover EVERY self-contained shell: index.html (main SPA) AND the
            # Control deck's orbit.html. Fingerprinting only index.html left an
            # open tab blind to an orbit.html change (e.g. a new resize bar), so
            # the Control iframe stayed stale until a manual reload.
            _uif = (os.path.join(WEBUI_DIR, "index.html"),
                    os.path.join(ORBIT_WEB, "orbit.html"))
            try:
                _b = "-".join("%d-%d" % (int(os.stat(p).st_mtime), os.stat(p).st_size)
                              for p in _uif)
            except OSError:
                _b = ""
            return self._send(200, {"build": _b})
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEBUI_DIR, "index.html"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "webui missing"})
        if path == "/api/self":
            return self._send(200, self_knowledge())
        if path == "/api/context":
            # JAG-258: measure against the SAME model the turn uses (explicit >
            # session model > default), never the arbitrarily-loaded router model.
            _sid = qs.get("session")
            _mdl = resolve_ctx_model(load_session(_sid) if _sid else None,
                                     qs.get("model"))
            return self._send(200, context_status(_sid, _mdl))
        if path == "/api/context/items":
            # JAG-267: Context-panel breakdown for ONE session (never mixes sessions).
            return self._send(200, context_items(qs.get("session")))
        if path == "/api/status":
            return self._send(200, status_payload())
        if path == "/api/models" or path == "/api/providers":
            return self._send(200, providers_catalog())
        if path == "/api/keys":
            return self._send(200, keys_status())
        if path == "/api/selfcheck":
            llm = qs.get("llm", "1").lower() not in ("0", "false", "no")
            return self._send(200, selfcheck_payload(
                host=getattr(self.server, "host", "127.0.0.1"),
                port=getattr(self.server, "port", 8790), llm_probe=llm))
        if path == "/api/feed":
            since = _int_arg(qs, "since", 0)
            # keep-alive is a /api/feed-only privilege (v0.6.1, JAG-48)
            return sse_response(self, feed_gen(since), keepalive=True)
        if path == "/api/plan":
            # JAG-129B/F3: read alias of the persistent task list, with
            # a backward-compatible shape {nodes,counts,goal,steps} (legacy consumers).
            sid = qs.get("session") or ""
            g = taskgraph.load(sid) if sid else None
            pub = taskgraph.public(g) or {"nodes": [], "counts": {}}
            pub["goal"] = (g or {}).get("goal") or ""
            # JAG-431r4: use CLOSED_STATUSES (done/cancelled/superseded) — a node
            # closed as `superseded` was reported as done=false (an open step).
            pub["steps"] = [{"id": n.get("id"), "title": n.get("label"),
                             "done": n.get("status") in taskgraph.CLOSED_STATUSES}
                            for n in (g or {}).get("nodes", [])]
            return self._send(200, pub)
        if path == "/api/tasks":
            tasks = load_tasks()
            # JAG-431r4: the FILTER tolerated a missing `status` (.get) but the body
            # then indexed t["status"]/t["title"] — a stored task without those keys
            # raised KeyError and dropped the connection with no reply.
            remaining = ["%s: %s" % (t.get("status", "?"), t.get("title", ""))
                         for t in tasks.get("tasks", []) if t.get("status") != "done"]
            return self._send(200, {**tasks, "remaining": remaining})
        if path == "/api/improve":
            # JAG-128B: list of self-improvement proposals for the WebUI card.
            from longrun.util import improve as improve_mod
            return self._send(200, {"proposals": improve_mod.list_proposals()})
        if path == "/api/improvement":
            # JAG-448/450: aggregated self-improvement view for the WebUI. Shows
            # what the loop ACTUALLY changed — proposals (with the diff approving
            # would append), the auto-written memory records (which lessons, in
            # which file), and a changelog filtered to MEANINGFUL events — plus
            # the methodology config so the operator can see HOW it works.
            from longrun.util import improve as improve_mod
            raw = improve_mod.list_proposals()
            # Collapse DUPLICATE proposals: the same (scope, content) was proposed
            # again and again (5x "usa sempre pytest -q", all denied) — keep the
            # newest per pair so the panel is a signal, not a flood.
            dedup, seen = [], set()
            for p in raw:
                key = (p.get("scope"), str(p.get("content") or "").strip())
                if key in seen:
                    continue
                seen.add(key)
                dedup.append(p)
            for p in dedup:
                if p.get("status") == "pending":
                    p["preview"] = improve_mod.diff_preview(p)
            mem, records, auto_kinds = {}, [], []
            try:
                from longrun.memory import memory as memory_mod
                auto_kinds = sorted(getattr(memory_mod, "AUTO_KINDS", []) or [])
                mem = memory_mod.provenance()
                for r in memory_mod.query(None, None, limit=120):
                    origin = str(r.get("source") or r.get("origin") or "").strip()
                    if origin == "user":
                        continue
                    records.append({
                        "mid": r.get("mid"),
                        "ts": r.get("ts"),
                        "kind": r.get("kind"),
                        "origin": origin or "unattributed",
                        "session": str(r.get("session") or ""),
                        "content": str(r.get("content") or ""),
                        "path": "data/memory/" + memory_mod.MEMORY_FIELDS.get(
                            r.get("kind"), "other.md"),
                    })
            except Exception:  # noqa: BLE001 — the panel must still load
                pass
            # The ledger is flooded by "turn ... wrote=[]" no-op rows; the panel
            # shows only entries that CHANGED something (or a decision).
            all_ledger = improve_mod.ledger_tail(500)
            meaningful = [e for e in all_ledger
                          if (e.get("kind") != "turn") or (e.get("wrote") or [])]
            return self._send(200, {
                "proposals": dedup,
                "proposals_total": len(raw),
                "ledger": meaningful[:120],
                "ledger_total": len(meaningful),
                "records": records,
                "memory": mem,
                "origins": list(improve_mod.ORIGINS),
                # JAG-451: the harness files the loop reads/writes live under the
                # repo root; expose an ABSOLUTE base so the panel's file links open
                # in the editor regardless of the session workspace.
                "root": improve_mod.REPO,
                "files": [
                    {"path": "data/improvement/ledger.jsonl", "kind": "audit ledger"},
                    {"path": "data/memory/agent_notes.md", "kind": "distilled lessons"},
                    {"path": "data/memory/user_memories.md", "kind": "user memory"},
                    {"path": "data/proposals", "kind": "rule/skill proposals"},
                ],
                "config": {
                    "importance_threshold": improve_mod.IMPORTANCE_THRESHOLD,
                    "ledger_max": improve_mod.LEDGER_MAX,
                    "auto_kinds": auto_kinds,
                    "origins": list(improve_mod.ORIGINS),
                },
            })
        if path == "/api/sessions":
            return self._send(200, {"sessions": list_sessions()})
        if path == "/api/sessions/new":
            # JAG-127: an explicitly requested folder must be honored — never silently
            # fall back to the default (that made a Z:/wrong path look like the
            # session was created in a folder the user never picked).
            # JAG-429: if the named folder does not exist yet, CREATE it (mkdir -p)
            # instead of refusing — naming it clearly expresses the intent to use it.
            ws = qs.get("workspace")
            if ws:
                from longrun.memory import rules as _rm
                real = _rm.check_dir(ws) or _rm.ensure_dir(ws)
                if not real:
                    return self._send(400, {"error": "cannot create folder: %s" % ws})
                ws = real
            sess = get_or_create_session(None, qs.get("title"), ws)
            publish("session.created", session=sess["id"], title=sess["title"])
            return self._send(200, sess)
        if path == "/api/history":
            sid = qs.get("session")
            sess = load_session(sid) if sid else None
            if not sess:
                return self._send(404, {"error": "session not found"})
            if ensure_job(sess):   # JAG-169: backfill a stable JX on first read
                save_session(sess)
            return self._send(200, sess)
        if path == "/api/events":
            # JAG-262: filtered event-log history for post-mortem. Answers "what
            # happened to session X" (or a kind / time window) after the fact.
            return self._send(200, {"events": query_events(
                session=qs.get("session"), kind=qs.get("kind"),
                since=qs.get("since"), until=qs.get("until"),
                limit=_int_arg(qs, "limit", 200))})
        if path == "/api/threads":
            # JAG-431j: THIS session's chat GROUPS in order (task + free) with the
            # free groups' agent-assigned titles + a content digest — the read view of
            # the durable thread ledger (written before compaction can rewrite the
            # transcript). Backfills once for a session that predates the ledger.
            sid = qs.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            from longrun.memory import threads as threads_mod
            return self._send(200, {"session": sid, "groups": threads_mod.outline(sid)})
        # JAG-426-fix: there is intentionally NO GET /api/checkpoints HERE — the
        # v0.3 route in api_v02.handle (dispatched earlier at the top of do_GET)
        # owns it and now returns the session's turn anchors under `marks`.
        if path == "/api/chat/live":
            # JAG-181: which sessions currently have a chat turn running (for the
            # WebUI to re-attach after a refresh / session switch).
            with _ACTIVE_CHAT_LOCK:
                return self._send(200, {"active": list(_ACTIVE_CHAT.keys())})
        if path == "/api/chat/attach":
            # JAG-181: resume following a still-running turn for `session`.
            sid = qs.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            since = _int_arg(qs, "since", 0)
            return sse_response(self, chat_attach_gen(sid, since))
        if path == "/api/chat/stream":
            # SSE chat. Session contract: see the Handler docstring (JAG-51).
            sid = qs.get("session")
            message = qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(sid)
            # JAG-201: prepare + append the user turn INSIDE the worker's turn lock
            # (chat_stream_gen), not here — two concurrent turns must not overwrite.
            return sse_response(self, chat_stream_gen(sess, message, qs.get("model"), None,
                                                      autonomous=qs.get("mode") == "goal"))
        # JAG-431r4: the old GET /api/agent/run block was DEAD — api_v02.handle()
        # (dispatched at the top of do_GET) already owns this path and drives the v2
        # loop (agent_stream_gen_v2). The unreachable copy called the OLD agent_run
        # loop, so any edit here silently diverged from the live behaviour.
        if path.startswith("/api/runs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "trace":
                t = get_run_trace(parts[2])
                return self._send(200, t) if t else self._send(404, {"error": "run not found"})
            if len(parts) == 4 and parts[3] == "graph":
                # v0.6: the run's task graph (linked to run_id + session_id).
                # JAG-189: a run with no graph YET is not an error — return an
                # empty graph (200) so the UI poll stops logging spurious 404s.
                g = taskgraph.load(parts[2])
                return self._send(200, taskgraph.public(g) or {
                    "run_id": parts[2], "session_id": None, "nodes": [],
                    "counts": {}, "status": "empty", "node_count": 0})
            return self._send(404, {"error": "not found"})
        if path == "/api/runs":
            return self._send(200, {"runs": runs_summary(_int_arg(qs, "limit", 50))})
        if path.startswith("/api/sessions/") and path.endswith("/graph"):
            # JAG-91: the chat graph is keyed by SESSION id (one task = one
            # session), so the WebUI plan panel reads the session graph directly
            # instead of the orphaned global plan.json.
            sess_id = path[len("/api/sessions/"):-len("/graph")].strip("/")
            g = taskgraph.load(sess_id)
            # JAG-189: no graph yet (fresh session, or a deleted one) is not an
            # error — return an empty graph (200) so the UI poll doesn't log 404s.
            return self._send(200, taskgraph.public(g) or {
                "session_id": sess_id, "run_id": sess_id, "nodes": [],
                "counts": {}, "status": "empty", "node_count": 0})
        if path == "/api/eval/tasks":
            return self._send(200, eval_list_tasks())
        if path == "/api/voice/status":
            return self._send(200, voice_status())
        if path.startswith("/api/voice/audio/"):
            fname = path.split("/")[-1]
            if not fname.startswith("tts-") or not fname.endswith(".wav") \
                    or "/" in fname or ".." in fname:
                return self._send(404, {"error": "not found"})
            fpath = os.path.join(DATA_DIR, fname)
            if not os.path.isfile(fpath):
                return self._send(404, {"error": "not found"})
            with open(fpath, "rb") as f:
                return self._send(200, f.read(), ctype="audio/wav")
        return self._send(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        path = path
        # Raw audio upload (phone records a wav and POSTs it directly)
        ctype = (self.headers.get("Content-Type") or "")
        if path == "/api/voice/stt" and ctype.startswith("audio/"):
            n = self._content_length()
            if not n:
                return self._send(400, {"error": "audio body required"})
            import tempfile
            ext = ".wav"
            # JAG-295-fix: cap the read — an unbounded Content-Length is a memory-DoS.
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(self.rfile.read(min(n, MAX_BODY_BYTES)))
                tmp = f.name
            try:
                return self._send(200, voice_stt(tmp))
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        # Raw skill zip upload (JAG-109) — before JSON parsing.
        if path == "/api/skills/install" and (
                ctype.startswith("application/zip") or ctype.startswith("application/x-zip")):
            n = self._content_length()
            if not n:
                return self._send(400, {"error": "zip body required"})
            data = self.rfile.read(min(n, MAX_BODY_BYTES))  # JAG-295-fix: bound the read
            res = api_v02.install_skill_raw(data, name=qs.get("name"),
                                            overwrite=qs.get("overwrite") == "1")
            return self._send(200 if res.get("ok") else 400, res)
        # JAG-279: raw attachment upload from the composer's native file picker.
        # A browser cannot expose a client path, so the picker sends the bytes and
        # we store them server-side; the model then gets a real absolute path.
        if path == "/api/attach" and ctype and not ctype.startswith("application/json"):
            n = self._content_length()
            if not n:
                return self._send(400, {"error": "empty body"})
            cap = int(os.environ.get("LONGRUN_ATTACH_MAX", str(32 * 1024 * 1024)))
            data = self.rfile.read(min(n, cap))
            res = api_v02.attach_save(data, name=qs.get("name"),
                                      session=qs.get("session"))
            return self._send(200 if res.get("ok") else 400, res)
        body = self._body()
        if api_v02.handle(self, "POST", path, qs, body):
            return
        if _orbit_handle(self, "POST", path, qs, body):   # JAG-285: optional beta API
            return

        if path == "/api/chat":
            # One-shot chat. Session contract: see the Handler docstring (JAG-51).
            message = body.get("message", "")
            # JAG-238: `message` becomes a persisted transcript turn. A non-string
            # (int/list/...) used to be stored verbatim and later crashed
            # /api/context (`len(int)`), so reject it at the boundary.
            if not isinstance(message, str):
                return self._send(400, {"error": "message must be a string"})
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session"))
            # JAG-201: one turn at a time per session; RELOAD + prepare INSIDE the
            # lock so a concurrent turn's save is never overwritten (lost update).
            with _turn_lock(sess["id"]):
                _fresh = load_session(sess["id"])
                if _fresh:
                    sess = _fresh
                # JAG-431q: clear a stale abort from a PREVIOUS turn here — at the very
                # start of this turn, before compaction/planner/answer model calls — so a
                # Stop pressed during any of them is honoured (see the stream path).
                clear_abort(sess["id"])
                # JAG-157: explicit model wins, else the session's own model.
                sess = prepare_session_for_turn(sess, body.get("model") or sess.get("model"))  # JAG-70: auto-compact @75%
                mark = session_mark(sess)  # JAG-51: boundary of this request
                # JAG-426: anchor this turn for rewind (same rule as the stream path).
                try:
                    from longrun.memory import rewind as _rewind
                    _rewind.mark(sess["id"], mark, label="turn %s" % mark)
                except Exception:  # noqa: BLE001
                    pass
                append_message(sess, "user", message)
                publish("chat.user", session=sess["id"], text=message)
                # JAG-325: bracket this turn in the active-turn registry too — the
                # sync path runs a REAL model turn but used to show NO running signal
                # (a phantom run). turn_end runs in the finally below, on any outcome.
                _turn_tok = turn_begin(sess["id"])
                trace = None
                try:
                    trace = RunTrace("chat", goal=message[:120], model=body.get("model"))
                    trace.span("chat.once", session=sess["id"])
                    # v0.6 first action: model-generated write_todos → per-run graph.
                    # JAG-76: key the graph by the SESSION (same key as
                    # `/api/chat/stream`), so every client that binds the panel to the
                    # session finds it. Keying it by the ephemeral trace id made the
                    # two chat paths disagree and the panel look empty.
                    # JAG-194: a finished task opens a NEW plan (keep the old nodes).
                    _ex = taskgraph.load(sess["id"])
                    if _ex and taskgraph.all_done(_ex):
                        taskgraph.begin_plan(_ex)
                    # JAG-301: this path is never a job turn — drop any job tag a
                    # previous job left on the graph so the fresh todos are not
                    # mislabelled as belonging to that job.
                    if _ex is not None:
                        _ex["jid"] = None
                        _ex["subjob"] = None
                        taskgraph.save(_ex)
                    # JAG-431q: make the PLANNER call abortable too — a Stop pressed while
                    # the planner is decoding must kill it, not wait for it to finish.
                    start_run_graph(sess["id"], message, sess["id"], routing.pick("planner"),
                                    cancel=(lambda: _is_aborted(sess["id"])))
                    reply, model = chat_once(sess, message, body.get("model"), trace=trace,
                                             autonomous=(body.get("mode") or qs.get("mode")) == "goal")
                except Exception as e:  # noqa: BLE001
                    # JAG-51: persist an explicit assistant error turn *before* the
                    # 502 — the user message must never stay orphaned.
                    ensure_reply_persisted(sess, mark, error=e, model=body.get("model"))
                    publish("chat.error", session=sess["id"], error=str(e))
                    if trace:
                        trace.finish("error")
                    return self._send(502, {"error": "router call failed: %s" % e,
                                            "session": sess["id"],
                                            "run_id": getattr(trace, "id", None),
                                            "stored_error": True})
                finally:
                    turn_end(sess["id"], _turn_tok)   # JAG-325: clear the running signal
                # JAG-431r4b: the sync path still called finish_run_graph() here, which
                # force-closes EVERY open node with fabricated "run completed" evidence —
                # exactly the JAG-63 bug the streaming path forbids (see the comment at
                # the top of chat_stream_gen). Nodes close only with real evidence.
                trace.model = model
                trace.finish("done")
                return self._send(200, {"session": sess["id"], "model": model, "run_id": trace.id,
                                        "reply": reply["content"], "reasoning": reply.get("reasoning"),
                                        "messages": len(sess["messages"]),
                                        "error": bool(reply.get("error"))})
        if path == "/api/chat/steer":
            # JAG-127b: drop a steering message into a RUNNING turn's loop (see
            # push_steer/drain_steer). No new turn, no new SSE.
            sid = body.get("session") or qs.get("session")
            text = body.get("message") or qs.get("message", "")
            if not sid or not text:
                return self._send(400, {"error": "session and message required"})
            depth = push_steer(sid, text)
            publish("chat.steer", session=sid, text=text, queued=depth)
            return self._send(200, {"ok": True, "queued": depth})
        if path == "/api/chat/abort":
            # JAG-129A: stops the in-flight turn (the agent must not continue).
            # JAG-431q: `all` aborts EVERY registered running turn — the UI's Stop is a
            # panic button, and with agents running in parallel a single-session abort
            # left the others decoding (a single-slot router then kept the GPU busy, so
            # "stop" looked like a no-op).
            if body.get("all") or qs.get("all"):
                with _ACTIVE_CHAT_LOCK:
                    sids = list(_ACTIVE_CHAT.keys())
                for _s in sids:
                    push_abort(_s)
                publish("chat.abort", session=None, all=len(sids))
                return self._send(200, {"ok": True, "aborted": sids})
            sid = body.get("session") or qs.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            push_abort(sid)
            publish("chat.abort", session=sid)
            return self._send(200, {"ok": True, "aborted": sid})
        if path == "/api/improve":
            # JAG-128B: approve/reject a self-improvement proposal.
            from longrun.util import improve as improve_mod
            pid = body.get("id") or qs.get("id", "")
            decision = body.get("decision") or qs.get("decision", "")
            res = improve_mod.decide(pid, decision)
            return self._send(200 if res.get("ok") else 400, res)
        if path == "/api/chat/stream":
            # a JSON body over query params). Same SSE contract.
            message = body.get("message") or qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session") or qs.get("session"))
            # JAG-201: prepare + append inside the worker's turn lock (see GET path).
            return sse_response(self, chat_stream_gen(
                sess, message, body.get("model") or qs.get("model"), None,
                autonomous=(body.get("mode") or qs.get("mode")) == "goal"))
        if path == "/api/model/ensure":
            alias = body.get("model") or qs.get("model") or \
                routing.pick("chat") or default_model()
            if not alias:
                return self._send(503, {"error": "no router model available"})
            res = ensure_model(alias, on_event=lambda k, **d: publish(k, **d))
            return self._send(200 if res.get("loaded") else 502, res)
        if path == "/api/plan":
            # JAG-129B/F3: the legacy "plan" IS the persistent task list, with
            # a backward-compatible shape {nodes,counts,goal,steps} (legacy consumers).
            sid = body.get("session") or qs.get("session") or ""
            g = taskgraph.load(sid) if sid else None
            pub = taskgraph.public(g) or {"nodes": [], "counts": {}}
            pub["goal"] = (g or {}).get("goal") or ""
            pub["steps"] = [{"id": n.get("id"), "title": n.get("label"),
                             "done": n.get("status") in taskgraph.CLOSED_STATUSES}
                            for n in (g or {}).get("nodes", [])]
            return self._send(200, pub)
        if path == "/api/plan/generate":
            goal = body.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            try:
                plan, answer, think, run_id = generate_plan(goal, body.get("model"))
            except Exception as e:
                return self._send(502, {"error": "planner failed: %s" % e})
            return self._send(200, {"plan": plan, "raw": answer[:800], "run_id": run_id})
        if path == "/api/plan/toggle":
            # JAG-129B: the legacy toggle acts on the persistent task list
            # (a single source of truth), no longer on plan.json.
            node_id = str(body.get("id") or qs.get("id") or "")
            _g = taskgraph.load(body.get("session") or qs.get("session") or "")
            node = taskgraph.find(_g, node_id=node_id) if _g else None
            if not node:
                return self._send(404, {"error": "step not found"})
            if node.get("status") == "done":
                taskgraph.update_node(_g, node_id, status="todo")
            else:
                taskgraph.complete_node(_g, node_id,
                                        evidence="manual toggle (legacy /api/plan/toggle)")
            return self._send(200, taskgraph.public(_g))
        if path == "/api/tasks":
            title = body.get("title", "")
            if not title:
                return self._send(400, {"error": "title required"})
            tasks = load_tasks()
            t = {"id": uuid.uuid4().hex[:6], "title": str(title)[:140],
                 "status": body.get("status", "todo"), "created": round(time.time(), 3)}
            tasks.setdefault("tasks", []).append(t)
            save_tasks(tasks)
            return self._send(200, t)
        # JAG-431r4: DEAD — api_v02.handle() (POST, dispatched at the top of do_POST)
        # already owns POST /api/agent/run and calls agent_run_v2. The unreachable
        # copy below dispatched the OLD agent_run loop.
        if path.startswith("/api/runs/") and path.endswith("/graph/nodes"):
            # v0.6: add/cancel node + incremental re-plan on a run's graph
            run_id = path[len("/api/runs/"):-len("/graph/nodes")].strip("/")
            payload, err, code = graph_post(run_id, body)
            return self._send(code, err if err else payload)
        if path.startswith("/api/sessions/") and path.endswith("/clear"):
            sid = path[len("/api/sessions/"):-len("/clear")].strip("/")
            if not _valid_sid(sid) or load_session(sid) is None:
                return self._send(404, {"error": "session not found"})
            clear_session(sid)
            return self._send(200, {"ok": True, "cleared": sid})
        if path.startswith("/api/sessions/") and path.endswith("/rename"):
            sid = path[len("/api/sessions/"):-len("/rename")].strip("/")
            sess = load_session(sid)
            if not sess:
                return self._send(404, {"error": "session not found"})
            title = str((body or {}).get("title") or "").strip()[:80]
            if not title:
                return self._send(400, {"error": "title required"})
            sess["title"] = title
            save_session(sess)
            # JAG-322: an agent IS a session — keep an org agent's NAME in lockstep
            # with its session TITLE so renaming here updates the Orbit table too.
            try:
                from longrun.agent import agents as _agents_mod
                if _agents_mod.REGISTRY.is_agent(sid):
                    _agents_mod.REGISTRY.set_name(sid, title)
            except Exception:  # noqa: BLE001 — the rename must never fail on this
                pass
            publish("session.renamed", session=sid, title=title)
            return self._send(200, {"ok": True, "id": sid, "title": title})
        if path.startswith("/api/sessions/") and path.endswith("/graph/reset"):
            # JAG-63: only the user clears the persistent task list (new task).
            sess_id = path[len("/api/sessions/"):-len("/graph/reset")].strip("/")
            return self._send(200, taskgraph.reset(sess_id))
        if path.startswith("/api/runs/") and path.endswith("/graph/reset"):
            # JAG-125: clear the CURRENT run graph from the UI (Execution panel).
            run_id = path[len("/api/runs/"):-len("/graph/reset")].strip("/")
            return self._send(200, taskgraph.reset(run_id))
        if path == "/api/context/compact":
            res = compact_session(body.get("session"), body.get("budget_tokens"), origin="manual")
            return self._send(200 if "error" not in res else 404, res)
        if path == "/api/sessions":
            sess = get_or_create_session(None, body.get("title"))
            publish("session.created", session=sess["id"], title=sess["title"])
            return self._send(200, sess)
        if path.startswith("/api/sessions/") and path.endswith("/model"):
            # JAG-157: per-session model — the session remembers its own LLM.
            sid = path[len("/api/sessions/"):-len("/model")].strip("/")
            if not sid or "/" in sid or ".." in sid:
                return self._send(404, {"error": "session not found"})
            sess = load_session(sid)
            if not sess:
                return self._send(404, {"error": "session not found"})
            ref = _set_session_model(sid, body.get("model"))
            return self._send(200, {"ok": True, "session": sid, "model": ref})
        # JAG-431r4: DEAD — api_v02.handle() (POST) already owns POST /api/checkpoints
        # (and accepts idempotency_key); this unreachable copy silently dropped it.
        if path == "/api/checkpoints/restore":
            # JAG-426: generic restore of one checkpoint (the non-turn-aware primitive).
            from longrun.memory import checkpoints as _ck
            cid = body.get("id")
            if not cid:
                return self._send(400, {"error": "id required"})
            r = _ck.rollback(cid)
            return self._send(200 if r.get("ok") else 400, r)
        if path == "/api/rewind":
            # JAG-426: restore a session to the state before user message `msg_index`.
            # JAG-431d: OR before a specific todo `node` (this node and everything after
            # it are undone — the "redo / drop from here" gesture).
            from longrun.memory import rewind as _rewind
            sid = body.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            if body.get("node"):
                r = _rewind.rewind_to_node(sid, body.get("node"), by="api")
            elif body.get("msg_index") is not None:
                r = _rewind.rewind(sid, body.get("msg_index"), by="api")
            else:
                return self._send(400, {"error": "msg_index or node required"})
            return self._send(200 if r.get("ok") else 400, r)
        if path == "/api/eval/run":
            return self._send(200, eval_run(body.get("model"), _as_int(body.get("max_steps", 6), 6),
                                            body.get("task_id"), body.get("save", True)))
        if path == "/api/voice/stt":
            return self._send(200, voice_stt(body.get("text") or body.get("path")))
        if path == "/api/voice/tts":
            return self._send(200, voice_tts(body.get("text", "")))
        return self._send(404, {"error": "not found"})

    # ---- PATCH ----
    def do_PATCH(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        body = self._body()
        if api_v02.handle(self, "PATCH", path, qs, body):
            return
        if _orbit_handle(self, "PATCH", path, qs, body):   # JAG-285: optional beta API
            return
        if path == "/api/tasks":
            tid, status = body.get("id"), body.get("status")
            tasks = load_tasks()
            for t in tasks.get("tasks", []):
                if t["id"] == tid:
                    if status in ("todo", "doing", "done"):
                        t["status"] = status
                        if status == "done":
                            t["done_ts"] = round(time.time(), 3)
                    if "title" in body:
                        t["title"] = str(body["title"])[:140]
                    save_tasks(tasks)
                    return self._send(200, t)
            return self._send(404, {"error": "task not found"})
        return self._send(404, {"error": "not found"})

    # ---- DELETE ----
    def do_DELETE(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        if api_v02.handle(self, "DELETE", path, qs, None):
            return
        if _orbit_handle(self, "DELETE", path, qs, None):   # JAG-285: optional beta API
            return
        if path.startswith("/api/sessions/"):
            sid = path[len("/api/sessions/"):]
            if not _valid_sid(sid):
                return self._send(404, {"error": "session not found"})
            fpath = os.path.join(SESSIONS_DIR, sid + ".json")
            if not os.path.isfile(fpath):
                return self._send(404, {"error": "session not found"})
            # JAG-179: cascade — the red X must also remove the session's graph,
            # run metrics and edit journal (+ backups), else they leak as orphans.
            # JAG-222: stop a running turn AND tombstone the id first, so the
            # worker's final write cannot resurrect the just-deleted session.
            push_abort(sid)
            with _deleted_lock:
                _DELETED_SESSIONS.add(sid)
                _persist_tombstones()   # JAG-315: survive a restart
            removed = _purge_session_artifacts(sid)
            _forget_session_runtime(sid)
            # JAG-431r6: deleting a session also drops its HIDDEN knowledge
            # notebook (the per-session KB scope) so it cannot leak as orphans
            # in the single global KB.
            try:
                from longrun.memory import knowledge as _kb
                _kb.purge_session(sid)
            except Exception:  # noqa: BLE001 — KB cleanup must not break the delete
                pass
            # JAG-314: an agent IS a session — deleting the session must also
            # release the agent designation (and scrub its jobs/routines), else a
            # later job/routine resurrects it via get_or_create_session.
            try:
                from longrun.agent import agents as agents_mod
                rel = agents_mod.REGISTRY.release(sid)
                if rel.get("released"):
                    removed.append("agent:" + str(rel["released"]))
            except Exception:  # noqa: BLE001
                pass
            publish("session.deleted", session=sid, removed=removed)
            return self._send(200, {"ok": True, "deleted": sid, "removed": removed})
        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def _lan_ipv4s():
    """Best-effort non-loopback IPv4 addresses of this host (for phone access)."""
    ips = []
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # UDP connect picks the default-route IP, no packet sent
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                ips.append(ip)
        finally:
            s.close()
    except Exception:  # noqa: BLE001 — LAN detection is best-effort
        pass
    return ips


def _start_tls(args):
    """JAG-416: serve the SAME handler over HTTPS on a second port.

    Why: the browser only allows the microphone (Web Speech API / getUserMedia) on a
    SECURE CONTEXT (https or localhost). On a plain-HTTP LAN origin voice input can
    never work — so the server also listens over TLS, making voice "just work" for
    anyone who opens the https URL (they accept the self-signed cert once). Fully
    best-effort: any failure disables HTTPS and prints the reason.
    """
    cert = args.tls_cert or os.path.join(DATA_DIR, "tls", "cert.pem")
    key = args.tls_key or os.path.join(DATA_DIR, "tls", "key.pem")
    port = int(args.tls_port or (args.port + 1))
    try:
        if not (os.path.isfile(cert) and os.path.isfile(key)):
            os.makedirs(os.path.dirname(cert), exist_ok=True)
            sans = ",".join(["DNS:localhost", "IP:127.0.0.1"] +
                            ["IP:%s" % ip for ip in _lan_ipv4s()])
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", key, "-out", cert, "-days", "3650", "-subj", "/CN=longrun",
                 "-addext", "subjectAltName=" + sans],
                check=True, capture_output=True)
        srv = ThreadingHTTPServer((args.host, port), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        srv.host, srv.port = args.host, port
    except Exception as e:  # noqa: BLE001 — voice stays disabled, nothing else breaks
        print("Longrun: HTTPS not started (%s: %s) — voice input stays blocked on plain HTTP."
              % (type(e).__name__, e), flush=True)
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Longrun: HTTPS (secure context — voice-ready) on https://%s:%d" % (args.host, port), flush=True)
    if args.host == "0.0.0.0":
        from urllib.parse import quote
        tok = ("?token=" + quote(args.token)) if args.token else ""
        for ip in _lan_ipv4s():
            print("Voice-ready (accept the self-signed cert once): https://%s:%d/%s" % (ip, port, tok),
                  flush=True)
    return srv


def main():
    global AUTH_TOKEN
    ap = argparse.ArgumentParser(description="Longrun harness server")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host (0.0.0.0 to expose to Tailscale/mobile)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--token", default=None, help="require Authorization: Bearer <token>")
    # JAG-416: an HTTPS listener makes the origin a SECURE CONTEXT so voice input
    # works; on by default (set LONGRUN_TLS=0 to disable).
    ap.add_argument("--tls", action="store_true", help="also serve HTTPS (secure context → voice)")
    ap.add_argument("--tls-cert", default=None, help="TLS cert path (self-signed generated if missing)")
    ap.add_argument("--tls-key", default=None, help="TLS key path")
    ap.add_argument("--tls-port", type=int, default=None, help="HTTPS port (default: --port + 1)")
    args = ap.parse_args()
    AUTH_TOKEN = args.token
    _sf_server.AUTH_TOKEN = args.token  # JAG-379: keep the re-exported copy in sync
    _ensure_dirs()
    try:
        from longrun.model import providers
        providers.load_env()
    except Exception:  # noqa: BLE001 — provider metadata is optional
        pass
    # JAG-123: CLAIM THE PORT FIRST, before any side effect. A second instance
    # (systemd auto-restart after a manual/orphan server already owns :8790) used
    # to run _ensure_dirs + providers.warm + backfill_session_workspaces and
    # publish("service.start") — writing to events.db and rewriting every session
    # every RestartSec — and ONLY THEN failed to bind. That crash looped 15k+
    # times, flooding the event feed and contending on SQLite with the live
    # server (chat "si blocca"). Failing before any write makes a duplicate start
    # a silent, harmless no-op.
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        print("Longrun: cannot bind %s:%d (%s) — another instance is already "
              "serving. Exiting without side effects." % (args.host, args.port, e))
        raise SystemExit(3)
    server.host, server.port = args.host, args.port
    try:
        from longrun.model import providers
        providers.warm()  # JAG-72: fetch remote model windows off the request path
    except Exception:  # noqa: BLE001 — provider metadata is optional
        pass
    backfill_session_workspaces()  # JAG-117: every session gets a folder
    backfill_jobs()                # JAG-169: every session gets a stable JX id
    reconcile_agent_models()       # JAG-309: agent model == its session's model
    reconcile_orphan_turns()       # JAG-262: close turns killed by a hard restart
    publish("service.start", host=args.host, port=args.port, router=ROUTER_BASE)
    try:
        from longrun.orchestrate import jobs as _jobs
        _jobs.JOBS.reconcile()  # JAG-288: close jobs killed by a hard restart
    except Exception:  # noqa: BLE001 — job reconcile is best-effort
        pass
    try:
        _start_event_pruning()  # JAG-300: keep the durable replay log bounded
    except Exception:  # noqa: BLE001 — pruning is best-effort
        pass
    try:
        from longrun.orchestrate import routines
        routines.start_scheduler()  # JAG-287 D: agents wake on a cadence
    except Exception:  # noqa: BLE001 — the heartbeat scheduler is optional
        pass
    print("Longrun v%s on http://%s:%d  (router: %s)" % (
        VERSION, args.host, args.port, ROUTER_BASE), flush=True)
    if args.host == "0.0.0.0":
        from urllib.parse import quote
        tok = ("?token=" + quote(args.token)) if args.token else ""
        for ip in _lan_ipv4s():
            print("Open on your phone: http://%s:%d/%s" % (ip, args.port, tok),
                  flush=True)
    # JAG-416: optionally bring up HTTPS (secure context → voice input works).
    if args.tls or os.environ.get("LONGRUN_TLS", "1") != "0":
        _start_tls(args)
    server.serve_forever()

