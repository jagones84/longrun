"""Telegram channel binding store — `data/telegram.json`.

This file is the ONE place that remembers, across restarts:

  * the bot identity seen at onboarding (`getMe`),
  * the Longrun session the channel is bound to (`telegram`),
  * the AUTHORISED chats (`paired`) and the codes waiting for approval
    (`pending`), the OpenClaw-style pairing gate,
  * the long-poll cursor (`last_update_id`, so a restart never replays an update),
  * whether the operator wants the channel running (`enabled`).

Deleting the bound session clears this file (the channel goes idle ⇒
re-onboarding), exactly like `webhooks.json` is the one owner of hook state
(`core/webhooks.py`). Writes are atomic through `util.fswrite.write_text`.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time

from longrun.util import paths
from longrun.util.fswrite import write_text

#: The owned Longrun session id. Kept here (not in the channel) so the binding and
#: the identity cannot drift; `agent.architect` mirrors the same literal.
SESSION_ID = "telegram"

#: Bounds, so a hostile DM cannot grow the file without limit.
MAX_PAIRED = 50
MAX_PENDING = 20

_LOCK = threading.Lock()


def store_path():
    """Where the binding lives (env override exists for tests)."""
    return (os.environ.get("LONGRUN_TELEGRAM")
            or os.path.join(paths.DATA_DIR, "telegram.json"))


def empty():
    """The pristine record: no bot, nobody paired, channel idle."""
    return {
        "session": SESSION_ID,
        "mode": "pairing",          # "pairing" (approve first DM) | "open"
        "enabled": False,
        "bot": {},                  # {id, username, first_name}
        "paired": [],               # [{chat_id, user_id, username, title, ts}]
        "pending": {},              # {code: {chat_id, user_id, username, ts}}
        "last_update_id": 0,
        # Telegram-ONLY display prefs (they change what the CHANNEL shows, never the
        # Longrun session): think = stream the model's thinking, reason = append the
        # final reasoning, verbose = relay every harness/tool event in real time.
        "prefs": {"think": False, "reason": False, "verbose": False},
    }


#: The Telegram-only display toggles (one owner for the valid keys).
PREF_KEYS = ("think", "reason", "verbose")


def prefs(doc):
    """The channel display prefs, defaults filled in (never raises)."""
    got = (doc or {}).get("prefs") or {}
    return {k: bool(got.get(k)) for k in PREF_KEYS}


def set_pref(doc, key, value):
    """Set one display pref on `doc` and return its new value (None if unknown)."""
    if key not in PREF_KEYS:
        return None
    doc.setdefault("prefs", {})
    doc["prefs"][key] = bool(value)
    return doc["prefs"][key]


def _coerce(doc):
    """Return a well-formed document, filling/repairing missing fields."""
    base = empty()
    if not isinstance(doc, dict):
        return base
    for key in ("mode", "enabled", "last_update_id"):
        if key in doc:
            base[key] = doc[key]
    if isinstance(doc.get("bot"), dict):
        base["bot"] = doc["bot"]
    if isinstance(doc.get("paired"), list):
        base["paired"] = [p for p in doc["paired"] if isinstance(p, dict)]
    if isinstance(doc.get("pending"), dict):
        base["pending"] = {k: v for k, v in doc["pending"].items()
                           if isinstance(v, dict)}
    if isinstance(doc.get("prefs"), dict):
        base["prefs"] = {k: bool(doc["prefs"].get(k)) for k in PREF_KEYS}
    base["session"] = SESSION_ID
    return base


def load():
    """Read the binding (never raises; a missing/corrupt file is the pristine one)."""
    with _LOCK:
        try:
            with open(store_path(), "r", encoding="utf-8") as stream:
                doc = json.load(stream)
        except (OSError, ValueError):
            return empty()
        return _coerce(doc)


def save(doc):
    """Persist a (coerced) binding atomically."""
    clean = _coerce(doc)
    with _LOCK:
        write_text(store_path(), json.dumps(clean, ensure_ascii=False, indent=2))
    return clean


# ------------------------------------------------------------------- helpers --

def exists():
    """True when a binding file is on disk (first run vs an explicit 'off').

    This is what tells a FRESH install ("just put the token") apart from a channel
    the operator deliberately turned off (logout, or the session was deleted): the
    first arms itself from the token, the second stays off until re-onboarded.
    """
    return os.path.isfile(store_path())


def is_paired(doc, chat_id):
    """True when `chat_id` is allowed to drive the agent."""
    want = str(chat_id)
    return any(str(p.get("chat_id")) == want for p in (doc or {}).get("paired") or [])


def upsert_paired(doc, chat_id, user_id=None, username="", title=""):
    """Add (or refresh) an authorised chat, bounded by `MAX_PAIRED`."""
    want = str(chat_id)
    paired = [p for p in (doc or {}).get("paired") or [] if str(p.get("chat_id")) != want]
    paired.append({"chat_id": chat_id, "user_id": user_id,
                   "username": str(username or ""), "title": str(title or ""),
                   "ts": round(time.time(), 3)})
    if len(paired) > MAX_PAIRED:
        paired = paired[-MAX_PAIRED:]
    doc["paired"] = paired
    return doc


def remove_paired(doc, chat_id=None):
    """Drop ONE chat, or every chat when `chat_id` is None."""
    if chat_id is None:
        doc["paired"] = []
        return doc
    want = str(chat_id)
    doc["paired"] = [p for p in (doc or {}).get("paired") or []
                     if str(p.get("chat_id")) != want]
    return doc


def new_code(doc, chat_id, user_id=None, username="", ttl=900.0):
    """Mint a short pairing code for `chat_id` and remember it (bounded + purged).

    Returns the code. The code is uppercase alphanumeric (Telegram-safe, easy to
    read aloud); `pending` entries older than `ttl` are dropped first.
    """
    now = time.time()
    pending = {c: r for c, r in (doc or {}).get("pending", {}).items()
               if now - float((r or {}).get("ts") or 0) <= float(ttl)}
    code = None
    for _ in range(8):
        cand = secrets.token_hex(3).upper()      # 6 chars
        if cand not in pending:
            code = cand
            break
    if code is None:
        code = secrets.token_hex(3).upper()
    pending[code] = {"chat_id": chat_id, "user_id": user_id,
                     "username": str(username or ""), "ts": round(now, 3)}
    if len(pending) > MAX_PENDING:
        for old in sorted(pending, key=lambda c: pending[c].get("ts") or 0):
            if len(pending) <= MAX_PENDING:
                break
            pending.pop(old, None)
    doc["pending"] = pending
    return code


def take_pending(doc, code):
    """Pop the pending record for `code` (case-insensitive); None if unknown."""
    pending = (doc or {}).get("pending") or {}
    key = str(code or "").strip().upper()
    rec = pending.pop(key, None)
    doc["pending"] = pending
    return rec


def reset():
    """Wipe the binding to pristine — used when the bound session is deleted."""
    return save(empty())
