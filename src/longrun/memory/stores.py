"""Session / plan / task persistence + the per-session runtime clean-up.

Owns the on-disk session transcripts (data/sessions/*.json), the plan + task
stores, the job / workspace bookkeeping and the append/persist helpers the chat
loop calls. Extracted from ``server.py`` (JAG-376). Stdlib + sibling modules only.
"""
import json
import os
import re
import threading
import time
import uuid

from longrun.memory import threads as threads_mod
from longrun.plan import taskgraph
from longrun.core.events import (_ACTIVE_CHAT, _ACTIVE_CHAT_LOCK, _TURN_LOCKS,
                     _TURN_LOCKS_GUARD, publish)
from longrun.util.fswrite import read_json, write_json
from longrun.util.paths import DATA_DIR, SESSIONS_DIR, REPO_ROOT as REPO, _JOBSEQ_FILE
from longrun.util.steering import STEER_INBOX, _steer_lock, clear_abort, push_abort
from longrun.util.tracing import _REAL_CACHED_TOKENS, _REAL_PROMPT_TOKENS


# ---------------------------------------------------------------- stores ----


def _ensure_dirs():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _store_path(name):
    return os.path.join(DATA_DIR, name)


def load_plan():
    return read_json(_store_path("plan.json"), {"goal": "", "steps": [], "updated": None})


def save_plan(plan):
    plan["updated"] = round(time.time(), 3)
    write_json(_store_path("plan.json"), plan)
    publish("plan.update", goal=plan.get("goal", ""), steps=plan.get("steps", []))


def load_tasks():
    return read_json(_store_path("tasks.json"), {"tasks": [], "updated": None})


def save_tasks(store):
    store["updated"] = round(time.time(), 3)
    write_json(_store_path("tasks.json"), store)
    publish("tasks.update", tasks=store.get("tasks", []))


_SID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def _valid_sid(sid):
    """A session id becomes a FILE name, so it must be a plain token (JAG-230).

    Ids arrive straight from the client (query string / JSON body). Anything
    with a path separator, a `..` segment or a non-string type is a traversal /
    type-confusion attempt and must never reach the filesystem.
    """
    return (isinstance(sid, str) and ".." not in sid
            and _SID_RE.match(sid) is not None)


def load_session(sid):
    if not _valid_sid(sid):
        return None
    return read_json(os.path.join(SESSIONS_DIR, sid + ".json"), None)


# JAG-222: a session deleted WHILE its turn is running used to be RESURRECTED —
# the (not-aborted) worker persisted the final reply and recreated the file. A
# tombstone makes the write a no-op until the id is deliberately re-created.
# JAG-315: the tombstone is now PERSISTED (`.deleted`, deliberately not `*.json`
# so `list_sessions` never reads it as a session) and survives a restart; and
# `get_or_create_session` no longer silently resurrects a deleted id — a chat or
# attach that still references it gets a FRESH session instead.
_DELETED_SESSIONS = set()
_deleted_lock = threading.Lock()
_TOMBSTONE_FILE = os.path.join(SESSIONS_DIR, ".deleted")


def _load_tombstones():
    """Reload the durable deleted-session ids (a missing file is fine)."""
    try:
        with open(_TOMBSTONE_FILE, encoding="utf-8") as f:
            for line in f:
                sid = line.strip()
                if sid and _valid_sid(sid):
                    _DELETED_SESSIONS.add(sid)
    except (FileNotFoundError, OSError):
        pass


def _persist_tombstones():
    """Write the deleted-session ids atomically so a restart cannot forget them."""
    tmp = "%s.%s.tmp" % (_TOMBSTONE_FILE, os.getpid())
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            for sid in sorted(_DELETED_SESSIONS):
                f.write(sid + "\n")
        os.replace(tmp, _TOMBSTONE_FILE)
    except OSError:
        pass


_load_tombstones()


def save_session(sess):
    sid = sess.get("id")
    if not _valid_sid(sid):
        return  # JAG-230: never write a transcript to a path from an unsafe id
    with _deleted_lock:
        if sid in _DELETED_SESSIONS:
            return  # JAG-222: the session was deleted — never resurrect it
    # JAG-431p: carry each TITLED free group's title/summary onto the message that
    # STARTS it, so the WebUI labels groups by data that rides the transcript (and
    # therefore survives compaction) instead of by an ordinal. Best-effort.
    try:
        threads_mod.sync_chapters(sess)
    except Exception:  # noqa: BLE001
        pass
    write_json(os.path.join(SESSIONS_DIR, sid + ".json"), sess)


def _purge_session_artifacts(sid):
    """JAG-179: delete EVERY per-session artifact, not just the transcript.

    A session owns four files, all keyed by the session id: the transcript
    (`data/sessions/<sid>.json`), its task graph (`data/graphs/<sid>.json`), its
    run metrics (`data/runs/<sid>.json`) and its edit journal
    (`data/edits/<sid>.json`). The delete button only removed the transcript, so
    graphs/runs/edits piled up as orphans (586 graph files for 76 sessions was
    exactly this leak). This also sweeps the `.bak-*` / `.reset-*` backups.
    """
    import glob
    if not _valid_sid(sid):
        return []  # JAG-230: a traversal-shaped id must never drive unlink()
    bases = [os.path.join(SESSIONS_DIR, sid + ".json")]
    try:
        bases.append(taskgraph._path(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        bases.append(threads_mod.path_for(sid))   # JAG-431j: the thread ledger
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.model import runmetrics
        bases.append(runmetrics._path(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.tools import edits
        bases.append(edits._key_file(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.orchestrate import roles as roles_mod
        bases.append(roles_mod.path_for(sid))   # JAG-314: the per-session ROLE.md
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.memory import checkpoints
        checkpoints.purge_session(sid)          # JAG-413: drop session checkpoints
    except Exception:  # noqa: BLE001
        pass
    removed = []
    for base in bases:
        for f in glob.glob(glob.escape(base) + "*"):
            if f.endswith(".tmp"):
                continue
            try:
                os.unlink(f)
                removed.append(os.path.basename(f))
            except OSError:
                pass
    return removed


def _forget_session_runtime(sid):
    """JAG-302: drop the IN-MEMORY per-session entries on delete.

    JAG-179 purged the per-session FILES; the runtime maps keyed by session id
    (ctx-cache, turn lock, steer inbox) were never pruned, so they grew without
    bound across create/chat/delete cycles. The abort flag is only cleared when
    no turn is live — a running turn must still see it to stop.
    """
    _REAL_PROMPT_TOKENS.pop(sid, None)
    _REAL_CACHED_TOKENS.pop(sid, None)
    with _steer_lock:
        STEER_INBOX.pop(sid, None)
    with _TURN_LOCKS_GUARD:
        _TURN_LOCKS.pop(sid, None)
    with _ACTIVE_CHAT_LOCK:
        active = sid in _ACTIVE_CHAT
        _ACTIVE_CHAT.pop(sid, None)
    if not active:
        clear_abort(sid)


def clear_session(sid):
    """JAG-321: TRULY wipe a session's transcript — messages AND the side stores.

    The transcript the WebUI rebuilds on reload (`loadHistory`) is the merge of
    `messages` + `tool_cards` + `injects`. The `/clear` endpoint used to reset
    only `messages`, so the persisted tool cards and the harness entries
    (nudge / pivot / final / retry) came straight back — a "reset" left the chat
    visibly un-cleared. Wipe all three. Returns the session dict, or None when
    the id does not exist.
    """
    sess = load_session(sid)
    if not sess:
        return None
    push_abort(sid)
    sess["messages"] = []
    sess["tool_cards"] = []
    sess["injects"] = []
    save_session(sess)
    try:
        taskgraph.reset(sid)
    except Exception:  # noqa: BLE001 — a missing graph must not block the clear
        pass
    threads_mod.clear(sid)   # JAG-431j: the thread ledger describes this session
    _forget_session_runtime(sid)
    publish("session.cleared", session=sid)
    return sess


def _rel_time(ts):
    """JAG-113: short relative label ('ora', '3 min', '15 h', '2 g') for a timestamp."""
    try:
        d = max(0.0, time.time() - float(ts))
    except (TypeError, ValueError):
        return ""
    if d < 60:
        return "ora"
    if d < 3600:
        return "%d min" % int(d // 60)
    if d < 86400:
        return "%d h" % int(d // 3600)
    return "%d g" % int(d // 86400)


def list_sessions():
    """JAG-113: sessions ordered by LAST USE (not creation), with an age label.

    JAG-323: each row carries a live ``running`` flag (from `_ACTIVE_CHAT`, the
    registry of turns in flight). Before, the main app's session list had NO such
    field, so a turn started HEADLESS — a job/routine turn on a session this
    browser did not open — was invisible: the session looked idle while a model
    burned GPU/tokens ("phantom run"). The flag is authoritative: every turn,
    whoever started it, registers in `_ACTIVE_CHAT` for its whole duration.
    """
    try:
        with _ACTIVE_CHAT_LOCK:
            _active = set(_ACTIVE_CHAT.keys())
    except Exception:  # noqa: BLE001
        _active = set()
    out = []
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if fn.endswith(".json"):
                s = read_json(os.path.join(SESSIONS_DIR, fn), None)
                if not s:
                    continue
                msgs = s.get("messages", [])
                stamps = [s.get("created") or 0]
                if msgs:
                    stamps.append(msgs[-1].get("ts") or 0)
                cards = s.get("tool_cards") or []
                if cards:
                    stamps.append(cards[-1].get("ts") or 0)
                upd = max(stamps)
                out.append({"id": s["id"], "title": s.get("title", ""),
                            "created": s.get("created"), "updated": upd,
                            "age": _rel_time(upd), "messages": len(msgs),
                            "workspace": s.get("workspace"),
                            "job": s.get("job"),
                            "model": s.get("model"),
                            "running": s["id"] in _active})
    except FileNotFoundError:
        pass
    return sorted(out, key=lambda s: s.get("updated") or 0, reverse=True)


def _max_job():
    """JAG-169/JAG-316: highest session job number ever assigned.

    Must be MONOTONIC. The old version took the max only over LIVE session
    files, so deleting the session that held the top number let the next session
    reuse it — two different sessions could both be labelled ``J12`` over time,
    contradicting the "assigned once, never shifts" contract. We now also read a
    persisted high-water mark (``.jobseq``, deliberately not ``*.json`` so
    ``list_sessions`` never reads it as a session).
    """
    best = _read_seq()
    try:
        for fn in os.listdir(SESSIONS_DIR):
            if fn.endswith(".json"):
                s = read_json(os.path.join(SESSIONS_DIR, fn), None) or {}
                try:
                    best = max(best, int(s.get("job") or 0))
                except (TypeError, ValueError):
                    pass
    except FileNotFoundError:
        pass
    return best


def _read_seq():
    try:
        with open(_JOBSEQ_FILE, encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, OSError, ValueError):
        return 0


def _write_seq(n):
    tmp = "%s.%s.tmp" % (_JOBSEQ_FILE, os.getpid())
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(int(n)))
        os.replace(tmp, _JOBSEQ_FILE)
    except OSError:
        pass


def ensure_job(sess):
    """JAG-169: a stable human id for a session — JX, X = job number.

    Assigned ONCE and persisted, so it never shifts when other sessions are
    deleted (unlike a position in the list). Returns True when it changed `sess`.
    """
    try:
        if int(sess.get("job") or 0) > 0:
            return False
    except (TypeError, ValueError):
        pass
    n = _max_job() + 1
    sess["job"] = n
    _write_seq(n)   # JAG-316: keep the counter monotonic across deletes
    return True


def ensure_session_workspace(sess, workspace=None):
    """JAG-117: every session is linked to a folder.

    Precedence: the explicit `workspace` argument, else the session's existing
    folder, else the global default. Returns True when it changed `sess`.
    """
    try:
        from longrun.memory import rules as rules_mod
        want = rules_mod.check_dir(workspace) or sess.get("workspace") or rules_mod.get_workspace()
    except Exception:  # noqa: BLE001 — never break session loading
        want = workspace or sess.get("workspace") or REPO
    if want and sess.get("workspace") != want:
        sess["workspace"] = want
        return True
    return False


def backfill_session_workspaces():
    """JAG-117: pin a folder on any stored session that has none yet."""
    n = 0
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".json"):
                continue
            s = read_json(os.path.join(SESSIONS_DIR, fn), None)
            if s and ensure_session_workspace(s):
                save_session(s)
                n += 1
    except FileNotFoundError:
        pass
    return n


def backfill_jobs():
    """JAG-169: give every stored session a stable JX job id (assigned once)."""
    n = 0
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".json"):
                continue
            s = read_json(os.path.join(SESSIONS_DIR, fn), None)
            if s and ensure_job(s):
                save_session(s)
                n += 1
    except FileNotFoundError:
        pass
    return n


def _set_session_model(sid, model):
    """JAG-309: the single writer for a session's model AND its agent's model.

    An agent IS a session (agents.py: agent["session"] == sid), yet two
    independent writers let the two diverge: Orbit set only `agent["model"]`
    (which jobs read) while the composer set only `session["model"]` (which
    interactive chat reads). A3 showed a local model in Orbit but
    `deepseek-reasoner` in the composer. Unify them here: one model per entity,
    served by BOTH surfaces. `""` clears the choice; `None` leaves it untouched
    is NOT the contract here — this is an explicit write, so `""` clears.
    """
    sid = str(sid or "").strip()
    if not sid:
        return None
    ref = str(model or "")[:120]
    sess = load_session(sid)
    if sess is not None:
        sess["model"] = ref
        save_session(sess)
    try:
        from longrun.agent import agents as agents_mod
        if agents_mod.REGISTRY.is_agent(sid):
            agents_mod.REGISTRY.designate(sid, model=ref)
    except Exception:  # noqa: BLE001 — the agent layer is optional for a session
        pass
    return ref


def reconcile_agent_models():
    """JAG-309: make every agent's model agree with its session's (agent wins).

    The agent model is the explicit per-agent choice made in Orbit and is what
    its jobs actually ran on, so it is authoritative; the session model is
    back-filled from it. When only the session has one, the agent inherits it.
    Idempotent; runs once at startup so pre-JAG-309 divergence heals.
    """
    try:
        from longrun.agent import agents as agents_mod
        rows = agents_mod.REGISTRY.list().get("agents", [])
    except Exception:  # noqa: BLE001 — agents are optional
        return 0
    fixed = 0
    for a in rows:
        sid = a.get("session")
        if not sid:
            continue
        sess = load_session(sid)
        if sess is None:
            continue
        am = a.get("model") or ""
        sm = sess.get("model") or ""
        if am == sm:
            continue
        if am:
            sess["model"] = str(am)[:120]
            save_session(sess)
            fixed += 1
        else:
            try:
                agents_mod.REGISTRY.designate(sid, model=sm)
                fixed += 1
            except Exception:  # noqa: BLE001
                pass
    return fixed


def _remember_workspace(path):
    """JAG-126: remember the folder of the session being used, so the NEXT new
    session defaults to it. Never breaks the session if the write fails."""
    try:
        from longrun.memory import rules as rules_mod
        rules_mod.remember_workspace(path)
    except Exception:  # noqa: BLE001
        pass


def _chat_workspace(sess):
    """JAG-127: the folder of the chatting session, for the tool approval gate
    (a file op outside it must be confirmed). Never raises."""
    try:
        from longrun.memory import rules as rules_mod
        return rules_mod.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        return None


def get_or_create_session(sid, title=None, workspace=None):
    if sid and not _valid_sid(sid):
        sid = None  # JAG-230: refuse a traversal-shaped id, allocate a safe one
    if sid:
        with _deleted_lock:
            _gone = sid in _DELETED_SESSIONS
        if _gone:
            # JAG-315: a deleted session must never come back. A caller that still
            # holds the old id (a chat / attach from a stale tab) gets a FRESH one
            # rather than silently resurrecting the deleted transcript.
            sid = None
        else:
            s = load_session(sid)
            if s:
                changed = ensure_session_workspace(s, workspace)
                changed = ensure_job(s) or changed   # JAG-169: backfill a stable JX id
                if changed:
                    save_session(s)
                _remember_workspace(s.get("workspace"))
                return s
    sid = sid or uuid.uuid4().hex[:12]
    s = {"id": sid, "title": title or "session " + sid[:6],
         "created": round(time.time(), 3), "messages": []}
    ensure_session_workspace(s, workspace)
    ensure_job(s)                                # JAG-169: allocate JX on creation
    save_session(s)
    _remember_workspace(s.get("workspace"))
    return s


def append_message(sess, role, content, reasoning=None, meta=None):
    # JAG-238: the transcript must only ever hold STRING content. A client could
    # POST {"message": 123}; the int was persisted and later crashed /api/context
    # (`len(int)` -> dropped connection). Coerce at this single choke point so no
    # caller can poison the stored transcript.
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    msg = {"role": role, "content": content, "ts": round(time.time(), 3)}
    if reasoning:
        msg["reasoning"] = reasoning
    if meta:
        msg.update(meta)
    # JAG-431j: file this turn into the session's durable thread ledger BEFORE the
    # transcript write — compaction rewrites `messages` (older turns -> one summary),
    # so the ledger must capture the content while it is still guaranteed present.
    threads_mod.record(sess, node=msg.get("node"), role=role, text=content,
                       idx=len(sess.get("messages", [])))
    sess["messages"].append(msg)
    save_session(sess)
    return msg


def persist_tool_card(sess, tool, ok, args=None, result="", error="",
                      exit_code=None, backend=None, node=None, think=None, after=None):
    """JAG-96: persist an inline tool card so cold-start UIs can rebuild it.

    Stored in `sess["tool_cards"]` — NOT in `messages` — so it never reaches the
    model prompt (`context_engine.build` only reads `messages`). `after` is the
    number of already-persisted messages the card follows, letting the WebUI and
    the mobile mirror interleave cards with the transcript on history reload.
    `node` (JAG-167) is the todo node id the card belongs to, so the in-chat tree
    can nest it under the right node on reload.

    JAG-192: `after` MUST be passed explicitly from the chat loop. During a turn
    the transcript lives in the local `msgs` list and is flushed into
    `sess["messages"]` only at the end, so `len(sess["messages"])` is frozen at
    the turn-start value — every card of a multi-step turn then collapsed onto
    the same boundary and a reload stacked the whole turn at the top instead of
    interleaving it (that is the "Ctrl+Shift+R reshuffles the chat" bug).
    `node` is coerced to its id so a caller that accidentally passes the node
    dict cannot poison the JSON with "[object Object]".
    """
    try:
        if isinstance(node, dict):
            node = node.get("id")
        args_str = args if isinstance(args, str) else json.dumps(args or {},
                                                                ensure_ascii=False)
        card = {
            "tool": str(tool),
            "ok": bool(ok),
            "args": args_str[:4000],
            "result": str(result or "")[:4000],
            "error": str(error or "")[:2000],
            "exit_code": exit_code,
            "backend": backend,
            "node": node,
            "think": (str(think)[:6000] if think else None),
            "after": (len(sess.get("messages", [])) if after is None else int(after)),
            "ts": round(time.time(), 3),
        }
        # JAG-431j: file the tool call into the thread ledger (digest) before it is
        # stored — the ledger must not depend on the (compactable) transcript.
        threads_mod.record(sess, node=node, text="\u2699 %s %s" % (tool, args_str),
                           idx=card["after"])
        sess.setdefault("tool_cards", []).append(card)
        save_session(sess)
        return card
    except Exception:  # noqa: BLE001 — persisting a card must never break a turn
        return None


def persist_inject(sess, kind, text, node=None, after=None):
    """JAG-167: persist a harness→LLM injection so the chat can rebuild it on reload.

    Mirrors `persist_tool_card`: stored in `sess["injects"]` (never sent to the
    model), with `after` (message boundary) + `node` (the todo node it belongs to)
    + `ts`, so `loadHistory` re-nests it under the right node. JAG-192: `after`
    is passed explicitly by the chat loop (see persist_tool_card) and `node` is
    coerced to its id.
    """
    try:
        if isinstance(node, dict):
            node = node.get("id")
        rec = {"kind": str(kind or "inject"), "text": str(text or "")[:8000],
               "node": node,
               "after": (len(sess.get("messages", [])) if after is None else int(after)),
               "ts": round(time.time(), 3)}
        threads_mod.record(sess, node=node, text=text, idx=rec["after"])
        sess.setdefault("injects", []).append(rec)
        save_session(sess)
        return rec
    except Exception:  # noqa: BLE001 — persisting an inject must never break a turn
        return None


# JAG-113: the live tool card must show input + output (truncated), like the
# persisted one rebuilt on reload — the live SSE event used to carry neither.
TOOL_EVENT_MAX = int(os.environ.get("LONGRUN_TOOL_EVENT_MAX", "2000"))


def _trunc(text, n=None):
    """Truncate to <= n chars INCLUDING the '… troncati' suffix (JAG-113)."""
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    n = n or TOOL_EVENT_MAX
    if len(s) <= n:
        return s
    keep = max(0, n - 48)
    return s[:keep] + "\n… [%d caratteri troncati]" % (len(s) - keep)


def _tool_event(tool, ok, args=None, output="", **extra):
    """Payload for a live tool card (args + truncated output + meta)."""
    args_s = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    ev = {"tool": str(tool), "ok": bool(ok), "args": _trunc(args_s),
          "output": _trunc(output or "")}
    ev.update(extra)
    return ev


# JAG-371: the API-key management (ENV_FILE, KNOWN_ENV_KEYS, _env_file_upsert,
# set_key, reveal_key, keys_status) moved to `keys.py` (imported above).


# --- JAG-51 session contract: no request without a persisted answer ---------
ERROR_PREFIX = "⚠️ error: "


def session_mark(sess):
    """Index (len of `messages`) to pass to `ensure_reply_persisted` as `since`.

    Call it *before* appending the request's `user` message: it captures the
    boundary of the request so the helper can tell whether that request
    produced an assistant turn.
    """
    return len(sess.get("messages", []))


def has_reply_since(sess, since):
    """True iff an `assistant` message was persisted at index >= `since`."""
    return any(m.get("role") == "assistant" for m in sess.get("messages", [])[since:])


def ensure_reply_persisted(sess, since, error=None, model=None):
    """JAG-51 invariant: a request never leaves an orphan `user` message.

    Every request on a session must end with an `assistant` message — the model
    reply, an explicit error turn, or both (reply + graph error are separate).
    If nothing assistant-shaped was persisted since `since`, append the explicit
    error record and return it; otherwise return None. Idempotent: calling it
    twice (e.g. from `except` and `finally`) never doubles a message.
    """
    if has_reply_since(sess, since):
        return None
    detail = str(error) if error else "empty reply from the model"
    return append_message(sess, "assistant", ERROR_PREFIX + detail,
                          meta={"model": model, "error": True, "error_detail": detail})


def reconcile_orphan_turns(session=None):
    """JAG-262: close turns left half-done by a hard restart.

    A systemd restart (SIGTERM) kills an in-flight chat turn; its `finally` never
    runs, so the session keeps a trailing `user` message with no reply and the
    WebUI shows it as if it were still working ("stuck"). At startup nothing can
    be in flight, so any session ending on a `user` turn is an orphan: close it
    with an explicit assistant notice (never silently dropped). Returns the count.

    `session` (JAG-263): restrict the sweep to one session id, so the agent can
    repair a single stuck session on demand via the `reconcile` tool.
    """
    fixed = 0
    if session:
        names = ([session + ".json"]
                 if os.path.exists(os.path.join(SESSIONS_DIR, session + ".json"))
                 else [])
    else:
        try:
            names = os.listdir(SESSIONS_DIR)
        except FileNotFoundError:
            return 0
    for fn in names:
        if not fn.endswith(".json"):
            continue
        sid = fn[:-5]
        # JAG-262b: a session with a LIVE turn has a trailing `user` message too
        # (the reply is persisted only at the end), so a blind sweep would corrupt
        # a working session. NEVER touch a session that currently owns a turn.
        if sid in _ACTIVE_CHAT:
            continue
        try:
            sess = load_session(sid)
        except Exception:  # noqa: BLE001
            continue
        msgs = (sess or {}).get("messages", [])
        if not msgs or msgs[-1].get("role") != "user":
            continue
        try:
            append_message(
                sess, "assistant",
                ERROR_PREFIX + "previous turn was interrupted by a service restart "
                "— send a new message to continue.",
                meta={"error": True, "error_detail": "interrupted-by-restart",
                      "interrupted": True})
            # also release progress left 'doing' by the killed turn, so the panel
            # does not show a phantom active step.
            try:
                from longrun.plan import taskgraph
                g = taskgraph.load(sid)
                if g:
                    for n in list(g.get("nodes", [])):
                        if n.get("status") == "doing":
                            taskgraph.update_node(g, n["id"], status="todo")
            except Exception:  # noqa: BLE001
                pass
            publish("session.reconciled", session=sid, reason="orphan_user_turn")
            fixed += 1
        except Exception:  # noqa: BLE001 — recovery must never block startup
            continue
    return fixed

