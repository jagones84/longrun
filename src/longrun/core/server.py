#!/usr/bin/env python3
"""Longrun — frontier-style agent harness server for the DGX Spark.

Wraps the local llama.cpp router (127.0.0.1:8080) with:
  - streaming chat with Chain-of-Thought timeline
  - model-generated PLAN (strategy steps)
  - TASKS board with remaining bullets
  - a safe agent loop (thought -> action -> observation; no shell)
  - an SSE loopback feed (/api/feed) for WebUI + mobile live views
  - a mobile command API (bind 0.0.0.0 to reach the phone over Tailscale)

Stdlib only. Data lives in ./data (gitignored). Optional bearer token auth.
"""

import argparse
import json
import os
import queue
import re
import select
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from longrun.core import api_v02  # v0.2 surface: tool registry, approvals, HITL control, MCP
from longrun.tools import approvals
from longrun.util import osutil
from longrun.model import otel_tracing  # v0.4: OpenTelemetry spans + fallback local spans
from longrun.tools import registry
from longrun.model import routing  # v0.3: role-based model selection + fallback chain
from longrun.tools import sandbox
from longrun.plan import taskgraph  # v0.6: per-run LLM task graph (write_todos, live, interactive)

# JAG-370: mechanical split of this module. The optional beta hooks, the SSE
# plumbing / think coalescer, and the prose-tolerant text helpers now live in
# bridge / sse / textkit and are re-exported here, so every existing reference
# (`server.sse_pump`, `server.extract_json`, `server.ThinkCoalescer`, ...) keeps
# working unchanged.
from longrun.agent.bridge import _orbit_handle, _orbit_page
from longrun.core.events import (DB_PATH, EVENTS_KEEP, MAX_FEED_EVENTS, PRUNE_BATCH,
                     PRUNE_INTERVAL_S, _ACTIVE_CHAT, _ACTIVE_CHAT_LOCK, _TURN_LOCKS,
                     _TURN_LOCKS_GUARD, _db_lock, _feed, _sse_lock, _sse_queues, db,
                     events_since, feed_seq, prune_events, publish, query_events,
                     _start_event_pruning, _turn_lock, turn_begin, turn_end)
from longrun.model.keys import ENV_FILE, KNOWN_ENV_KEYS, keys_status, reveal_key, set_key
from longrun.core.sse import (CHAT_THINK_FLUSH_S, CHAT_THINK_LIVE_CAP, ThinkCoalescer,
                  sse_response, sse_pump)
from longrun.util.steering import (ABORT_INBOX, STEER_INBOX, _abort_lock, _is_aborted,
                       _steer_lock, clear_abort, drain_steer, has_steer, push_abort,
                       push_steer)
from longrun.util.textkit import extract_json, strip_think
from longrun.util.tracing import (MODEL_PRICES, RunTrace, _REAL_CACHED_TOKENS, _REAL_PROMPT_TOKENS,
                      count_tokens, get_run_trace, runs_summary)
from longrun.util.voice import (SHERPA_TTS_MODEL, WHISPER_BIN, WHISPER_MODEL, voice_status,
                    voice_stt, voice_tts)

from longrun.model.rllm import (ROUTER_BASE, ROUTER_RETRIES, ROUTER_BACKOFF,
                   ROUTER_BACKOFF_MAX, MODEL_LOAD_TIMEOUT, ROUTER_IDLE_TIMEOUT,
                   router_models, CONTEXT_RESERVE, AUTOCOMPACT_PCT,
                   AUTOCOMPACT_TARGET_PCT, COMPACT_FORCE_RATIO,
                   COMPACT_MANUAL_KEEP_RECENT, SUMMARIZER_MAX_CHARS,
                   model_context_window, context_budget, _local_ref, default_model,
                   model_loaded, router_ping, _router_load, _fire, ensure_model,
                   measure_llm_latency, selfcheck_payload, _open_with_retry,
                   _set_read_idle, _chat_endpoint, MAX_TOKENS, REPEAT_GUARD,
                   _REPEAT_MIN_PERIOD, _REPEAT_MAX_PERIOD, _REPEAT_LIMIT,
                   _RepetitionGuard, _reasoning_effort, _completion_body,
                   CONNECT_TIMEOUT, _reachable, _router_stream)
from longrun.util.evals import (EVAL_DIR, GOLD_PATH, EVAL_RESULTS_DIR, eval_list_tasks,
                    _is_subsequence, eval_score, eval_run)
from longrun.util.paths import (DATA_DIR, SESSIONS_DIR, WEBUI_DIR, _JOBSEQ_FILE,
                    REPO_ROOT as REPO)
from longrun.memory.stores import (_ensure_dirs, _read_json, _write_json, _store_path, load_plan,
                     save_plan, load_tasks, save_tasks, _SID_RE, _valid_sid,
                     load_session, _DELETED_SESSIONS, _deleted_lock, _TOMBSTONE_FILE,
                     _load_tombstones, _persist_tombstones, save_session,
                     _purge_session_artifacts, _forget_session_runtime, clear_session,
                     _rel_time, list_sessions, _max_job, _read_seq, _write_seq,
                     ensure_job, ensure_session_workspace, backfill_session_workspaces,
                     backfill_jobs, _set_session_model, reconcile_agent_models,
                     _remember_workspace, _chat_workspace, get_or_create_session,
                     append_message, persist_tool_card, persist_inject, TOOL_EVENT_MAX,
                     _trunc, _tool_event, ERROR_PREFIX, session_mark, has_reply_since,
                     ensure_reply_persisted, reconcile_orphan_turns)

# The optional "Bridge" (former "Orbit") beta hooks moved to `bridge.py` (JAG-370).

# Static assets for the WebUI (vendored editor libs, css, images). Served
# read-only from webui/assets with an extension whitelist so a crafted path can
# never reach outside the assets root.
ASSET_EXTS = {".js", ".mjs", ".css", ".map", ".json", ".svg", ".png", ".jpg",
              ".jpeg", ".webp", ".gif", ".ico", ".woff2"}
ASSET_CTYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".map": "application/json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

# JAG-377: the router config (ROUTER_BASE / ROUTER_RETRIES / ROUTER_BACKOFF /
# ROUTER_BACKOFF_MAX / MODEL_LOAD_TIMEOUT / ROUTER_IDLE_TIMEOUT) moved to `rllm.py`
# (imported above, so `server.ROUTER_BASE` and friends still resolve).
# JAG-372: MAX_FEED_EVENTS moved to events.py (imported above).
# JAG-208 (v208): cap the request body we buffer (memory-DoS guard). Larger
# bodies are drained, not allocated; the endpoint then sees an empty body.
MAX_BODY_BYTES = int(os.environ.get("LONGRUN_MAX_BODY", str(8 * 1024 * 1024)))
# JAG-295-fix: /api/feed must never replay the whole durable log (it can hold
# millions of rows). A live tail only needs the newest window.
FEED_REPLAY_MAX = int(os.environ.get("LONGRUN_FEED_REPLAY", "300"))
STORE_LOCK = threading.RLock()

VERSION = "1.0.0"
# JAG-377: ROUTER_RETRIES / ROUTER_BACKOFF / ROUTER_BACKOFF_MAX / MODEL_LOAD_TIMEOUT
# moved to `rllm.py` (imported above).

# SSE termination (v0.6.1, JAG-48). A chat stream must end — and the socket must
# close — shortly after its terminal `done`; it must never outlive it.
#   ROUTER_IDLE_TIMEOUT: max silence tolerated from the router mid-stream (now in
#                        `rllm.py`, imported above).
#   CHAT_STREAM_IDLE:    max silence on a chat SSE stream before the server
#                        finishes the stream itself (error + done) and closes.
CHAT_STREAM_IDLE = float(os.environ.get("LONGRUN_CHAT_STREAM_IDLE", 900.0))
# JAG-370: the think-coalescing constants + ThinkCoalescer moved to `sse.py`
# (imported above, so `server.CHAT_THINK_FLUSH_S` and friends still resolve).

# JAG-372: the durable event log (sqlite) moved to `events.py` (imported above).


# JAG-372: the live SSE feed, publish(), turn locks and event queries moved to
# `events.py` (imported above).


# JAG-376: moved to `stores.py` (imported above).


# JAG-376: moved to `rllm.py` (imported above).


# ----------------------------------------------------- tracing / cost ----


def stream_with_fallback(messages, model, role, on_delta, timeout=300, usage=None,
                         guard=None, cancel=None):
    """v0.3 multi-model routing with fallback.

    Tries `model` (or the role-selected one) first; on a router failure walks
    the role's fallback chain (which always terminates on the DeepSeek alias
    when it exists in the roster) before giving up. Returns (answer, think,
    model_used).
    """
    primary = model or routing.pick(role)
    if not primary:
        primary = default_model()
    chain = [primary] + [a for a in routing.fallback_chain(role) if a != primary]
    # JAG-403: a non-thinking model may reject `reasoning_effort`. When thinking
    # effort is ON, retry the SAME model once with the field OMITTED before
    # failing over — a model without reasoning must never crash the turn.
    reasoning_on = bool(_reasoning_effort())
    attempts = (False, True) if reasoning_on else (False,)
    last_err = None
    for i, alias in enumerate(chain):
        for no_reasoning in attempts:
            try:
                if usage is not None:
                    usage.clear()  # a failed attempt must not leave stale numbers
                answer, think = _router_stream(messages, alias, on_delta, timeout,
                                               usage, guard, cancel,
                                               no_reasoning=no_reasoning)
                if i > 0:
                    publish("model.fallback", role=role, from_model=chain[0],
                            to_model=alias)
                return answer, think, alias
            except Exception as e:  # noqa: BLE001
                last_err = e
                if no_reasoning:
                    break  # already retried without the field
        publish("model.failover", role=role, failed=alias,
                next_model=chain[i + 1] if i + 1 < len(chain) else None)
    raise last_err if last_err else RuntimeError("no router model available")


# JAG-374: RunTrace + token/cost accounting moved to `tracing.py` (imported above).


# JAG-380: the agent core (prompts, chat loop, multi-step agent run) moved to
# `agent.py`. Imported at the BOTTOM: the agent core reads `VERSION` /
# `stream_with_fallback` / the prompt+context helpers through the `server` module
# object, so the module must be fully populated first. Re-exported here so
# `server.agent_run`, `server.chat_once`, `server.system_prompt`, ... still resolve
# for `httpapi` (imported just below) and every other caller.
from longrun.agent.agent import (SYSTEM_PROMPT, PMCP_PROMPT, system_prompt, RULES_POLICY,
                    rules_context, PLANNER_PROMPT, MEMORY_POLICY, CHAT_APPROVAL_WAIT,
                    SKILLS_POLICY, self_summary, self_knowledge, context_summary,
                    state_block, start_run_graph, finish_run_graph, graph_post,
                    CHAT_TOOL_MAX_STEPS, CHAT_TOOL_MAX_ITERS, PLAN_ONLY_MAX_STEPS,
                    PLAN_ONLY_TOOLS, _LAST_SYS_INJECT, CHAT_TOOL_OBS_LIMIT,
                    SUBAGENT_WAIT, CHAT_OBS_FULL, CHAT_TOOL_PROMPT, TASK_POLICY,
                    HARNESS_MARK, harness_wrap, _pivot_decide, _pivot_sync_text,
                    _next_stale, _looks_like_json_action, _JSON_ACTION_KEYS,
                    _JSON_TOOL_ARG_KEYS, _looks_like_action_dict, _PROMISE_RE,
                    _looks_like_promise, _skill_hints, _stuck_note, _repeat_block_note,
                    _plan_only_refusal, _open_plan_steps, _open_todo_brief,
                    _nudge_open_todos, _OFFLOAD_SEQ, _OFFLOAD_HEAD, _OFFLOAD_TAIL,
                    _offload_observation, _chat_tool_call, _apply_chat_todos,
                    _resolve_graph_node, _apply_chat_todo_updates, _apply_chat_replan,
                    _apply_chat_subagent, _REFLECT_LATEST, _REFLECT_COOLDOWN,
                    maybe_reflect, _apply_skill_slash, assemble_turn,
                    _HARNESS_ACTION_NAMES, _TERMINAL_ACTIONS, _term_action,
                    _normalize_action, _dsml_action, _looks_like_dsml,
                    _extract_action, _harness_start_note, chat_once, generate_plan,
                    AGENT_ACTIONS, AGENT_PROMPT, apply_agent_action, _mirror_graph,
                    _agent_history, agent_run)


# JAG-376: moved to `evals.py` (imported above).


# JAG-373: voice (whisper STT / sherpa-onnx TTS) moved to `voice.py` (imported above).


# JAG-379: the HTTP/JSON API, the SSE routes and `main()` moved to `httpapi.py`.
# Imported at the BOTTOM so `httpapi` can `from .server import (...)` against a
# fully-populated module (no import cycle). The names are re-exported here, so
# `server.Handler`, `server.main`, `server._tool_context`, ... still resolve.
from longrun.core.httpapi import (AUTH_TOKEN, check_auth, _as_int, _int_arg, _should_autoplan,
                      chat_stream_gen, _ATTACH_KINDS, _attach_frame, chat_attach_gen,
                      agent_stream_gen, feed_gen, telemetry_summary, context_status,
                      resolve_ctx_model, providers_catalog, _tool_context,
                      _system_prompt, context_display, _RX_URL, _RX_TOOL, _RX_PATH,
                      context_items, context_usage, prepare_session_for_turn,
                      _summarize_with_llm, compact_session, status_payload, Handler,
                      main)


if __name__ == "__main__":
    main()







