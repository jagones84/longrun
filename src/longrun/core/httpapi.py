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
from longrun.core.server import (ASSET_CTYPES, ASSET_EXTS, AUTOCOMPACT_PCT, AUTOCOMPACT_TARGET_PCT,
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
                     chat_once, clear_session, context_budget, default_model,
                     ensure_job, ensure_model, ensure_reply_persisted, eval_list_tasks,
                     eval_run, events_since, feed_seq, finish_run_graph, generate_plan,
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


def _should_autoplan(jid, graph, autonomous, message):
    """JAG-308: may the end-of-turn fallback planner run for this turn?

    The JAG-76 fallback exists so the interactive 🧩 GRAPH panel is never empty:
    when the model answers in prose (no `write_todos`) we still show a plan. But
    it creates todos NOBODY executes — and the harness, by design (JAG-173),
    never auto-closes a step, so on a headless job turn (no HITL gate, JAG-295)
    they dangled as OPEN on a job already `done`. A JOB turn (`jid` set) already
    owns its graph — the coordinator decomposes and the workers author/close
    their own steps — so it must NEVER be auto-planned.
    """
    if jid is not None:                      # a job turn: the graph is the job's
        return False
    if graph is not None and taskgraph.plan_nodes(graph):
        return False                         # the current plan already has steps
    return bool(autonomous or len(str(message).split()) >= 4)


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
    # JAG-426: anchor this turn so it can be rewound. `since` is the index of the
    # user message in the transcript, so the snapshot captures the state the turn
    # STARTED from; idempotent, and it can never break the turn.
    try:
        from longrun.memory import rewind as _rewind
        _rewind.mark(sess["id"], since, label="turn %s" % since)
    except Exception:  # noqa: BLE001
        pass
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
                # JAG-76: guarantee a plan. The model normally authors the list
                # itself via `write_todos`; when it answers with prose only (which
                # left the app's 🧩 GRAPH panel empty — "there is no plan"), we
                # generate the graph from the request so the panel is never empty.
                # Skipped for one-liners (greetings/chit-chat) where a task list
                # would be noise.
                _g = taskgraph.load(gkey)
                # JAG-197: never spawn a planner model call for an ABORTED turn —
                # it ignores Stop and pins the session in _ACTIVE_CHAT (the turn
                # looked hung). The planner call is also made abortable.
                # JAG-216: run the fallback planner in a BACKGROUND daemon thread
                # and emit its nodes on the FEED (`publish`), NOT the turn's SSE.
                # Before this the planner call sat between the reply and `done`, so
                # the session stayed "running" (and the plan/ctx panels only
                # refreshed at `done`) for the whole planner round-trip — measured
                # ~20s of tail after a 1.4s reply. The WebUI renders graph events
                # from the feed too (index.html /api/feed handler -> applyGraphEvent
                # with a session guard), so nothing is lost. The turn now closes as
                # soon as the reply is done; the graph fills in a moment later.
                # JAG-308: never auto-plan a JOB turn (see `_should_autoplan`) —
                # its graph belongs to the job, not to a fallback UI planner.
                if _should_autoplan(jid, _g, autonomous, message) and \
                        not _is_aborted(sess["id"]):
                    threading.Thread(
                        target=start_run_graph,
                        args=(gkey, message, gkey, routing.pick("planner")),
                        kwargs={"on_event": publish,
                                "cancel": (lambda: _is_aborted(sess["id"]))},
                        daemon=True).start()
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


_ATTACH_KINDS = ("chat.run", "chat.delta", "chat.done")


def _attach_frame(ev, terminal=False):
    kind = "done" if (terminal or ev.get("kind") == "chat.done") else ev.get("kind")
    return "id: %d\nevent: %s\ndata: %s\n\n" % (
        ev["id"], kind, json.dumps(ev, ensure_ascii=False))


def chat_attach_gen(sid, since=0):
    """JAG-181: re-attach a refreshed / reopened WebUI to a chat turn that is still
    RUNNING for `sid`.

    A page refresh or a session switch loses the browser's SSE channel but never
    stops the server-side worker. This generator replays the turn's streaming
    events (chat.delta text) from the durable event log and then tails new ones
    until the turn ends, so the reload resumes exactly where it left off instead of
    looking "interrupted". Only the streaming/render events are replayed: tool
    cards, todo tree and injects are already rebuilt by loadHistory, so replaying
    them would duplicate.
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
    while True:
        with _ACTIVE_CHAT_LOCK:
            if sid not in _ACTIVE_CHAT:
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
        if not emitted:
            idle += 1
            if idle % 15 == 0:
                yield ": ping\n\n"
    yield "event: done\ndata: {}\n\n"


def agent_stream_gen(goal, max_steps, model, workspace=None):
    q = queue.Queue()
    # JAG-111: create the run HERE so the generator can abort it when the client
    # disconnects; pass it to agent_run so /api/agent/control can stop it too.
    st = api_v02.new_run(goal, model, max_steps)

    def on_event(kind, **d):
        q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
        if not kind.startswith("agent.think"):
            publish(kind, **d)

    def worker():
        try:
            agent_run(goal, max_steps, model, on_event, run_state=st, workspace=workspace)
        except Exception as e:  # noqa: BLE001
            q.put("event: error\ndata: %s\n\n" % json.dumps({"error": str(e)}))
        finally:
            q.put(None)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        yield from sse_pump(q, t, open_comment=": agent stream open\n\n",
                            idle_timeout=CHAT_STREAM_IDLE or None)
    finally:
        # client gone (socket closed): stop the loop instead of leaving an orphan
        # worker streaming forever.
        if t.is_alive():
            st.abort = True


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
    near = pct_f >= AUTOCOMPACT_PCT
    state = "over" if over else ("near" if near else "normal")
    threshold = int(round(AUTOCOMPACT_PCT))
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
            "auto_compact_pct": AUTOCOMPACT_PCT,
            "auto_compact_target_pct": AUTOCOMPACT_TARGET_PCT}
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
           "over_threshold": pct >= AUTOCOMPACT_PCT,
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
        target = int(usage["budget_tokens"] * AUTOCOMPACT_TARGET_PCT / 100.0)
        stats = compact_session(sess["id"], target, origin="auto")
        publish("context.auto_compact", session=sess["id"],
                pct=usage.get("pct"), threshold=AUTOCOMPACT_PCT,
                target_pct=AUTOCOMPACT_TARGET_PCT,
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
    # JAG-214: never hand the summarizer more than it can hold. A session may be
    # dominated by one huge paste; keep the head + tail so the call always fits.
    if len(transcript) > SUMMARIZER_MAX_CHARS:
        head = int(SUMMARIZER_MAX_CHARS * 0.7)
        tail = SUMMARIZER_MAX_CHARS - head
        transcript = transcript[:head] + "\n…[middle omitted]…\n" + transcript[-tail:]
    prompt = (
        "You are compacting the OLDER turns of an ongoing chat so the assistant can "
        "keep working with less context. Write a faithful, compact summary IN THE "
        "SAME LANGUAGE as the transcript. Preserve: decisions made, concrete facts, "
        "file paths and commands, user preferences, and any OPEN tasks or questions. "
        "Drop chit-chat and repetition. Reply with the summary text ONLY (no preamble), "
        "at most ~200 words.\n\nTRANSCRIPT:\n" + transcript)
    # JAG-160: honour an explicitly pinned summarizer model (Settings -> Models)
    # before falling back to pattern-based routing for the "summarizer" role.
    if not model:
        try:
            from longrun.model import routing as _routing
            model = _routing.role_model("summarizer")
        except Exception:  # noqa: BLE001
            model = None
    try:
        answer, _think, used = stream_with_fallback(
            [{"role": "user", "content": prompt}], model, "summarizer",
            lambda ch, t: None, timeout=180)
        answer = (answer or "").strip()
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
    meta = {}
    kwargs = {"summarizer": lambda old: _summarize_with_llm(old, meta=meta),
              "force": manual}
    if keep_recent is not None:
        kwargs["keep_recent"] = keep_recent
    msgs, stats = context_engine.compact(messages, room, **kwargs)
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
    publish("context.compact", **stats)
    return stats


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
                  "open": len([t for t in tasks.get("tasks", []) if t["status"] != "done"])},
        "sandbox": {"backend": probe["backend"], "isolated": probe["isolated"],
                    "requested": probe["requested"]},
        "tools": {"registered": len(registry.catalog()),
                  "enabled": len([t for t in registry.catalog() if t["enabled"]])},
        "approvals": approvals.stats(),
        "runs": {"active": len([r for r in api_v02.RUNS.values()
                                if r.status in ("running", "paused", "aborting")]),
                 "total": len(api_v02.RUNS)},
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
            pub["steps"] = [{"id": n.get("id"), "title": n.get("label"),
                             "done": n.get("status") in ("done", "cancelled")}
                            for n in (g or {}).get("nodes", [])]
            return self._send(200, pub)
        if path == "/api/tasks":
            tasks = load_tasks()
            remaining = ["%s: %s" % (t["status"], t["title"]) for t in tasks.get("tasks", [])
                         if t.get("status") != "done"]
            return self._send(200, {**tasks, "remaining": remaining})
        if path == "/api/improve":
            # JAG-128B: list of self-improvement proposals for the WebUI card.
            from longrun.util import improve as improve_mod
            return self._send(200, {"proposals": improve_mod.list_proposals()})
        if path == "/api/sessions":
            return self._send(200, {"sessions": list_sessions()})
        if path == "/api/sessions/new":
            # JAG-127: an explicitly requested folder must exist — never silently
            # fall back to the default (that made a Z:/wrong path look like the
            # session was created in a folder the user never picked).
            ws = qs.get("workspace")
            if ws:
                from longrun.memory import rules as _rm
                if not _rm.check_dir(ws):
                    return self._send(400, {"error": "no such folder: %s" % ws})
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
        if path == "/api/agent/run":
            goal = qs.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            _ws_sess = load_session(qs.get("session")) if qs.get("session") else None
            from longrun.memory import rules as _rules_mod
            _ws = _rules_mod.resolve_workspace(_ws_sess)
            return sse_response(self, agent_stream_gen(goal, _int_arg(qs, "max_steps", 6),
                                                       qs.get("model"), workspace=_ws))
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
                # JAG-157: explicit model wins, else the session's own model.
                sess = prepare_session_for_turn(sess, body.get("model") or sess.get("model"))  # JAG-70: auto-compact @75%
                mark = session_mark(sess)  # JAG-51: boundary of this request
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
                    start_run_graph(sess["id"], message, sess["id"], routing.pick("planner"))
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
                finish_run_graph(sess["id"], sess["id"], message)
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
                             "done": n.get("status") in ("done", "cancelled")}
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
        if path == "/api/agent/run":
            goal = body.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            result = agent_run(goal, _as_int(body.get("max_steps", 6), 6), body.get("model"))
            return self._send(200, result)
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

