#!/usr/bin/env python3
"""Effect state — a label travels with the file, so the same command is not the
same action twice.

Source: arXiv:2611.25599, "Tether" (round 164). A stateless allowlist cannot tell
step 1 from step 3 of its own running example: `curl --json @scratch/report.txt`
is public at step 1 and sensitive at step 3, after `cp data/servers.csv
scratch/report.txt` (`tether-stateful-policy_2611.25599.md:63-92`). Tether traces
system calls in a copy-on-write sandbox, infers 11 abstract actions and updates a
security state `⟨T, P, σ⟩` (`:127-186`); it blocks 344/344 in-scope adversarial
trajectories at 2.3–5.0% benign FPR (`:402`).

This module is the narrow transfer a harness without syscall tracing can honestly
make: it reads the PATH ARGUMENTS the tool call already declares, keeps a taint
set per session, propagates a taint through `cp`/`mv`/redirection, and blocks an
egress call that NAMES a tainted path. It does not claim Tether's guarantee —
exact data flow is undecidable and Tether itself over-approximates (`:44`, `:461`),
and arXiv:2611.25325 proves no finite guardrail decides safety (`:28`). It claims
one rule over the paths the harness can see, and `unverifiable` for the rest.
A URL is never treated as a local path: only filesystem arguments are labelled
and only they can be sent, so a URL whose path segment reads `/secret` or
`/token.json` is not a sensitive file. The catalogue has no structured copy or
move tool today (165 tools: `fs.read`/`fs.write`/`fs.edit` carry no source path),
so `cp`/`mv` are the only copy carriers; when a copy tool lands, `observe` must
taint its destination or the label stops travelling.

Pure functions over a dict state; the live caller keeps one state per session.
"""
from __future__ import annotations

import json
import re

FORMAT = "longrun-effect-state/1"

#: Default sensitive patterns. A path containing any of these becomes labelled.
SENSITIVE = (".env", "id_rsa", "id_ed25519", ".ssh/", "credentials", "secret",
             "api_key", "apikey", "token.json", "passwd", "shadow")

#: Tools that send bytes out.
EGRESS_TOOLS = {"http.fetch", "browser.fetch", "web.fetch"}
#: Commands that send bytes out when a shell call names a tainted path.
EGRESS_CMD = re.compile(
    r"(?i)\b(curl|wget|nc|ncat|netcat|scp|sftp|ssh|rsync|ftp|telnet)\b")
#: A path-like token: contains a separator, or ends in a known extension.
PATHISH = re.compile(
    r"(?i)(?<![\w.])\.env\b|(?<![\w.])\.ssh\b|"
    r"[A-Za-z0-9_.@+-]*(?:/[A-Za-z0-9_.@+-]+)+|"
    r"\b[A-Za-z0-9_.-]+\.(?:env|pem|key|csv|json|txt|db|sqlite|ya?ml|log|toml)")
_COPY = re.compile(r"(?i)^\s*(cp|mv)\s+(?:-\S+\s+)*(\S+)\s+(\S+)")
_REDIR = re.compile(r"(?i)>>?\s*(\S+)")
#: A URL is a remote address, not a filesystem path: its path segment may say
#: "secret" or end in "token.json" without being a local file that was read.
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s'\"<>)]+")


def _args_text(args):
    if isinstance(args, str):
        return args
    return json.dumps(args or {}, ensure_ascii=False, default=str)


def _without_urls(text):
    return _URL.sub(" ", str(text or ""))


def paths(text):
    return [p.strip("'\"") for p in PATHISH.findall(str(text or ""))]


def is_sensitive(path, patterns=None):
    low = str(path or "").lower()
    return any(str(p).lower() in low for p in (patterns or SENSITIVE))


def _command(args):
    if isinstance(args, dict):
        return str(args.get("command") or args.get("cmd") or args.get("script") or "")
    return ""


def observe(state, tool, args, patterns=None):
    """Record the labels a completed call leaves behind. Mutates and returns state."""
    state = state if isinstance(state, dict) else {}
    tainted = state.setdefault("tainted", {})
    # Only LOCAL paths are labelled: a URL's path segment is not a file.
    text = _without_urls(_args_text(args))
    for path in paths(text):
        if is_sensitive(path, patterns):
            tainted[path] = True
    command = _command(args)
    if command:
        match = _COPY.match(command)
        if match and any(src in match.group(2) for src in tainted):
            tainted[match.group(3)] = True
        redir = _REDIR.search(command)
        if redir and any(src in command for src in tainted):
            tainted[redir.group(1)] = True
    state["calls"] = int(state.get("calls") or 0) + 1
    return state


def egress_path(state, tool, args, patterns=None):
    """The tainted path this call would send, or "" when the call is not egress.

    Two ways a path is named: it is already labelled in this session, or the call
    itself names a sensitive path (a direct upload with no prior read).
    """
    state = state if isinstance(state, dict) else {}
    text = _args_text(args)
    command = _command(args)
    is_egress = str(tool or "") in EGRESS_TOOLS or bool(EGRESS_CMD.search(command))
    if not is_egress:
        return ""
    for path in list(state.get("tainted") or {}):
        if path and path.lower() in text.lower():
            return path
    # A DIRECT sensitive path (no prior read) is judged on LOCAL paths only: the
    # URL's own path segment (`/secret`, `/token.json`) is not a file this call
    # would send, and blocking it refuses legitimate egress.
    for path in paths(_without_urls(text)):
        if is_sensitive(path, patterns):
            return path
    return ""


def reason(path, tool=""):
    return ("BLOCKED by harness stateful policy (arXiv:2611.25599 §2.1): this call "
            "would send `%s`, which this session read or copied. The label travels "
            "with the file, so the same command that was allowed earlier is not "
            "allowed now. Nothing was executed. Use a path that was never tainted, "
            "or ask the OPERATOR to lift the block." % (path or "a sensitive path"))


_STATES = {}
_CAP = 256


def state_for(session):
    """The one taint state for a session (bounded; oldest evicted first)."""
    sid = str(session or "")
    if not sid:
        return {}
    if sid not in _STATES:
        if len(_STATES) >= _CAP:
            _STATES.pop(next(iter(_STATES)))
        _STATES[sid] = {}
    return _STATES[sid]


def reset(session=None):
    if session is None:
        _STATES.clear()
    else:
        _STATES.pop(str(session), None)


def describe(state):
    tainted = sorted((state or {}).get("tainted") or {})
    return {"format": FORMAT, "tainted": tainted, "calls": int((state or {}).get("calls") or 0)}
