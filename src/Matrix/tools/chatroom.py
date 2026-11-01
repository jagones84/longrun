"""Matrix tool namespace: chatroom.

chatroom.broadcast — the team loudspeaker: send ONE message to MANY agents
(A-ids or session ids) at once. Each target gets a real server-side turn via
the builtin `sessions.send` (never a subagent, never a dispatch), and the
tool optionally collects every reply with `sessions.wait` so the caller gets
a single transcript instead of N round-trips.

Born from the live 'stanza di chat' test (A48<->A49, 2 rounds OK): before
this tool, a multi-agent chat cost one sessions.send + one sessions.wait per
agent, by hand.

Inputs:
  agents    : list of targets — A-ids ("A48") or session ids ("55a29...").
              "team:T8" broadcasts to every member of team T8.
  message   : the text to deliver (required).
  wait_secs : optional; if > 0, wait up to that many seconds per reply and
              collect the final text of each peer (default 0 = fire-and-forget).
  sender    : optional label for the payload header (defaults to run_id).

Output:
  { ok, sent: [{agent, session, message_id, mode}], replies: [{agent, session,
  reply, state}], errors: [{target, error}] }
"""

import time

from longrun.tools import tools as _tools
from longrun.agent.agents import REGISTRY as _AGENTS
from longrun.memory.stores import load_session as _load_session


TOOL_SCHEMAS = {
    "chatroom.broadcast": {
        "description": "Broadcast ONE message to many agents (A-ids, session ids, or 'team:<TN>') via real server-side turns (builtin sessions.send, never a subagent), then optionally collect every peer reply with sessions.wait. Inputs: agents (list of 'A48'/'<sid>'/'team:T8'), message (required text), wait_secs (optional, 0=fire-and-forget, >0 = wait per reply), sender (optional label). Output: {ok, sent:[{agent,session,message_id,mode}], replies:[{agent,session,reply,state}], errors:[{target,error}]}.",
        "type": "object",
        "properties": {
            "agents": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Targets: agent ids (A48), session ids, or 'team:T8' for every member of a team.",
            },
            "message": {"type": "string", "description": "The text delivered to every target."},
            "wait_secs": {"type": "number", "description": "Seconds to wait per reply (0 = fire-and-forget).", "default": 0},
            "sender": {"type": "string", "description": "Optional sender label for the payload header."},
        },
        "required": ["agents", "message"],
        "approval": "auto",
    },
}

TOOL_SCHEMA = dict(TOOL_SCHEMAS["chatroom.broadcast"])


def _resolve_targets(refs):
    """Expand A-ids / session ids / 'team:TN' into [(agent_label, session_id)]."""
    out, seen = [], set()
    store = _AGENTS
    for ref in refs or []:
        ref = str(ref or "").strip()
        if not ref:
            continue
        if ref.startswith("team:"):
            tref = ref[5:].strip()
            try:
                members = store.agents_of_team(tref)
            except Exception:
                members = []
            for m in members or []:
                aid = str(m.get("id") or "")
                sid = str(m.get("session") or "")
                if sid and sid not in seen:
                    seen.add(sid)
                    out.append(("%s (team %s)" % (aid or sid, tref), sid))
            continue
        sid = ref
        label = ref
        rec = None
        try:
            rec = store.by_id(ref)
        except Exception:
            rec = None
        if rec and rec.get("session"):
            sid = str(rec["session"])
            label = "%s (%s)" % (ref, str(rec.get("name") or ""))
        if sid and sid not in seen:
            try:
                exists = bool(_load_session(sid))
            except Exception:
                exists = False
            if not exists:
                continue
            seen.add(sid)
            out.append((label, sid))
    return out


def _reject(error):
    """One fail-closed shape for every malformed call: nothing is sent."""
    return {"ok": False, "exit_code": 64, "error": error,
            "sent": [], "replies": [], "errors": []}


def _wait_secs(raw):
    """(seconds, error). wait_secs is VALIDATED, never coerced into a crash.

    Live defect this closes: wait_secs="not-a-number" raised ValueError at
    float() and escaped as exit=1 with a traceback (chatroom.py:102).
    """
    if raw is None or raw == "":
        return 0.0, ""
    if isinstance(raw, bool):
        return 0.0, "wait_secs must be a number >= 0 (got a boolean)"
    if isinstance(raw, str):
        try:
            raw = float(raw.strip())
        except (TypeError, ValueError):
            return 0.0, "wait_secs must be a number >= 0 (got %r)" % (raw,)
    if not isinstance(raw, (int, float)):
        return 0.0, "wait_secs must be a number >= 0 (got %r)" % (raw,)
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return 0.0, "wait_secs must be a number >= 0 (got %r)" % (raw,)
    if value != value or value in (float("inf"), float("-inf")):
        return 0.0, "wait_secs must be finite (got %r)" % (raw,)
    if value < 0:
        return 0.0, "wait_secs must be >= 0 (got %r)" % (raw,)
    return value, ""


def execute(args, run_id=None, subtool=None):
    args = args or {}
    raw_message = args.get("message")
    if not isinstance(raw_message, str) or not raw_message.strip():
        return _reject("message must be a non-empty string (got %s)"
                       % (type(raw_message).__name__,))
    message = raw_message.strip()
    refs = args.get("agents") or []
    wait_secs, wait_error = _wait_secs(args.get("wait_secs"))
    if wait_error:
        return _reject(wait_error)
    raw_sender = args.get("sender")
    if raw_sender is not None and not isinstance(raw_sender, str):
        return _reject("sender must be a string (got %s)"
                       % (type(raw_sender).__name__,))
    # The label is a CLAIM: the envelope sessions.send prepends still carries the
    # real "[message from session <sid>]". `sender_source` says whether this run
    # had to trust an explicit label or derived one from the caller.
    sender = str(raw_sender or run_id or "unknown")
    sender_source = ("explicit" if raw_sender else
                     ("run_id" if run_id else "unknown"))
    targets = _resolve_targets(refs)
    if not targets:
        return _reject("no resolvable targets in agents=%r" % (refs,))

    header = "[chatroom.broadcast from %s]" % sender
    sent, errors = [], []
    for label, sid in targets:
        res = _tools.execute("sessions.send", {
            "session": sid,
            "message": "%s\n%s" % (header, message),
        }, run_id=run_id)
        if res.get("ok"):
            sent.append({"agent": label, "session": sid,
                         "message_id": res.get("message_id") or "",
                         "mode": res.get("mode") or "turn"})
        else:
            errors.append({"target": label, "session": sid,
                           "error": res.get("error") or res.get("stdout") or "send failed"})

    replies = []
    if wait_secs > 0:
        for item in sent:
            mid = item.get("message_id") or ""
            if not mid:
                continue
            try:
                w = _tools.execute("sessions.wait", {"message_id": mid}, run_id=run_id)
            except Exception as exc:  # one stuck peer must not kill the room
                replies.append({"agent": item["agent"], "session": item["session"],
                                "reply": "", "state": "wait_error: %s" % exc})
                continue
            if w.get("ok") and w.get("reply"):
                replies.append({"agent": item["agent"], "session": item["session"],
                                "reply": w.get("reply"), "state": "completed"})
            else:
                replies.append({"agent": item["agent"], "session": item["session"],
                                "reply": "", "state": "running_or_timeout"})

    return {"ok": True, "exit_code": 0, "sender": sender,
            "sender_source": sender_source,
            "targets": len(targets), "sent": sent, "replies": replies,
            "errors": errors,
            "stdout": ("broadcast delivered to %d/%d targets (%d errors, %d replies collected)"
                       % (len(sent), len(targets), len(errors), len(replies))),
            "backend": "host", "sandboxed": False}
