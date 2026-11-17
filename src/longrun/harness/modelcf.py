#!/usr/bin/env python3
"""Change ONE model-visible fact of a STORED transcript, re-ask the model.

The step-level counterfactual (`harness/counterfactual.py`) replays a recorded
tool call and compares the OBSERVATION. This module answers the other half of the
same question (HD-1, model branch): *if the model had seen a different
observation, would its next ACTION have differed?*

It is pure by construction: nothing is executed. One model call is issued over
the stored transcript with one message replaced, and the reply is compared with
the action the model actually produced at that point. A mutating step cannot be
duplicated because no step runs at all — which is what makes this instrument
usable where a step replay is not (a write, a network call, a service).

What it does NOT restore, and says so in every answer: the live system prompt
(memory index, rules, runtime facts) and the per-turn volatile blocks the
original turn carried (`agent.user_turn_context`). The comparison is therefore
"same transcript, current system prompt" — enough to attribute a decision to one
observation, not enough to bit-exactly re-run the provider's call.

Pure module: no server import, no model, no store write.
"""
import re

USER = "user"
ASSISTANT = "assistant"


def _messages(sess):
    return [m for m in (sess.get("messages") or []) if isinstance(m, dict)]


def _index(value, n):
    """(index, reason). Accepts a 0-based position or a negative offset."""
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None, "index must be an integer (a message position, -1 = the last)"
    if i < 0:
        i = n + i
    if i < 0 or i >= n:
        return None, "index %r is outside the transcript (0..%d)" % (value, n - 1)
    return i, ""


def plan(sess, index, change):
    """(plan, error). The plan names the one message to replace and its successor.

    The target must be a USER message (the model's input: an observation, a nudge,
    a peer's message) and must be followed by an ASSISTANT message (the recorded
    next action to compare against). Editing the assistant's own reply is history
    editing, not an intervention on the model's input, and is refused.
    """
    msgs = _messages(sess)
    if not msgs:
        return {}, "the session has no stored messages"
    i, why = _index(index, len(msgs))
    if why:
        return {}, why
    if i >= len(msgs) - 1:
        return {}, ("message %d is the last one: there is no recorded next action "
                    "to compare against" % i)
    target = msgs[i]
    if str(target.get("role") or "") != USER:
        return {}, ("message %d is %r; only a USER message (an observation or a "
                    "nudge — the model's INPUT) can be intervened on"
                    % (i, target.get("role")))
    if not isinstance(target.get("content"), str):
        return {}, ("message %d has structured content (image blocks); only a text "
                    "message can be replaced" % i)
    if not isinstance(change, dict):
        return {}, "change must be an object like {\"content\": \"…\"}"
    content = change.get("content")
    if not isinstance(content, str) or not content.strip():
        return {}, "change.content is required: the replacement text of that message"
    if content.strip() == str(target.get("content") or "").strip():
        return {}, ("the change is identical to the recorded message: a "
                    "counterfactual that changes nothing is a re-run")
    nxt = msgs[i + 1]
    if str(nxt.get("role") or "") != ASSISTANT:
        return {}, ("message %d is %r, not an assistant action"
                    % (i + 1, nxt.get("role")))
    return {"index": i, "original": target.get("content"),
            "replacement": content, "recorded_reply": nxt.get("content") or "",
            "fidelity": "transcript+live-system",
            "caveat": ("the stored transcript is replayed with the CURRENT system "
                       "prompt; the volatile per-turn blocks the original turn "
                       "carried (memory index, task list) are not restored"),
            "messages": len(msgs)}, ""


def _norm(action):
    if not isinstance(action, dict) or not action:
        return {}
    return action


def compare(recorded, replayed):
    """(verdict, moved, recorded, replayed) between two parsed actions.

    `same-action` means the model produced the same action with the same tool and
    arguments; `different-action` names the top-level keys that moved;
    `no-action` means neither reply carried a tool action (a plain answer).
    """
    rec, rep = _norm(recorded), _norm(replayed)
    if not rec and not rep:
        return {"verdict": "no-action", "moved": [], "recorded": {},
                "replayed": {}}
    if not rec or not rep:
        return {"verdict": "different-action", "moved": ["action"],
                "recorded": rec, "replayed": rep}
    moved = sorted(k for k in set(rec) | set(rep) if rec.get(k) != rep.get(k))
    return {"verdict": "same-action" if not moved else "different-action",
            "moved": moved, "recorded": rec, "replayed": rep}


def action_kind(action):
    """The one-word kind of an action, for a readable report line."""
    a = _norm(action)
    return str(a.get("action") or ("none" if not a else "?"))


_SHORT = re.compile(r"\s+")


def one_line(action, limit=240):
    """A compact rendering of an action for stdout and the event feed."""
    a = _norm(action)
    if not a:
        return "(no action)"
    kind = action_kind(a)
    if kind in ("tool", "shell", "fs.read"):
        tool = a.get("tool") or kind
        args = a.get("args") or {}
        try:
            import json
            body = json.dumps(args, ensure_ascii=False, sort_keys=True)
        except Exception:  # noqa: BLE001 — a report line must never fail
            body = str(args)
        return "%s %s %s" % (kind, tool, _SHORT.sub(" ", body)[:limit])
    if kind == "batch":
        calls = a.get("calls") or []
        names = [str((c or {}).get("tool") or "?") for c in calls]
        return "batch [%s]" % ", ".join(names)
    return "%s %s" % (kind, _SHORT.sub(" ", str(a.get("args") or ""))[:limit])
